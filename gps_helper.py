"""GPS position feeder for the map layout.

Runs as a reader thread (like ``can_helper.read_can`` / ``gpio_helper.read_io``)
and writes ``lat`` / ``lon`` / ``heading_deg`` / ``gps_speed_kmh`` straight into
the shared ``SensorState``. Fields are written directly (not via
``state.update()``) so GPS activity never stamps the CAN-activity clock and
break the no-CAN demo detection.

Two sources, tried in order:

  * **USB GPS module** (``GPS_DEV`` env, default ``/dev/ttyACM0``): NMEA 0183
    over serial — the ``$..RMC`` sentence carries fix, speed and course. If the
    device disappears mid-drive we fall back to the mock and retry the port
    every few seconds.
  * **Mock drive** (no module present): follows the real-street ``route`` baked
    into ``map_data.json`` (São Marcos - RS) at town speeds, ping-ponging
    between the route's ends, with a rate-limited heading so turns sweep
    naturally instead of snapping.
"""

import json
import math
import os
import time

GPS_DEV = os.environ.get("GPS_DEV", "/dev/ttyACM0")
GPS_BAUD = int(os.environ.get("GPS_BAUD", "9600"))
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
            if os.path.exists(GPS_DEV):
                _read_nmea(state)      # returns when the port drops
            else:
                _mock_drive(state)     # returns if the device shows up
        except Exception as e:
            print("[gps] error:", e, flush=True)
            time.sleep(3)


def _read_nmea(state):
    """Read RMC sentences from a USB NMEA module until the port fails."""
    import serial  # already a dependency (pyserial)

    with serial.Serial(GPS_DEV, GPS_BAUD, timeout=2) as port:
        print(f"[gps] reading NMEA from {GPS_DEV} @ {GPS_BAUD}", flush=True)
        while True:
            line = port.readline().decode("ascii", errors="replace").strip()
            if "RMC" not in line or not line.startswith("$"):
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
    print(f"[gps] no {GPS_DEV} — mock drive on baked route "
          f"({len(route)} pts)", flush=True)

    # start downtown (route point nearest the map origin), not at a far end
    seg_i = min(range(len(route) - 1), key=lambda i: math.hypot(*route[i]))
    seg_t, direction = 0.0, 1             # 0..1 along the segment, +/-1
    e, n = route[seg_i]
    heading = 0.0
    t = 0.0
    dt = 1.0 / MOCK_HZ

    while not os.path.exists(GPS_DEV):
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
    print(f"[gps] {GPS_DEV} appeared — switching to NMEA", flush=True)
