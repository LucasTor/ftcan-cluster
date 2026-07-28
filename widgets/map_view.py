"""Perspective street-map view (the "map" layout's centrepiece).

Draws the real São Marcos road network (baked offline into ``map_data.json``
from OpenStreetMap — the Pi has no internet) as a heading-up 2D map tilted
into perspective, nav-style: the car sits at a fixed anchor near the bottom,
streets converge toward a horizon and fade into fog with distance.

Geometry pipeline, per frame:

  1. smooth the displayed pose toward the GPS pose (exponential approach, so a
     1-10 Hz GPS feed still pans/rotates smoothly at 30 fps),
  2. cull roads by precomputed bounding box against a view circle ahead of the
     car (service alleys only very near by),
  3. rotate world points into the car frame (heading-up), clip each polyline
     to the visible forward range,
  4. project ground metres to screen: ``y = CAR_Y + RISE·d/(d+DEPTH)`` with
     lateral scale ``PPM·DEPTH/(d+DEPTH)`` — a plane homography, so straight
     streets stay straight and no subdivision is needed.
"""

import json
import math
import os
import time

from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Mesh, Rectangle
from kivy.graphics.instructions import InstructionGroup
from kivy.graphics.texture import Texture

from theme import BG, WINDOW_WIDTH

_MAP_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         os.pardir, "map_data.json")

# --- projection constants (design space 1920x720) ---
CX = WINDOW_WIDTH / 2   # car screen anchor x
CAR_Y = 200             # car screen anchor y
RISE = 360              # CAR_Y -> horizon (d = infinity) vertical span
DEPTH = 70.0            # perspective depth constant (m): smaller = more tilt
PPM = 7.0               # px per metre at the car's feet
D_NEAR = -35.0          # metres kept behind the car
D_FAR = 480.0           # forward draw distance (fog swallows the cutoff)
FOG_Y0, FOG_Y1 = 400, 535   # fog gradient band (transparent -> solid BG)

VIEW_AHEAD = 200.0      # view-circle centre this far ahead of the car
VIEW_R = 540.0          # view-circle radius for bbox culling
SERVICE_R = 260.0       # service alleys drawn only within this range

POSE_SMOOTH = 0.30      # per-frame exponential approach factor

# per-class (colour, half-width at the car in px), class 0 = major .. 3 =
# service. Roads render as Mesh triangle-strip ribbons whose width follows the
# perspective scale continuously per vertex — no depth bands, no stepping.
# NFS-style: a bright core over a wide soft glow (below). Minor-road hues stay
# close together (hierarchy comes from width) so a street that changes OSM
# class mid-block doesn't visibly change colour.
_ROAD_STYLE = [
    ((0.62, 0.82, 1.0, 1.0), 7.0),
    ((0.80, 0.87, 0.96, 0.72), 5.0),
    ((0.88, 0.91, 0.96, 0.50), 4.0),
    ((1.0, 1.0, 1.0, 0.20), 2.2),
]
# under-glow per class (colour incl. alpha, half-width multiplier); service
# roads get none. Drawn twice per road (wide faint + narrow stronger layer,
# see _GLOW_LAYERS) so the halo falls off softly instead of reading as a
# hard outline.
_GLOW_STYLE = [
    ((0.353, 0.651, 0.918, 0.26), 2.0),
    ((0.353, 0.651, 0.918, 0.15), 1.9),
    ((0.55, 0.70, 0.90, 0.09), 1.8),
    (None, 0),
]
_GLOW_LAYERS = ((1.7, 0.40), (1.0, 1.0))   # (extra width x, alpha x), wide first
_MITER_MAX = 3.0        # cap the miter extension at sharp street corners

_CAR_GLOW = (0.353, 0.651, 0.918, 0.28)
_CAR_FILL = (0.420, 0.706, 0.945, 1.0)
_CAR_EDGE = (0.949, 0.957, 0.973, 1.0)


