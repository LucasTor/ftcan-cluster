"""Comet-trail RPM ring for the dense "detail" layout (QML build).

Scene-graph twin of the ring in widgets/big_dial.py: a wide annulus whose
colour trails the needle — strongest right behind it, fading back toward 0,
igniting through pale gold and orange to red past the redline. Drawn as ONE
vertex-coloured triangle strip (QSGGeometryNode), rebuilt when `rpm` changes;
the needle / hub / numbers / gear live in BigDial.qml on top.

PySide6 scene-graph gotchas handled here (found the hard way):
  * the AttributeSet must outlive every geometry built from it (module global);
  * keep Python refs to node/geometry/material or shiboken frees them;
  * vertex data is written by packing bytes and memmove-ing into vertexData()
    (the per-vertex accessors don't expose an array in PySide6);
  * needs QSG_RENDER_LOOP=basic (set by cluster_qml before the app starts).
"""

import ctypes
import math
import struct

from PySide6.QtQuick import (QQuickItem, QSGGeometry, QSGGeometryNode, QSGNode,
                             QSGVertexColorMaterial)
from PySide6.QtCore import Property, Signal

COLORED_2D = QSGGeometry.defaultAttributes_ColoredPoint2D()

# geometry/colour constants — keep in sync with widgets/big_dial.py
START = -160.0        # 0 at ~6:40 (0 = top, +ve clockwise)
SWEEP = 245.0
EXT = 14.0            # ring extends past 0 and 8 so the numbers sit on it
RING_R = 190
RING_W = 128
SEGS = 500            # angular samples across the number span
FADE_RPM = 700        # rpm over which the trail switches cyan -> red

WHITE = (0.97, 0.985, 1.0, 1.0)
CYAN = (0.05, 0.80, 1.0, 1.0)
RED = (0.98, 0.26, 0.05, 1.0)
PALE_GOLD = (1.0, 0.85, 0.45, 1.0)
ORANGE = (1.0, 0.55, 0.02, 1.0)
HUE_STOPS = [(0.0, CYAN), (0.35, PALE_GOLD), (0.7, ORANGE), (1.0, RED)]

_VERT = struct.Struct("=ff4B")


def _lerp(a, b, t):
    return tuple(a[j] + (b[j] - a[j]) * t for j in range(4))


class RingItem(QQuickItem):
    """The coloured ring band only; QML feeds it the display-smoothed RPM
    (and the Theme's night-dim factor, since these colours never pass
    through QML)."""

    rpmChanged = Signal()
    dimChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlag(QQuickItem.ItemHasContents, True)
        self._rpm = 0.0
        self._dim = 0.0
        self._max = 8000.0
        self._redline = 5000.0

        # precomputed angle samples (deg -> sin/cos) and each sample's rpm
        lo, hi = START - EXT, START + SWEEP + EXT
        nseg = round(SEGS * (hi - lo) / SWEEP)
        self._samples = []
        for i in range(nseg + 1):
            a = lo + (hi - lo) * i / nseg
            th = math.radians(a)
            self._samples.append(
                (math.sin(th), math.cos(th), ((a - START) / SWEEP) * self._max))
        self._nverts = 2 * len(self._samples)

    def _get_rpm(self):
        return self._rpm

    def _set_rpm(self, v):
        if v != self._rpm:
            self._rpm = float(v)
            self.rpmChanged.emit()
            self.update()

    rpm = Property(float, _get_rpm, _set_rpm, notify=rpmChanged)

    def _get_dim(self):
        return self._dim

    def _set_dim(self, v):
        if v != self._dim:
            self._dim = float(v)
            self.dimChanged.emit()
            self.update()

    dim = Property(float, _get_dim, _set_dim, notify=dimChanged)

    def _hue(self, rpm):
        if rpm <= self._redline:
            return CYAN
        t = min(1.0, (rpm - self._redline) / FADE_RPM)
        for (t0, c0), (t1, c1) in zip(HUE_STOPS, HUE_STOPS[1:]):
            if t <= t1:
                return _lerp(c0, c1, (t - t0) / (t1 - t0))
        return RED

    def updatePaintNode(self, node, _data):
        if node is None:
            node = QSGGeometryNode()
            geom = QSGGeometry(COLORED_2D, self._nverts)
            geom.setDrawingMode(QSGGeometry.DrawTriangleStrip)
            node.setGeometry(geom)
            mat = QSGVertexColorMaterial()
            node.setMaterial(mat)
            self._node, self._geom, self._mat = node, geom, mat

        cx = self.width() / 2
        cy = self.height() / 2
        r_in = RING_R - RING_W / 2
        r_out = RING_R + RING_W / 2
        disp = self._rpm
        n = max(disp, 1.0)
        hue = self._hue(disp)
        k = 1.0 - self._dim * 0.55   # palette night dim (see Theme.d)

        buf = bytearray(self._nverts * _VERT.size)
        off = 0
        for sin_a, cos_a, rpm_s in self._samples:
            if rpm_s <= 0 or rpm_s > disp:      # margins / above needle: white
                c = WHITE
            else:                               # behind the needle: fade
                c = _lerp(WHITE, hue, rpm_s / n)
            cr, cg, cb = (int(x * k * 255) for x in c[:3])
            ca = int(c[3] * 255)
            _VERT.pack_into(buf, off, cx + r_in * sin_a, cy - r_in * cos_a,
                            cr, cg, cb, ca)
            off += _VERT.size
            _VERT.pack_into(buf, off, cx + r_out * sin_a, cy - r_out * cos_a,
                            cr, cg, cb, ca)
            off += _VERT.size

        ctypes.memmove(int(self._geom.vertexData()), bytes(buf), len(buf))
        self._node.markDirty(QSGNode.DirtyGeometry)
        return self._node
