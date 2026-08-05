"""Perspective street-map scene-graph item (QML build of widgets/map_view.py).

Same geometry pipeline as the Kivy MapView — pose smoothing, spatial-index
culling, car-frame rotation, depth clipping, plane-homography projection,
mitred tapered ribbons — but instead of ~600-900 Kivy Meshes per frame, all
ribbons of one colour are stitched (with degenerate triangles) into a single
triangle strip, giving 10 QSGGeometryNodes total: 2 glow layers x 3 glowing
classes + 4 core classes. Fog and the car marker are drawn by MapLayout.qml
on top of this item.

Coordinates: the projection math stays in the Kivy design space (y up from the
bottom of the 1920x720 window) and flips to QML's y-down at the last step.
"""

import ctypes
import json
import math
import os
import struct
import time

from PySide6.QtCore import Property, Signal
from PySide6.QtGui import QColor
from PySide6.QtQuick import (QQuickItem, QSGFlatColorMaterial, QSGGeometry,
                             QSGGeometryNode, QSGNode)

POINT_2D = QSGGeometry.defaultAttributes_Point2D()

_MAP_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "map_data.json")

# --- projection constants (design space 1920x720, y up) — keep in sync with
# widgets/map_view.py ---
WINDOW_W, WINDOW_H = 1920, 720
CX = WINDOW_W / 2
CAR_Y = 200
RISE = 360
DEPTH = 70.0
PPM = 7.0
D_NEAR = -35.0
D_FAR = 480.0

VIEW_AHEAD = 200.0
VIEW_R = 540.0
SERVICE_R = 260.0
CELL = 1000.0

POSE_SMOOTH = 0.30

_ROAD_STYLE = [
    ((0.62, 0.82, 1.0, 1.0), 7.0),
    ((0.80, 0.87, 0.96, 0.72), 5.0),
    ((0.88, 0.91, 0.96, 0.50), 4.0),
    ((1.0, 1.0, 1.0, 0.20), 2.2),
]
_GLOW_STYLE = [
    ((0.353, 0.651, 0.918, 0.26), 2.0),
    ((0.353, 0.651, 0.918, 0.15), 1.9),
    ((0.55, 0.70, 0.90, 0.09), 1.8),
    (None, 0),
]
_GLOW_LAYERS = ((1.7, 0.40), (1.0, 1.0))   # (extra width x, alpha x), wide first
_MITER_MAX = 3.0

_XY = struct.Struct("=ff")


def _clip_depth(local, d_near, d_far):
    """Split a car-frame polyline into chunks inside d in [d_near, d_far]."""
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
        if a >= b:
            close()
            continue
        if a > 0.0:
            close()
            cur.append((x0 + (x1 - x0) * a, d0 + dd * a))
        elif not cur:
            cur.append((x0, d0))
        cur.append((x0 + (x1 - x0) * b, d0 + dd * b))
        if b < 1.0:
            close()
    close()
    return chunks


def _ribbon_strip(chunk, hw0, out):
    """Append a clipped car-frame polyline to ``out`` as strip vertices.

    Projects each point to screen (QML y-down) with its own half-width from
    the perspective scale at that depth, then extrudes along the screen-space
    normals (mitred at interior corners). Returns True if anything was added.
    """
    pts = []
    for x, d in chunk:
        s = DEPTH / (d + DEPTH)
        sx = CX + x * PPM * s
        sy = WINDOW_H - (CAR_Y + RISE * d / (d + DEPTH))
        if pts and abs(sx - pts[-1][0]) + abs(sy - pts[-1][1]) < 0.5:
            continue
        pts.append((sx, sy, hw0 * s))
    m = len(pts)
    if m < 2:
        return False

    first = len(out) == 0
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
            if tl < 1e-6:
                tx, ty, k = ax / al, ay / al, 1.0
            else:
                tx, ty, k = tx / tl, ty / tl, min(_MITER_MAX, 2.0 / tl)
        nx, ny = -ty * hw * k, tx * hw * k
        if i == 0 and not first:
            # stitch onto the running strip with two degenerate vertices
            out.append(out[-1])
            out.append((x + nx, y + ny))
        out.append((x + nx, y + ny))
        out.append((x - nx, y - ny))
    return True


