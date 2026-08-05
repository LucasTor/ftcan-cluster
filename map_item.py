"""Perspective street-map scene-graph item (QML build of widgets/map_view.py).

All geometry (projection, culling, clipping, pose smoothing, mitred tapered
ribbons) comes from ``map_geometry`` — shared with the Kivy MapView — but
instead of ~600-900 Kivy Meshes per frame, all ribbons of one colour are
stitched (with degenerate triangles) into a single triangle strip, giving 10
QSGGeometryNodes total: 2 glow layers x 3 glowing classes + 4 core classes.
Fog and the car marker are drawn by MapLayout.qml on top of this item.

Coordinates: the shared pipeline works in the Kivy design space (y up from the
bottom of the 1920x720 window); this item flips to QML's y-down at the last
step.
"""

import ctypes
import struct
import time

from PySide6.QtCore import Property, Signal
from PySide6.QtGui import QColor
from PySide6.QtQuick import (QQuickItem, QSGFlatColorMaterial, QSGGeometry,
                             QSGGeometryNode, QSGNode)

from map_geometry import (ROAD_STYLE, GLOW_STYLE, GLOW_LAYERS,
                          RoadMap, SmoothedPose, ribbon_points, ribbon_quads)
from theme import WINDOW_HEIGHT

POINT_2D = QSGGeometry.defaultAttributes_Point2D()

_XY = struct.Struct("=ff")


class MapItem(QQuickItem):
    """Road ribbons + glow, fed lat/lon/heading via QML property bindings.
    ``dim`` carries the Theme's night-dim factor (these colours never pass
    through QML)."""

    poseChanged = Signal()
    dimChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlag(QQuickItem.ItemHasContents, True)

        self._map = RoadMap()
        self._pose = SmoothedPose()
        self._lat = self._lon = 0.0
        self._heading = 0.0
        self._dim = 0.0
        self._perf_acc, self._perf_n = 0.0, 0

        # (class, colour, half-width) per node, paint order: wide glow
        # minor->major, tight glow minor->major, cores minor->major
        self._passes = []
        for lw_k, la_k in GLOW_LAYERS:
            for cls in (2, 1, 0):
                color, wk = GLOW_STYLE[cls]
                self._passes.append(
                    (cls, (color[0], color[1], color[2], color[3] * la_k),
                     ROAD_STYLE[cls][1] * wk * lw_k))
        for cls in (3, 2, 1, 0):
            self._passes.append((cls, ROAD_STYLE[cls][0], ROAD_STYLE[cls][1]))

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

        if not (self._lat == 0.0 and self._lon == 0.0):  # no fix: hold at origin
            te, tn = self._map.to_en(self._lat, self._lon)
            self._pose.update(te, tn, self._heading)
        by_class = self._map.visible_chunks(self._pose.e, self._pose.n,
                                            self._pose.hdg)

        for (node, geom, _mat), (cls, _color, hw) in zip(self._nodes, self._passes):
            verts = []
            for chunk in by_class[cls]:
                self._ribbon_strip(chunk, hw, verts)
            count = len(verts)
            geom.allocate(count)
            if count:
                buf = bytearray(count * _XY.size)
                off = 0
                for x, y in verts:
                    _XY.pack_into(buf, off, x, y)
                    off += _XY.size
                ctypes.memmove(int(geom.vertexData()),
                               (ctypes.c_char * len(buf)).from_buffer(buf),
                               len(buf))
            node.markDirty(QSGNode.DirtyGeometry)

        # rolling redraw-cost log ([map] in the journal), same as the Kivy build
        self._perf_acc += time.perf_counter() - t0
        self._perf_n += 1
        if self._perf_n >= 600:
            print(f"[map] redraw avg {1000 * self._perf_acc / self._perf_n:.1f}ms "
                  f"over {self._perf_n} frames", flush=True)
            self._perf_acc, self._perf_n = 0.0, 0
        return root

    @staticmethod
    def _ribbon_strip(chunk, hw0, out):
        """Append a chunk's extruded ribbon to the running strip (QML y-down),
        stitching onto any previous ribbon with two degenerate vertices."""
        pts = ribbon_points(chunk, hw0)
        if len(pts) < 2:
            return
        first = len(out) == 0
        for i, ((xl, yl), (xr, yr)) in enumerate(ribbon_quads(pts)):
            a = (xl, WINDOW_HEIGHT - yl)
            if i == 0 and not first:
                out.append(out[-1])
                out.append(a)
            out.append(a)
            out.append((xr, WINDOW_HEIGHT - yr))
