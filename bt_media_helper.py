"""Bluetooth media feeder — the iPhone's now-playing info for the cluster.

Runs as a reader thread (like ``gps_helper.read_gps``) and writes
``bt_connected`` / ``bt_device`` / ``track_*`` straight into the shared
``SensorState``. Fields are written directly (not via ``state.update()``) so
Bluetooth activity never stamps the CAN-activity clock and breaks the no-CAN
demo detection.

The audio itself never touches Python: the phone streams A2DP into bluez-alsa,
which plays it out an ALSA device (see ``tools/setup_bluetooth.sh``). This
module only reads the AVRCP *metadata* that bluetoothd exposes on the system
D-Bus as ``org.bluez.MediaPlayer1`` (Track title/artist/album/duration, playback
status, position). It polls with ``busctl --json`` at 1 Hz instead of a D-Bus
client library — no new dependency, works on the stock bookworm image, and the
JSON parser is pure (``parse_managed_objects``) so it's testable off-target.

Notes:
  * ``Position`` only moves when the phone sends an AVRCP event, so between
    events it can sit still; a progress bar should extrapolate from
    ``track_position_s`` while ``track_status == "playing"`` rather than expect
    1 Hz updates.
  * Cover art is NOT read here: it needs BlueZ >= 5.79 (obexd BIP client,
    ``org.bluez.obex.Image1``) and bookworm ships 5.66. When the Pi's BlueZ is
    upgraded, the track metadata grows an image handle — fetch it via obexd and
    add an art-path field then.
  * On a machine without busctl/BlueZ (this Mac) the thread logs once and
    exits; the fields just stay at their empty defaults.

Live discovery tool (run on the Pi, phone connected):
    poetry run python bt_media_helper.py
"""

import json
import os
import re
import subprocess
import time

# a BlueZ device object path, with or without trailing components — 5.87
# nests players at .../dev_XX/avrcp/player0 (5.66 had no /avrcp/ segment)
_DEV_RE = re.compile(r"(.*/dev_[0-9A-Fa-f_]+)")

POLL_S = 1.0

# what every field reads as when no phone / no player is present
_IDLE = {
    "bt_connected": False,
    "bt_device": "",
    "track_title": "",
    "track_artist": "",
    "track_album": "",
    "track_status": "",
    "track_position_s": 0.0,
    "track_duration_s": 0.0,
}


def _unwrap(value):
    """Strip busctl's ``{"type": ..., "data": ...}`` variant wrappers.

    busctl's JSON modes differ in how deeply values are wrapped; unwrapping
    recursively accepts either shape.
    """
    if isinstance(value, dict):
        if set(value) == {"type", "data"}:
            return _unwrap(value["data"])
        return {k: _unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_unwrap(v) for v in value]
    return value


def parse_managed_objects(objects):
    """BlueZ GetManagedObjects payload -> ``(vals, meta)``.

    ``vals`` is the ``_IDLE``-shaped field dict; ``meta`` carries the cover-art
    context (``img_handle``, ``device_mac``) that is not SensorState data.
    ``objects`` is ``{object_path: {interface: {property: value}}}``. A media
    player lives at ``.../dev_XX_.../playerN``, so its owning phone is the
    parent path's ``org.bluez.Device1``. With several players (rare), the one
    actually playing wins.
    """
    vals = dict(_IDLE)
    meta = {"img_handle": "", "device_mac": ""}
    devices = {}
    players = []
    for path, ifaces in objects.items():
        if "org.bluez.Device1" in ifaces:
            devices[path] = _unwrap(ifaces["org.bluez.Device1"])
        if "org.bluez.MediaPlayer1" in ifaces:
            players.append((path, _unwrap(ifaces["org.bluez.MediaPlayer1"])))

    connected = {p: d for p, d in devices.items() if d.get("Connected")}
    vals["bt_connected"] = bool(connected)

    players.sort(key=lambda pm: pm[1].get("Status") != "playing")
    if players:
        path, player = players[0]
        m = _DEV_RE.match(path)
        dev_path = m.group(1) if m else path.rsplit("/", 1)[0]
        device = devices.get(dev_path, {})
        track = player.get("Track") or {}
        vals["bt_device"] = str(device.get("Alias") or device.get("Name") or "")
        vals["track_title"] = str(track.get("Title") or "")
        vals["track_artist"] = str(track.get("Artist") or "")
        vals["track_album"] = str(track.get("Album") or "")
        vals["track_status"] = str(player.get("Status") or "")
        vals["track_position_s"] = float(player.get("Position") or 0) / 1000.0
        vals["track_duration_s"] = float(track.get("Duration") or 0) / 1000.0
        # cover art (AVRCP 1.6 BIP): needs bluetoothd >= 5.79 running with -E,
        # otherwise ImgHandle never appears in the track metadata
        meta["img_handle"] = str(track.get("ImgHandle") or "")
        if m:
            meta["device_mac"] = \
                dev_path.rsplit("dev_", 1)[-1].replace("_", ":")
    elif connected:
        device = next(iter(connected.values()))
        vals["bt_device"] = str(device.get("Alias") or device.get("Name") or "")
    return vals, meta


