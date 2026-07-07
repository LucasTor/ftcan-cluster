"""
Car Cluster Dashboard Application

Main application file for the car cluster display system.
"""

import os
import time
from kivy.config import Config

from theme import WINDOW_WIDTH, WINDOW_HEIGHT, BG

# Development mode flag
DEV = os.environ.get('DEV', 'true').lower() == 'true'

if DEV:
    os.environ['KIVY_METRICS_DENSITY'] = '1'
    os.environ['KIVY_DPI'] = '96'

Config.set('graphics', 'show_cursor', '0')  # must be before Window import
Config.set("graphics", "width", str(WINDOW_WIDTH))
Config.set("graphics", "height", str(WINDOW_HEIGHT))

import kivy
from kivy.app import App
from kivy.uix.widget import Widget
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.core.text import LabelBase, DEFAULT_FONT

from widgets import TopAlerts, AlarmBar, NightDim
from widgets.layouts import LAYOUTS
from model import SensorState
from demo import simulate

kivy.require("2.0.0")

# ============================================================================
# Configuration Constants
# ============================================================================

# Startup layout: which registered layout to show first (name or index).
STARTUP_LAYOUT = os.environ.get("LAYOUT", "0")

# Critical alarm thresholds (the bottom red banner)
ALARM_LEAN_LAMBDA = 1.05       # lean mixture
ALARM_OVERHEAT_C = 110         # coolant overheat
ALARM_OIL_PRESS_BAR = 1.0      # minimum oil pressure...
ALARM_OIL_PRESS_RPM = 1500     # ...only checked above this rpm (idle runs lower)
ALARM_EGT_C = 750              # any cylinder EGT above this is too hot

# After this many seconds with no CAN frame, run the animated demo loop so the
# cluster shows live values on a bench / when not connected to the car.
NO_CAN_DEMO_DELAY = 3.0

# Start rendering live data once the gauges' startup sweep has finished.
RENDER_START_DELAY = 5.0

# ============================================================================
# Application Setup
# ============================================================================


Window.show_fps = False
Window.clearcolor = BG  # near-black background for the minimal look

# Register custom font
LabelBase.register(DEFAULT_FONT, "fonts/Compagnon-Medium.otf")


# ============================================================================
# Dashboard Widget
# ============================================================================

def _startup_index():
    """Resolve STARTUP_LAYOUT (a name or an index string) to a layout index."""
    names = [cls.name for cls in LAYOUTS]
    if STARTUP_LAYOUT in names:
        return names.index(STARTUP_LAYOUT)
    try:
        return int(STARTUP_LAYOUT) % len(LAYOUTS)
    except (ValueError, ZeroDivisionError):
        return 0


