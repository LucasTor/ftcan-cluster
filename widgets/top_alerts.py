"""Top-of-cluster tell-tale row (the "alerts").

A horizontal row of bare icon tell-tales centred at the top of the cluster.
Each glyph sits calm and faint until its signal fires, then it lights up in its
ISO colour — matching the minimal Painel Gol design where the tell-tales stay
invisible until they have something to say. Turn signals, the 2-step and the
over-boost warning blink while active.
"""

import os
import time

from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.core.window import Window
from kivy.clock import Clock

from theme import (
    FONT_ICONS, WINDOW_HEIGHT,
    TT_GREEN, TT_BLUE, TT_RED, TT_AMBER, TT_CYAN, TT_BOOST,
    PILL_OFF_TEXT,
)

PILL_HEIGHT = 40
PILL_GAP = 10
PILL_WIDTH = 48      # icon tell-tales are all the same width
ICON_SIZE = "32sp"   # MDI glyph size
ROW_TOP_MARGIN = 24  # gap between the window top and the pill row
BLINK_PERIOD = 0.4   # seconds per blink toggle
CHASE_STEP = 0.35    # demo bulb-check: seconds each tell-tale stays lit
CHASE_HOLD = 1.6     # demo bulb-check: seconds of everything-on after the chase
WIFI_MARGIN_X = 40   # left inset of the standalone WiFi tell-tale
WIFI_POLL = 3.0      # seconds between WiFi status checks
EGT_HOT_C = 750      # hottest-cylinder EGT tell-tale threshold (= cluster.ALARM_EGT_C)
LAMBDA_LEAN = 1.05   # lambda above this = lean, red (= cluster.ALARM_LEAN_LAMBDA)
LAMBDA_RICH = 0.75   # lambda below this = over-rich, amber


