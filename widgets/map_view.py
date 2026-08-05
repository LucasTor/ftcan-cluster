"""Perspective street-map view (the "map" layout's centrepiece).

Draws the real São Marcos road network (baked offline into ``map_data.json``
from OpenStreetMap — the Pi has no internet) as a heading-up 2D map tilted
into perspective, nav-style: the car sits at a fixed anchor near the bottom,
streets converge toward a horizon and fade into fog with distance.

All geometry (projection constants, culling, clipping, pose smoothing and the
mitred tapered-ribbon extrusion) lives in ``map_geometry`` — shared with the
QML build's map_item.py; this widget only turns the shared pipeline's output
into Kivy Meshes and draws the fog + car marker on top.
"""

import math
import time

from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Mesh, Rectangle
from kivy.graphics.instructions import InstructionGroup
from kivy.graphics.texture import Texture

from theme import BG, WINDOW_WIDTH, WINDOW_HEIGHT
from map_geometry import (CX, CAR_Y, ROAD_STYLE, GLOW_STYLE, GLOW_LAYERS,
                          RoadMap, SmoothedPose, ribbon_points, ribbon_quads)

FOG_Y0, FOG_Y1 = 400, 535   # fog gradient band (transparent -> solid BG)

_CAR_GLOW = (0.353, 0.651, 0.918, 0.28)
_CAR_FILL = (0.420, 0.706, 0.945, 1.0)
_CAR_EDGE = (0.949, 0.957, 0.973, 1.0)


class MapView(Widget):
    """Full-window perspective map, fed lat/lon/heading via ``update(state)``."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._map = RoadMap()
        self._pose = SmoothedPose()
        self._perf_acc, self._perf_n = 0.0, 0

        self._lines = InstructionGroup()   # rebuilt every frame
        self.canvas.add(self._lines)
        self._add_fog()
        self._add_car_marker()

    # --- static canvas pieces -------------------------------------------------

    def _add_fog(self):
        """Distance fog: BG-coloured vertical gradient over the far field."""
        grad = Texture.create(size=(1, 64), colorfmt="rgba")
        r, g, b = (int(c * 255) for c in BG[:3])
        buf = bytearray()
        for i in range(64):
            buf += bytes((r, g, b, int(255 * i / 63)))
        grad.blit_buffer(bytes(buf), colorfmt="rgba", bufferfmt="ubyte")
        with self.canvas:
            Color(1, 1, 1, 1)
            Rectangle(texture=grad, pos=(0, FOG_Y0), size=(WINDOW_WIDTH, FOG_Y1 - FOG_Y0))
            Color(*BG)
            Rectangle(pos=(0, FOG_Y1), size=(WINDOW_WIDTH, WINDOW_HEIGHT - FOG_Y1))

    def _add_car_marker(self):
        """Nav-style marker: soft radial glow, dark seat for contrast over
        bright roads, then a swept-wing arrow (white rim + Azul Boreal fill)."""
        glow = Texture.create(size=(64, 64), colorfmt="rgba")
        buf = bytearray()
        for j in range(64):
            for i in range(64):
                r = math.hypot(i - 31.5, j - 31.5) / 32.0
                a = max(0.0, 1.0 - r) ** 2
                buf += bytes((90, 166, 234, int(255 * a)))
        glow.blit_buffer(bytes(buf), colorfmt="rgba", bufferfmt="ubyte")

        def arrow(shape):
            # tip, right wing, tail notch, left wing (triangle fan, y-rel CAR_Y)
            verts = []
            for px, py in shape:
                verts += (CX + px, CAR_Y + py, 0, 0)
            return verts

        # outer (white rim) and inner (fill) silhouettes, hand-inset ~3.5 px
        # for an even rim; the inner notch is shallower so the tail crevice
        # stays rimmed without a white blob
        outer = ((0, 38.5), (24, -20), (0, -10.5), (-24, -20))
        inner = ((0, 33), (19.5, -15.5), (0, -7.5), (-19.5, -15.5))

        with self.canvas:
            Color(1, 1, 1, _CAR_GLOW[3] * 3)
            Rectangle(texture=glow, pos=(CX - 62, CAR_Y - 54), size=(124, 124))
            Color(BG[0], BG[1], BG[2], 0.55)
            Ellipse(pos=(CX - 30, CAR_Y - 22), size=(60, 60))
            Color(*_CAR_EDGE)
            Mesh(vertices=arrow(outer), indices=[0, 1, 2, 3], mode="triangle_fan")
            Color(*_CAR_FILL)
            Mesh(vertices=arrow(inner), indices=[0, 1, 2, 3], mode="triangle_fan")

    # --- per-frame update -----------------------------------------------------

    def update(self, state):
        t0 = time.perf_counter()
        lat, lon = state.lat, state.lon
        if not (lat == 0.0 and lon == 0.0):   # no fix yet: hold at map origin
            te, tn = self._map.to_en(lat, lon)
            self._pose.update(te, tn, state.heading_deg)
        self._redraw()
        # rolling redraw-cost log ([map] in the journal) — the ribbon+glow
        # rebuild is the priciest per-frame Python in the app, and the Pi's
        # screen can't be seen remotely, so this is how it gets profiled
        self._perf_acc += time.perf_counter() - t0
        self._perf_n += 1
        if self._perf_n >= 600:            # ~20 s at 30 fps
            print(f"[map] redraw avg {1000 * self._perf_acc / self._perf_n:.1f}ms "
                  f"over {self._perf_n} frames", flush=True)
            self._perf_acc, self._perf_n = 0.0, 0

    def _redraw(self):
        pose = self._pose
        by_class = self._map.visible_chunks(pose.e, pose.n, pose.hdg)

        g = self._lines
        g.clear()

        # pass 1: soft under-glow in two falloff layers (minor classes first so
        # major glows sit on top); pass 2: bright cores, same order
        for lw_k, la_k in GLOW_LAYERS:
            for cls in (2, 1, 0):
                color, wk = GLOW_STYLE[cls]
                chunks = by_class[cls]
                if not chunks:
                    continue
                g.add(Color(color[0], color[1], color[2], color[3] * la_k))
                hw = ROAD_STYLE[cls][1] * wk * lw_k
                for chunk in chunks:
                    self._draw_ribbon(g, chunk, hw)
        for cls in (3, 2, 1, 0):
            chunks = by_class[cls]
            if not chunks:
                continue
            g.add(Color(*ROAD_STYLE[cls][0]))
            for chunk in chunks:
                self._draw_ribbon(g, chunk, ROAD_STYLE[cls][1])

    @staticmethod
    def _draw_ribbon(g, chunk, hw0):
        """Draw a clipped car-frame polyline as a tapered triangle strip."""
        pts = ribbon_points(chunk, hw0)
        if len(pts) < 2:
            return
        verts = []
        for (xl, yl), (xr, yr) in ribbon_quads(pts):
            verts += (xl, yl, 0, 0, xr, yr, 0, 0)
        g.add(Mesh(vertices=verts, indices=list(range(2 * len(pts))),
                   mode="triangle_strip"))
