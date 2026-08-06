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
from demo import DemoFeed
from gesture import FlashHold
from decisions import (NO_CAN_DEMO_DELAY, RENDER_START_DELAY, compute_alarms,
                       startup_index)

kivy.require("2.0.0")

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

class Dashboard(Widget):
    """Host: shows one swappable content layout under the global overlays
    (tell-tales, alarm banner, night dim) and delegates ``update`` to it.

    The active layout is switched with :meth:`next_layout` — bound to the ``L``
    key for bench/dev, and on the car to the high-beam stalk via the
    flash-and-hold gesture (one short flash, then pull and hold ~0.6 s — see
    ``gesture.py``). All layouts are built once up front so switching is
    instant and never re-triggers the gauges' startup sweep."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._flash_hold = FlashHold()

        self.layouts = [cls() for cls in LAYOUTS]
        self.active = startup_index([cls.name for cls in LAYOUTS])
        self.add_widget(self.layouts[self.active])

        # global overlays — added after the layout so they draw on top and
        # persist across every switch
        self.top_alerts = TopAlerts()
        self.add_widget(self.top_alerts)
        # tell-tale bulb check timed to finish with the gauges' startup sweep
        self.top_alerts.start_bulb_check(RENDER_START_DELAY)
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

    def update(self, state, demo_t=None):
        """Update the active layout from shared state, plus the global overlays.

        Args:
            state: A ``SensorState`` instance, continuously updated by the CAN
                and GPIO reader threads (see model.py for the full schema).
            demo_t: Seconds since the no-CAN demo loop engaged, or ``None`` when
                running on real CAN. Drives the tell-tale bulb-check animation.
        """
        if self._flash_hold.sample(state.io.high_beam, time.monotonic()):
            print("[gesture] flash+hold -> next layout", flush=True)
            self.next_layout()
        self.layouts[self.active].update(state)
        self.top_alerts.set_state(state, demo_t)
        self.night_dim.set_night(state.night)
        self.alarm_bar.set_alarms(compute_alarms(state))


# ============================================================================
# Application Entry Point
# ============================================================================

class CarClusterApp(App):
    """Main Kivy application for the car cluster dashboard."""

    def __init__(self, state=None):
        super().__init__()
        self.state = state or SensorState()
        self.dashboard = None
        self._demo = DemoFeed()

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
            demo_t = self._demo.feed(self.state, time.monotonic())
        else:
            self._demo.reset(self.state)
            demo_t = None
        self.dashboard.update(self.state, demo_t)


def run_cluster(state):
    """
    Run the cluster application against the provided sensor state.

    Args:
        state: A ``SensorState`` instance to display (and read live updates from).
    """
    try:
        app = CarClusterApp(state)
        app.run()
    except Exception:
        # full stack into the journal — it's the only diagnostic channel on
        # the headless Pi
        import traceback
        traceback.print_exc()


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    print(f"Window size: {Window.size}")

    # Standalone run (no start_cluster.py): feed the map layout's position from
    # the GPS thread as well — mock drive, or a real USB module if present.
    from threading import Thread
    from gps_helper import read_gps

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

    Thread(target=read_gps, args=(state,), daemon=True).start()
    run_cluster(state)
