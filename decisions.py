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
