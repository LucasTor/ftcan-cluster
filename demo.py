"""Drive simulation used when there's no CAN signal (bench / not-in-car).

A ~15s loop — idle -> 2-step -> on-boost pull -> cruise -> decel — ported from
the Painel Gol design's animation. Only engine / CAN-derived fields are produced;
GPIO inputs (turn signals, headlights) are left to the real hardware.
"""

import math

CYCLE = 15.0  # seconds per loop


class DemoFeed:
    """Feeds the simulation into a ``SensorState`` while no CAN is present.

    Writes only engine/CAN-derived fields (not GPIO inputs) directly into the
    state — bypassing ``update()`` so it doesn't reset the CAN-activity clock.
    Real CAN frames take over automatically the moment they arrive. Both UI
    builds drive this from their render tick.
    """

    def __init__(self):
        self._t0 = None  # monotonic time the demo loop engaged

    def feed(self, state, now):
        """Write simulated values for ``now`` and return the demo elapsed time
        (drives the tell-tale bulb check)."""
        if self._t0 is None:
            self._t0 = now
        t = now - self._t0
        vals = simulate(t)
        state.rpm = vals["rpm"]
        state.wheel_speed_fl_kmh = vals["speed"]
        state.map = vals["map"]
        state.lambda_afr = vals["lambda_afr"]
        state.engine_temp = vals["engine_temp"]
        state.air_temp = vals["air_temp"]
        state.oil_pressure_bar = vals["oil"]
        state.oil_temp = vals["oiltemp"]
        state.fuel_level = vals["fuel"]
        state.egt1, state.egt2, state.egt3, state.egt4 = (
            vals["egt1"], vals["egt2"], vals["egt3"], vals["egt4"])
        return t

    def reset(self):
        self._t0 = None


def _lerp(a, b, k):
    k = max(0.0, min(1.0, k))
    return a + (b - a) * k


def _ease(k):
    if k <= 0:
        return 0.0
    if k >= 1:
        return 1.0
    return k * k * (3 - 2 * k)


def simulate(t):
    """Return simulated sensor values (dict of SensorState fields) at time t."""
    t = t % CYCLE
    speed, rpm, boost, lam = 0.0, 900.0, -0.5, 0.99
    coolant, intake, oil, fuel = 80.0, 36.0, 3.2, 64.0

    if t < 2:  # idle
        rpm = 900 + 40 * math.sin(t * 9)
        boost, lam, coolant, intake = -0.5, 0.99, 78, 36
    elif t < 4:  # 2-step armed
        rpm = 4750 + 220 * math.sin(t * 22)
        boost = _lerp(0.2, 0.7, _ease((t - 2) / 2))
        lam, coolant, intake = 0.90, 84, 42
    elif t < 10:  # on boost, through the gears
        p = (t - 4) / 6
        speed = _lerp(0, 188, _ease(p))
        lp = ((t - 4) % 2.0) / 2.0
        rpm = _lerp(3700, 6850, lp)
        boost = 1.22 + 0.16 * math.sin((t - 4) * 3.0)
        lam, oil = 0.82, 3.6
        coolant, intake = _lerp(88, 104, p), _lerp(44, 63, p)
    elif t < 13:  # cruise
        p = (t - 10) / 3
        speed = _lerp(188, 118, p)
        rpm = 3000 + 60 * math.sin(t * 4)
        boost, lam, intake = 0.06, 0.95, 56
        coolant = _lerp(104, 101, p)
    else:  # decel
        p = (t - 13) / 2
        speed = _lerp(118, 0, _ease(p))
        rpm = _lerp(2600, 900, _ease(p))
        boost, lam, intake = -0.4, 1.03, 48
        coolant = _lerp(101, 96, p)

    # EGT per cylinder — rises with load; cyl 3 drifts hot on boost to show the
    # balance dots turning red, otherwise the four sit close (all green).
    base_egt = max(140.0, _lerp(360, 900, _ease(min(1.0, (rpm - 900) / 6000))) + boost * 90)
    offsets = [6.0, -10.0, (95.0 if boost > 0.8 else 12.0), -4.0]
    egt = [base_egt + o for o in offsets]

    return {
        "rpm": rpm, "speed": speed, "map": boost, "lambda_afr": lam,
        "engine_temp": coolant, "air_temp": intake, "oil": oil, "fuel": fuel,
        "oiltemp": coolant + 8,   # oil runs a little hotter than coolant
        "egt1": egt[0], "egt2": egt[1], "egt3": egt[2], "egt4": egt[3],
    }
