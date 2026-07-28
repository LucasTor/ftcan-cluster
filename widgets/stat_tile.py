"""A compact stat tile: label · big value · full-width bottom bar with range.

Used by the dense "detail" layout (GhostDash-style). The value reads big and
white; a full-width bar at the bottom shows where it sits in range — bright-cyan
fill on a dark-teal track, with ``min`` / ``unit`` / ``max`` sitting on the bar.
Built at a fixed pos/size passed by the layout (read in ``__init__``).

Pass ``bar=False`` for a discrete readout (e.g. GEAR): no bar/range, the value
is centred big and ``set()`` accepts any string.
"""

from kivy.uix.widget import Widget
from kivy.uix.label import Label
from kivy.graphics import Color, RoundedRectangle, Rectangle, Line

TILE_BG = (0.075, 0.086, 0.105, 1.0)   # dark panel
TILE_BORDER = (0.32, 0.60, 0.72, 0.30)  # subtle teal border
BAR_TRACK = (0.055, 0.290, 0.360, 1.0)  # dark teal (unfilled)
BAR_FILL = (0.078, 0.784, 1.0, 1.0)     # bright cyan (filled)
LABEL_COL = (0.80, 0.84, 0.88, 0.92)    # light-grey tile label
VALUE_COL = (0.97, 0.98, 1.0, 1.0)      # white value
RANGE_COL = (0.90, 0.93, 0.96, 0.95)    # white min/max
UNIT_COL = (0.62, 0.78, 0.85, 0.85)     # muted unit
BAR_H = 26                              # bottom bar strip height


class StatTile(Widget):
    def __init__(self, label, unit="", vmin=0.0, vmax=100.0, fmt="{:.1f}",
                 warn=None, warn_color=None, bar=True, **kwargs):
        super().__init__(**kwargs)
        self.vmin, self.vmax = float(vmin), float(vmax)
        self.fmt = fmt
        self.warn = warn or (lambda v: False)
        self.warn_color = warn_color or VALUE_COL
        self._has_bar = bar

        x, y, w, h = self.x, self.y, self.width, self.height
        self._bar_x = x
        self._bar_w = w

        with self.canvas:
            Color(*TILE_BG)
            RoundedRectangle(pos=(x, y), size=(w, h), radius=[6])
            Color(*TILE_BORDER)
            Line(rounded_rectangle=(x, y, w, h, 6), width=1.3)
            if bar:
                Color(*BAR_TRACK)
                Rectangle(pos=(x, y), size=(w, BAR_H))
                self._fill_color = Color(*BAR_FILL)
                self._fill = Rectangle(pos=(x, y), size=(0, BAR_H))

        # value (big, fills the middle above the bar), label (top)
        top = y + h
        self._label = Label(text=label, font_size="19sp",
                           color=LABEL_COL, halign="center", valign="middle",
                           size_hint=(None, None), size=(w, 26), pos=(x, top - 34))
        value_pos = (x, y + BAR_H + 22) if bar else (x, y + 8)
        value_h = (h - BAR_H - 56) if bar else (h - 42)
        self._value = Label(text="—", font_size="78sp", bold=True, color=VALUE_COL,
                           halign="center", valign="middle", size_hint=(None, None),
                           size=(w, value_h), pos=value_pos)
        labels = [self._label, self._value]
        if bar:
            # min / unit / max sitting on the bar strip
            self._min = Label(text=f"{vmin:g}", font_size="14sp", color=RANGE_COL,
                             halign="left", valign="middle", size_hint=(None, None),
                             size=(w - 16, BAR_H), pos=(x + 8, y))
            self._unit = Label(text=unit, font_size="13sp", color=UNIT_COL,
                              halign="center", valign="middle", size_hint=(None, None),
                              size=(w, BAR_H), pos=(x, y))
            self._max = Label(text=f"{vmax:g}", font_size="14sp", color=RANGE_COL,
                             halign="right", valign="middle", size_hint=(None, None),
                             size=(w - 16, BAR_H), pos=(x + 8, y))
            labels += [self._min, self._unit, self._max]
        for lbl in labels:
            lbl.text_size = lbl.size
            self.add_widget(lbl)

    def set(self, value):
        """Update the value text, bar fill and colour. ``None`` leaves it as-is.
        Accepts a string when the tile has no bar (e.g. a gear label)."""
        if value is None:
            return
        self._value.text = self.fmt.format(value)
        if not self._has_bar:
            return
        warn = self.warn(value)
        self._value.color = self.warn_color if warn else VALUE_COL
        span = self.vmax - self.vmin
        frac = max(0.0, min(1.0, (value - self.vmin) / span)) if span else 0
        self._fill.size = (self._bar_w * frac, BAR_H)
        self._fill_color.rgba = self.warn_color if warn else BAR_FILL
