"""Car Cluster Dashboard — QML/Qt Quick build (parallel to the Kivy cluster.py).

Same architecture as the Kivy app: the CAN/GPIO/GPS reader threads write into
``model.SensorState``; here a 30 Hz timer mirrors that state into a
``SensorBridge`` QObject whose properties QML binds to, and Qt repaints only
what changed. All *decision* logic stays in Python (tell-tale states incl. the
boot bulb check, critical alarms, the no-CAN demo loop, the flash-and-hold
layout gesture); QML is presentation only.

Run standalone (self-animates via the no-CAN demo + mock GPS) or through
``start_cluster_qml.py`` for the full reader-thread setup.
"""

import os
import sys
import time

# Python-implemented updatePaintNode (map_item/ring_item) needs the
# single-threaded render loop — the threaded loop crashes into the GIL.
os.environ.setdefault("QSG_RENDER_LOOP", "basic")

from PySide6.QtCore import Property, QTimer, QUrl, Signal, Slot, QObject, Qt
from PySide6.QtGui import QGuiApplication, QCursor
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import QQuickView

from model import SensorState
from demo import simulate
from gesture import FlashHold
from map_item import MapItem
from ring_item import RingItem

DEV = os.environ.get('DEV', 'true').lower() == 'true'

# Startup layout: which registered layout to show first (name or index).
STARTUP_LAYOUT = os.environ.get("LAYOUT", "street")
LAYOUT_NAMES = ["street", "detail", "map"]

# Critical alarm thresholds (= cluster.py)
ALARM_LEAN_LAMBDA = 1.05
ALARM_OVERHEAT_C = 110
ALARM_OIL_PRESS_BAR = 1.0
ALARM_OIL_PRESS_RPM = 1500
ALARM_EGT_C = 750

NO_CAN_DEMO_DELAY = 3.0
RENDER_START_DELAY = 5.0

# Tell-tale thresholds / timing (= widgets/top_alerts.py)
EGT_HOT_C = 750
LAMBDA_LEAN = 1.05
LAMBDA_RICH = 0.75
CHASE_HOLD = 1.6
WIFI_POLL_MS = 3000
TICK_MS = 33            # ~30 Hz, matching the Kivy render loop

TT_GREEN, TT_BLUE, TT_RED, TT_AMBER, TT_CYAN = (
    "#33d17a", "#5aa6ea", "#ff5a45", "#ffb02e", "#22d3ee")

# (key, MDI codepoint, colour, blinks) — same order/colours as TopAlerts.PILLS
PILLS = [
    ("left",    0xF0731, TT_GREEN, False),   # arrow-left-bold
    ("high",    0xF0C4C, TT_BLUE,  False),   # car-light-high
    ("fan",     0xF0210, TT_BLUE,  False),   # fan
    ("booster", 0xF0874, TT_AMBER, False),   # gauge-full (choke lever reused)
    ("2step",   0xF0238, TT_RED,   False),   # fire
    ("fuel",    0xF0298, TT_RED,   False),   # gas-station
    ("brake",   0xF0D5F, TT_RED,   False),   # car-brake-parking
    ("batt",    0xF010C, TT_RED,   False),   # car-battery
    ("lambda",  0xF0627, TT_RED,   True),    # lambda (red lean / amber rich)
    ("egt",     0xF0E03, TT_RED,   True),    # thermometer-chevron-up
    ("temp",    0xF03C8, TT_RED,   True),    # coolant-temperature
    ("oil",     0xF03C7, TT_RED,   True),    # oil (can)
    ("right",   0xF0734, TT_GREEN, False),   # arrow-right-bold
]
_PILL_KEYS = [p[0] for p in PILLS]


def _wifi_connected():
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


def _startup_index():
    if STARTUP_LAYOUT in LAYOUT_NAMES:
        return LAYOUT_NAMES.index(STARTUP_LAYOUT)
    try:
        return int(STARTUP_LAYOUT) % len(LAYOUT_NAMES)
    except (ValueError, ZeroDivisionError):
        return 0


