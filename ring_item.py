"""Comet-trail RPM ring for the dense "detail" layout (QML build).

Scene-graph twin of the ring in widgets/big_dial.py: a wide annulus whose
colour trails the needle — strongest right behind it, fading back toward 0,
igniting through pale gold and orange to red past the redline. Drawn as ONE
vertex-coloured triangle strip (QSGGeometryNode), rebuilt when `rpm` changes;
the needle / hub / numbers / gear live in BigDial.qml on top. Geometry and
trail colours come from ``dial_spec`` (shared with the Kivy dial).

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

from dial_spec import (START, SWEEP, EXT, RING_R, RING_W, SEGS,
                       MAX_RPM, WHITE, hue, lerp4)

COLORED_2D = QSGGeometry.defaultAttributes_ColoredPoint2D()

# Skip rebuilds for sub-visual rpm deltas: 4 rpm ≈ 0.1° of band. Without this
# the 150 ms display Behavior in BigDial.qml re-packs all ~1060 vertices every
# frame while it settles toward a steady value.
RPM_EPS = 4.0

_VERT = struct.Struct("=ff4B")


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

        # precomputed angle samples (deg -> sin/cos) and each sample's rpm
        lo, hi = START - EXT, START + SWEEP + EXT
        nseg = round(SEGS * (hi - lo) / SWEEP)
        self._samples = []
        for i in range(nseg + 1):
            a = lo + (hi - lo) * i / nseg
            th = math.radians(a)
            self._samples.append(
                (math.sin(th), math.cos(th), ((a - START) / SWEEP) * MAX_RPM))
        self._nverts = 2 * len(self._samples)

    def _get_rpm(self):
        return self._rpm

    def _set_rpm(self, v):
        v = float(v)
        if abs(v - self._rpm) < RPM_EPS:
            return
        self._rpm = v
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
        # Kivy's Line.width is a HALF-width: the original band is extruded
        # +-RING_W around the centreline (inner 62, outer 318 — verified by
        # FBO-measuring the Kivy dial, 2026-08-05), overflowing the 600px
        # widget. The hub covers the inner part; numbers and rim dots sit ON
        # the band.
        r_in = RING_R - RING_W
        r_out = RING_R + RING_W
        disp = self._rpm
        n = max(disp, 1.0)
        trail = hue(disp)
        k = 1.0 - self._dim * 0.55   # palette night dim (see Theme.d)

        buf = bytearray(self._nverts * _VERT.size)
        off = 0
        for sin_a, cos_a, rpm_s in self._samples:
            if rpm_s <= 0 or rpm_s > disp:      # margins / above needle: white
                c = WHITE
            else:                               # behind the needle: fade
                c = lerp4(WHITE, trail, rpm_s / n)
            cr, cg, cb = (int(x * k * 255) for x in c[:3])
            ca = int(c[3] * 255)
            _VERT.pack_into(buf, off, cx + r_in * sin_a, cy - r_in * cos_a,
                            cr, cg, cb, ca)
            off += _VERT.size
            _VERT.pack_into(buf, off, cx + r_out * sin_a, cy - r_out * cos_a,
                            cr, cg, cb, ca)
            off += _VERT.size

        ctypes.memmove(int(self._geom.vertexData()),
                       (ctypes.c_char * len(buf)).from_buffer(buf), len(buf))
        self._node.markDirty(QSGNode.DirtyGeometry)
        return self._node
