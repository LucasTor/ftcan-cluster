"""Swappable content layouts for the cluster.

A *layout* is the swappable content layer of the dashboard: gauges + readouts.
The host (``cluster.Dashboard``) keeps the global overlays that must appear in
every layout — tell-tales, the alarm banner, night dimming — and shows exactly
one layout underneath them, delegating ``update(state)`` to it.

Each layout is a plain ``Widget`` that builds its own children and exposes
``update(state)``. Add a new one by writing a class here and registering it in
``LAYOUTS`` (see ``cluster.py``).

  * ``StreetLayout``  — the minimal twin-dial view (SPEED + RPM + centre card).
  * ``DetailLayout``  — a dense RPM-dial + 4x3 stat-tile grid (GhostDash style).
  * ``MapLayout``     — perspective street map of São Marcos at the car's GPS
    position (mocked by ``gps_helper`` until the USB module arrives).
"""

from kivy.uix.widget import Widget
from kivy.uix.label import Label
from kivy.graphics import Color, Ellipse

from theme import (TT_RED, TT_AMBER, FONT_MONO, FONT_LIGHT, GAUGE_CENTER,
                   LABEL_ACCENT, LABEL_DIM)
from .gauge import Gauge
from .big_dial import BigDial
from .center_info import CenterInfo
from .stat_tile import StatTile
from .map_view import MapView


# Shift light: flash the RPM gauge above this engine speed.
SHIFT_RPM_THRESHOLD = 6000

# shift-light LEDs: green -> amber -> red as RPM approaches the shift point,
# all flashing red once at/above it.
_LED_GREEN = (0.20, 0.85, 0.30, 1.0)
_LED_AMBER = (1.0, 0.72, 0.10, 1.0)
_LED_RED = (1.0, 0.20, 0.12, 1.0)
_LED_OFF = (1.0, 1.0, 1.0, 0.10)
_LED_START = 3500     # rpm at which the first LED lights (up to SHIFT_RPM_THRESHOLD)


def _led_color(i, n):
    f = i / max(1, n - 1)
    return _LED_GREEN if f < 0.45 else (_LED_AMBER if f < 0.75 else _LED_RED)


def _rpm_text(v):
    """Full number below 1000 rpm, compact 'x.xk' at/above 1000."""
    v = int(v)
    return str(v) if v < 1000 else f"{v / 1000:.1f}k"


SPEED_GAUGE_CONFIG = {
    "title": "SPEED", "subtitle": "KM/H", "max_value": 240, "unit": "km/h",
    "size": (600, 600), "pos": (60, 60), "ticks": 13, "angle_range": 270,
}

RPM_GAUGE_CONFIG = {
    "title": "RPM", "subtitle": "X1000", "max_value": 8000, "unit": "rpm",
    "size": (600, 600), "pos": (1260, 60), "ticks": 9, "redline_from": 5500,
    "value_formatter": _rpm_text,
    "label_map": {n * 1000: str(n) for n in range(1, 9)},
}


class StreetLayout(Widget):
    """The minimal twin-dial view: SPEED (left) + RPM (right) + centre card."""

    name = "street"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.speed_gauge = Gauge(**SPEED_GAUGE_CONFIG)
        self.add_widget(self.speed_gauge)
        self.rpm_gauge = Gauge(**RPM_GAUGE_CONFIG)
        self.add_widget(self.rpm_gauge)
        self.center_info = CenterInfo()
        self.add_widget(self.center_info)

    def update(self, state):
        self.rpm_gauge.update_value(state.rpm)
        self.speed_gauge.update_value(state.wheel_speed_fl_kmh)
        self.rpm_gauge.set_shift(state.rpm >= SHIFT_RPM_THRESHOLD)
        self.center_info.set_values(
            intake_c=state.air_temp,
            water_c=state.engine_temp,
            oil_press_bar=state.oil_pressure_bar,
            lambda_val=state.lambda_afr,
            boost_bar=max(0.0, state.map),
            fuel_level=state.fuel_level,
            fuel_press_bar=state.fuel_pressure_bar,
            ethanol=state.ethanol,
            rpm=state.rpm,
            oil_temp=state.oil_temp,
        )
        self.center_info.set_egt((state.egt1, state.egt2, state.egt3, state.egt4))