def _wifi_connected():
    """True if any wireless interface is associated/up (read straight from sysfs)."""
    base = "/sys/class/net"
    try:
        for iface in os.listdir(base):
            d = os.path.join(base, iface)
            if os.path.isdir(os.path.join(d, "wireless")) or os.path.exists(os.path.join(d, "phy80211")):
                try:
                    with open(os.path.join(d, "operstate")) as f:
                        if f.read().strip() == "up":
                            return True
                except OSError:
                    continue
    except OSError:
        pass
    return False


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
    """Row of tell-tale pills across the top of the cluster."""

    # (key, pill kwargs, colour, blinks) — icons are MDI codepoints.
    # Between the turn arrows, ordered least → most important left to right:
    # plain status lights first, then armed modes, then warnings, ending with
    # the you-are-breaking-the-engine criticals.
    PILLS = [
        ("left",    {"icon": "\U000F0731"}, TT_GREEN, False),  # arrow-left-bold
        ("high",    {"icon": "\U000F0C4C"}, TT_BLUE,  False),  # car-light-high
        ("fan",     {"icon": "\U000F0210"}, TT_BLUE,  False),  # fan
        ("booster", {"icon": "\U000F0874"}, TT_AMBER, False),  # gauge-full (choke lever reused as booster switch)
        ("2step",   {"icon": "\U000F0238"}, TT_RED,   False),  # fire
        ("fuel",    {"icon": "\U000F0298"}, TT_RED,   False),  # gas-station
        ("brake",   {"icon": "\U000F0D5F"}, TT_RED,   False),  # car-brake-parking
        # ("cel",     {"icon": "\U000F01FA"}, TT_AMBER, False),  # engine
        ("batt",    {"icon": "\U000F010C"}, TT_RED,   False),  # car-battery
        # ("boost",   {"icon": "\U000F101A"}, TT_BOOST, True),   # car-turbocharger
        ("lambda",  {"icon": "\U000F0627"}, TT_RED,   True),   # lambda (red lean / amber rich)
        ("egt",     {"icon": "\U000F0E03"}, TT_RED,   True),   # thermometer-chevron-up
        ("temp",    {"icon": "\U000F03C8"}, TT_RED,   True),   # coolant-temperature
        ("oil",     {"icon": "\U000F03C7"}, TT_RED,   True),   # oil (can)
        ("right",   {"icon": "\U000F0734"}, TT_GREEN, False),  # arrow-right-bold
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._active = {}
        self._blink_on = True
        self._demo_chase = False  # bulb-check chase running (suspends blink)
        self._boot_ev = None      # Clock event of the boot bulb check
        self._boot_t0 = 0.0
        self._boot_step = CHASE_STEP
        self._boot_duration = 0.0

        self.row = BoxLayout(orientation="horizontal", size_hint=(None, None),
                             spacing=PILL_GAP, height=PILL_HEIGHT)
        self.pills = {}
        for key, pill_kwargs, color, blinks in self.PILLS:
            pill = TellTale(key, color, blinks=blinks, **pill_kwargs)
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
        if _wifi_connected():
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
        io = state.io
        fuel = state.fuel_level
        # mixture: red when lean, amber when over-rich; meaningless below idle
        # (an off engine pegs lambda lean on ambient O2)
        lam = False
        if state.rpm > 500:
            if state.lambda_afr > LAMBDA_LEAN:
                lam = TT_RED
            elif state.lambda_afr < LAMBDA_RICH:
                lam = TT_AMBER
        self._active = {
            "left":  io.left_indicator,
            "right": io.right_indicator,
            "high":  io.high_beam,
            "booster": io.choke,  # booster arm switch on the old choke lever
            "temp":  state.engine_temp > 100,
            "egt":   max(state.egt1, state.egt2, state.egt3, state.egt4) > EGT_HOT_C,
            "lambda": lam,
            # genuine loss of oil pressure only (avoid false alarms at rest)
            "oil":   state.rpm > 500 and 0 < state.oil_pressure_bar < 0.8,
            "fuel":  0 < fuel < 15,
            "boost": state.map > 1.32,
            "fan":   state.radiator_fan,
            "2step": state.two_step,
            "brake": io.parking_brake,
            "batt":  False,
            "cel":   False,
        }
        self._refresh()

    def _set_demo(self, t, step=CHASE_STEP):
        """Bulb-check animation: chase down the row, then everything on."""
        keys = list(self.pills)
        cycle = len(keys) * step + CHASE_HOLD
        t = t % cycle
        if t < len(keys) * step:
            lit = int(t / step)
            self._demo_chase = True  # each slot is shorter than a blink period
            self._active = {key: i == lit for i, key in enumerate(keys)}
        else:
            self._demo_chase = False  # all on — let the blink pills blink
            self._active = {key: True for key in keys}
        self._refresh()

    def start_bulb_check(self, duration):
        """Run one chase + all-on bulb check spanning ``duration`` seconds.

        Fired at boot so the tell-tales self-test while the gauges do their
        startup sweep. It ends itself after one full cycle (demo mode keeps
        the row dark afterwards); the first real-CAN ``set_state`` cancels it
        early, so it never fights real data.
        """
        self._boot_step = max(0.05, (duration - CHASE_HOLD) / len(self.pills))
        self._boot_duration = len(self.pills) * self._boot_step + CHASE_HOLD
        self._boot_t0 = time.monotonic()
        self._boot_ev = Clock.schedule_interval(self._boot_tick, 1 / 30)

    def _boot_tick(self, _):
        t = time.monotonic() - self._boot_t0
        if t >= self._boot_duration:  # one full cycle, then done
            self._boot_ev.cancel()
            self._boot_ev = None
            self._demo_chase = False
            self._active = {}
            self._refresh()
            return
        self._set_demo(t, self._boot_step)

    def _refresh(self):
        # _active values are truthy/falsy; an RGBA tuple lights the pill in
        # that colour instead of its default (used by the lambda rich/lean pill)
        for key, pill in self.pills.items():
            val = self._active.get(key, False)
            on = bool(val) and (not pill.blinks or self._blink_on or self._demo_chase)
            pill.set_lit(on, val if isinstance(val, tuple) else None)
