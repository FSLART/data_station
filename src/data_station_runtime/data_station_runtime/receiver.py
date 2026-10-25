"""Consume the fixed telemetry contract without importing ROS or Qt."""

import json
import re
import time
from collections import OrderedDict
from math import isfinite

from .telemetry import TelemetryStore, signal_definition


def ros_name(raw):
    """Match the existing lart_msgs generator's field and topic spelling."""
    slug = re.sub(r"[^a-zA-Z0-9_]", "_", raw).strip("_").lower()
    return "val_" + slug if slug and slug[0].isdigit() else slug


def ros_type_name(raw):
    return "".join(word.capitalize() for word in ros_name(raw).split("_") if word)


def signal_value(signal):
    if signal.kind == 0:
        return int(signal.int_value)
    if signal.kind == 1:
        return int(signal.uint_value)
    if signal.kind == 2:
        return float(signal.float_value)
    raise ValueError(f"Unknown telemetry value kind: {signal.kind}")


def health_summary(text):
    buses = json.loads(text)["buses"]
    if not isinstance(buses, dict):
        raise ValueError("Invalid acquisition status")
    totals = {key: 0 for key in ("received", "dropped", "publish_errors", "io_errors", "decode_errors")}
    for bus in buses.values():
        for key in totals:
            value = bus.get(key, 0)
            if type(value) is not int or value < 0:
                raise ValueError("Invalid acquisition counter")
            totals[key] += value
    return (f"{totals['received']} frames · {totals['dropped'] + totals['publish_errors']} dropped"
            f" · {totals['io_errors'] + totals['decode_errors']} errors")


class TelemetryReceiver:
    def __init__(self, stale_after=1.0):
        self.store = TelemetryStore(stale_after)
        self.catalog_version = 0
        self._hashes = {}
        self._pending = OrderedDict()

    def manifest(self, text):
        manifest = json.loads(text)
        catalog, buses = manifest["catalog"], manifest["buses"]
        if not isinstance(catalog, list) or not isinstance(buses, dict):
            raise ValueError("Invalid DBC manifest")
        definitions = []
        for item in catalog:
            expected = signal_definition(item["bus"], item["message"], item["signal"])
            if item["id"] != expected["id"] or item["bus"] not in buses:
                raise ValueError("DBC catalog identity does not match its bus")
            definitions.append(dict(item))
        hashes = {bus: info["sha256"] for bus, info in buses.items()}
        if any(not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value)
               for value in hashes.values()):
            raise ValueError("Invalid DBC SHA-256")
        if hashes == self._hashes:
            return
        self.store.replace_catalog(definitions)
        self._hashes = hashes
        self.catalog_version += 1
        for key, (frame, received_at) in list(self._pending.items()):
            if hashes.get(frame.bus) == frame.dbc_sha256:
                del self._pending[key]
                self.frame(frame, received_at=received_at)

    def frame(self, frame, *, received_at=None):
        if not frame.message or not frame.signals:
            return False
        received_at = time.monotonic() if received_at is None else received_at
        # The two DDS topics can arrive in either order after a DBC reload.
        if self._hashes.get(frame.bus) != frame.dbc_sha256:
            key = (frame.bus, frame.message, frame.dbc_sha256,
                   tuple(signal.name for signal in frame.signals))
            self._pending.pop(key, None)
            self._pending[key] = (frame, received_at)
            if len(self._pending) > 512:
                self._pending.popitem(last=False)
            return False
        values = {signal.name: signal_value(signal) for signal in frame.signals}
        if len(values) != len(frame.signals):
            raise ValueError("Duplicate telemetry signal")
        timestamp = frame.header.stamp.sec + frame.header.stamp.nanosec / 1e9
        self.store.update(frame.bus, frame.message, values,
                          timestamp=timestamp, received_at=received_at)
        return True

    def register_dds(self, catalog):
        grouped = {}
        for item in catalog:
            metadata = {key: value for key, value in item.items()
                        if key not in ("id", "bus", "message", "signal")}
            grouped.setdefault(item["message"], {})[item["signal"]] = metadata
        for message, signals in grouped.items():
            self.store.register("dds", message, signals)
        self.catalog_version += 1

    def dds(self, message_name, fields, message, *, received_at=None):
        values = {}
        for signal, field in fields.items():
            value = getattr(message, field)
            if isinstance(value, bool):
                value = int(value)
            if type(value) not in (int, float):
                raise TypeError(f"DDS signal {message_name}/{signal} is not numeric")
            values[signal] = value
        header = getattr(message, "header", None)
        timestamp = None
        if header is not None:
            stamp = header.stamp.sec + header.stamp.nanosec / 1e9
            if isfinite(stamp) and stamp > 0:
                timestamp = stamp
        self.store.update("dds", message_name, values,
                          timestamp=timestamp, received_at=received_at)
