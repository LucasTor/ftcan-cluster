"""Minimal centre readout (no box).

Top: a quiet mono micro-grid in 3 columns (AIR / ENGINE / OIL / FUEL P / FUEL / GEAR).
Below, split by hairlines: big bold BOOST and LAMBDA values.

Matches the minimal "Painel Gol" design — calm on a near-black background, one
accent, colour reserved for out-of-range values.
"""

from kivy.uix.widget import Widget
from kivy.uix.label import Label
from kivy.core.window import Window
from kivy.uix.gridlayout import GridLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.graphics import Color, Rectangle, Ellipse

from theme import (
    FONT_MONO, VALUE, LABEL_DIM, LABEL_ACCENT, UNIT_DIM, HAIRLINE,
    BOOST_NORMAL, TT_RED, TT_AMBER, CARD_WIDTH, CARD_HEIGHT,
    WINDOW_HEIGHT,
    EGT_BALANCED, EGT_MID, EGT_UNBALANCED, EGT_INACTIVE, EGT_SPREAD_RED, EGT_ACTIVE_MIN,
)
from .readout import Readout


BIG_VALUE_FONT = "120sp"
BIG_BLOCK_H = 176     # height of the BOOST / LAMBDA blocks (trimmed to fit the EGT row)
CENTER_Y_OFFSET = 32  # nudge the whole readout down, away from the top tell-tales
EGT_DOT_R = 9         # EGT channel dot radius
EGT_ROW_H = 48        # EGT row height inside the card
EGT_CELL_W = 48       # per-channel cell width
EGT_CELL_GAP = 14     # gap between channels (centred cluster, kept tight)


def _egt_median(vals):
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _egt_lerp(a, b, k):
    return tuple(a[j] + (b[j] - a[j]) * k for j in range(4))


def _egt_color(k):
    """Heat-scale colour for a balance deviation k (0..1): green -> amber -> red.
    Routed through amber so mid-range values stay a clean colour instead of the
    muddy brown a direct green->red RGB lerp produces."""
    if k <= 0.5:
        return _egt_lerp(EGT_BALANCED, EGT_MID, k * 2.0)
    return _egt_lerp(EGT_MID, EGT_UNBALANCED, (k - 0.5) * 2.0)


