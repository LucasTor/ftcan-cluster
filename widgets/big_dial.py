"""RPM dial for the dense "detail" layout — GhostDash "details" style.

A wide ring carries big bold numbers. The colour trails the needle: strongest
right behind the needle and fading back toward 0 (a "comet tail"), turning red in
the redline zone; the scale above the needle stays white. The ring extends a
little past 0 and 8 so those numbers sit fully on it. A black needle points at
the current RPM; a big black hub holds the gear. The RPM readout + shift-lights
are drawn by the layout (below the dial), not here. Built at a fixed pos/size.
"""

import math

from kivy.uix.widget import Widget
from kivy.uix.label import Label
from kivy.graphics import Color, Ellipse, Line, PushMatrix, PopMatrix, Rotate
from kivy.clock import Clock

START = -160.0        # 0 at ~6:40 (Kivy angles: 0=top, +ve clockwise)
SWEEP = 245.0         # numbers 0..8 span this; the rest is the bottom-right gap
EXT = 14.0            # ring extends this many degrees past 0 and 8

RING_R = 190          # ring centreline radius
RING_W = 128          # ring thickness (wide — fills from the hub to the rim)
NUM_R = 236           # numbers sit near the outer edge of the ring band
HUB_R = 128           # big black hub (holds the gear) — ~half the outer radius
SEGS = 500            # angular segments across the number span (fade smoothness)
FADE_RPM = 700        # rpm over which the whole trail switches cyan -> red

NUM_FONT = "fonts/Compagnon-Medium.otf"   # same font as the side tiles

WHITE = (0.97, 0.985, 1.0, 1.0)   # ring above the needle / faded tail
CYAN = (0.05, 0.80, 1.0, 1.0)     # colour just behind the needle
RED = (0.98, 0.26, 0.05, 1.0)     # colour in the redline
FACE = (0.03, 0.04, 0.06, 1.0)
RIM_DOT = (0.36, 0.40, 0.47, 1.0)
NUM_COL = (0.05, 0.07, 0.10, 1.0)
NUM_OUTLINE = (1.0, 1.0, 1.0, 1.0)
NEEDLE_COL = (0.04, 0.04, 0.05, 1.0)
NEEDLE_EDGE = (1.0, 1.0, 1.0, 0.92)
GEAR_COL = (0.98, 0.99, 1.0, 1.0)

# redline transition keyframes (see _hue): cyan brightens to pale gold, then
# ignites through orange to red. A direct cyan->red lerp muddies to grey-brown,
# and a white bridge vanishes against the white ring — gold stays visible.
PALE_GOLD = (1.0, 0.85, 0.45, 1.0)
ORANGE = (1.0, 0.55, 0.02, 1.0)
HUE_STOPS = [(0.0, CYAN), (0.35, PALE_GOLD), (0.7, ORANGE), (1.0, RED)]

INTRO_SWEEP_AT = 2.5
INTRO_RESET_AT = 3.9


def _lerp(a, b, t):
    return tuple(a[j] + (b[j] - a[j]) * t for j in range(4))