class SensorBridge(QObject):
    """QML-facing mirror of SensorState plus the cluster's decision logic."""

    ticked = Signal()
    layoutChanged = Signal()
    wifiChanged = Signal()

    def __init__(self, state):
        super().__init__()
        self._state = state
        self._active_layout = _startup_index()
        self._flash_hold = FlashHold()
        self._demo_t0 = None
        self._live = False
        self._alarms = []
        self._pill_active = {}
        self._pill_chase = False
        self._wifi = False

        # boot bulb check: chase down the row + all-on, timed to end with the
        # gauges' startup sweep (RENDER_START_DELAY), cancelled by real CAN
        self._boot_t0 = time.monotonic()
        self._boot_step = max(0.05, (RENDER_START_DELAY - CHASE_HOLD) / len(PILLS))
        self._boot_duration = len(PILLS) * self._boot_step + CHASE_HOLD
        self._boot_running = True

    # ---- sensor mirror (one notify signal; QML re-reads on each tick) ----

    _S = lambda attr, _sig=ticked: Property(   # noqa: E731 — tiny property factory
        float, lambda s, a=attr: float(getattr(s._state, a)), notify=_sig)

    rpm = _S("rpm")
    map = _S("map")
    tps = _S("tps")
    air_temp = _S("air_temp")
    engine_temp = _S("engine_temp")
    oil_temp = _S("oil_temp")
    oil_pressure_bar = _S("oil_pressure_bar")
    fuel_pressure_bar = _S("fuel_pressure_bar")
    lambda_afr = _S("lambda_afr")
    battery = _S("battery")
    fuel_level = _S("fuel_level")
    ethanol = _S("ethanol")
    egt1 = _S("egt1")
    egt2 = _S("egt2")
    egt3 = _S("egt3")
    egt4 = _S("egt4")
    lat = _S("lat")
    lon = _S("lon")
    heading_deg = _S("heading_deg")
    wheel_speed_fl_kmh = _S("wheel_speed_fl_kmh")
    del _S

    gear_label = Property(str, lambda s: str(s._state.gear_label), notify=ticked)
    night = Property(bool, lambda s: bool(s._state.night), notify=ticked)
    live = Property(bool, lambda s: s._live, notify=ticked)
    alarms = Property('QVariantList', lambda s: s._alarms, notify=ticked)
    pill_active = Property('QVariantMap', lambda s: s._pill_active, notify=ticked)
    pill_chase = Property(bool, lambda s: s._pill_chase, notify=ticked)
    wifi = Property(bool, lambda s: s._wifi, notify=wifiChanged)
    pill_model = Property('QVariantList', lambda s: [
        {"key": k, "icon": icon, "color": color, "blinks": blinks}
        for k, icon, color, blinks in PILLS], constant=True)

    active_layout = Property(int, lambda s: s._active_layout, notify=layoutChanged)

    @Slot()
    def next_layout(self):
        """Advance to the next registered layout (wraps around)."""
        self._active_layout = (self._active_layout + 1) % len(LAYOUT_NAMES)
        self.layoutChanged.emit()

    @Slot()
    def toggle_night(self):
        """Bench/dev: flip night mode ('N' key). On the car the ECU's
        day/night broadcast overwrites this on the next frame."""
        self._state.night = not self._state.night

    # ---- 30 Hz tick ----

    def tick(self):
        now = time.monotonic()
        state = self._state

        if self._boot_running:
            self._boot_tick(now)

        if not self._live and now - self._boot_t0 >= RENDER_START_DELAY:
            self._live = True   # gauges' startup sweep done: render live data

        if self._live:
            if self._flash_hold.sample(state.io.high_beam, now):
                print("[gesture] flash+hold -> next layout", flush=True)
                self.next_layout()
            demo_t = self._run_demo() if state.since_can() > NO_CAN_DEMO_DELAY else None
            if demo_t is None:
                self._demo_t0 = None
            self._set_pills(state, demo_t)
            self._alarms = self._compute_alarms(state)

        self.ticked.emit()

    def poll_wifi(self):
        wifi = _wifi_connected()
        if wifi != self._wifi:
            self._wifi = wifi
            self.wifiChanged.emit()

    def _run_demo(self):
        """Feed the animated simulation into the state when no CAN is present.

        Writes only engine/CAN-derived fields directly into the state —
        bypassing ``update()`` so it doesn't reset the CAN-activity clock.
        Real CAN frames take over automatically the moment they arrive.
        """
        if self._demo_t0 is None:
            self._demo_t0 = time.monotonic()
        demo_t = time.monotonic() - self._demo_t0
        vals = simulate(demo_t)
        s = self._state
        s.rpm = vals["rpm"]
        s.wheel_speed_fl_kmh = vals["speed"]
        s.map = vals["map"]
        s.lambda_afr = vals["lambda_afr"]
        s.engine_temp = vals["engine_temp"]
        s.air_temp = vals["air_temp"]
        s.oil_pressure_bar = vals["oil"]
        s.oil_temp = vals["oiltemp"]
        s.fuel_level = vals["fuel"]
        s.egt1, s.egt2, s.egt3, s.egt4 = (vals["egt1"], vals["egt2"],
                                          vals["egt3"], vals["egt4"])
        return demo_t

    # ---- tell-tales (port of TopAlerts.set_state / bulb check) ----

    def _boot_tick(self, now):
        t = now - self._boot_t0
        if t >= self._boot_duration:      # one full cycle, then done
            self._boot_running = False
            self._pill_chase = False
            self._pill_active = {}
            return
        t %= len(PILLS) * self._boot_step + CHASE_HOLD
        if t < len(PILLS) * self._boot_step:
            lit = int(t / self._boot_step)
            self._pill_chase = True       # each slot is shorter than a blink
            self._pill_active = {k: i == lit for i, k in enumerate(_PILL_KEYS)}
        else:
            self._pill_chase = False      # all on — let the blink pills blink
            self._pill_active = {k: True for k in _PILL_KEYS}

    def _set_pills(self, state, demo_t):
        """Recompute the active tell-tales; see TopAlerts.set_state for why
        the row stays dark in demo mode and which signals are wired."""
        if demo_t is not None:
            if not self._boot_running:    # boot check done — dark in demo mode
                self._pill_chase = False
                self._pill_active = {}
            return
        self._boot_running = False        # first real update ends the boot check
        self._pill_chase = False
        io = state.io
        fuel = state.fuel_level
        lam = False
        if state.rpm > 500:
            if state.lambda_afr > LAMBDA_LEAN:
                lam = TT_RED
            elif state.lambda_afr < LAMBDA_RICH:
                lam = TT_AMBER
        self._pill_active = {
            "left":  io.left_indicator,
            "right": io.right_indicator,
            "high":  io.high_beam,
            "booster": io.choke,
            "temp":  state.engine_temp > 100,
            "egt":   max(state.egt1, state.egt2, state.egt3, state.egt4) > EGT_HOT_C,
            "lambda": lam,
            "oil":   state.rpm > 500 and 0 < state.oil_pressure_bar < 0.8,
            "fuel":  0 < fuel < 15,
            "fan":   state.radiator_fan,
            "2step": state.two_step,
            "brake": io.parking_brake,
            "batt":  False,
        }

    @staticmethod
    def _compute_alarms(state):
        """Active critical alarms for the bottom banner (= cluster.Dashboard)."""
        alarms = []
        if state.rpm < 500:
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


