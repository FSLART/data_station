"""Exercise transport precision, raw capture, and reload boundaries without ROS."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import can
import pytest

from data_station_runtime.can_node import (
    CanRuntimeNode, FrameInbox, encode_signal, legacy_value, ros_name,
)
from data_station_runtime.dbc import DbcRuntime


ROOT = Path(__file__).resolve().parents[3]


class SignalValue:
    INT64, UINT64, FLOAT64 = 0, 1, 2

    def __init__(self):
        self.name, self.unit = "", ""
        self.kind, self.int_value, self.uint_value, self.float_value = 0, 0, 0, 0.0


class Publisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(deepcopy(message))


class Logger:
    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


def frame_type():
    return SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=0, nanosec=0)), signals=[])


def node_without_ros():
    node = object.__new__(CanRuntimeNode)
    node._runtime = DbcRuntime({"can0": ROOT / "dbc_signals" / "data_t26.dbc"})
    node._manifest = node._runtime.manifest()
    node._descriptions, node._legacy = {}, {}
    node._frame_type, node._signal_type = frame_type, SignalValue
    node._publisher = Publisher()
    node._precharge_key = ("can1", "Start_PreCharge", "Precharge_Request")
    node._precharge_pub = Publisher()
    node._bool_type = lambda: SimpleNamespace(data=False)
    node._counts = {"can0": dict(published=0, decode_errors=0, unknown_frames=0,
                                legacy_errors=0, publish_errors=0)}
    node.get_logger = lambda: Logger()
    return node


def received(message):
    queue = FrameInbox(["can0"])
    queue.capture("can0", message)
    return queue.pop()


@pytest.mark.parametrize("value,kind,field", [
    (-(1 << 63), SignalValue.INT64, "int_value"),
    (-1, SignalValue.INT64, "int_value"),
    (0, SignalValue.UINT64, "uint_value"),
    ((1 << 56) - 1, SignalValue.UINT64, "uint_value"),
    ((1 << 64) - 1, SignalValue.UINT64, "uint_value"),
    (-123.456, SignalValue.FLOAT64, "float_value"),
])
def test_generic_transport_preserves_numeric_kind_and_all_bits(value, kind, field):
    signal = encode_signal("counter", value, {"unit": "count"}, SignalValue)
    assert (signal.name, signal.unit, signal.kind) == ("counter", "count", kind)
    assert getattr(signal, field) == value
    assert type(getattr(signal, field)) is type(value)


@pytest.mark.parametrize("value,error", [
    (-(1 << 63) - 1, OverflowError), ((1 << 64), OverflowError),
    (True, TypeError), ("7", TypeError),
])
def test_unrepresentable_signal_is_rejected(value, error):
    with pytest.raises(error):
        encode_signal("bad", value, {}, SignalValue)


def test_fixed_ros_schema_matches_encoded_fields_and_captures_raw_flags():
    signal = (ROOT / "src/data_station_msgs/msg/SignalValue.msg").read_text()
    frame = (ROOT / "src/data_station_msgs/msg/CanTelemetry.msg").read_text()
    for line in ("uint8 INT64=0", "uint8 UINT64=1", "uint8 FLOAT64=2",
                 "int64 int_value", "uint64 uint_value", "float64 float_value"):
        assert line in signal.splitlines()
    for line in ("bool is_remote", "bool is_error", "bool is_fd", "uint8 dlc",
                 "bool bitrate_switch", "bool error_state_indicator", "string dbc_sha256"):
        assert line in frame.splitlines()


def test_legacy_adapter_uses_installed_field_types_and_rejects_lossy_integer_changes():
    assert legacy_value((1 << 64) - 1, "uint64") == (1 << 64) - 1
    assert type(legacy_value(7, "float32")) is float
    assert type(legacy_value(-2, "int8")) is int
    assert legacy_value(1, "boolean") is True
    for value, kind in [(256, "uint8"), (-1, "uint8"), (1.25, "int32"), (float("nan"), "int32")]:
        with pytest.raises((ValueError, OverflowError)):
            legacy_value(value, kind)
    assert ros_name("3A Temperature") == "val_3a_temperature"


def test_inbox_copies_frames_and_reports_drops_without_blocking_publisher():
    queue = FrameInbox(["left", "right"], capacity=2)
    message = can.Message(arbitration_id=0x123, data=[1, 2], is_extended_id=False)
    queue.capture("left", message)
    message.data[0] = 99
    queue.capture("right", message)
    queue.capture("left", message)
    status = queue.status()
    assert status["buses"]["left"]["received"] == 2
    assert status["buses"]["left"]["dropped"] == 1
    assert status["buses"]["left"]["queue_depth"] == 1
    assert queue.pop().data == b"\x01\x02"
    assert queue.pop().bus == "right"
    assert queue.pop() is None
    queue.error("right", RuntimeError("socket closed"))
    assert queue.status()["buses"]["right"]["last_error"] == "socket closed"


def test_reload_queue_boundary_discards_old_bytes_and_preserves_new_receipts():
    queue = FrameInbox(["can0"])
    message = can.Message(arbitration_id=0x123, data=[1], is_extended_id=False)
    queue.capture("can0", message)
    activated = []
    queue.switch(lambda: activated.append("new schema"))
    assert activated == ["new schema"]
    assert queue.pop() is None
    assert queue.status()["reload_discarded"] == 1
    queue.capture("can0", message)
    assert queue.pop().data == b"\x01"


def test_actual_icd_value_reaches_generic_topic_without_float_conversion():
    node = node_without_ros()
    frame = received(can.Message(arbitration_id=0x501, data=bytes.fromhex("e4ffffffffffffff"),
                                 timestamp=1234.25, is_extended_id=False))
    node._publish_frame(frame)
    out = node._publisher.messages[-1]
    signals = {signal.name: signal for signal in out.signals}
    assert out.message == "ICD_Response"
    assert signals["Resp_ArticleNumber"].uint_value == (1 << 56) - 1
    assert out.header.stamp.sec == 1234
    assert out.header.stamp.nanosec == 250_000_000
    assert out.dbc_sha256 == node._manifest["can0"]["sha256"]
    assert node._counts["can0"]["published"] == 1


@pytest.mark.parametrize("options", [
    {"arbitration_id": 0x1FFFFFFF, "is_extended_id": True, "is_fd": True,
     "bitrate_switch": True, "error_state_indicator": True, "data": bytes(range(16))},
    {"arbitration_id": 0x501, "is_extended_id": False, "is_remote_frame": True, "dlc": 8},
    {"arbitration_id": 0x501, "is_extended_id": False, "is_error_frame": True, "data": b"12345678"},
])
def test_unknown_remote_and_error_frames_keep_raw_bytes_and_flags(options):
    node = node_without_ros()
    frame = received(can.Message(timestamp=1234.0, **options))
    node._publish_frame(frame)
    out = node._publisher.messages[-1]
    assert out.data == list(frame.data)
    assert out.dlc == frame.dlc
    assert out.is_remote == frame.is_remote_frame
    assert out.is_error == frame.is_error_frame
    assert out.is_extended == frame.is_extended_id
    assert out.is_fd == frame.is_fd
    assert out.bitrate_switch == frame.bitrate_switch
    assert out.error_state_indicator == frame.error_state_indicator
    assert out.signals == []
    assert out.dbc_sha256 == node._manifest["can0"]["sha256"]
    assert node._counts["can0"]["decode_errors"] == 0


def test_malformed_known_frame_still_records_raw_and_increments_error_count():
    node = node_without_ros()
    frame = received(can.Message(arbitration_id=0x501, data=b"\x00", timestamp=1234.0,
                                 is_extended_id=False))
    node._publish_frame(frame)
    assert node._publisher.messages[-1].data == [0]
    assert node._publisher.messages[-1].signals == []
    assert node._counts["can0"]["decode_errors"] == 1
    assert node._counts["can0"]["published"] == 1


def test_precharge_compact_topic_repeats_valid_samples_and_never_assumes_false():
    node = node_without_ros()
    assert not node._precharge_pub.messages
    for ignored in ({}, {"Other": 0}, {"Precharge_Request": float("nan")},
                    {"Precharge_Request": float("inf")}):
        node._publish_precharge("can1", "Start_PreCharge", ignored)
    node._publish_precharge("can0", "Start_PreCharge", {"Precharge_Request": 0})
    node._publish_precharge("can1", "Other", {"Precharge_Request": 0})
    assert not node._precharge_pub.messages
    for value in (1, 1, 0.5, 0):
        node._publish_precharge("can1", "Start_PreCharge", {"Precharge_Request": value})
    assert [message.data for message in node._precharge_pub.messages] == [True, True, True, False]


def test_decoded_precharge_sample_uses_compact_topic_and_keeps_generic_raw(tmp_path):
    dbc = tmp_path / "runtime.dbc"
    dbc.write_text('''VERSION ""
NS_ :
BS_:
BU_: VCU
BO_ 131 Start_PreCharge: 1 VCU
 SG_ Precharge_Request : 0|1@1+ (1,0) [0|1] "" VCU
''', encoding="utf-8")
    node = node_without_ros()
    node._runtime = DbcRuntime({"can1": dbc})
    node._manifest = node._runtime.manifest()
    node._counts["can1"] = dict(node._counts["can0"])
    queue = FrameInbox(["can1"])
    queue.capture("can1", can.Message(arbitration_id=131, data=[1], timestamp=1234.0,
                                     is_extended_id=False))
    node._publish_frame(queue.pop())
    assert node._precharge_pub.messages[-1].data is True
    assert node._publisher.messages[-1].data == [1]
    assert node._publisher.messages[-1].signals[0].uint_value == 1
