"""Car Cluster Dashboard — QML/Qt Quick build (parallel to the Kivy cluster.py).

Same architecture as the Kivy app: the CAN/GPIO/GPS reader threads write into
``model.SensorState``; here a 30 Hz timer mirrors that state into a
``SensorBridge`` QObject whose properties QML binds to, and Qt repaints only
what changed. Every property has its own change signal and ``tick()`` emits
only the ones whose value actually moved, so a steady sensor costs no QML
binding re-evaluations. All *decision* logic lives in the shared ``decisions``
module (tell-tale states incl. the boot bulb check, critical alarms, the
thresholds) plus ``demo``/``gesture``; QML is presentation only.

Run standalone (self-animates via the no-CAN demo + mock GPS) or through
``start_cluster_qml.py`` for the full reader-thread setup.
"""

import os
import signal
import sys
import time

# Python-implemented updatePaintNode (map_item/ring_item) needs the
# single-threaded render loop — the threaded loop crashes into the GIL.
os.environ.setdefault("QSG_RENDER_LOOP", "basic")

from PySide6.QtCore import Property, QTimer, QUrl, Signal, Slot, QObject, Qt
from PySide6.QtGui import QGuiApplication, QCursor
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import QQuickView

import dial_spec
from decisions import (LAYOUT_NAMES, NO_CAN_DEMO_DELAY, RENDER_START_DELAY,
                       INTRO_PAUSE_MS, INTRO_SWEEP_MS, INTRO_GAUGE_HOLD_MS,
                       INTRO_DIAL_HOLD_MS, INTRO_RETURN_MS,
                       PILLS, BulbCheck, compute_alarms, compute_pills,
                       startup_index, wifi_connected)
from model import SensorState
from demo import DemoFeed
from gesture import FlashHold
from map_item import MapItem
from ring_item import RingItem

DEV = os.environ.get('DEV', 'true').lower() == 'true'

WIFI_POLL_MS = 3000
TICK_MS = 33            # ~30 Hz, matching the Kivy render loop

# QML-side intro sweep timing (ms), from the shared spec
_INTRO_QML = {
    "pause": INTRO_PAUSE_MS, "sweep": INTRO_SWEEP_MS,
    "gaugeHold": INTRO_GAUGE_HOLD_MS, "dialHold": INTRO_DIAL_HOLD_MS,
    "back": INTRO_RETURN_MS,
}

# state fields mirrored 1:1 as float properties (each gets its own
# <name>Changed signal; see the generation loop in SensorBridge)
_SENSOR_FLOATS = (
    "rpm", "map", "tps", "air_temp", "engine_temp", "oil_temp",
    "oil_pressure_bar", "fuel_pressure_bar", "lambda_afr", "battery",
    "fuel_level", "ethanol", "egt1", "egt2", "egt3", "egt4",
    "lat", "lon", "heading_deg", "wheel_speed_fl_kmh",
)