# --- DetailLayout geometry (design space is WINDOW_WIDTH x WINDOW_HEIGHT) ---
DIAL_POS = (40, 60)
DIAL_SIZE = (600, 600)

_GRID_X0 = 700             # left edge of the tile grid
_GRID_TOP = 630            # top edge of the top tile row
TILE_W, TILE_H = 282, 180
GAP_X, GAP_Y = 16, 15

# (key, label, unit, vmin, vmax, fmt, warn, warn_color) laid out row-major. GEAR
# is a bar-less discrete tile; it fills the last row's first cell.
_TILES = [
    ("boost",  "BOOST",       "BAR", 0, 2,   "{:.2f}", lambda v: v > 1.32, TT_RED),
    ("fuel",   "FUEL LEVEL",  "%",   0, 100, "{:.0f}", None, None),
    ("engine", "ENGINE TEMP", "°C", 0, 120, "{:.0f}", lambda v: v > 104, TT_RED),
    ("intake", "INTAKE TEMP", "°C", 0, 110, "{:.0f}", lambda v: v > 58, TT_AMBER),
    ("batt",   "BATTERY",     "V",   8, 16,  "{:.1f}", lambda v: v < 11.5, TT_RED),
    ("fpress", "FUEL PRESS",  "BAR", 0, 6,   "{:.1f}", None, None),
    ("opress", "OIL PRESS",   "BAR", 0, 10,  "{:.1f}", None, None),
    ("ethanol", "ETHANOL",    "%",   0, 100, "E{:.0f}", None, None),
    None,  # empty slot (gear lives in the dial hub), matching the reference
    ("tps",    "TPS",         "%",   0, 100, "{:.0f}", None, None),
    ("map",    "MAP",         "BAR", 0, 3,   "{:.2f}", None, None),
    ("lambda", "LAMBDA",      "λ", 0.7, 1.3, "{:.2f}", lambda v: v > 1.05, TT_RED),
]


