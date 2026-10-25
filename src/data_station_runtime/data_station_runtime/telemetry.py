"""Thread-safe numeric telemetry with metadata and monotonic freshness."""

from copy import deepcopy
from math import isfinite
from threading import RLock
import time


def _signal_id(bus, message, signal):
    for component in (bus, message, signal):
        if not isinstance(component, str) or not component or "/" in component:
            raise ValueError("Telemetry identity components must be nonempty and contain no '/'")
    return f"{bus}/{message}/{signal}"


def signal_definition(bus, message, signal, **metadata):
    """Build an unambiguous identity without changing DBC names."""
    return {
        "unit": None, "choices": {}, "minimum": None, "maximum": None,
        "frame_id": None, "is_extended_id": False, "bit_length": None,
        "is_signed": None, "is_float": None, "multiplexer_signal": None,
        "multiplexer_ids": None, **deepcopy(metadata),
        "id": _signal_id(bus, message, signal),
        "bus": bus, "message": message, "signal": signal,
    }


class TelemetryStore:
    """Retain exact integers; never use wall-clock time to determine freshness."""

    def __init__(self, stale_after=1.0):
        if not isfinite(stale_after) or stale_after <= 0:
            raise ValueError("stale_after must be finite and positive")
        self.stale_after = stale_after
        self._lock = RLock()
        self._definitions = {}
        self._external = {}
        self._samples = {}

    def replace_catalog(self, definitions):
        """Replace CAN definitions and samples, preserving externally registered data."""
        candidate = {item["id"]: deepcopy(item) for item in definitions}
        if len(candidate) != len(definitions):
            raise ValueError("Duplicate telemetry signal identity")
        with self._lock:
            self._external = {key: item for key, item in self._external.items()
                              if key not in candidate}
            self._definitions = self._external | candidate
            self._samples = {key: sample for key, sample in self._samples.items()
                             if key in self._external}

    def register(self, bus, message, signals):
        """Register external signal names mapped to metadata, using {} when unknown."""
        definitions = [signal_definition(bus, message, name, **metadata)
                       for name, metadata in signals.items()]
        with self._lock:
            for item in definitions:
                key = item["id"]
                if key in self._definitions and key not in self._external:
                    continue
                if self._definitions.get(key) != item:
                    self._samples.pop(key, None)
                self._external[key] = item
                self._definitions[key] = item

    def update(self, bus, message, values, *, timestamp=None, received_at=None):
        """Update only received signals; inactive multiplexed fields age independently."""
        timestamp = time.time() if timestamp is None else timestamp
        received_at = time.monotonic() if received_at is None else received_at
        if not isfinite(timestamp) or not isfinite(received_at):
            raise ValueError("Telemetry timestamps must be finite")
        samples = {}
        for signal, value in values.items():
            if type(value) not in (int, float):
                raise TypeError("Telemetry values must be Python int or float")
            key = _signal_id(bus, message, signal)
            samples[key] = (value, timestamp, received_at)
        with self._lock:
            missing = samples.keys() - self._definitions.keys()
            if missing:
                raise KeyError(f"Unregistered telemetry signals: {sorted(missing)}")
            self._samples.update(samples)

    def catalog(self):
        with self._lock:
            return deepcopy(list(self._definitions.values()))

    def snapshot(self, now=None):
        """Return JSON-ready samples; unseen, stale, and nonfinite values are invalid."""
        now = time.monotonic() if now is None else now
        if not isfinite(now):
            raise ValueError("Snapshot monotonic time must be finite")
        with self._lock:
            result = []
            for key in self._definitions:
                sample = self._samples.get(key)
                value, timestamp, received_at = sample if sample else (None, None, None)
                age = now - received_at if sample else None
                finite = not isinstance(value, float) or isfinite(value)
                result.append({
                    "id": key, "value": value if finite else None,
                    "timestamp": timestamp, "age": age, "seen": sample is not None,
                    "valid": sample is not None and finite and 0 <= age <= self.stale_after,
                })
            return result