def _busctl(*args, timeout="15"):
    """One busctl call; returns the parsed --json=short payload data list."""
    proc = subprocess.run(
        ["busctl", "call", "--json=short", f"--timeout={timeout}", *args],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"busctl exit {proc.returncode}")
    return json.loads(proc.stdout)["data"]

_OBEX = "org.bluez.obex"


def _jpeg_complete(path):
    """True if the file is a complete JPEG (SOI header + EOI trailer).

    Rapid track-skipping aborts the OBEX transfer mid-stream and leaves a
    truncated file; QML decodes the intact top rows and renders garbage for
    the rest, which shows up as a "broken image" in the art square. A JPEG
    cut short never carries its end-of-image marker, so this check rejects
    exactly those files. (The EOI is searched in the tail rather than the
    last two bytes only — encoders may pad after it.)
    """
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return False
            f.seek(max(0, os.path.getsize(path) - 512))
            return b"\xff\xd9" in f.read()
    except OSError:
        return False


def _psm_from_cache(mac):
    """The phone's cover-art OBEX L2CAP PSM, from BlueZ's SDP record cache.

    iPhones advertise the AVRCP cover-art OBEX server only inside the AVRCP
    target record's additional protocol list — obexd's own SDP search (which
    looks for an Imaging 0x111A record) can't find it, so the PSM must be
    passed to CreateSession explicitly. The cache line format is
    ``handle=hex-encoded-record``; the pattern below is the DES encoding of
    "L2CAP + uint16 PSM followed by OBEX UUID". 0 = not found.
    """
    import glob
    import re
    for f in glob.glob(f"/var/lib/bluetooth/*/cache/{mac}"):
        try:
            raw = open(f).read()
        except OSError:
            continue
        for line in raw.splitlines():
            if "=" not in line:
                continue
            hexrec = line.split("=", 1)[1].strip().lower()
            m = re.search(r"350619010009([0-9a-f]{4})3503190008", hexrec)
            if m:
                return int(m.group(1), 16)
    return 0


