from kivy.uix.widget import Widget
from kivy.graphics import (
    Color,
    Ellipse,
    Line,
    Rotate,
    PushMatrix,
    PopMatrix,
)
from kivy.uix.label import Label
from kivy.clock import Clock

from theme import (
    FONT_MONO, GAUGE_FACE, GAUGE_RING, GAUGE_TICK, GAUGE_TICK_MINOR, GAUGE_NUM,
    GAUGE_ARC, GAUGE_NEEDLE, GAUGE_REDLINE, GAUGE_SHIFT, GAUGE_SHIFT_TEXT,
    GAUGE_SHIFT_FLASH, GAUGE_CENTER, GAUGE_SUB, GAUGE_UNIT,
)

import math

DIGIT_FONT = "78sp"
SHIFT_FONT = "64sp"
ARC_WIDTH = 5
SHIFT_ARC_WIDTH = 13      # fat amber arc while shifting
SHIFT_BLINK = 0.06        # fast strobe (s per toggle)
SHIFT_FLASH_ALPHA = 0.55  # red disc wash intensity on the bright phase

# Startup self-test sweep timing (seconds, from the shared intro spec). The
# initial delay lets the display finish coming up so the whole sweep is
# visible, not just its tail.
from decisions import INTRO_PAUSE_MS, INTRO_SWEEP_MS, INTRO_GAUGE_HOLD_MS

INTRO_SWEEP_AT = INTRO_PAUSE_MS / 1000   # sweep needle to full scale
INTRO_RESET_AT = (INTRO_PAUSE_MS + INTRO_SWEEP_MS + INTRO_GAUGE_HOLD_MS) / 1000


