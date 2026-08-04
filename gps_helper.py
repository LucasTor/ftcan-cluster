"""GPS position feeder for the map layout.

Runs as a reader thread (like ``can_helper.read_can`` / ``gpio_helper.read_io``)
and writes ``lat`` / ``lon`` / ``heading_deg`` / ``gps_speed_kmh`` straight into
the shared ``SensorState``. Fields are written directly (not via
``state.update()``) so GPS activity never stamps the CAN-activity clock and
break the no-CAN demo detection.

Two sources, tried in order:

  * **USB GPS module**: the owner's **VK-162** (u-blox 7, USB CDC, 9600 baud).
    Discovered via ``/dev/serial/by-id/*u-blox*`` — NOT a bare ``ttyACM``
    number, because the CANable may also enumerate a CDC serial interface and
    grab ``ttyACM0``; matching by udev identity can never open the CAN
    adapter's port by mistake. Set ``GPS_DEV`` to an explicit path to override
    (e.g. for a non-u-blox module). Reads NMEA 0183 — the ``$..RMC`` sentence
    carries fix, speed and course, and sentences failing their checksum are
    dropped. The baud is auto-detected (clones of this dongle ship u-blox,
    CASIC, MTK or SiRF silicon — SiRF talks 4800, the rest 9600; ``GPS_BAUD``
    pins it explicitly). On every port open we send 5 Hz fix-rate commands in
    the u-blox, CASIC and MTK dialects (RAM-only; each chip ignores the
    dialects it doesn't speak). If the device disappears mid-drive we fall
    back to the mock and retry every few seconds.
  * **Mock drive** (no module present): follows the real-street ``route`` baked
    into ``map_data.json`` (São Marcos - RS) at town speeds, ping-ponging
    between the route's ends, with a rate-limited heading so turns sweep
    naturally instead of snapping.
"""

import glob
import json
import math
import os
import time

GPS_DEV = os.environ.get("GPS_DEV")            # explicit device path override
GPS_ID_GLOB = "/dev/serial/by-id/*u-blox*"     # stable udev identity (VK-162)
GPS_BAUD = os.environ.get("GPS_BAUD")          # pin a baud; empty = auto-detect
# candidate bauds, likeliest first: 9600 (u-blox/CASIC/MTK), 4800 (SiRF — the
# BU-353S4-style receivers this dongle's listing claims to replace), then the
# occasional high-rate factory config
_BAUDS = [9600, 4800, 38400, 115200]


def _gps_dev():
    """Path of the GPS serial device, or None if not plugged in."""
    if GPS_DEV:
        return GPS_DEV if os.path.exists(GPS_DEV) else None
    hits = sorted(glob.glob(GPS_ID_GLOB))
    return hits[0] if hits else None
MAP_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "map_data.json")

# mock drive tuning
MOCK_HZ = 20               # position update rate (a real module does 1-10 Hz)
MOCK_SPEED_KMH = 45.0      # cruise speed around town...
MOCK_SPEED_SWING = 20.0    # ...swinging +/- this much over a slow cycle
MOCK_TURN_RATE = 75.0      # max heading slew (deg/s) so corners sweep smoothly


def _load_map():
    with open(MAP_DATA) as f:
        return json.load(f)


def _meters_per_degree(lat0):
    return 111132.95, 111319.49 * math.cos(math.radians(lat0))


def read_gps(state):
    """Feed GPS position into the state forever (thread entry point)."""
    while True:
        try:
            dev = _gps_dev()
            if dev:
                _read_nmea(state, dev)  # returns when the port drops
            else:
                _mock_drive(state)      # returns if the device shows up
        except Exception as e:
            print("[gps] error:", e, flush=True)
            time.sleep(3)


# 5 Hz fix-rate commands, one per chipset family found in VK-162s (clones may
# carry CASIC or MediaTek silicon instead of u-blox). Each chip obeys its own
# dialect and silently ignores the others, so all three are sent at port open.
# RAM-only settings on every family, hence resent at each open.
_RATE_5HZ_CMDS = (
    bytes.fromhex("b56206080600c80001000100de6a"),  # u-blox UBX-CFG-RATE 200ms
    b"$PCAS02,200*1D\r\n",                          # CASIC AT6558 family
    b"$PMTK220,200*2C\r\n",                         # MediaTek family
)


def _nmea_ok(line):
    """Validate the NMEA '*hh' checksum (XOR of everything between $ and *)."""
    body, star, ck = line[1:].partition("*")
    if not star:
        return False
    x = 0
    for ch in body:
        x ^= ord(ch)
    try:
        return x == int(ck[:2], 16)
    except ValueError:
        return False


