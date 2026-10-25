import json
from types import SimpleNamespace as NS

import pytest

from data_station_runtime.receiver import (TelemetryReceiver, health_summary, ros_name,
                                           ros_type_name, signal_value)
from data_station_runtime.telemetry import signal_definition


def manifest(signal="Value", digest="a" * 64):
    return json.dumps({"catalog": [signal_definition("can0", "Example", signal)],
                       "buses": {"can0": {"sha256": digest}}})


def frame(value, *, digest="a" * 64, kind=1):
    return NS(bus="can0", message="Example", dbc_sha256=digest,
              header=NS(stamp=NS(sec=100, nanosec=123)),
              signals=[NS(name="Value", kind=kind, uint_value=value,
                          int_value=value, float_value=float(value))])


def test_uint64_reaches_store_exactly_and_requires_matching_schema():
    receiver = TelemetryReceiver()
    msg = frame(2**64 - 1)
    assert not receiver.frame(msg)
    receiver.manifest(manifest())
    assert receiver.frame(msg, received_at=10)
    sample = receiver.store.snapshot(now=10)[0]
    assert sample["value"] == 2**64 - 1
    assert type(sample["value"]) is int
    assert sample["valid"]
    receiver.manifest(manifest("NewSignal", "b" * 64))
    assert not receiver.frame(msg, received_at=11)
    assert not receiver.store.snapshot(now=11)[0]["seen"]


def test_manifest_validation_does_not_replace_active_catalog():
    receiver = TelemetryReceiver()
    receiver.manifest(manifest())
    before = receiver.store.catalog()
    invalid = json.loads(manifest())
    invalid["catalog"][0]["id"] = "can1/Example/Value"
    with pytest.raises(ValueError):
        receiver.manifest(json.dumps(invalid))
    assert receiver.store.catalog() == before
    assert receiver.catalog_version == 1


def test_dds_registration_and_header_survive_can_reload():
    receiver = TelemetryReceiver()
    receiver.register_dds([signal_definition("dds", "JETSON", "AS_STATE")])
    receiver.dds("JETSON", {"AS_STATE": "as_state"},
                 NS(as_state=3, header=NS(stamp=NS(sec=42, nanosec=0))), received_at=10)
    receiver.manifest(manifest())
    sample = next(row for row in receiver.store.snapshot(now=10) if row["id"].startswith("dds/"))
    assert sample["value"] == 3
    assert sample["timestamp"] == 42
    assert sample["valid"]


def test_unknown_kind_and_duplicate_values_are_rejected():
    with pytest.raises(ValueError):
        signal_value(NS(kind=99))
    receiver = TelemetryReceiver()
    receiver.manifest(manifest())
    msg = frame(1)
    msg.signals *= 2
    with pytest.raises(ValueError):
        receiver.frame(msg)


def test_ros_names_match_existing_frozen_interfaces():
    assert ros_name("Start_PreCharge") == "start_precharge"
    assert ros_type_name("Start_PreCharge") == "StartPrecharge"
    assert ros_name("1Hz-Result") == "val_1hz_result"
    assert ros_type_name("SLAM_STATS_CAN") == "SlamStatsCan"


def test_frame_before_manifest_replays_with_original_freshness():
    receiver = TelemetryReceiver()
    assert not receiver.frame(frame(2**64 - 1), received_at=10)
    receiver.manifest(manifest())
    sample = receiver.store.snapshot(now=12)[0]
    assert sample["value"] == 2**64 - 1
    assert sample["age"] == 2
    assert not sample["valid"]
    receiver.manifest(manifest())
    assert receiver.store.snapshot(now=12)[0]["seen"]


def test_pending_unknown_schemas_are_bounded():
    receiver = TelemetryReceiver()
    for index in range(600):
        receiver.frame(frame(1, digest=f"{index:064x}"), received_at=10)
    assert len(receiver._pending) == 512


def test_health_summary_validates_counters():
    assert health_summary(json.dumps({"buses": {"can0": {
        "received": 12, "dropped": 1, "publish_errors": 2, "decode_errors": 3
    }}})) == "12 frames · 3 dropped · 3 errors"
    with pytest.raises(ValueError):
        health_summary('{"buses":{"can0":{"received":-1}}}')
