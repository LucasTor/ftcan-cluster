"""Shared, UI-free decision logic for the cluster.

Both frontends — the Kivy build (cluster.py / widgets/top_alerts.py) and the
QML build (cluster_qml.py SensorBridge) — must render the same decisions:
which tell-tales are lit, which critical alarms are active, the boot
bulb-check animation. This module is the single source for those decisions
and their thresholds, so a tuning change lands in both builds at once.
Pure Python: no Kivy, no Qt.
"""

import os

# --- engine state gate ---
# Below this the engine is off / cranking: lambda pegs lean on ambient O2 and
# oil pressure is naturally low, so mixture/oil warnings are meaningless.
MIN_RUNNING_RPM = 500

# --- critical alarm thresholds (the bottom red banner) ---
ALARM_LEAN_LAMBDA = 1.05       # lean mixture
ALARM_OVERHEAT_C = 110         # coolant overheat
ALARM_OIL_PRESS_BAR = 1.0      # minimum oil pressure...
ALARM_OIL_PRESS_RPM = 1500     # ...only checked above this rpm (idle runs lower)
ALARM_EGT_C = 750              # any cylinder EGT above this is too hot

# --- tell-tale thresholds ---
EGT_HOT_C = ALARM_EGT_C        # hottest-cylinder EGT tell-tale
LAMBDA_LEAN = ALARM_LEAN_LAMBDA  # lambda above this = lean (red)
LAMBDA_RICH = 0.75             # lambda below this = over-rich (amber)
TEMP_WARN_C = 100              # coolant tell-tale (below the alarm threshold)
OIL_WARN_BAR = 0.8             # genuine loss of oil pressure (0 = no sender)
FUEL_LOW_PCT = 15              # low-fuel tell-tale (0 = no sender)

# --- timing ---
# After this many seconds with no CAN frame, run the animated demo loop so the
# cluster shows live values on a bench / when not connected to the car.
NO_CAN_DEMO_DELAY = 3.0
# Start rendering live data once the gauges' startup sweep has finished.
RENDER_START_DELAY = 5.0
CHASE_HOLD = 1.6               # bulb check: seconds of everything-on after the chase

# --- startup intro sweep (both gauges and the big dial), milliseconds ---
# The whole intro must land before RENDER_START_DELAY unleashes live data.
INTRO_PAUSE_MS = 2500          # let the display come up so the sweep is visible
INTRO_SWEEP_MS = 700           # needle 0 -> full scale
INTRO_GAUGE_HOLD_MS = 600      # street gauges hold at full scale...
INTRO_DIAL_HOLD_MS = 700       # ...the detail dial holds a touch longer
INTRO_RETURN_MS = 700          # full scale -> 0
assert (INTRO_PAUSE_MS + INTRO_SWEEP_MS
        + max(INTRO_GAUGE_HOLD_MS, INTRO_DIAL_HOLD_MS)
        + INTRO_RETURN_MS) <= RENDER_START_DELAY * 1000

# --- session peaks ---
class PeakTracker:
    """Modern-car 'peak recall': highest rpm / boost / speed / EGT since
    power-on (session-only — the read-only Pi has nowhere to persist them).
    The bench demo does feed it so the tile animates, but the first real CAN
    frame after a demo episode resets the maxima, so a real drive never shows
    simulated peaks (same ownership rule as the demo media playlist)."""

    def __init__(self):
        self.reset()
        self._was_demo = False

    def reset(self):
        self.rpm = self.boost = self.speed = self.egt = 0.0

    def update(self, state, demo_active):
        if self._was_demo and not demo_active:
            self.reset()
        self._was_demo = demo_active
        self.rpm = max(self.rpm, state.rpm)
        self.boost = max(self.boost, state.map)
        self.speed = max(self.speed, state.wheel_speed_fl_kmh)
        self.egt = max(self.egt, state.egt1, state.egt2, state.egt3, state.egt4)


# --- clock ---
# The Pi has no RTC and the car no internet, so wall time comes from the GPS
# RMC sentences (gps_helper stamps gps_time_utc/_mono). RS runs UTC-3 all year
# (Brazil abolished DST in 2019).
CLOCK_UTC_OFFSET_H = -3


