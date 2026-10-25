"""Runtime decoding requires no ROS interfaces, generated code, or UI imports."""

from pathlib import Path
import hashlib

import cantools
import pytest

from data_station_runtime import DbcRuntime, TelemetryStore


ROOT = Path(__file__).resolve().parents[3]
HEADER = 'VERSION ""\nNS_ :\nBS_:\nBU_: Board\n'


def write_dbc(path, body):
    path.write_text(HEADER + body, encoding="utf-8")
    return path


@pytest.fixture
def actual_runtime():
    return DbcRuntime({bus: ROOT / "dbc_signals" / filename for bus, filename in {
        "data": "data_t26.dbc", "pwt": "powertrain_t26.dbc",
        "autonomous": "autonomous_t26.dbc",
    }.items()})


def by_id(rows):
    return {row["id"]: row for row in rows}


def test_shared_ids_decode_on_the_correct_bus(actual_runtime):
    data = actual_runtime.decode("data", 0x750, bytes.fromhex("68 10 a0 11 4e 0c af 0a"),
                                 timestamp=1234.5, received_at=10.0)
    pwt = actual_runtime.decode("pwt", 0x750, bytes.fromhex("96 fa bd 64 15 f9 bd 9a"),
                                timestamp=1234.6, received_at=10.1)
    assert data["overall_maximum_voltage"] == pytest.approx(4.2)
    assert pwt["front_left_speed"] == pytest.approx(61.5)
    assert pwt["tv_shift"] == -17
    assert actual_runtime.describe_frame("data", 0x750)["message"] == "Master_MSC_ID_3"
    assert actual_runtime.describe_frame("pwt", 0x750)["message"] == "VCU_states"
    samples = by_id(actual_runtime.store.snapshot(now=10.5))
    voltage = samples["data/Master_MSC_ID_3/overall_maximum_voltage"]
    assert voltage == {"id": voltage["id"], "value": 4.2, "timestamp": 1234.5,
                       "age": 0.5, "valid": True, "seen": True}
    assert actual_runtime.decode("unknown", 0x750, b"12345678") is None
    assert actual_runtime.decode("data", 0x750, b"12345678", is_extended_id=True) is None


def test_actual_icd_multiplexing_retains_integer_precision(actual_runtime):
    values = actual_runtime.decode("data", 1281, bytes.fromhex("e4ffffffffffffff"),
                                   timestamp=100.0, received_at=5.0)
    assert values == {"Resp_MuxID": 228, "Resp_ArticleNumber": (1 << 56) - 1}
    assert type(values["Resp_ArticleNumber"]) is int
    samples = by_id(actual_runtime.store.snapshot(now=5.1))
    assert samples["data/ICD_Response/Resp_ArticleNumber"]["value"] == (1 << 56) - 1
    assert samples["data/ICD_Response/Resp_AhCounter"]["seen"] is False
    values = actual_runtime.decode("data", 1281, bytes.fromhex("92ffffffff000000"),
                                   timestamp=101.0, received_at=5.2)
    assert values == {"Resp_MuxID": 146, "Resp_AhCounter": -1}
    assert "Resp_ArticleNumber" not in values
    metadata = by_id(actual_runtime.store.catalog())["data/ICD_Response/Resp_ArticleNumber"]
    assert metadata["bit_length"] == 56
    assert metadata["multiplexer_signal"] == "Resp_MuxID"
    assert metadata["multiplexer_ids"] == [228]