class DetailLayout(Widget):
    """Dense view: a left RPM dial (gear in the hub, RPM + shift LEDs in the
    bottom-right gap) and a 4x3 grid of stat tiles on the right (GhostDash)."""

    name = "detail"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Bold fill-style RPM ring: gear in the hub, RPM in the bottom gap.
        self.dial = BigDial(pos=DIAL_POS, size=DIAL_SIZE, max_value=8000, ticks=9,
                            label_map={n * 1000: str(n) for n in range(9)},
                            shift_from=SHIFT_RPM_THRESHOLD)
        self.add_widget(self.dial)

        # 4x3 tile grid (one empty slot where the reference has none)
        self.tiles = {}
        for i, spec in enumerate(_TILES):
            if spec is None:
                continue
            key, label, unit, vmin, vmax, fmt, warn, warn_color = spec
            col, row = i % 4, i // 4
            x = _GRID_X0 + col * (TILE_W + GAP_X)
            y = _GRID_TOP - TILE_H - row * (TILE_H + GAP_Y)
            tile = StatTile(label, unit=unit, vmin=vmin, vmax=vmax, fmt=fmt,
                            warn=warn, warn_color=warn_color, bar=(key != "gear"),
                            pos=(x, y), size=(TILE_W, TILE_H))
            self.add_widget(tile)
            self.tiles[key] = tile

        # big RPM readout + shift-lights in the bottom band, between the dial gap
        # and the empty tile slot
        rcx, rcy = 632, 186
        self._rpm = Label(text="0", font_name="fonts/Compagnon-Medium.otf", bold=True,
                          font_size="124sp", color=(0.97, 0.98, 1.0, 1.0),
                          halign="center", valign="middle", size_hint=(None, None),
                          size=(780, 150), pos=(rcx - 390, rcy - 75))
        self._rpm.text_size = self._rpm.size
        self.add_widget(self._rpm)
        self._sub = Label(text="RPM", font_name="fonts/ShareTechMono-Regular.ttf",
                          font_size="20sp", color=(0.353, 0.651, 0.918, 0.95),
                          halign="center", valign="middle", size_hint=(None, None),
                          size=(780, 24), pos=(rcx - 390, rcy - 96))
        self._sub.text_size = self._sub.size
        self.add_widget(self._sub)
        self._leds = []
        self._flash = 0
        n, r, step = 20, 9, 30
        ly = rcy - 128
        with self.canvas:
            for i in range(n):
                dx = rcx - (n - 1) * step / 2 + i * step
                self._leds.append(Color(*_LED_OFF))
                Ellipse(pos=(dx - r, ly - r), size=(2 * r, 2 * r))

    def update(self, state):
        self.dial.update_value(state.rpm)
        self.dial.set_shift(state.rpm >= SHIFT_RPM_THRESHOLD)
        self.dial.set_gear(state.gear_label)
        self._rpm.text = f"{int(state.rpm)}"
        self._shift_leds(state.rpm)

        boost = max(0.0, state.map)
        self.tiles["boost"].set(boost)
        self.tiles["fuel"].set(state.fuel_level)
        self.tiles["engine"].set(state.engine_temp)
        self.tiles["intake"].set(state.air_temp)
        self.tiles["batt"].set(state.battery)
        self.tiles["fpress"].set(state.fuel_pressure_bar)
        self.tiles["opress"].set(state.oil_pressure_bar)
        self.tiles["ethanol"].set(state.ethanol)
        self.tiles["tps"].set(state.tps)
        self.tiles["map"].set(boost)
        self.tiles["lambda"].set(state.lambda_afr)

    def _shift_leds(self, rpm):
        leds = self._leds
        n = len(leds)
        if rpm >= SHIFT_RPM_THRESHOLD:                 # at/over shift: flash all red
            self._flash = (self._flash + 1) % 8
            for c in leds:
                c.rgba = _LED_RED if self._flash < 4 else _LED_OFF
            return
        self._flash = 0
        span = SHIFT_RPM_THRESHOLD - _LED_START
        frac = (rpm - _LED_START) / span if span else 0
        lit = int(round(max(0.0, min(1.0, frac)) * n))
        for i, c in enumerate(leds):
            c.rgba = _led_color(i, n) if i < lit else _LED_OFF


_CARDINALS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _hud_label(text, font, size_sp, color, pos, size, halign):
    lbl = Label(text=text, font_name=font, font_size=f"{size_sp}sp", color=color,
                halign=halign, valign="middle", size_hint=(None, None),
                size=size, pos=pos)
    lbl.text_size = lbl.size
    return lbl


class MapLayout(Widget):
    """Perspective map + a minimal HUD: GPS speed (bottom-left), compass
    heading (top-right), raw coordinates (bottom-right)."""

    name = "map"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.map = MapView()
        self.add_widget(self.map)

        self._speed = _hud_label("0", FONT_LIGHT, 130, GAUGE_CENTER,
                                 (60, 100), (320, 150), "left")
        self.add_widget(self._speed)
        self.add_widget(_hud_label("KM/H", FONT_MONO, 20, LABEL_ACCENT,
                                   (64, 72), (320, 24), "left"))
        self._compass = _hud_label("N 000°", FONT_MONO, 26, LABEL_ACCENT,
                                   (1920 - 260 - 48, 720 - 60 - 30), (260, 30), "right")
        self.add_widget(self._compass)
        self._coords = _hud_label("", FONT_MONO, 17, LABEL_DIM,
                                  (1920 - 420 - 48, 78), (420, 22), "right")
        self.add_widget(self._coords)

    def update(self, state):
        self.map.update(state)
        # wheel speed is the trusted speed source (GPS speed lags and drops out)
        self._speed.text = f"{int(round(state.wheel_speed_fl_kmh))}"
        hdg = state.heading_deg % 360
        card = _CARDINALS[int((hdg + 22.5) // 45) % 8]
        self._compass.text = f"{card} {hdg:03.0f}°"
        if state.lat or state.lon:
            self._coords.text = f"{state.lat:.5f}  {state.lon:.5f}"
        else:
            self._coords.text = "NO GPS"


LAYOUTS = [StreetLayout, DetailLayout, MapLayout]