class Gauge(Widget):
    """Minimal analog gauge: hairline ticks and a thin Azul Boreal needle on a
    dark disc, with a thin progress arc. At the shift point the arc and needle
    flash amber and a red SHIFT! pulses over the centre (see ``set_shift``)."""

    def __init__(
        self,
        title="Speed",
        subtitle="",
        max_value=180,
        unit="km/h",
        ticks=10,
        angle_range=270,
        label_map=None,
        show_digital_value=True,
        redline_from=None,
        value_formatter=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.title = title
        self.subtitle = subtitle
        self.max_value = max_value
        self.unit = unit
        self.ticks = ticks
        self.angle_range = angle_range
        self.label_map = label_map or {}
        self.show_title = show_digital_value
        self.redline_from = redline_from
        self.value_formatter = value_formatter or (lambda v: f"{int(v)}")
        self.needle_angle = 180
        self.current_angle = 180
        self.value = 0

        self._shift_active = False
        self._shift_on = False
        self._shift_ev = None

        with self.canvas:
            self.draw_gauge()

        Clock.schedule_once(self.init_needle, 0)
        Clock.schedule_interval(self.smooth_update, 1 / 60.0)

        self.value_label = Label(
            text="0",
            font_size=DIGIT_FONT,
            bold=True,
            pos=(self.center_x, self.center_y),
            size_hint=(None, None),
            size=(100, 50),
            halign="center",
            valign="middle",
            color=GAUGE_CENTER,
        )
        self.value_label.bind(size=self.value_label.setter("text_size"))
        self.value_label.center = self.center
        if show_digital_value:
            self.add_widget(self.value_label)

        self.update_value(0, smooth=False)
        Clock.schedule_once(
            lambda _: self.update_value(max_value, update_label=False), INTRO_SWEEP_AT
        )
        Clock.schedule_once(lambda _: self.update_value(0), INTRO_RESET_AT)

    def draw_gauge(self):
        cx, cy = self.center
        radius = min(self.width, self.height) / 2
        self._cx, self._cy = cx, cy
        self._arc_r = radius * 0.92

        # dark dial face + faint edge ring (no chrome, no rectangular border)
        Color(*GAUGE_FACE)
        Ellipse(pos=self.pos, size=self.size)
        # shift-light red wash over the whole disc (alpha strobed in _apply_shift)
        self._flash_color = Color(*GAUGE_SHIFT_FLASH[:3], 0)
        Ellipse(pos=self.pos, size=self.size)
        Color(*GAUGE_RING)
        Line(circle=(cx, cy, radius * 0.995), width=1)

        # ticks: bright majors (labelled) + faint minors at the midpoints
        tick_outer = radius * 0.90
        major_len = radius * 0.10
        minor_len = radius * 0.05
        num_radius = radius * 0.66
        num_box = (80, 44)
        base_angle = -90 - ((360 - self.angle_range) / 2)
        tick_angle = (-self.angle_range) / (self.ticks - 1)

        def tick_line(frac_index, inner_len, color, width):
            a = math.radians(base_angle + tick_angle * frac_index)
            cos_a, sin_a = math.cos(a), math.sin(a)
            Color(*color)
            Line(
                points=[
                    cx + (tick_outer - inner_len) * cos_a,
                    cy + (tick_outer - inner_len) * sin_a,
                    cx + tick_outer * cos_a,
                    cy + tick_outer * sin_a,
                ],
                width=width,
                cap="round",
            )

        for i in range(self.ticks):
            tick_line(i, major_len, GAUGE_TICK, 2)
            if i < self.ticks - 1:
                tick_line(i + 0.5, minor_len, GAUGE_TICK_MINOR, 1)

            a = math.radians(base_angle + tick_angle * i)
            value = int((i / (self.ticks - 1)) * self.max_value)
            label = self.label_map.get(value, value)
            num = Label(
                text=str(label),
                size_hint=(None, None), size=num_box,
                pos=(cx + num_radius * math.cos(a) - num_box[0] / 2,
                     cy + num_radius * math.sin(a) - num_box[1] / 2),
                font_size="30sp", halign="center", valign="middle",
                color=GAUGE_NUM,
            )
            num.text_size = num_box
            self.add_widget(num)

        # bold progress arc (filled live in smooth_update)
        self._arc_color = Color(*GAUGE_ARC)
        self.arc = Line(
            circle=(cx, cy, self._arc_r, self._angle_for_value(0),
                    self._angle_for_value(0) + 0.01),
            width=ARC_WIDTH,
            cap="round",
        )

        # redline arc
        if self.redline_from and 0 < self.redline_from < self.max_value:
            start = self._angle_for_value(self.redline_from)
            end = self._angle_for_value(self.max_value)
            if start > end:
                start, end = end, start
            Color(*GAUGE_REDLINE)
            Line(circle=(cx, cy, radius * 0.92, start, end), width=8, cap="round")

        # sub-label (SPEED / RPM) and unit (KM/H / x1000), quiet under the digit
        self.add_widget(Label(
            text=self.title, font_name=FONT_MONO, color=GAUGE_SUB,
            size=(self.width, 30), pos=(self.x, self.y + self.height * 0.24),
            font_size="36sp", halign="center", valign="middle",
        ))
        self.add_widget(Label(
            text=self.subtitle, font_name=FONT_MONO, color=GAUGE_UNIT,
            size=(self.width, 24), pos=(self.x, self.y + self.height * 0.165),
            font_size="24sp", halign="center", valign="middle",
        ))

    def _angle_for_value(self, v):
        # Value in [0, max_value] -> Kivy circle angle (deg, clockwise from top),
        # matching update_value()'s needle math.
        v = max(0, min(v, self.max_value))
        return (-self.angle_range / 2.0) + (v / float(self.max_value)) * self.angle_range

    def init_needle(self, *args):
        self.center_x = self.x + self.width / 2
        self.center_y = self.y + self.height / 2
        radius = min(self.width, self.height) / 2
        with self.canvas:
            PushMatrix()
            self.rot = Rotate(origin=(self.center_x, self.center_y), angle=self.needle_angle)
            self._needle_color = Color(*GAUGE_NEEDLE)
            # a floating pointer that stops short of the centre, leaving the
            # digit a clean space (no hub disc).
            self.needle = Line(
                points=[self.center_x, self.center_y + radius * 0.30,
                        self.center_x, self.center_y + radius * 0.86],
                width=4,
                cap="round",
            )
            PopMatrix()
        # needle was just appended to the canvas (init_needle runs after
        # __init__), so keep the centre digit on top of it.
        if self.value_label.parent:
            self.remove_widget(self.value_label)
            self.add_widget(self.value_label)

    def update_value(self, value, smooth=True, update_label=True):
        clamped = max(0, min(value, self.max_value))
        self.value = clamped
        angle = -self._angle_for_value(clamped)
        self.needle_angle = angle
        if not smooth:
            self.current_angle = angle

        # while shifting, the centre stays "SHIFT!" — don't write the number
        if update_label and not self._shift_active:
            self._show_value()

        self.value_label.center = self.center

    def _show_value(self):
        """Render the numeric value in the centre."""
        self.value_label.font_size = DIGIT_FONT
        self.value_label.text = self.value_formatter(self.value)
        if self.redline_from and self.value > self.redline_from:
            self.value_label.color = GAUGE_REDLINE
        else:
            self.value_label.color = GAUGE_CENTER

    def set_shift(self, active):
        """Shift light: a steady red SHIFT! in the centre while the disc, arc and
        needle strobe amber. The centre text doesn't blink — only the flash does."""
        active = bool(active)
        if active == self._shift_active:
            return
        self._shift_active = active
        if active:
            self.value_label.font_size = SHIFT_FONT
            self.value_label.text = "SHIFT!"
            self.value_label.color = GAUGE_SHIFT_TEXT
            self.value_label.center = self.center
            self._shift_ev = Clock.schedule_interval(self._shift_blink, SHIFT_BLINK)
        else:
            if self._shift_ev is not None:
                self._shift_ev.cancel()
                self._shift_ev = None
            self._shift_on = False
            self._apply_flash(False)
            self._show_value()
            self.value_label.center = self.center

    def _shift_blink(self, _):
        self._shift_on = not self._shift_on
        self._apply_flash(self._shift_on)

    def _apply_flash(self, on):
        """Strobe only the disc wash, arc and needle — never the centre text."""
        if on:
            self._arc_color.rgba = GAUGE_SHIFT
            self.arc.width = SHIFT_ARC_WIDTH
            self._flash_color.a = SHIFT_FLASH_ALPHA
            if hasattr(self, "_needle_color"):
                self._needle_color.rgba = GAUGE_SHIFT
        else:
            self._arc_color.rgba = GAUGE_ARC
            self.arc.width = ARC_WIDTH
            self._flash_color.a = 0
            if hasattr(self, "_needle_color"):
                self._needle_color.rgba = GAUGE_NEEDLE

    def smooth_update(self, dt):
        smoothing_speed = 5
        diff = self.needle_angle - self.current_angle
        self.current_angle += diff * smoothing_speed * dt

        if hasattr(self, "rot"):
            self.rot.angle = self.current_angle
        if hasattr(self, "arc"):
            start = self._angle_for_value(0)
            end = max(start + 0.01, -self.current_angle)
            self.arc.circle = (self._cx, self._cy, self._arc_r, start, end)
