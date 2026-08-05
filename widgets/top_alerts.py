"""Top-of-cluster tell-tale row (the "alerts").

A horizontal row of bare icon tell-tales centred at the top of the cluster.
Each glyph sits calm and faint until its signal fires, then it lights up in its
ISO colour — matching the minimal Painel Gol design where the tell-tales stay
invisible until they have something to say. Turn signals, the 2-step and the
over-boost warning blink while active.
"""

import time

from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.core.window import Window
from kivy.clock import Clock

from theme import (
    FONT_ICONS, WINDOW_HEIGHT,
    TT_GREEN, TT_BLUE, TT_RED, TT_AMBER,
    PILL_OFF_TEXT,
)
from decisions import PILLS, BulbCheck, compute_pills, wifi_connected

PILL_HEIGHT = 40
PILL_GAP = 10
PILL_WIDTH = 48      # icon tell-tales are all the same width
ICON_SIZE = "32sp"   # MDI glyph size
ROW_TOP_MARGIN = 24  # gap between the window top and the pill row
BLINK_PERIOD = 0.4   # seconds per blink toggle
WIFI_MARGIN_X = 40   # left inset of the standalone WiFi tell-tale
WIFI_POLL = 3.0      # seconds between WiFi status checks

# colour names in the shared pill spec -> theme colours
PILL_COLORS = {"green": TT_GREEN, "blue": TT_BLUE, "red": TT_RED,
               "amber": TT_AMBER}


class TellTale(Widget):
    """A single bare tell-tale: an icon glyph, no outline."""

    def __init__(self, key, color, icon=None, blinks=False, **kwargs):
        super().__init__(**kwargs)
        self.key = key
        self.on_color = color
        self.blinks = blinks

        self.size_hint = (None, None)
        self.size = (PILL_WIDTH, PILL_HEIGHT)

        self._label = Label(
            text=icon, font_name=FONT_ICONS, font_size=ICON_SIZE,
            color=PILL_OFF_TEXT, halign="center", valign="middle",
        )
        self.add_widget(self._label)

        self.bind(pos=self._layout, size=self._layout)
        self.set_lit(False)

    def _layout(self, *_):
        self._label.pos = self.pos
        self._label.size = self.size
        self._label.text_size = self.size

    def set_lit(self, lit, color=None):
        """Light the glyph (optionally in a non-default colour) or dim it."""
        self._label.color = (color or self.on_color) if lit else PILL_OFF_TEXT


class TopAlerts(Widget):
    """Row of tell-tale pills across the top of the cluster.

    Which pills exist, their icons/colours and which are active all come from
    the shared ``decisions`` module (also consumed by the QML build); this
    widget only renders them and runs the blink/bulb-check presentation.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._active = {}
        self._blink_on = True
        self._demo_chase = False  # bulb-check chase running (suspends blink)
        self._boot_ev = None      # Clock event of the boot bulb check
        self._boot_t0 = 0.0
        self._bulb = None         # BulbCheck of the boot self-test

        self.row = BoxLayout(orientation="horizontal", size_hint=(None, None),
                             spacing=PILL_GAP, height=PILL_HEIGHT)
        self.pills = {}
        for key, codepoint, color, blinks in PILLS:
            pill = TellTale(key, PILL_COLORS[color], icon=chr(codepoint),
                            blinks=blinks)
            self.pills[key] = pill
            self.row.add_widget(pill)
        self.add_widget(self.row)

        self.row.width = (sum(p.width for p in self.pills.values())
                          + PILL_GAP * (len(self.pills) - 1))

        # standalone WiFi tell-tale (top-left): hidden unless connected, blue when up
        self.wifi_pill = TellTale("wifi", TT_BLUE, icon="\U000F05A9")  # wifi
        self.add_widget(self.wifi_pill)
        self.wifi_pill.opacity = 0

        self._reposition()
        Window.bind(on_resize=lambda *_: self._reposition())
        Clock.schedule_interval(self._blink, BLINK_PERIOD)
        Clock.schedule_once(self._check_wifi, 1)
        Clock.schedule_interval(self._check_wifi, WIFI_POLL)

    def _reposition(self, *_):
        top_y = WINDOW_HEIGHT - PILL_HEIGHT - ROW_TOP_MARGIN
        self.row.pos = ((Window.width - self.row.width) / 2, top_y)
        self.wifi_pill.pos = (WIFI_MARGIN_X, top_y)

    def _blink(self, _):
        self._blink_on = not self._blink_on
        self._refresh()

    def _check_wifi(self, _):
        if wifi_connected():
            self.wifi_pill.opacity = 1
            self.wifi_pill.set_lit(True)
        else:
            self.wifi_pill.opacity = 0

    def set_state(self, state, demo_t=None):
        """Recompute which tell-tales are active from the sensor state.

        Only signals we actually have are wired; the rest (BATT/CEL/BRAKE/2-STEP)
        stay dark until a source exists, which keeps the cluster calm rather than
        showing warnings we can't substantiate.

        With ``demo_t`` set (no-CAN bench demo), the row stays dark instead:
        the simulated drive loop would otherwise light warnings (temp, oil...)
        on every lap, drowning out the boot bulb check — which is left running
        if still in progress.
        """
        if demo_t is not None:
            if self._boot_ev is None:  # boot check done — dark in demo mode
                self._demo_chase = False
                self._active = {}
                self._refresh()
            return
        if self._boot_ev is not None:  # first real update ends the boot check
            self._boot_ev.cancel()
            self._boot_ev = None
        self._demo_chase = False
        self._active = compute_pills(state)
        self._refresh()

    def start_bulb_check(self, duration):
        """Run one chase + all-on bulb check spanning ``duration`` seconds.

        Fired at boot so the tell-tales self-test while the gauges do their
        startup sweep. It ends itself after one full cycle (demo mode keeps
        the row dark afterwards); the first real-CAN ``set_state`` cancels it
        early, so it never fights real data.
        """
        self._bulb = BulbCheck(duration, keys=list(self.pills))
        self._boot_t0 = time.monotonic()
        self._boot_ev = Clock.schedule_interval(self._boot_tick, 1 / 30)

    def _boot_tick(self, _):
        frame = self._bulb.frame(time.monotonic() - self._boot_t0)
        if frame is None:             # one full cycle, then done
            self._boot_ev.cancel()
            self._boot_ev = None
            self._demo_chase = False
            self._active = {}
        else:
            self._demo_chase, self._active = frame
        self._refresh()

    def _refresh(self):
        # _active values are truthy/falsy; a colour name ("red"/"amber") lights
        # the pill in that colour instead of its default (the lambda pill)
        for key, pill in self.pills.items():
            val = self._active.get(key, False)
            on = bool(val) and (not pill.blinks or self._blink_on or self._demo_chase)
            pill.set_lit(on, PILL_COLORS[val] if isinstance(val, str) else None)