def _detect_baud(dev):
    """First baud that yields a checksum-valid NMEA sentence (None if none).

    Skipped when ``GPS_BAUD`` pins a rate. Reading garbage at a wrong baud is
    harmless — lines just never validate and we move on after ~3 s.
    """
    import serial

    if GPS_BAUD:
        return int(GPS_BAUD)
    for baud in _BAUDS:
        with serial.Serial(dev, baud, timeout=1) as port:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                line = port.readline().decode("ascii", errors="replace").strip()
                if line.startswith("$") and _nmea_ok(line):
                    return baud
        print(f"[gps] no NMEA at {baud} baud", flush=True)
    return None


def _read_nmea(state, dev):
    """Read RMC sentences from a USB NMEA module until the port fails."""
    import serial  # already a dependency (pyserial)

    baud = _detect_baud(dev)
    if baud is None:
        print(f"[gps] {dev}: no valid NMEA at any baud, retrying", flush=True)
        time.sleep(3)
        return

    with serial.Serial(dev, baud, timeout=2) as port:
        print(f"[gps] reading NMEA from {dev} @ {baud}", flush=True)
        try:
            for cmd in _RATE_5HZ_CMDS:
                port.write(cmd)
        except Exception as e:
            print("[gps] 5 Hz rate config not sent:", e, flush=True)
        while True:
            line = port.readline().decode("ascii", errors="replace").strip()
            if "RMC" not in line or not line.startswith("$") or not _nmea_ok(line):
                continue
            f = line.split("*")[0].split(",")
            # $GxRMC,time,status,lat,N/S,lon,E/W,speed(kn),course,...
            if len(f) < 9 or f[2] != "A":
                continue  # V = no fix yet
            try:
                state.lat = _nmea_deg(f[3], f[4])
                state.lon = _nmea_deg(f[5], f[6])
                state.gps_speed_kmh = float(f[7] or 0) * 1.852
                if f[8]:  # course is empty when stationary — keep the last one
                    state.heading_deg = float(f[8])
            except ValueError:
                continue


def _nmea_deg(v, hemi):
    """NMEA ddmm.mmmm -> signed decimal degrees."""
    v = float(v)
    deg = int(v / 100)
    dec = deg + (v - deg * 100) / 60.0
    return -dec if hemi in ("S", "W") else dec


def _mock_drive(state):
    """Drive the baked São Marcos route until a real GPS device appears."""
    data = _load_map()
    lat0, lon0 = data["origin"]
    m_lat, m_lon = _meters_per_degree(lat0)
    route = data["route"]
    print(f"[gps] no GPS module — mock drive on baked route "
          f"({len(route)} pts)", flush=True)

    # start downtown (route point nearest the map origin), not at a far end
    seg_i = min(range(len(route) - 1), key=lambda i: math.hypot(*route[i]))
    seg_t, direction = 0.0, 1             # 0..1 along the segment, +/-1
    e, n = route[seg_i]
    heading = 0.0
    t = 0.0
    dt = 1.0 / MOCK_HZ

    while _gps_dev() is None:
        speed_kmh = MOCK_SPEED_KMH + MOCK_SPEED_SWING * math.sin(t / 19.0)
        step = speed_kmh / 3.6 * dt

        # advance along the polyline, ping-ponging at the ends
        while step > 0:
            ax, ay = route[seg_i]
            bx, by = route[seg_i + 1]
            seg_len = math.hypot(bx - ax, by - ay) or 1e-9
            remain = (1.0 - seg_t) * seg_len if direction > 0 else seg_t * seg_len
            if step < remain:
                seg_t += direction * step / seg_len
                step = 0
            else:
                step -= remain
                seg_i += direction
                if seg_i >= len(route) - 1 or seg_i < 0:
                    direction = -direction
                    seg_i = max(0, min(len(route) - 2, seg_i))
                    seg_t = 1.0 if direction < 0 else 0.0
                else:
                    seg_t = 0.0 if direction > 0 else 1.0
            ax, ay = route[seg_i]
            bx, by = route[seg_i + 1]
            e = ax + (bx - ax) * seg_t
            n = ay + (by - ay) * seg_t

        # heading: slew toward the segment bearing at a car-like turn rate
        want = math.degrees(math.atan2((bx - ax) * direction,
                                       (by - ay) * direction))  # ° cw from north
        diff = (want - heading + 180) % 360 - 180
        max_step = MOCK_TURN_RATE * dt
        heading = (heading + max(-max_step, min(max_step, diff))) % 360

        state.lat = lat0 + n / m_lat
        state.lon = lon0 + e / m_lon
        state.heading_deg = heading
        state.gps_speed_kmh = speed_kmh

        t += dt
        time.sleep(dt)
    print(f"[gps] {_gps_dev()} appeared — switching to NMEA", flush=True)