def test_uint64_and_standard_extended_identity(tmp_path):
    dbc = write_dbc(tmp_path / "bus.dbc", '''
BO_ 256 Standard: 8 Board
 SG_ Counter : 0|64@1+ (1,0) [0|18446744073709551615] "count" Board
BO_ 2147483904 Extended: 1 Board
 SG_ State : 0|8@1+ (1,0) [0|255] "" Board
VAL_ 2147483904 State 0 "off" 1 "on";
''')
    runtime = DbcRuntime({"can0": dbc})
    values = runtime.decode("can0", 256, b"\xff" * 8, received_at=1.0)
    assert values["Counter"] == (1 << 64) - 1
    assert type(values["Counter"]) is int
    assert runtime.decode("can0", 256, b"\x01", is_extended_id=True) == {"State": 1}
    metadata = by_id(runtime.store.catalog())
    assert metadata["can0/Standard/Counter"]["unit"] == "count"
    assert metadata["can0/Extended/State"]["choices"] == {0: "off", 1: "on"}
    assert metadata["can0/Extended/State"]["is_extended_id"] is True
    snapshot = by_id(runtime.store.snapshot(now=1.1))
    assert snapshot["can0/Standard/Counter"]["value"] == (1 << 64) - 1


def test_freshness_uses_monotonic_receive_time_and_unseen_is_invalid():
    store = TelemetryStore(stale_after=0.5)
    store.register("ros", "Status", {"speed": {"unit": "km/h"}, "state": {}})
    assert all(not row["valid"] and not row["seen"] for row in store.snapshot(now=10.0))
    store.update("ros", "Status", {"speed": 12}, timestamp=9_999_999_999, received_at=10.0)
    row = by_id(store.snapshot(now=10.5))["ros/Status/speed"]
    assert row["valid"] is True
    assert row["timestamp"] == 9_999_999_999
    assert row["value"] == 12
    assert by_id(store.snapshot(now=10.50001))["ros/Status/speed"]["valid"] is False
    assert by_id(store.snapshot(now=9.0))["ros/Status/speed"]["valid"] is False


def test_invalid_reload_preserves_all_buses_catalog_and_samples(tmp_path):
    left = write_dbc(tmp_path / "left.dbc", '''
BO_ 256 Sample: 1 Board
 SG_ Old : 0|8@1+ (1,0) [0|255] "V" Board
''')
    right = write_dbc(tmp_path / "right.dbc", '''
BO_ 257 Other: 1 Board
 SG_ Value : 0|8@1+ (1,0) [0|255] "A" Board
''')
    runtime = DbcRuntime({"left": left, "right": right})
    runtime.decode("left", 256, b"\x07", timestamp=100.0, received_at=10.0)
    catalog = runtime.store.catalog()
    samples = runtime.store.snapshot(now=10.1)
    manifest = runtime.manifest()
    write_dbc(left, '''
BO_ 256 Sample: 1 Board
 SG_ New : 0|8@1+ (1,0) [0|255] "V" Board
''')
    right.write_text("not a DBC", encoding="utf-8")
    with pytest.raises(cantools.database.errors.UnsupportedDatabaseFormatError):
        runtime.reload()
    assert runtime.store.catalog() == catalog
    assert runtime.store.snapshot(now=10.1) == samples
    assert runtime.manifest() == manifest
    assert runtime.decode("left", 256, b"\x09") == {"Old": 9}
    assert runtime.decode("right", 257, b"\x06") == {"Value": 6}


def test_reload_adds_and_removes_fields_without_codegen_and_preserves_dds(tmp_path):
    path = write_dbc(tmp_path / "bus.dbc", '''
BO_ 256 Sample: 1 Board
 SG_ Old : 0|8@1+ (1,0) [0|255] "V" Board
''')
    runtime = DbcRuntime({"can0": path})
    runtime.store.register("ros", "Jetson", {"mission": {}})
    runtime.store.update("ros", "Jetson", {"mission": 4}, timestamp=100.0, received_at=10.0)
    runtime.decode("can0", 256, b"\x07", received_at=10.0)
    write_dbc(path, '''
BO_ 256 Sample: 1 Board
 SG_ New : 0|4@1+ (0.5,0) [0|7.5] "A" Board
 SG_ State : 4|4@1+ (1,0) [0|15] "" Board
''')
    runtime.reload()
    metadata = by_id(runtime.store.catalog())
    assert set(metadata) == {"can0/Sample/New", "can0/Sample/State", "ros/Jetson/mission"}
    samples = by_id(runtime.store.snapshot(now=10.1))
    assert samples["can0/Sample/New"]["seen"] is False
    assert samples["ros/Jetson/mission"]["value"] == 4
    assert samples["ros/Jetson/mission"]["valid"] is True
    assert runtime.decode("can0", 256, b"\x37") == {"New": 3.5, "State": 3}