class _EgtDot(Widget):
    """A small filled circle, centred in its allocated cell; colour is settable."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            self._col = Color(*EGT_INACTIVE)
            self._ell = Ellipse()
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *_):
        cx, cy = self.center_x, self.center_y
        self._ell.pos = (cx - EGT_DOT_R, cy - EGT_DOT_R)
        self._ell.size = (2 * EGT_DOT_R, 2 * EGT_DOT_R)

    def set_color(self, rgba):
        self._col.rgba = rgba


class CenterInfo(Widget):
    # (key, label, value format, warn predicate, warn colour)
    MICRO_FIELDS = [
        ("air",     "AIR",    "{:.0f} °C",  lambda v: v > 58,  TT_AMBER),
        ("engine",  "ENGINE", "{:.0f} °C",  lambda v: v > 104, TT_RED),
        ("oil",     "OIL",    "{:.1f} BAR", None,              None),
        ("egtavg",  "EGT",    "{:.0f} °C",  lambda v: v > 750, TT_RED),
        ("fpress",  "FUEL P", "{:.1f} BAR", None,              None),
        ("fuel",    "LEVEL",  "{:.0f} %",   None,              None),
        ("oiltemp", "OIL T",  "{:.0f} °C",  lambda v: v > 120, TT_RED),
        # Flex-fuel ethanol content, shown as an "E85"-style blend in the slot
        # where GEAR used to be (gear needs a position sensor we don't read).
        ("ethanol", "FUEL",   "E{:.0f}",    None,              None),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.readouts = {}

        self.size = (CARD_WIDTH, CARD_HEIGHT)
        self._center_vert = (WINDOW_HEIGHT / 2) - (self.size[1] / 2) - CENTER_Y_OFFSET
        self._reposition()

        self.vbox = BoxLayout(
            orientation="vertical",
            size_hint=(None, None),
            size=self.size,
            pos=self.pos,
            padding=[10, 8, 10, 8],
            spacing=6,
        )
        self.add_widget(self.vbox)

        # --- micro-grid: 3 columns, 2 rows (temps / pressures / level / gear) ---
        grid = GridLayout(cols=4, size_hint=(1, None), height=134, spacing=[10, 6])
        self.vbox.add_widget(grid)
        for key, label, fmt, warn, warn_color in self.MICRO_FIELDS:
            grid.add_widget(self._micro_cell(key, label, fmt, warn, warn_color))

        # --- EGT balance row: 4 cylinder dots + temps (green in balance, red as
        #     a channel deviates from the group median) ---
        self.vbox.add_widget(self._egt_block())

        self.vbox.add_widget(self._hairline())

        # --- big BOOST ---
        self.boost_value = self._big_block("BOOST", "BAR")
        self.vbox.add_widget(self._hairline())

        # --- big LAMBDA --- (starts at stoich 1.00, blue)
        self.lambda_value, self.lambda_tag = self._big_block(
            "LAMBDA", "STOICH", initial="1.00", with_ref=True)

        self.bind(pos=self._sync, size=self._sync)
        Window.bind(on_resize=lambda *_: self._reposition())

    # ---- builders ----

    def _cell(self, label, initial):
        """A label-over-value micro cell; returns (cell, value_label)."""
        cell = BoxLayout(orientation="vertical", spacing=2)
        name = Label(text=label, font_name=FONT_MONO, font_size="18sp",
                     color=LABEL_DIM, halign="center", valign="middle",
                     size_hint=(1, None), height=22)
        value = Label(text=initial, font_name=FONT_MONO, font_size="22sp", bold=True,
                      color=VALUE, halign="center", valign="middle",
                      size_hint=(1, None), height=40)
        for lbl in (name, value):
            lbl.bind(size=lbl.setter("text_size"))
        cell.add_widget(name)
        cell.add_widget(value)
        return cell, value

    def _micro_cell(self, key, label, fmt, warn, warn_color):
        cell, value = self._cell(label, "—")
        kw = {"fmt": fmt}
        if warn is not None:
            kw.update(warn=warn, warn_color=warn_color)
        self.readouts[key] = Readout(value, **kw)
        return cell

    def _egt_block(self):
        """4 cylinder cells (dot over temperature), centred as a tight cluster."""
        holder = AnchorLayout(anchor_x="center", anchor_y="center",
                              size_hint=(1, None), height=EGT_ROW_H)
        row = BoxLayout(orientation="horizontal", size_hint=(None, None),
                        height=EGT_ROW_H, spacing=EGT_CELL_GAP,
                        width=4 * EGT_CELL_W + 3 * EGT_CELL_GAP)
        self._egt_dots = []
        self._egt_vals = []
        for _ in range(4):
            cell = BoxLayout(orientation="vertical", spacing=2,
                             size_hint=(None, None), size=(EGT_CELL_W, EGT_ROW_H))
            dot = _EgtDot(size_hint=(1, None), height=22)
            val = Label(text="—", font_name=FONT_MONO, font_size="18sp", bold=True,
                        color=(1, 1, 1, 0.25), halign="center", valign="middle",
                        size_hint=(1, None), height=22)
            val.bind(size=val.setter("text_size"))
            cell.add_widget(dot)
            cell.add_widget(val)
            row.add_widget(cell)
            self._egt_dots.append(dot)
            self._egt_vals.append(val)
        holder.add_widget(row)
        return holder

    def _big_block(self, title, unit, initial="0.00", with_ref=False):
        # The value sizes to its own rendered glyphs (never clipped). Title and
        # unit are placed just outside the visible digits using a fraction of the
        # value's *rendered* glyph height — that fraction scales with font/density
        # so the spacing is identical on the dev Mac and the Pi.
        # Starts in the accent blue so it matches the gauges during the intro
        # sweep (before any data arrives), rather than flashing white first.
        block = FloatLayout(size_hint=(1, None), height=BIG_BLOCK_H)
        value = Label(text=initial, bold=True, font_size=BIG_VALUE_FONT,
                      color=BOOST_NORMAL, size_hint=(None, None))
        name = Label(text=title, font_name=FONT_MONO, font_size="30sp",
                     color=LABEL_ACCENT, size_hint=(None, None))
        sub = Label(text=unit, font_name=FONT_MONO, font_size="16sp",
                    color=UNIT_DIM, size_hint=(None, None))
        for lbl in (value, name, sub):
            lbl.bind(texture_size=lbl.setter("size"))
            block.add_widget(lbl)

        def place(*_):
            # Digits aren't centred in their line box (big ascent leading): the
            # caps sit ~0.22 above centre, the baseline ~0.42 below. Offsets are
            # fractions of the rendered glyph height, so they hold at any density.
            cx, cy = block.center_x, block.center_y
            value.center_x, value.center_y = cx, cy
            top = value.height * 0.27   # just above the digit caps
            bot = value.height * 0.42   # just below the digit baseline
            name.center_x = cx
            name.center_y = cy + top + name.height * 0.5 + 1
            sub.center_x = cx
            sub.center_y = cy - bot - sub.height * 0.5 - 1

        for lbl in (value, name, sub):
            lbl.bind(size=place)
        block.bind(pos=place, size=place)

        self.vbox.add_widget(block)
        return (value, sub) if with_ref else value

    def _hairline(self):
        # An AnchorLayout reliably centres the bar regardless of layout order
        # (positioning a raw Rectangle by center_x raced the layout on the Pi).
        holder = AnchorLayout(size_hint=(1, None), height=22)
        bar = Widget(size_hint=(None, None), size=(64, 1))
        with bar.canvas:
            Color(*HAIRLINE)
            rect = Rectangle(size=bar.size)
        bar.bind(pos=lambda *_: setattr(rect, "pos", bar.pos),
                 size=lambda *_: setattr(rect, "size", bar.size))
        holder.add_widget(bar)
        return holder

    # ---- layout housekeeping ----

    def _reposition(self):
        self.pos = ((Window.width - self.width) / 2, self._center_vert)

    def _sync(self, *_):
        self.vbox.pos = self.pos
        self.vbox.size = self.size

    # ---- data ----

    def set_egt(self, temps):
        """Update the 4 EGT dots/readouts; colour each by deviation from the median
        (green in balance, reddening as a channel drifts from the group)."""
        temps = list(temps)[:4]
        active = bool(temps) and max(temps) > EGT_ACTIVE_MIN
        ref = _egt_median(temps) if active else 0.0
        self.readouts["egtavg"].set(sum(temps) / len(temps) if active else None)
        for i in range(4):
            if not active:
                self._egt_dots[i].set_color(EGT_INACTIVE)
                self._egt_vals[i].text = "—"
                self._egt_vals[i].color = (1, 1, 1, 0.25)
                continue
            k = min(1.0, abs(temps[i] - ref) / EGT_SPREAD_RED)
            self._egt_dots[i].set_color(_egt_color(k))
            self._egt_vals[i].text = f"{int(round(temps[i]))}"
            self._egt_vals[i].color = VALUE

    def set_values(self, intake_c=None, water_c=None, oil_press_bar=None,
                   lambda_val=None, boost_bar=None, fuel_level=None,
                   fuel_press_bar=None, ethanol=None, rpm=None, oil_temp=None):
        self.readouts["air"].set(intake_c)
        self.readouts["engine"].set(water_c)
        self.readouts["oil"].set(oil_press_bar)
        self.readouts["oiltemp"].set(oil_temp)
        self.readouts["fpress"].set(fuel_press_bar)
        self.readouts["fuel"].set(fuel_level)
        self.readouts["ethanol"].set(ethanol)

        if boost_bar is not None:
            self.boost_value.text = f"{boost_bar:.2f}"
            self.boost_value.color = TT_RED if boost_bar > 1.32 else BOOST_NORMAL

        if lambda_val is not None:
            self.lambda_value.text = f"{lambda_val:.2f}"
            # Below ~500 rpm the engine isn't burning, so lambda reads pegged-lean
            # on ambient O2 — suppress the RICH/LEAN alert and stay neutral.
            if rpm is not None and rpm < 500:
                self.lambda_value.color, self.lambda_tag.text = BOOST_NORMAL, "STOICH"
            # Match the rest of the cluster's palette: accent blue when safe,
            # amber when rich, red when lean (lean is the dangerous side).
            elif lambda_val < 0.85:
                self.lambda_value.color, self.lambda_tag.text = TT_AMBER, "RICH"
            elif lambda_val > 1.05:
                self.lambda_value.color, self.lambda_tag.text = TT_RED, "LEAN"
            else:
                self.lambda_value.color, self.lambda_tag.text = BOOST_NORMAL, "STOICH"