class _ArtFetcher:
    """Cover art via obexd's BIP client (``org.bluez.obex.Image1``).

    Creates a ``bip-avrcp`` OBEX session to the phone and pulls the 200x200
    thumbnail for the current track's ``ImgHandle`` into ``/tmp``. Needs
    BlueZ >= 5.79 with obexd on the system bus; on the stock 5.66 stack
    ``ImgHandle`` never appears so this never runs. Fetch failures are logged
    once per track and not retried until the track changes.

    Uses dbus-python (Debian ``python3-dbus``, reached via the system
    dist-packages path) with one long-lived system-bus connection — obexd
    destroys a client session the moment its creating D-Bus connection goes
    away, so sessions made through one-shot ``busctl`` calls die instantly.
    Without the module (dev Mac), cover art is silently disabled.
    """

    def __init__(self):
        self._dbus = None         # dbus module, once importable
        self._bus = None          # persistent SystemBus connection
        self._session = None      # obex session object path
        self._key = None          # (mac, handle) last attempted
        self._path = ""           # art file of the current key ("" = failed)
        self._seq = 0
        self._primed = None       # device we already opened a session for
        self._retry_at = 0.0      # backoff for failed prime attempts
        self._disabled = False

    def _ensure_bus(self):
        if self._bus is None:
            import sys
            if "/usr/lib/python3/dist-packages" not in sys.path:
                sys.path.append("/usr/lib/python3/dist-packages")
            import dbus
            self._dbus = dbus
            self._bus = dbus.SystemBus()
        return self._bus

    def _iface(self, path, iface):
        bus = self._ensure_bus()
        return self._dbus.Interface(bus.get_object(_OBEX, path), iface)

    def prime(self, mac):
        """Open the BIP session as soon as a phone has a player: iPhones only
        start including the cover-art handle in track metadata once the
        imaging OBEX channel is connected (chicken-and-egg otherwise).
        Retries with backoff — right at connect the SDP cache (where the PSM
        comes from) may still be mid-rewrite."""
        if self._disabled or not mac or self._primed == mac:
            return
        if time.monotonic() < self._retry_at:
            return
        try:
            self._ensure_session(mac)
            self._primed = mac
            print("[bt] cover art session open", flush=True)
        except ImportError:
            self._disabled = True
            print("[bt] python3-dbus missing — cover art disabled", flush=True)
        except Exception as e:
            self._retry_at = time.monotonic() + 5.0
            print("[bt] cover art session failed (will retry):", e, flush=True)

    @property
    def key(self):
        """The (mac, handle) the cached ``current()`` result belongs to."""
        return self._key

    def reset(self):
        """Phone gone: forget the session so the next connect re-primes."""
        self._drop_session()
        self._primed = None
        self._retry_at = 0.0

    def _ensure_session(self, mac):
        if self._session is None:
            psm = _psm_from_cache(mac)
            client = self._iface("/org/bluez/obex", _OBEX + ".Client1")
            args = {"Target": "bip-avrcp"}
            if psm:  # iPhones: PSM only in the AVRCP record, SDP can't find it
                args["PSM"] = self._dbus.UInt16(psm)
            self._session = str(client.CreateSession(mac, args, timeout=20))
        return self._session

    def _drop_session(self):
        if self._session is not None and self._bus is not None:
            try:
                self._iface("/org/bluez/obex", _OBEX + ".Client1") \
                    .RemoveSession(self._dbus.ObjectPath(self._session),
                                   timeout=10)
            except Exception:
                pass
        self._session = None

    def _thumbnail(self, mac, handle, target):
        session = self._ensure_session(mac)
        img = self._iface(session, _OBEX + ".Image1")
        transfer, _props = img.GetThumbnail(target, handle, timeout=20)
        props = self._iface(str(transfer), "org.freedesktop.DBus.Properties")
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                status = str(props.Get(_OBEX + ".Transfer1", "Status"))
            except Exception:
                status = ""  # transfer object gone: completed transfers vanish
            if status == "complete":
                return True
            if status == "error":
                return False
            if status == "":
                return os.path.exists(target)
            time.sleep(0.3)
        return False

    def current(self, mac, handle):
        """Art file path for (mac, handle), fetching on change; "" if none."""
        if self._disabled or not (mac and handle):
            return ""
        key = (mac, handle)
        if key == self._key:
            return self._path
        self._key = key
        old = self._path
        self._path = ""
        self._seq += 1
        target = f"/tmp/track_art_{self._seq}.jpg"
        try:
            ok = self._thumbnail(mac, handle, target)
            if not ok:  # stale session (phone reconnect) — one clean retry
                self._drop_session()
                ok = self._thumbnail(mac, handle, target)
            if ok and _jpeg_complete(target):
                self._path = target
                if old:
                    try:
                        os.unlink(old)
                    except OSError:
                        pass
                print(f"[bt] cover art -> {target} "
                      f"({os.path.getsize(target)}B)", flush=True)
            else:
                print(f"[bt] cover art rejected (ok={ok}, "
                      f"truncated/aborted transfer) handle={handle}",
                      flush=True)
                try:  # never leave a partial file around
                    os.unlink(target)
                except OSError:
                    pass
        except Exception as e:
            self._drop_session()
            print("[bt] cover art fetch failed:", e, flush=True)
        return self._path