class SensorBridge(QObject):
    """QML-facing mirror of SensorState; decisions come from ``decisions``."""

    layoutChanged = Signal()
    wifiChanged = Signal()

    # ---- sensor mirror: one property + change signal per field. tick()
    # compares against the previously emitted value and fires only the signals
    # whose value moved, so bindings on steady sensors never re-evaluate ----
    _ns = locals()
    for _f in _SENSOR_FLOATS:
        _ns[_f + "Changed"] = Signal()
        _ns[_f] = Property(
            float, (lambda a: lambda s: float(getattr(s._state, a)))(_f),
            notify=_ns[_f + "Changed"])
    del _ns, _f

    gear_labelChanged = Signal()
    gear_label = Property(str, lambda s: str(s._state.gear_label),
                          notify=gear_labelChanged)
    nightChanged = Signal()
    night = Property(bool, lambda s: bool(s._state.night), notify=nightChanged)
    liveChanged = Signal()
    live = Property(bool, lambda s: s._live, notify=liveChanged)
    alarmsChanged = Signal()
    alarms = Property('QVariantList', lambda s: s._alarms, notify=alarmsChanged)
    pill_activeChanged = Signal()
    pill_active = Property('QVariantMap', lambda s: s._pill_active,
                           notify=pill_activeChanged)
    pill_chaseChanged = Signal()
    pill_chase = Property(bool, lambda s: s._pill_chase,
                          notify=pill_chaseChanged)
    wifi = Property(bool, lambda s: s._wifi, notify=wifiChanged)

    # ---- constants for QML (colour names resolve via Theme in TopAlerts) ----
    pill_model = Property('QVariantList', lambda s: [
        {"key": k, "icon": icon, "color": color, "blinks": blinks}
        for k, icon, color, blinks in PILLS], constant=True)
    dial = Property('QVariantMap', lambda s: dict(dial_spec.QML_SPEC),
                    constant=True)
    intro = Property('QVariantMap', lambda s: dict(_INTRO_QML), constant=True)

    active_layout = Property(int, lambda s: s._active_layout,
                             notify=layoutChanged)

    def __init__(self, state):
        super().__init__()
        self._state = state
        self._active_layout = startup_index(LAYOUT_NAMES)
        self._flash_hold = FlashHold()
        self._demo = DemoFeed()
        self._live = False
        self._alarms = []
        self._pill_active = {}
        self._pill_chase = False
        self._wifi = False
        self._prev = {}   # last-emitted value per property (change detection)

        # boot bulb check: chase down the row + all-on, timed to end with the
        # gauges' startup sweep (RENDER_START_DELAY), cancelled by real CAN
        self._boot_t0 = time.monotonic()
        self._bulb = BulbCheck(RENDER_START_DELAY)

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

        if self._bulb is not None:
            frame = self._bulb.frame(now - self._boot_t0)
            if frame is None:         # one full cycle, then done
                self._bulb = None
                self._pill_chase, self._pill_active = False, {}
            else:
                self._pill_chase, self._pill_active = frame

        if not self._live and now - self._boot_t0 >= RENDER_START_DELAY:
            self._live = True   # gauges' startup sweep done: render live data

        if self._live:
            if self._flash_hold.sample(state.io.high_beam, now):
                print("[gesture] flash+hold -> next layout", flush=True)
                self.next_layout()
            if state.since_can() > NO_CAN_DEMO_DELAY:
                demo_t = self._demo.feed(state, now)
            else:
                self._demo.reset()
                demo_t = None
            self._set_pills(state, demo_t)
            self._alarms = compute_alarms(state)

        self._emit_changes()

    def _emit_changes(self):
        """Fire the change signal of every property whose value moved."""
        prev = self._prev
        state = self._state
        for name in _SENSOR_FLOATS:
            v = float(getattr(state, name))
            if v != prev.get(name):
                prev[name] = v
                getattr(self, name + "Changed").emit()
        for name, v in (("gear_label", str(state.gear_label)),
                        ("night", bool(state.night)),
                        ("live", self._live),
                        ("pill_chase", self._pill_chase),
                        ("alarms", self._alarms),
                        ("pill_active", self._pill_active)):
            if v != prev.get(name):
                prev[name] = v
                getattr(self, name + "Changed").emit()

    def poll_wifi(self):
        wifi = wifi_connected()
        if wifi != self._wifi:
            self._wifi = wifi
            self.wifiChanged.emit()

    def _set_pills(self, state, demo_t):
        """Recompute the active tell-tales; with the no-CAN demo running the
        row stays dark instead (the simulated drive would light warnings on
        every lap, drowning out the boot bulb check — left running if still
        in progress)."""
        if demo_t is not None:
            if self._bulb is None:    # boot check done — dark in demo mode
                self._pill_chase = False
                self._pill_active = {}
            return
        self._bulb = None             # first real update ends the boot check
        self._pill_chase = False
        self._pill_active = compute_pills(state)


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
        # Ctrl-C: a KeyboardInterrupt raised inside a Qt-invoked Python slot
        # can't unwind through the C++ event loop, so SIGINT must quit the app
        # directly. The 30 Hz tick keeps Python bytecode running, which is
        # what gets the handler serviced.
        signal.signal(signal.SIGINT, lambda *_: app.quit())
        view.show()
        app.exec()
    except Exception:
        # full stack into the journal — it's the only diagnostic channel on
        # the headless Pi
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Standalone run: feed the map layout's position from the GPS thread as
    # well — mock drive, or a real USB module if present.
    from threading import Thread
    from gps_helper import read_gps

    state = SensorState()
    Thread(target=read_gps, args=(state,), daemon=True).start()
    run_cluster(state)
