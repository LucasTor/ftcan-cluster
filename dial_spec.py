"""Geometry and trail-colour spec for the detail layout's big RPM dial.

Single source for the three renderers of the same dial: the Kivy build
(widgets/big_dial.py), the QML scene-graph ring (ring_item.py) and
BigDial.qml (via ``SensorBridge.dial``). Pure Python, no UI imports.
"""

START = -160.0        # 0 at ~6:40 (0 = top, +ve clockwise)
SWEEP = 245.0         # numbers 0..8 span this; the rest is the bottom-right gap
EXT = 14.0            # ring extends this many degrees past 0 and 8
RING_R = 190          # ring centreline radius
RING_W = 128          # ring thickness (wide — fills from the hub to the rim)
NUM_R = 236           # numbers sit near the outer edge of the ring band
HUB_R = 128           # big black hub (holds the gear) — ~half the outer radius
SEGS = 500            # angular samples across the number span (fade smoothness)

MAX_RPM = 8000.0
REDLINE_RPM = 5000.0
FADE_RPM = 700        # rpm over which the whole trail switches cyan -> red

# Kivy's Line.width is a HALF-width: the band is extruded +-RING_W around the
# centreline (inner 62, outer 318 — FBO-measured 2026-08-05). The face disc,
# needle tip and rim dots key off the *nominal* outer edge instead:
OUTER_R = RING_R + RING_W / 2

WHITE = (0.97, 0.985, 1.0, 1.0)   # ring above the needle / faded tail
CYAN = (0.05, 0.80, 1.0, 1.0)     # colour just behind the needle
RED = (0.98, 0.26, 0.05, 1.0)     # colour in the redline
# redline transition keyframes (see hue): cyan brightens to pale gold, then
# ignites through orange to red. A direct cyan->red lerp muddies to grey-brown,
# and a white bridge vanishes against the white ring — gold stays visible.
PALE_GOLD = (1.0, 0.85, 0.45, 1.0)
ORANGE = (1.0, 0.55, 0.02, 1.0)
HUE_STOPS = [(0.0, CYAN), (0.35, PALE_GOLD), (0.7, ORANGE), (1.0, RED)]

# constants BigDial.qml needs (exposed through SensorBridge.dial)
QML_SPEC = {
    "start": START, "sweep": SWEEP, "hubR": HUB_R, "outer": OUTER_R,
    "numR": NUM_R, "maxRpm": MAX_RPM,
}


def lerp4(a, b, t):
    return tuple(a[j] + (b[j] - a[j]) * t for j in range(4))


def hue(rpm, redline=REDLINE_RPM):
    """Trail hue for the whole comet tail at this rpm."""
    if rpm <= redline:
        return CYAN
    t = min(1.0, (rpm - redline) / FADE_RPM)
    for (t0, c0), (t1, c1) in zip(HUE_STOPS, HUE_STOPS[1:]):
        if t <= t1:
            return lerp4(c0, c1, (t - t0) / (t1 - t0))
    return RED
