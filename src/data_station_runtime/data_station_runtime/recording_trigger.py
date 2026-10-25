"""Combine independent recording requests without depending on ROS.

Publisher silence leaves its last request unchanged. Only an explicit inactive
sample clears a request, so a lost publisher cannot silently stop a running bag.
"""

class RecordingTriggers:
    def __init__(self, on_trigger):
        self._on_trigger = on_trigger
        self._precharge = False
        self._autonomous = False

    @property
    def active(self) -> bool:
        return self._precharge or self._autonomous

    def on_precharge(self, active: bool) -> None:
        self._precharge = active
        self._on_trigger(self.active)

    def on_jetson_state(self, as_state: int) -> None:
        self._autonomous = as_state in (2, 3)  # READY remains active through DRIVING.
        self._on_trigger(self.active)
