"""Drive simulation used when there's no CAN signal (bench / not-in-car).

A ~15s loop — idle -> 2-step -> on-boost pull -> cruise -> decel — ported from
the Painel Gol design's animation. Only engine / CAN-derived fields are produced;
GPIO inputs (turn signals, headlights) are left to the real hardware.
"""

import math

CYCLE = 15.0  # seconds per loop

# Fake now-playing rotation so the bench also exercises the media toast and
# the map's NowPlaying: late-80s rock a '92 Gol would actually be playing
# (Engenheiros and Nenhum de Nós are gaúcho bands, matching the baked map).
# Each entry "plays" for TRACK_S seconds — short enough that the toast shows
# up regularly on the bench.
TRACK_S = 45.0
PLAYLIST = [
    ("Infinita Highway", "Engenheiros do Hawaii", "A Revolta dos Dândis"),
    ("Tempo Perdido", "Legião Urbana", "Dois"),
    ("O Astronauta de Mármore", "Nenhum de Nós", "Cardume"),
    ("Sonífera Ilha", "Titãs", "Cabeça Dinossauro"),
]
# Defer to bt_media_helper while it has seen a real phone this recently.
BT_REAL_HOLDOFF = 3.0


class DemoFeed:
    """Feeds the simulation into a ``SensorState`` while no CAN is present.

    Writes only engine/CAN-derived fields (not GPIO inputs) directly into the
    state — bypassing ``update()`` so it doesn't reset the CAN-activity clock.
    Real CAN frames take over automatically the moment they arrive. Both UI
    builds drive this from their render tick. Also rotates the fake
    ``PLAYLIST`` through the Bluetooth media fields — unless a real phone is
    connected (``state.since_bt()`` fresh), which always wins.
    """

    def __init__(self):
        self._t0 = None  # monotonic time the demo loop engaged
        self._media_owned = False  # we wrote the media fields (vs a real phone)

    def feed(self, state, now):
        """Write simulated values for ``now`` and return the demo elapsed time
        (drives the tell-tale bulb check)."""
        if self._t0 is None:
            self._t0 = now
        t = now - self._t0
        vals = simulate(t)
        state.rpm = vals["rpm"]
        state.wheel_speed_fl_kmh = vals["speed"]
        state.map = vals["map"]
        state.lambda_afr = vals["lambda_afr"]
        state.engine_temp = vals["engine_temp"]
        state.air_temp = vals["air_temp"]
        state.oil_pressure_bar = vals["oil"]
        state.oil_temp = vals["oiltemp"]
        state.fuel_level = vals["fuel"]
        state.egt1, state.egt2, state.egt3, state.egt4 = (
            vals["egt1"], vals["egt2"], vals["egt3"], vals["egt4"])
        self._feed_media(state, t)
        return t

    def _feed_media(self, state, t):
        if state.since_bt() < BT_REAL_HOLDOFF:
            self._media_owned = False  # a real phone owns the fields now
            return
        title, artist, album = PLAYLIST[int(t / TRACK_S) % len(PLAYLIST)]
        self._media_owned = True
        state.bt_connected = True
        state.bt_device = "DEMO"
        state.track_title = title
        state.track_artist = artist
        state.track_album = album
        state.track_status = "playing"
        state.track_position_s = t % TRACK_S
        state.track_duration_s = TRACK_S
        state.track_art_path = ""  # demo has no cover; the placeholder shows

    def _clear_media(self, state):
        state.bt_connected = False
        state.bt_device = ""
        state.track_title = ""
        state.track_artist = ""
        state.track_album = ""
        state.track_status = ""
        state.track_position_s = 0.0
        state.track_duration_s = 0.0
        state.track_art_path = ""

    def reset(self, state=None):
        if self._t0 is None:
            return  # called every live-CAN frame; only act on the transition
        self._t0 = None
        # the fake track must not linger once real CAN takes over
        if self._media_owned and state is not None:
            self._clear_media(state)
        self._media_owned = False


def _lerp(a, b, k):
    k = max(0.0, min(1.0, k))
    return a + (b - a) * k


def _ease(k):
    if k <= 0:
        return 0.0
    if k >= 1:
        return 1.0
    return k * k * (3 - 2 * k)


def simulate(t):
    """Return simulated sensor values (dict of SensorState fields) at time t."""
    t = t % CYCLE
    speed, rpm, boost, lam = 0.0, 900.0, -0.5, 0.99
    coolant, intake, oil, fuel = 80.0, 36.0, 3.2, 64.0

    if t < 2:  # idle
        rpm = 900 + 40 * math.sin(t * 9)
        boost, lam, coolant, intake = -0.5, 0.99, 78, 36
    elif t < 4:  # 2-step armed
        rpm = 4750 + 220 * math.sin(t * 22)
        boost = _lerp(0.2, 0.7, _ease((t - 2) / 2))
        lam, coolant, intake = 0.90, 84, 42
    elif t < 10:  # on boost, through the gears
        p = (t - 4) / 6
        speed = _lerp(0, 188, _ease(p))
        lp = ((t - 4) % 2.0) / 2.0
        rpm = _lerp(3700, 6850, lp)
        boost = 1.22 + 0.16 * math.sin((t - 4) * 3.0)
        lam, oil = 0.82, 3.6
        coolant, intake = _lerp(88, 104, p), _lerp(44, 63, p)
    elif t < 13:  # cruise
        p = (t - 10) / 3
        speed = _lerp(188, 118, p)
        rpm = 3000 + 60 * math.sin(t * 4)
        boost, lam, intake = 0.06, 0.95, 56
        coolant = _lerp(104, 101, p)
    else:  # decel
        p = (t - 13) / 2
        speed = _lerp(118, 0, _ease(p))
        rpm = _lerp(2600, 900, _ease(p))
        boost, lam, intake = -0.4, 1.03, 48
        coolant = _lerp(101, 96, p)

    # EGT per cylinder — rises with load; cyl 3 drifts hot on boost to show the
    # balance dots turning red, otherwise the four sit close (all green).
    base_egt = max(140.0, _lerp(360, 900, _ease(min(1.0, (rpm - 900) / 6000))) + boost * 90)
    offsets = [6.0, -10.0, (95.0 if boost > 0.8 else 12.0), -4.0]
    egt = [base_egt + o for o in offsets]

    return {
        "rpm": rpm, "speed": speed, "map": boost, "lambda_afr": lam,
        "engine_temp": coolant, "air_temp": intake, "oil": oil, "fuel": fuel,
        "oiltemp": coolant + 8,   # oil runs a little hotter than coolant
        "egt1": egt[0], "egt2": egt[1], "egt3": egt[2], "egt4": egt[3],
    }