class Dashboard(Widget):
    """Host: shows one swappable content layout under the global overlays
    (tell-tales, alarm banner, night dim) and delegates ``update`` to it.

    The active layout is switched with :meth:`next_layout` — bound to the ``L``
    key for bench/dev; wire it to a GPIO button (or a FuelTech CAN dash button)
    on the car. All layouts are built once up front so switching is instant and
    never re-triggers the gauges' startup sweep."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.layouts = [cls() for cls in LAYOUTS]
        self.active = _startup_index()
        self.add_widget(self.layouts[self.active])

        # global overlays — added after the layout so they draw on top and
        # persist across every switch
        self.top_alerts = TopAlerts()
        self.add_widget(self.top_alerts)
        self.night_dim = NightDim()
        self.add_widget(self.night_dim)
        self.alarm_bar = AlarmBar()
        self.add_widget(self.alarm_bar)

        Window.bind(on_key_down=self._on_key)

        if DEV:
            Window.size = (WINDOW_WIDTH / 2, WINDOW_HEIGHT / 2)

    def next_layout(self):
        """Advance to the next registered layout (wraps around)."""
        self.remove_widget(self.layouts[self.active])
        self.active = (self.active + 1) % len(self.layouts)
        # re-insert the content beneath the overlays (end of the children list)
        self.add_widget(self.layouts[self.active], index=len(self.children))

    def _on_key(self, _window, key, _scancode, codepoint, _modifiers):
        if codepoint == "l":            # 'L' cycles layouts (dev / bench)
            self.next_layout()
            return True

    def update(self, state):
        """Update the active layout from shared state, plus the global overlays.

        Args:
            state: A ``SensorState`` instance, continuously updated by the CAN
                and GPIO reader threads (see model.py for the full schema).
        """
        self.layouts[self.active].update(state)
        self.top_alerts.set_state(state)
        self.night_dim.set_night(state.night)
        self.alarm_bar.set_alarms(self._alarms(state))

    @staticmethod
    def _alarms(state):
        """Active critical alarms for the bottom banner."""
        alarms = []
        # engine not running (off / cranking) — these readings aren't meaningful
        # (lambda pegs lean on ambient O2, etc.), so keep the banner clear.
        if state.rpm < 500:
            return alarms
        if state.lambda_afr > ALARM_LEAN_LAMBDA:
            alarms.append("LEAN")
        if state.engine_temp > ALARM_OVERHEAT_C:
            alarms.append("OVERHEAT")
        # low oil pressure, but only above idle (idle naturally runs lower)
        if state.rpm > ALARM_OIL_PRESS_RPM and state.oil_pressure_bar < ALARM_OIL_PRESS_BAR:
            alarms.append("OIL PRESSURE")
        if max(state.egt1, state.egt2, state.egt3, state.egt4) > ALARM_EGT_C:
            alarms.append("EGT")
        return alarms


# ============================================================================
# Application Entry Point
# ============================================================================

class CarClusterApp(App):
    """Main Kivy application for the car cluster dashboard."""

    def __init__(self, state=None):
        super().__init__()
        self.state = state or SensorState()
        self.dashboard = None
        self._demo_t0 = None  # monotonic time the demo loop engaged

    def build(self):
        """Build and return the main dashboard widget."""
        self.dashboard = Dashboard()
        return self.dashboard

    def on_start(self):
        """Start the render loop once the gauges have finished their intro sweep."""
        Clock.schedule_once(
            lambda _: Clock.schedule_interval(self.update_values, 1 / 30), RENDER_START_DELAY
        )

    def update_values(self, _):
        """Render the current state, falling back to the demo loop with no CAN."""
        if not self.dashboard:
            return
        if self.state.since_can() > NO_CAN_DEMO_DELAY:
            self._run_demo()
        else:
            self._demo_t0 = None
        self.dashboard.update(self.state)

    def _run_demo(self):
        """Feed the animated simulation into the state when no CAN is present.

        Writes only engine/CAN-derived fields (not GPIO inputs) directly into the
        state — bypassing ``update()`` so it doesn't reset the CAN-activity clock.
        Real CAN frames take over automatically the moment they arrive.
        """
        if self._demo_t0 is None:
            self._demo_t0 = time.monotonic()
        vals = simulate(time.monotonic() - self._demo_t0)
        s = self.state
        s.rpm = vals["rpm"]
        s.wheel_speed_fl_kmh = vals["speed"]
        s.map = vals["map"]
        s.lambda_afr = vals["lambda_afr"]
        s.engine_temp = vals["engine_temp"]
        s.air_temp = vals["air_temp"]
        s.oil_pressure_bar = vals["oil"]
        s.oil_temp = vals["oiltemp"]
        s.fuel_level = vals["fuel"]
        s.egt1, s.egt2, s.egt3, s.egt4 = vals["egt1"], vals["egt2"], vals["egt3"], vals["egt4"]


def run_cluster(state):
    """
    Run the cluster application against the provided sensor state.

    Args:
        state: A ``SensorState`` instance to display (and read live updates from).
    """
    try:
        app = CarClusterApp(state)
        app.run()
    except Exception as e:
        print(f"Error running cluster: {e}")


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    print(f"Window size: {Window.size}")
    
    # Sample data for testing
    state = SensorState(
        wheel_speed_fl_kmh=63,
        lambda_afr=0.826,
        map=0.345,
        engine_temp=67,
        air_temp=102,
        rpm=1420,
        oil_pressure_bar=2.7,
        fuel_level=68,
    )

    run_cluster(state)