def create_app(state):
    """Build the Qt app + view + bridge (also used by capture harnesses)."""
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    qmlRegisterType(MapItem, "Cluster", 1, 0, "MapItem")
    qmlRegisterType(RingItem, "Cluster", 1, 0, "RingItem")

    bridge = SensorBridge(state)
    view = QQuickView()
    # 4x MSAA smooths every drawn edge (arcs, ticks, needles, map ribbons).
    # Well within the Pi's V3D budget at 1920x720, but check the journal's
    # [map] redraw log after first deploy anyway.
    fmt = view.format()
    fmt.setSamples(4)
    view.setFormat(fmt)
    scale = 0.5 if DEV else 1.0
    view.rootContext().setContextProperty("sensors", bridge)
    view.rootContext().setContextProperty("dev_scale", scale)
    qml_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml")
    view.setSource(QUrl.fromLocalFile(os.path.join(qml_dir, "Main.qml")))
    if view.status() == QQuickView.Error:
        raise RuntimeError("\n".join(e.toString() for e in view.errors()))
    view.resize(int(1920 * scale), int(720 * scale))
    if not DEV:
        view.setCursor(QCursor(Qt.BlankCursor))

    ticker = QTimer(bridge)
    ticker.setInterval(TICK_MS)
    ticker.timeout.connect(bridge.tick)
    ticker.start()
    wifi_timer = QTimer(bridge)
    wifi_timer.setInterval(WIFI_POLL_MS)
    wifi_timer.timeout.connect(bridge.poll_wifi)
    wifi_timer.start()
    QTimer.singleShot(1000, bridge.poll_wifi)

    return app, view, bridge


def run_cluster(state):
    """Run the cluster application against the provided sensor state."""
    try:
        app, view, _bridge = create_app(state)
        view.show()
        app.exec()
    except Exception as e:
        print(f"Error running cluster: {e}")


if __name__ == "__main__":
    # Standalone run: feed the map layout's position from the GPS thread as
    # well — mock drive, or a real USB module if present.
    from threading import Thread
    from gps_helper import read_gps

    state = SensorState()
    Thread(target=read_gps, args=(state,), daemon=True).start()
    run_cluster(state)
