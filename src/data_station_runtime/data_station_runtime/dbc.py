"""Load DBCs as runtime data and decode each CAN bus independently."""

from copy import deepcopy
import hashlib
from pathlib import Path

import cantools

from .telemetry import TelemetryStore, signal_definition


class DbcRuntime:
    """Validate all DBCs before startup or an atomic explicit reload."""

    def __init__(self, paths, stale_after=1.0):
        self.store = TelemetryStore(stale_after)
        self._paths = {}
        self._databases = {}
        self._messages = {}
        self._frames = {}
        self._manifest = {}
        self.reload(paths)

    def reload(self, paths=None):
        """Keep the active databases, catalog, and samples when any validation fails."""
        with self.store._lock:
            paths = dict(self._paths if paths is None else paths)
        if not paths:
            raise ValueError("At least one CAN bus DBC is required")
        databases, messages, frames, definitions, manifest = {}, {}, {}, [], {}
        for bus, filename in paths.items():
            signal_definition(bus, "_", "_")
            data = Path(filename).read_bytes()
            try:
                text = data.decode("utf-8")
                encoding = "utf-8"
            except UnicodeDecodeError:
                text = data.decode("cp1252")
                encoding = "cp1252"
            database = cantools.database.load_string(text, database_format="dbc", strict=True)
            manifest[bus] = {"path": str(Path(filename).resolve()),
                             "sha256": hashlib.sha256(data).hexdigest(),
                             "content": text, "encoding": encoding}
            databases[bus] = database
            names = set()
            for message in database.messages:
                key = (bus, message.frame_id, message.is_extended_frame)
                if key in messages or message.name in names:
                    raise ValueError(f"Duplicate CAN message in bus {bus}: {message.name}")
                names.add(message.name)
                signals = []
                signal_names = set()
                for signal in message.signals:
                    if signal.name in signal_names:
                        raise ValueError(f"Duplicate signal in {bus}/{message.name}: {signal.name}")
                    signal_names.add(signal.name)
                    signals.append(signal_definition(
                        bus, message.name, signal.name,
                        frame_id=message.frame_id, is_extended_id=message.is_extended_frame,
                        unit=signal.unit, minimum=signal.minimum, maximum=signal.maximum,
                        choices={code: str(label) for code, label in (signal.choices or {}).items()},
                        bit_length=signal.length, is_signed=signal.is_signed,
                        is_float=signal.is_float, multiplexer_signal=signal.multiplexer_signal,
                        multiplexer_ids=signal.multiplexer_ids,
                    ))
                messages[key] = message
                frames[key] = {
                    "bus": bus, "message": message.name, "frame_id": message.frame_id,
                    "is_extended_id": message.is_extended_frame, "signals": signals,
                }
                definitions.extend(signals)
        with self.store._lock:
            self.store.replace_catalog(definitions)
            self._paths = paths
            self._databases = databases
            self._messages = messages
            self._frames = frames
            self._manifest = manifest

    def manifest(self):
        """Return the exact validated sources and hashes, including legacy encoding."""
        with self.store._lock:
            return deepcopy(self._manifest)

    def describe_frame(self, bus, frame_id, is_extended_id=False):
        with self.store._lock:
            return deepcopy(self._frames.get((bus, frame_id, is_extended_id)))

    def decode(self, bus, frame_id, payload, *, is_extended_id=False,
               timestamp=None, received_at=None):
        """Return numeric active signals, or None for unknown bus/ID/frame format."""
        with self.store._lock:
            message = self._messages.get((bus, frame_id, is_extended_id))
            if message is None:
                return None
            values = message.decode(payload, decode_choices=False, allow_excess=False)
            self.store.update(bus, message.name, values,
                              timestamp=timestamp, received_at=received_at)
            return values
