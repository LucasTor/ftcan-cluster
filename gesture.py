"""Flash-and-hold gesture detector on the high-beam flasher stalk.

Cycling the dash layout needs a driver control that exists in a 1992 Gol and
can't fire by accident. The gesture: **one short flash, then pull again and
hold** (~0.6 s). Discrimination against real-world stalk use:

  * normal high beam        — single long ON, no short pulse before it -> no.
  * single flash-to-pass    — one short pulse -> no.
  * double flash-to-pass    — two short pulses (second one released) -> no.
  * flash + hold            — short pulse, brief gap, sustained pull -> FIRE.

Pure logic, no GPIO imports, so it runs and tests anywhere. Feed it the
active-state each frame via :meth:`sample`; it returns ``True`` exactly once
per completed gesture (the stalk must be released to re-arm).
"""

PULSE_MAX = 0.45   # s: first pull must be shorter than this (a "flash")
GAP_MAX = 0.90     # s: max release time between the flash and the hold-pull
HOLD_MIN = 0.60    # s: second pull must be sustained this long to fire


class FlashHold:
    """State machine over (active, now) samples; ``sample`` -> fired bool."""

    _IDLE, _PULSE, _GAP, _HOLD, _DONE = range(5)

    def __init__(self):
        self._st = self._IDLE
        self._t = 0.0          # entry time of the current phase
        self._was = False

    def sample(self, active, now):
        active = bool(active)
        rising = active and not self._was
        falling = self._was and not active
        self._was = active

        if self._st == self._IDLE:
            if rising:
                self._st, self._t = self._PULSE, now
        elif self._st == self._PULSE:
            if falling:
                if now - self._t <= PULSE_MAX:
                    self._st, self._t = self._GAP, now   # it was a flash
                else:
                    self._st = self._IDLE                # too long: high beam
        elif self._st == self._GAP:
            if rising:
                self._st, self._t = self._HOLD, now
            elif now - self._t > GAP_MAX:
                self._st = self._IDLE                    # second pull too late
        elif self._st == self._HOLD:
            if falling:
                self._st = self._IDLE                    # released too soon
            elif now - self._t >= HOLD_MIN:
                self._st = self._DONE                    # fire once
                return True
        elif self._st == self._DONE:
            if falling:
                self._st = self._IDLE                    # re-arm on release
        return False