def clock_text(state, now_mono):
    """Wall clock 'HH:MM' extrapolated from the last GPS fix; '' before one."""
    if state.gps_time_utc <= 0:
        return ""
    t = (state.gps_time_utc + (now_mono - state.gps_time_mono)
         + CLOCK_UTC_OFFSET_H * 3600)
    m = int(t // 60) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


# --- layouts ---
LAYOUT_NAMES = ["street", "detail", "map"]
STARTUP_LAYOUT = os.environ.get("LAYOUT", "street")


def startup_index(names=None):
    """Resolve STARTUP_LAYOUT (a name or an index string) to a layout index."""
    names = LAYOUT_NAMES if names is None else names
    if STARTUP_LAYOUT in names:
        return names.index(STARTUP_LAYOUT)
    try:
        return int(STARTUP_LAYOUT) % len(names)
    except (ValueError, ZeroDivisionError):
        return 0


# --- tell-tale row spec ---
# (key, MDI codepoint, colour name, blinks) — icons are Material Design Icons
# codepoints; colour names resolve to each UI's theme (theme.TT_* / Theme.tt*).
# Between the turn arrows, ordered least -> most important left to right:
# plain status lights first, then armed modes, then warnings, ending with the
# you-are-breaking-the-engine criticals.
PILLS = [
    ("left",    0xF0731, "green", False),  # arrow-left-bold
    ("high",    0xF0C4C, "blue",  False),  # car-light-high
    ("fan",     0xF0210, "blue",  False),  # fan
    ("booster", 0xF0874, "amber", False),  # gauge-full (choke lever reused)
    ("2step",   0xF0238, "red",   False),  # fire
    ("fuel",    0xF0298, "red",   False),  # gas-station
    ("brake",   0xF0D5F, "red",   False),  # car-brake-parking
    ("batt",    0xF010C, "red",   False),  # car-battery
    ("lambda",  0xF0627, "red",   True),   # lambda (red lean / amber rich)
    ("egt",     0xF0E03, "red",   True),   # thermometer-chevron-up
    ("temp",    0xF03C8, "red",   True),   # coolant-temperature
    ("oil",     0xF03C7, "red",   True),   # oil (can)
    ("right",   0xF0734, "green", False),  # arrow-right-bold
]
PILL_KEYS = [p[0] for p in PILLS]


def compute_pills(state):
    """Which tell-tales are active, from the sensor state.

    Values are truthy/falsy; the lambda pill returns a colour name ("red" for
    lean / "amber" for over-rich) that overrides its default colour. Only
    signals we actually have are wired; BATT stays dark until a source exists,
    which keeps the cluster calm rather than showing warnings we can't
    substantiate.
    """
    io = state.io
    lam = False
    if state.rpm > MIN_RUNNING_RPM:
        if state.lambda_afr > LAMBDA_LEAN:
            lam = "red"
        elif state.lambda_afr < LAMBDA_RICH:
            lam = "amber"
    return {
        "left":  io.left_indicator,
        "right": io.right_indicator,
        "high":  io.high_beam,
        "booster": io.choke,  # booster arm switch on the old choke lever
        "temp":  state.engine_temp > TEMP_WARN_C,
        "egt":   max(state.egt1, state.egt2, state.egt3, state.egt4) > EGT_HOT_C,
        "lambda": lam,
        # genuine loss of oil pressure only (avoid false alarms at rest)
        "oil":   state.rpm > MIN_RUNNING_RPM
                 and 0 < state.oil_pressure_bar < OIL_WARN_BAR,
        "fuel":  0 < state.fuel_level < FUEL_LOW_PCT,
        "fan":   state.radiator_fan,
        "2step": state.two_step,
        "brake": io.parking_brake,
        "batt":  False,
    }


def compute_alarms(state):
    """Active critical alarms for the bottom banner."""
    alarms = []
    if state.rpm < MIN_RUNNING_RPM:
        return alarms
    if state.lambda_afr > ALARM_LEAN_LAMBDA:
        alarms.append("LEAN")
    if state.engine_temp > ALARM_OVERHEAT_C:
        alarms.append("OVERHEAT")
    if (state.rpm > ALARM_OIL_PRESS_RPM
            and state.oil_pressure_bar < ALARM_OIL_PRESS_BAR):
        alarms.append("OIL PRESSURE")
    if max(state.egt1, state.egt2, state.egt3, state.egt4) > ALARM_EGT_C:
        alarms.append("EGT")
    return alarms


class BulbCheck:
    """The boot bulb check: chase down the pill row, then everything on.

    Timed to span ``duration`` seconds total (chase + CHASE_HOLD of all-on) so
    it ends with the gauges' startup sweep. ``frame(t)`` returns
    ``(chase_running, active_dict)`` for ``t`` seconds into the check, or
    ``None`` once the single full cycle has completed.
    """

    def __init__(self, duration, keys=None, hold=CHASE_HOLD):
        self.keys = list(PILL_KEYS if keys is None else keys)
        self.step = max(0.05, (duration - hold) / len(self.keys))
        self.duration = len(self.keys) * self.step + hold

    def frame(self, t):
        if t >= self.duration:
            return None
        t %= self.duration
        if t < len(self.keys) * self.step:
            lit = int(t / self.step)
            # chase: each slot is shorter than a blink period, suspend blinking
            return True, {k: i == lit for i, k in enumerate(self.keys)}
        return False, {k: True for k in self.keys}  # all on — blink pills blink


# --- Bluetooth media toast ---
# Transient now-playing overlay along the bottom of every layout. Envelope:
# fade in, hold, fade out; a retrigger mid-display keeps the alpha continuous
# and restarts the hold.
TOAST_FADE_IN_S = 0.25
TOAST_HOLD_S = 6.0
TOAST_FADE_OUT_S = 0.6

# MDI "disc" — the album-art placeholder until AVRCP cover art lands (needs
# BlueZ >= 5.79; see CLAUDE.md "Bluetooth audio" entry)
MEDIA_ART_ICON = 0xF05EE


class MediaToast:
    """The transient now-playing / connection toast.

    Pure logic (like ``BulbCheck``): feed ``sample()`` every frame and render
    the returned ``(alpha, line1, line2)``. Fires on a track change
    (title / artist) and on phone connect (device / "CONNECTED"); hides
    instantly when the phone drops off.
    """

    def __init__(self):
        self._prev_track = None   # (title, artist) last seen (None = unseeded)
        self._connected = None    # None until the first sample
        self._t0 = None           # toast start time (None = hidden)
        self._lines = ("", "")

    def _alpha_at(self, t):
        if self._t0 is None:
            return 0.0
        dt = t - self._t0
        if dt < TOAST_FADE_IN_S:
            return dt / TOAST_FADE_IN_S
        dt -= TOAST_FADE_IN_S + TOAST_HOLD_S
        if dt < 0:
            return 1.0
        if dt < TOAST_FADE_OUT_S:
            return 1.0 - dt / TOAST_FADE_OUT_S
        return 0.0

    def _fire(self, t, line1, line2):
        # start so the fade-in resumes from the current alpha, not from 0
        self._t0 = t - TOAST_FADE_IN_S * self._alpha_at(t)
        self._lines = (line1, line2)

    def sample(self, t, connected, device, title, artist):
        """Toast alpha (0..1) and its two lines for monotonic time ``t``."""
        if connected != self._connected:
            was = self._connected
            self._connected = connected
            if connected and was is not None:
                self._fire(t, device or "BLUETOOTH", "CONNECTED")
            elif not connected:
                self._t0 = None
        track = (title, artist)
        if track != self._prev_track:
            self._prev_track = track
            if title:
                self._fire(t, title, artist)
        if self._t0 is None:
            return 0.0, "", ""
        if t - self._t0 >= TOAST_FADE_IN_S + TOAST_HOLD_S + TOAST_FADE_OUT_S:
            self._t0 = None
            return 0.0, "", ""
        return self._alpha_at(t), self._lines[0], self._lines[1]


def wifi_connected():
    """True if any wireless interface is associated/up (read from sysfs)."""
    base = "/sys/class/net"
    try:
        for iface in os.listdir(base):
            d = os.path.join(base, iface)
            if (os.path.isdir(os.path.join(d, "wireless"))
                    or os.path.exists(os.path.join(d, "phy80211"))):
                try:
                    with open(os.path.join(d, "operstate")) as f:
                        if f.read().strip() == "up":
                            return True
                except OSError:
                    continue
    except OSError:
        pass
    return False
