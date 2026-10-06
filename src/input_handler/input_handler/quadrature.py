"""Quarter-step quadrature decoder (no ROS / GPIO deps, so it is testable anywhere).

State is (a << 1) | b. Valid Gray-code transitions give +1 / -1; anything else
(contact bounce that skipped a state) gives 0 and is ignored.
"""

# (prev_state, new_state) -> step. Sequence 00 -> 01 -> 11 -> 10 -> 00 is +1.
_STEP = {
    (0b00, 0b01): 1, (0b01, 0b11): 1, (0b11, 0b10): 1, (0b10, 0b00): 1,
    (0b00, 0b10): -1, (0b10, 0b11): -1, (0b11, 0b01): -1, (0b01, 0b00): -1,
}


class Quadrature:
    """Feed it the new (a, b) levels on every edge; update() returns detent steps (-1, 0, +1)."""

    def __init__(self, a: int, b: int, steps_per_detent: int = 4):
        self._state = (a << 1) | b
        self._steps_per_detent = steps_per_detent
        self._acc = 0

    def update(self, a: int, b: int) -> int:
        new = (a << 1) | b
        self._acc += _STEP.get((self._state, new), 0)
        self._state = new
        if abs(self._acc) >= self._steps_per_detent:
            detent = 1 if self._acc > 0 else -1
            self._acc = 0
            return detent
        return 0