@pytest.mark.parametrize("body", [
    '''BO_ 256 First: 1 Board
 SG_ A : 0|8@1+ (1,0) [0|255] "" Board
BO_ 256 Second: 1 Board
 SG_ B : 0|8@1+ (1,0) [0|255] "" Board
''',
    '''BO_ 256 Same: 1 Board
 SG_ A : 0|8@1+ (1,0) [0|255] "" Board
BO_ 257 Same: 1 Board
 SG_ B : 0|8@1+ (1,0) [0|255] "" Board
''',
    '''BO_ 256 Overlap: 1 Board
 SG_ A : 0|8@1+ (1,0) [0|255] "" Board
 SG_ B : 0|8@1+ (1,0) [0|255] "" Board
''',
])
def test_startup_rejects_ambiguous_or_invalid_database(tmp_path, body):
    path = write_dbc(tmp_path / "bad.dbc", body)
    with pytest.raises((ValueError, cantools.database.errors.UnsupportedDatabaseFormatError)):
        DbcRuntime({"can0": path})


def test_bad_payload_does_not_update_previous_values(actual_runtime):
    actual_runtime.decode("data", 0x750, bytes.fromhex("68 10 a0 11 4e 0c af 0a"),
                           timestamp=10.0, received_at=20.0)
    before = actual_runtime.store.snapshot(now=20.1)
    for payload in (b"\x00", b"\x00" * 9):
        with pytest.raises(cantools.database.errors.DecodeError):
            actual_runtime.decode("data", 0x750, payload, received_at=20.1)
        assert actual_runtime.store.snapshot(now=20.1) == before


def test_catalog_and_frame_description_cannot_mutate_active_metadata(actual_runtime):
    frame = actual_runtime.describe_frame("data", 1281)
    frame["signals"].clear()
    catalog = actual_runtime.store.catalog()
    catalog[0]["unit"] = "wrong"
    assert actual_runtime.describe_frame("data", 1281)["signals"]
    assert actual_runtime.store.catalog()[0]["unit"] != "wrong"


def test_manifest_matches_the_exact_validated_bytes(tmp_path):
    path = tmp_path / "legacy.dbc"
    content = (HEADER + '''BO_ 256 Sample: 1 Board
 SG_ Value : 0|8@1+ (1,0) [0|255] "°C" Board
''').replace("\n", "\r\n").encode("cp1252")
    path.write_bytes(content)
    runtime = DbcRuntime({"can0": path})
    manifest = runtime.manifest()
    source = manifest["can0"]
    assert source["path"] == str(path.resolve())
    assert source["sha256"] == hashlib.sha256(content).hexdigest()
    assert source["content"].encode(source["encoding"]) == content
    source["content"] = "changed"
    assert runtime.manifest()["can0"]["content"] != "changed"


def test_external_update_validates_before_mutating_and_handles_nonfinite_values():
    store = TelemetryStore()
    store.register("ros", "Status", {"speed": {}, "voltage": {}})
    store.update("ros", "Status", {"speed": 7}, timestamp=100.0, received_at=10.0)
    before = store.snapshot(now=10.1)
    with pytest.raises(KeyError):
        store.update("ros", "Status", {"speed": 8, "unknown": 9})
    with pytest.raises(TypeError):
        store.update("ros", "Status", {"speed": "9"})
    with pytest.raises(ValueError):
        store.update("ros", "Status", {"speed": 9}, received_at=float("nan"))
    assert store.snapshot(now=10.1) == before
    store.update("ros", "Status", {"voltage": float("inf")}, received_at=10.0)
    row = by_id(store.snapshot(now=10.1))["ros/Status/voltage"]
    assert row["value"] is None
    assert row["seen"] is True
    assert row["valid"] is False