class MapItem(QQuickItem):
    """Road ribbons + glow, fed lat/lon/heading via QML property bindings.
    ``dim`` carries the Theme's night-dim factor (these colours never pass
    through QML)."""

    poseChanged = Signal()
    dimChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlag(QQuickItem.ItemHasContents, True)

        with open(_MAP_DATA) as f:
            data = json.load(f)
        self.origin = data["origin"]
        lat0 = self.origin[0]
        self._m_per_deg = (111132.95, 111319.49 * math.cos(math.radians(lat0)))
        self._roads = sorted(
            ((r["c"], r["p"], self._bbox(r["p"])) for r in data["roads"]),
            key=lambda r: -r[0])
        self._cells = {}
        for i, (_cls, _pts, bb) in enumerate(self._roads):
            for cx in range(int(bb[0] // CELL), int(bb[2] // CELL) + 1):
                for cy in range(int(bb[1] // CELL), int(bb[3] // CELL) + 1):
                    self._cells.setdefault((cx, cy), []).append(i)

        self._lat = self._lon = 0.0
        self._heading = 0.0
        self._dim = 0.0
        self._e = self._n = 0.0
        self._hdg = 0.0
        self._have_pose = False
        self._perf_acc, self._perf_n = 0.0, 0

        # (class, is_glow, colour, half-width multiplier) per node, paint order:
        # wide glow minor->major, tight glow minor->major, cores minor->major
        self._passes = []
        for lw_k, la_k in _GLOW_LAYERS:
            for cls in (2, 1, 0):
                color, wk = _GLOW_STYLE[cls]
                self._passes.append(
                    (cls, (color[0], color[1], color[2], color[3] * la_k),
                     _ROAD_STYLE[cls][1] * wk * lw_k))
        for cls in (3, 2, 1, 0):
            self._passes.append((cls, _ROAD_STYLE[cls][0], _ROAD_STYLE[cls][1]))

        self._nodes = None   # [(node, geom, mat)] refs — shiboken must not free

    # --- QML-facing pose properties (set at 30 Hz from the bridge) ---

    def _get_lat(self):
        return self._lat

    def _set_lat(self, v):
        self._lat = float(v)
        self.poseChanged.emit()
        self.update()

    def _get_lon(self):
        return self._lon

    def _set_lon(self, v):
        self._lon = float(v)
        self.poseChanged.emit()
        self.update()

    def _get_heading(self):
        return self._heading

    def _set_heading(self, v):
        self._heading = float(v)
        self.poseChanged.emit()
        self.update()

    lat = Property(float, _get_lat, _set_lat, notify=poseChanged)
    lon = Property(float, _get_lon, _set_lon, notify=poseChanged)
    heading = Property(float, _get_heading, _set_heading, notify=poseChanged)

    def _get_dim(self):
        return self._dim

    def _set_dim(self, v):
        if v != self._dim:
            self._dim = float(v)
            self.dimChanged.emit()
            self.update()

    dim = Property(float, _get_dim, _set_dim, notify=dimChanged)

    # --- scene-graph build ---

    def updatePaintNode(self, root, _data):
        t0 = time.perf_counter()
        if root is None:
            root = QSGNode()
            self._nodes = []
            for _cls, color, _hw in self._passes:
                node = QSGGeometryNode()
                geom = QSGGeometry(POINT_2D, 0)
                geom.setDrawingMode(QSGGeometry.DrawTriangleStrip)
                node.setGeometry(geom)
                mat = QSGFlatColorMaterial()
                mat.setColor(QColor.fromRgbF(*color))
                node.setMaterial(mat)
                root.appendChildNode(node)
                self._nodes.append((node, geom, mat))
            self._root = root

        # palette night dim (see Theme.d): scale material colours in place
        k = 1.0 - self._dim * 0.55
        for (node, _geom, mat), (_cls, color, _hw) in zip(self._nodes, self._passes):
            mat.setColor(QColor.fromRgbF(color[0] * k, color[1] * k,
                                         color[2] * k, color[3]))
            node.markDirty(QSGNode.DirtyMaterial)

        self._smooth_pose()
        strips = self._build_strips()
        for (node, geom, _mat), verts in zip(self._nodes, strips):
            count = len(verts)
            geom.allocate(count)
            if count:
                buf = bytearray(count * _XY.size)
                off = 0
                for x, y in verts:
                    _XY.pack_into(buf, off, x, y)
                    off += _XY.size
                ctypes.memmove(int(geom.vertexData()), bytes(buf), len(buf))
            node.markDirty(QSGNode.DirtyGeometry)

        # rolling redraw-cost log ([map] in the journal), same as the Kivy build
        self._perf_acc += time.perf_counter() - t0
        self._perf_n += 1
        if self._perf_n >= 600:
            print(f"[map] redraw avg {1000 * self._perf_acc / self._perf_n:.1f}ms "
                  f"over {self._perf_n} frames", flush=True)
            self._perf_acc, self._perf_n = 0.0, 0
        return root

    def _smooth_pose(self):
        lat, lon = self._lat, self._lon
        if lat == 0.0 and lon == 0.0:      # no fix yet: hold at the map origin
            return
        m_lat, m_lon = self._m_per_deg
        te = (lon - self.origin[1]) * m_lon
        tn = (lat - self.origin[0]) * m_lat
        if not self._have_pose:            # snap on the first fix
            self._e, self._n, self._hdg = te, tn, self._heading
            self._have_pose = True
        else:
            k = POSE_SMOOTH
            self._e += (te - self._e) * k
            self._n += (tn - self._n) * k
            diff = (self._heading - self._hdg + 180) % 360 - 180
            self._hdg = (self._hdg + diff * k) % 360

    def _build_strips(self):
        e, n = self._e, self._n
        h = math.radians(self._hdg)
        sin_h, cos_h = math.sin(h), math.cos(h)
        ce = e + VIEW_AHEAD * sin_h
        cn = n + VIEW_AHEAD * cos_h

        seen = set()
        cand = []
        for cx in range(int((ce - VIEW_R) // CELL), int((ce + VIEW_R) // CELL) + 1):
            for cy in range(int((cn - VIEW_R) // CELL), int((cn + VIEW_R) // CELL) + 1):
                for i in self._cells.get((cx, cy), ()):
                    if i not in seen:
                        seen.add(i)
                        cand.append(i)
        cand.sort()

        by_class = ([], [], [], [])   # chunk lists per road class
        for i in cand:
            cls, pts, bb = self._roads[i]
            if cls == 3:
                if self._bbox_dist2(bb, e, n) > SERVICE_R * SERVICE_R:
                    continue
            elif self._bbox_dist2(bb, ce, cn) > VIEW_R * VIEW_R:
                continue
            local = [((p[0] - e) * cos_h - (p[1] - n) * sin_h,
                      (p[0] - e) * sin_h + (p[1] - n) * cos_h) for p in pts]
            chunks = _clip_depth(local, D_NEAR, D_FAR)
            if chunks:
                by_class[cls].extend(chunks)

        strips = []
        for cls, _color, hw in self._passes:
            out = []
            for chunk in by_class[cls]:
                _ribbon_strip(chunk, hw, out)
            strips.append(out)
        return strips

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