class MapView(Widget):
    """Full-window perspective map, fed lat/lon/heading via ``update(state)``."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        with open(_MAP_DATA) as f:
            data = json.load(f)
        self.origin = data["origin"]
        lat0 = self.origin[0]
        self._m_per_deg = (111132.95, 111319.49 * math.cos(math.radians(lat0)))
        # (class, points, bbox) drawn minor-first so major roads sit on top
        self._roads = sorted(
            ((r["c"], r["p"], self._bbox(r["p"])) for r in data["roads"]),
            key=lambda r: -r[0])

        self._e = self._n = 0.0     # displayed pose (m from origin / degrees)
        self._hdg = 0.0
        self._have_pose = False
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
            Rectangle(pos=(0, FOG_Y1), size=(WINDOW_WIDTH, 720 - FOG_Y1))

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
        self._update(state)
        # rolling redraw-cost log ([map] in the journal) — the ribbon+glow
        # rebuild is the priciest per-frame Python in the app, and the Pi's
        # screen can't be seen remotely, so this is how it gets profiled
        self._perf_acc += time.perf_counter() - t0
        self._perf_n += 1
        if self._perf_n >= 600:            # ~20 s at 30 fps
            print(f"[map] redraw avg {1000 * self._perf_acc / self._perf_n:.1f}ms "
                  f"over {self._perf_n} frames", flush=True)
            self._perf_acc, self._perf_n = 0.0, 0

    def _update(self, state):
        lat, lon = state.lat, state.lon
        if lat == 0.0 and lon == 0.0:      # no fix yet: hold at the map origin
            self._redraw()
            return
        m_lat, m_lon = self._m_per_deg
        te = (lon - self.origin[1]) * m_lon
        tn = (lat - self.origin[0]) * m_lat

        if not self._have_pose:            # snap on the first fix
            self._e, self._n, self._hdg = te, tn, state.heading_deg
            self._have_pose = True
        else:
            k = POSE_SMOOTH
            self._e += (te - self._e) * k
            self._n += (tn - self._n) * k
            diff = (state.heading_deg - self._hdg + 180) % 360 - 180
            self._hdg = (self._hdg + diff * k) % 360

        self._redraw()

    def _redraw(self):
        e, n = self._e, self._n
        h = math.radians(self._hdg)
        sin_h, cos_h = math.sin(h), math.cos(h)
        ce = e + VIEW_AHEAD * sin_h        # view-circle centre, ahead of the car
        cn = n + VIEW_AHEAD * cos_h

        g = self._lines
        g.clear()

        # cull + transform + clip once (already sorted minor-first at load so
        # major roads draw on top within each pass)
        drawlist = []
        for cls, pts, bb in self._roads:
            if cls == 3:
                if self._bbox_dist2(bb, e, n) > SERVICE_R * SERVICE_R:
                    continue
            elif self._bbox_dist2(bb, ce, cn) > VIEW_R * VIEW_R:
                continue
            local = self._to_local(pts, e, n, sin_h, cos_h)
            chunks = _clip_depth(local, D_NEAR, D_FAR)
            if chunks:
                drawlist.append((cls, chunks))

        # pass 1: soft under-glow in two falloff layers; pass 2: bright cores
        for lw_k, la_k in _GLOW_LAYERS:
            last_cls = None
            for cls, chunks in drawlist:
                color, wk = _GLOW_STYLE[cls]
                if color is None:
                    continue
                if cls != last_cls:
                    g.add(Color(color[0], color[1], color[2], color[3] * la_k))
                    last_cls = cls
                for chunk in chunks:
                    self._draw_ribbon(g, chunk, _ROAD_STYLE[cls][1] * wk * lw_k)
        last_cls = None
        for cls, chunks in drawlist:
            if cls != last_cls:
                g.add(Color(*_ROAD_STYLE[cls][0]))
                last_cls = cls
            for chunk in chunks:
                self._draw_ribbon(g, chunk, _ROAD_STYLE[cls][1])

    @staticmethod
    def _to_local(pts, e, n, sin_h, cos_h):
        """Rotate world points into the car frame (lateral, forward depth)."""
        return [((p[0] - e) * cos_h - (p[1] - n) * sin_h,
                 (p[0] - e) * sin_h + (p[1] - n) * cos_h) for p in pts]

    @staticmethod
    def _draw_ribbon(g, chunk, hw0):
        """Draw a clipped car-frame polyline as a tapered triangle strip.

        Projects each point to screen with its own half-width from the
        perspective scale at that depth, then extrudes a ribbon along the
        screen-space normals (mitred at interior corners)."""
        pts = []
        for x, d in chunk:
            s = DEPTH / (d + DEPTH)
            sx, sy = CX + x * PPM * s, CAR_Y + RISE * d / (d + DEPTH)
            if pts and abs(sx - pts[-1][0]) + abs(sy - pts[-1][1]) < 0.5:
                continue                      # drop sub-pixel steps
            pts.append((sx, sy, hw0 * s))
        m = len(pts)
        if m < 2:
            return

        verts = []
        for i, (x, y, hw) in enumerate(pts):
            if i == 0:
                tx, ty = pts[1][0] - x, pts[1][1] - y
                tl = math.hypot(tx, ty) or 1.0
                tx, ty, k = tx / tl, ty / tl, 1.0
            elif i == m - 1:
                tx, ty = x - pts[i - 1][0], y - pts[i - 1][1]
                tl = math.hypot(tx, ty) or 1.0
                tx, ty, k = tx / tl, ty / tl, 1.0
            else:
                ax, ay = x - pts[i - 1][0], y - pts[i - 1][1]
                bx, by = pts[i + 1][0] - x, pts[i + 1][1] - y
                al = math.hypot(ax, ay) or 1.0
                bl = math.hypot(bx, by) or 1.0
                tx, ty = ax / al + bx / bl, ay / al + by / bl
                tl = math.hypot(tx, ty)
                if tl < 1e-6:                 # 180° reversal: fall back
                    tx, ty, k = ax / al, ay / al, 1.0
                else:
                    # miter length 1/cos(half-angle) = 2/|t1+t2|, capped
                    tx, ty, k = tx / tl, ty / tl, min(_MITER_MAX, 2.0 / tl)
            nx, ny = -ty * hw * k, tx * hw * k
            verts += (x + nx, y + ny, 0, 0, x - nx, y - ny, 0, 0)

        g.add(Mesh(vertices=verts, indices=list(range(2 * m)),
                   mode="triangle_strip"))

    @staticmethod
    def _bbox(pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    @staticmethod
    def _bbox_dist2(bb, x, y):
        dx = max(bb[0] - x, 0, x - bb[2])
        dy = max(bb[1] - y, 0, y - bb[3])
        return dx * dx + dy * dy


def _clip_depth(local, d_near, d_far):
    """Split a car-frame polyline into chunks inside d in [d_near, d_far].

    Per-segment 1-D Liang-Barsky on the depth axis, so a single long segment
    spanning the whole visible band (both ends outside) still draws.
    """
    chunks, cur = [], []

    def close():
        if len(cur) >= 2:
            chunks.append(list(cur))
        cur.clear()

    for (x0, d0), (x1, d1) in zip(local, local[1:]):
        dd = d1 - d0
        if dd == 0.0:
            if d_near <= d0 <= d_far:
                if not cur:
                    cur.append((x0, d0))
                cur.append((x1, d1))
            else:
                close()
            continue
        a = max(0.0, ((d_near if dd > 0 else d_far) - d0) / dd)
        b = min(1.0, ((d_far if dd > 0 else d_near) - d0) / dd)
        if a >= b:          # segment entirely outside the band
            close()
            continue
        if a > 0.0:         # enters the band mid-segment: new chunk
            close()
            cur.append((x0 + (x1 - x0) * a, d0 + dd * a))
        elif not cur:
            cur.append((x0, d0))
        cur.append((x0 + (x1 - x0) * b, d0 + dd * b))
        if b < 1.0:         # leaves the band mid-segment
            close()
    close()
    return chunks
