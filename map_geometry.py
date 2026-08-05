"""Shared geometry pipeline for the perspective street map.

Single source for everything both map renderers — widgets/map_view.py (Kivy
Meshes) and map_item.py (QML scene-graph strips) — must agree on: the
projection constants, road/glow styling, the baked-road spatial index and
culling, pose smoothing, depth clipping and the mitred tapered-ribbon
extrusion. Each view only adapts the output (Kivy keeps y-up design space and
interleaves texture coords; QML flips to y-down and stitches one strip per
colour). Pure Python, no UI imports.

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

from theme import WINDOW_WIDTH

MAP_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "map_data.json")

# --- projection constants (design space 1920x720, y up) ---
CX = WINDOW_WIDTH / 2   # car screen anchor x
CAR_Y = 200             # car screen anchor y
RISE = 360              # CAR_Y -> horizon (d = infinity) vertical span
DEPTH = 70.0            # perspective depth constant (m): smaller = more tilt
PPM = 7.0               # px per metre at the car's feet
D_NEAR = -35.0          # metres kept behind the car
D_FAR = 480.0           # forward draw distance (fog swallows the cutoff)

VIEW_AHEAD = 200.0      # view-circle centre this far ahead of the car
VIEW_R = 540.0          # view-circle radius for bbox culling
SERVICE_R = 260.0       # service alleys drawn only within this range
CELL = 1000.0           # spatial-index cell size (m): per-frame culling only
                        # walks roads in cells near the view, so cost tracks
                        # local density, not total map size (25x25 km)

POSE_SMOOTH = 0.30      # per-frame exponential approach factor

# per-class (colour, half-width at the car in px), class 0 = major .. 3 =
# service. Roads render as triangle-strip ribbons whose width follows the
# perspective scale continuously per vertex — no depth bands, no stepping.
# NFS-style: a bright core over a wide soft glow (below). Minor-road hues stay
# close together (hierarchy comes from width) so a street that changes OSM
# class mid-block doesn't visibly change colour.
ROAD_STYLE = [
    ((0.62, 0.82, 1.0, 1.0), 7.0),
    ((0.80, 0.87, 0.96, 0.72), 5.0),
    ((0.88, 0.91, 0.96, 0.50), 4.0),
    ((1.0, 1.0, 1.0, 0.20), 2.2),
]
# under-glow per class (colour incl. alpha, half-width multiplier); service
# roads get none. Drawn twice per road (wide faint + narrow stronger layer,
# see GLOW_LAYERS) so the halo falls off softly instead of reading as a
# hard outline.
GLOW_STYLE = [
    ((0.353, 0.651, 0.918, 0.26), 2.0),
    ((0.353, 0.651, 0.918, 0.15), 1.9),
    ((0.55, 0.70, 0.90, 0.09), 1.8),
    (None, 0),
]
GLOW_LAYERS = ((1.7, 0.40), (1.0, 1.0))   # (extra width x, alpha x), wide first
MITER_MAX = 3.0         # cap the miter extension at sharp street corners


class SmoothedPose:
    """Displayed pose, exponentially approaching the raw GPS pose."""

    def __init__(self):
        self.e = self.n = 0.0   # metres east/north of the map origin
        self.hdg = 0.0          # degrees clockwise from true north
        self._have = False

    def update(self, te, tn, heading_deg):
        if not self._have:                 # snap on the first fix
            self.e, self.n, self.hdg = te, tn, heading_deg
            self._have = True
            return
        k = POSE_SMOOTH
        self.e += (te - self.e) * k
        self.n += (tn - self.n) * k
        diff = (heading_deg - self.hdg + 180) % 360 - 180
        self.hdg = (self.hdg + diff * k) % 360


class RoadMap:
    """Baked road network: load, spatial-index, cull and clip per frame."""

    def __init__(self, path=MAP_DATA):
        with open(path) as f:
            data = json.load(f)
        self.origin = data["origin"]
        lat0 = self.origin[0]
        self._m_per_deg = (111132.95, 111319.49 * math.cos(math.radians(lat0)))
        # (class, points, bbox) sorted minor-first so majors draw on top
        self._roads = sorted(
            ((r["c"], r["p"], _bbox(r["p"])) for r in data["roads"]),
            key=lambda r: -r[0])
        # spatial index: cell -> road indices whose bbox overlaps the cell
        self._cells = {}
        for i, (_cls, _pts, bb) in enumerate(self._roads):
            for cx in range(int(bb[0] // CELL), int(bb[2] // CELL) + 1):
                for cy in range(int(bb[1] // CELL), int(bb[3] // CELL) + 1):
                    self._cells.setdefault((cx, cy), []).append(i)

    def to_en(self, lat, lon):
        """WGS84 -> local metres east/north of the map origin."""
        m_lat, m_lon = self._m_per_deg
        return (lon - self.origin[1]) * m_lon, (lat - self.origin[0]) * m_lat

    def visible_chunks(self, e, n, hdg_deg):
        """Clipped car-frame polylines per road class for this pose.

        Returns four lists (class 0..3) of chunks — each a list of
        ``(lateral, depth)`` points — culled by the spatial index and the view
        circle, rotated heading-up, and clipped to [D_NEAR, D_FAR].
        """
        h = math.radians(hdg_deg)
        sin_h, cos_h = math.sin(h), math.cos(h)
        ce = e + VIEW_AHEAD * sin_h        # view-circle centre, ahead of the car
        cn = n + VIEW_AHEAD * cos_h

        # candidate roads from the spatial index (view circle fully covers the
        # service-range circle around the car, so one lookup serves both)
        seen = set()
        cand = []
        for cx in range(int((ce - VIEW_R) // CELL), int((ce + VIEW_R) // CELL) + 1):
            for cy in range(int((cn - VIEW_R) // CELL), int((cn + VIEW_R) // CELL) + 1):
                for i in self._cells.get((cx, cy), ()):
                    if i not in seen:
                        seen.add(i)
                        cand.append(i)
        cand.sort()   # index order = minor-first draw order within each class

        by_class = ([], [], [], [])
        for i in cand:
            cls, pts, bb = self._roads[i]
            if cls == 3:
                if _bbox_dist2(bb, e, n) > SERVICE_R * SERVICE_R:
                    continue
            elif _bbox_dist2(bb, ce, cn) > VIEW_R * VIEW_R:
                continue
            local = [((p[0] - e) * cos_h - (p[1] - n) * sin_h,
                      (p[0] - e) * sin_h + (p[1] - n) * cos_h) for p in pts]
            chunks = clip_depth(local, D_NEAR, D_FAR)
            if chunks:
                by_class[cls].extend(chunks)
        return by_class


def clip_depth(local, d_near, d_far):
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


def ribbon_points(chunk, hw0):
    """Project a clipped car-frame chunk to screen points (design space, y up).

    Each point carries its own half-width from the perspective scale at that
    depth; sub-pixel steps are dropped. Returns ``[(sx, sy, hw), ...]``.
    """
    pts = []
    for x, d in chunk:
        s = DEPTH / (d + DEPTH)
        sx, sy = CX + x * PPM * s, CAR_Y + RISE * d / (d + DEPTH)
        if pts and abs(sx - pts[-1][0]) + abs(sy - pts[-1][1]) < 0.5:
            continue
        pts.append((sx, sy, hw0 * s))
    return pts


def ribbon_quads(pts):
    """Extrude projected ribbon points along mitred screen-space normals.

    Yields one ``((xl, yl), (xr, yr))`` vertex pair per point (y up); consumed
    in order they form a tapered triangle strip.
    """
    m = len(pts)
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
                tx, ty, k = tx / tl, ty / tl, min(MITER_MAX, 2.0 / tl)
        nx, ny = -ty * hw * k, tx * hw * k
        yield (x + nx, y + ny), (x - nx, y - ny)


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_dist2(bb, x, y):
    dx = max(bb[0] - x, 0, x - bb[2])
    dy = max(bb[1] - y, 0, y - bb[3])
    return dx * dx + dy * dy