class BigDial(Widget):
    def __init__(self, max_value=8000, ticks=9, label_map=None, shift_from=6000,
                 redline_from=5000, **kwargs):
        super().__init__(**kwargs)
        self.max_value = max_value
        self.ticks = ticks
        self.label_map = label_map or {}
        self.shift_from = shift_from
        self.redline_from = redline_from
        self.value = 0.0
        self._disp = 0.0

        cx = self.x + self.width / 2
        cy = self.y + self.height / 2
        self._cx, self._cy = cx, cy
        outer = RING_R + RING_W / 2

        with self.canvas:
            Color(*FACE)
            Ellipse(pos=(cx - outer - 12, cy - outer - 12),
                    size=(2 * (outer + 12), 2 * (outer + 12)))
            # flat colour ring (extends EXT past 0 and 8). One colour per angular
            # segment; colours set per-frame (see _anim) to trail the needle.
            self._segs = []
            lo, hi = START - EXT, START + SWEEP + EXT
            nseg = round(SEGS * (hi - lo) / SWEEP)
            seg_w = (hi - lo) / nseg
            for s in range(nseg):
                a0 = lo + s * seg_w
                rpm_s = ((a0 + seg_w / 2 - START) / SWEEP) * max_value
                c = Color(*WHITE)
                Line(circle=(cx, cy, RING_R, a0, a0 + seg_w + 0.7), width=RING_W,
                     cap="none")
                self._segs.append((c, rpm_s))
            # black needle (rotates to the current RPM)
            PushMatrix()
            self._needle_rot = Rotate(origin=(cx, cy), angle=0)
            Color(*NEEDLE_EDGE)
            Line(points=[cx, cy + HUB_R - 4, cx, cy + outer - 2], width=8, cap="round")
            Color(*NEEDLE_COL)
            Line(points=[cx, cy + HUB_R - 4, cx, cy + outer - 2], width=4.5, cap="round")
            PopMatrix()
            Color(0, 0, 0, 1)
            Ellipse(pos=(cx - HUB_R, cy - HUB_R), size=(2 * HUB_R, 2 * HUB_R))
            Color(*RIM_DOT)
            steps = (ticks - 1) * 2
            for i in range(steps + 1):
                th = math.radians(START + (i / steps) * SWEEP)
                dx = cx + (outer + 15) * math.sin(th)
                dy = cy + (outer + 15) * math.cos(th)
                Ellipse(pos=(dx - 3, dy - 3), size=(6, 6))

        # big bold numbers on the ring (same font as the tiles)
        for i in range(ticks):
            val = int(i / (ticks - 1) * max_value)
            th = math.radians(START + (i / (ticks - 1)) * SWEEP)
            lbl = Label(text=str(self.label_map.get(val, val)), font_name=NUM_FONT,
                        font_size="80sp", bold=True, color=NUM_COL,
                        outline_width=2, outline_color=NUM_OUTLINE,
                        halign="center", valign="middle", size_hint=(None, None),
                        size=(112, 100),
                        pos=(cx + NUM_R * math.sin(th) - 56,
                             cy + NUM_R * math.cos(th) - 50))
            lbl.text_size = lbl.size
            self.add_widget(lbl)

        # gear in the hub. Compagnon's line box is bottom-heavy, so a "middle"
        # valign draws the glyph ~0.14em below the visual centre — lift the
        # label to compensate (measured on a rendered capture).
        gear_fs = 150
        self._gear = Label(text="N", font_name=NUM_FONT, font_size=f"{gear_fs}sp",
                          bold=True,
                          color=GEAR_COL, halign="center", valign="middle",
                          size_hint=(None, None), size=(2 * HUB_R, 2 * HUB_R),
                          pos=(cx - HUB_R, cy - HUB_R + round(0.143 * gear_fs)))
        self._gear.text_size = self._gear.size
        self.add_widget(self._gear)

        Clock.schedule_interval(self._anim, 1 / 50.0)
        Clock.schedule_once(lambda _: self.update_value(max_value, False), INTRO_SWEEP_AT)
        Clock.schedule_once(lambda _: self.update_value(0), INTRO_RESET_AT)

    def _hue(self, rpm):
        if rpm <= self.redline_from:
            return CYAN
        t = min(1.0, (rpm - self.redline_from) / FADE_RPM)
        # keyframed blend through pale gold and orange (see HUE_STOPS).
        for (t0, c0), (t1, c1) in zip(HUE_STOPS, HUE_STOPS[1:]):
            if t <= t1:
                return _lerp(c0, c1, (t - t0) / (t1 - t0))
        return RED

    def update_value(self, v, update_label=True):
        self.value = max(0.0, min(v, self.max_value))

    def set_gear(self, label):
        self._gear.text = str(label)

    def set_shift(self, active):
        pass

    def _anim(self, dt):
        self._disp += (self.value - self._disp) * min(1.0, 8.0 * dt)
        n = max(self._disp, 1.0)
        self._needle_rot.angle = -(START + (self._disp / self.max_value) * SWEEP)
        hue = self._hue(self._disp)                    # whole trail hue from the RPM
        for c, rpm_s in self._segs:
            if rpm_s <= 0 or rpm_s > self._disp:       # margins / above needle: white
                c.rgba = WHITE
            else:                                      # behind the needle: fade
                c.rgba = _lerp(WHITE, hue, rpm_s / n)