def _managed_objects():
    """One GetManagedObjects round-trip to bluetoothd, parsed from JSON."""
    proc = subprocess.run(
        ["busctl", "call", "--json=short", "--timeout=5", "org.bluez", "/",
         "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"busctl exit {proc.returncode}")
    return json.loads(proc.stdout)["data"][0]


def _log_changes(old, new):
    if new["bt_connected"] != old.get("bt_connected"):
        if new["bt_connected"]:
            print(f"[bt] connected: {new['bt_device'] or 'unknown device'}",
                  flush=True)
        else:
            print("[bt] disconnected", flush=True)
    played = (new["track_title"], new["track_artist"])
    if new["track_title"] and played != (old.get("track_title"),
                                         old.get("track_artist")):
        print(f"[bt] now playing: {new['track_artist']} - {new['track_title']}"
              f" ({new['track_album']})", flush=True)


class _TrackPresenter:
    """Atomic now-playing transitions (owner's call, 2026-08-06).

    On a skip, iOS updates the Track in staggered pushes — the ImgHandle
    changes first (often still under the old title), then the title lands
    with a *reissued* handle. Reacting to each push individually flashes
    placeholders and double-fetches the same artwork. Instead, the display
    keeps showing the OLD title/artist/art until the new track's metadata
    has been stable for a full poll AND its art has been fetched (or found
    unavailable) — then title, artist, album and cover swap in one go.
    Rapid skipping holds the current display until the skipping stops.
    """

    HELD = ("track_title", "track_artist", "track_album")

    def __init__(self, fetcher):
        self._fetcher = fetcher
        self._pending = None
        self._displayed = None

    def sample(self, state, vals, meta):
        """Advance the presentation; writes the held fields + art into state."""
        if not vals["track_title"]:
            if self._displayed is not None:  # only clear what WE displayed —
                for f in self.HELD:          # never the demo playlist's fields
                    setattr(state, f, "")
                state.track_art_path = ""
            self._pending = None
            self._displayed = None
            return
        key = (meta["device_mac"], vals["track_title"], vals["track_artist"],
               vals["track_album"], meta["img_handle"])
        if key == self._displayed:
            return
        if key != self._pending:
            self._pending = key   # first sighting — hold the old display
            return
        # stable for a full poll: fetch the art (blocking), then swap as one
        path = self._fetcher.current(meta["device_mac"], meta["img_handle"])
        for f in self.HELD:
            setattr(state, f, vals[f])
        state.track_art_path = path
        self._displayed = key

    def reset(self):
        self._pending = None
        self._displayed = None


def read_bt_media(state):
    """Feed Bluetooth media info into the state forever (thread entry point)."""
    last = {}
    down_logged = False
    art = _ArtFetcher()
    presenter = _TrackPresenter(art)
    while True:
        try:
            objects = _managed_objects()
        except FileNotFoundError:
            print("[bt] busctl not found — Bluetooth media disabled", flush=True)
            return
        except Exception as e:
            if not down_logged:
                print("[bt] BlueZ not reachable (setup_bluetooth.sh not run "
                      "yet?):", e, flush=True)
                down_logged = True
            time.sleep(10)
            continue
        down_logged = False

        vals, meta = parse_managed_objects(objects)
        if vals["bt_connected"]:
            state.stamp_bt()  # a real phone is here — demo playlist backs off
        # write only on change: with no phone around, the idle values land
        # once and then the demo playlist (demo.DemoFeed) owns the fields.
        # Title/artist/album are HELD BACK — the presenter swaps them
        # atomically together with the cover art (see _TrackPresenter).
        if vals != last:
            _log_changes(last, vals)
            last = vals
            for key, value in vals.items():
                if key not in _TrackPresenter.HELD:
                    setattr(state, key, value)  # direct writes — see docstring
        if not vals["bt_connected"]:
            art.reset()
            presenter.reset()
        elif meta["device_mac"]:
            art.prime(meta["device_mac"])
        presenter.sample(state, vals, meta)
        time.sleep(POLL_S)


if __name__ == "__main__":
    # standalone monitor: dump the parsed media state once a second
    while True:
        try:
            vals, meta = parse_managed_objects(_managed_objects())
            print(json.dumps({**vals, **meta}, indent=2, ensure_ascii=False),
                  flush=True)
        except Exception as e:
            print("error:", e, flush=True)
        time.sleep(1)
