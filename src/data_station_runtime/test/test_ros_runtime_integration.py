"""Exercise generated ROS interfaces, DDS publication and live DBC reload.

The virtual CAN backend needs no SocketCAN device or elevated privileges.
These tests run after colcon builds the interfaces; hosts without ROS skip them.
"""

import json
import os
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch
import uuid

import pytest

rclpy = pytest.importorskip("rclpy")
import can
import yaml

from data_station_msgs.msg import CanTelemetry, SignalValue
from lart_msgs.msg import StartPrecharge

from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.serialization import deserialize_message, serialize_message
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger

from data_station_runtime.can_node import CanRuntimeNode
from data_station_runtime.recorder import TelemetryRecorderNode
from data_station_runtime.recording_trigger import RecordingTriggers
from lart_bringup.bag_recorder import BagRecorderNode
from lart_bringup.trigger_state import State, TriggerStateMachine


HEADER = 'VERSION ""\nNS_ :\nBS_:\nBU_: VCU\n'
INITIAL_DBC = HEADER + '''
BO_ 131 Start_PreCharge: 2 VCU
 SG_ Precharge_Request : 0|1@1+ (1,0) [0|1] "" VCU

BO_ 132 Wide_Counter: 8 VCU
 SG_ Counter : 0|64@1+ (1,0) [0|18446744073709551615] "" VCU
'''
UPDATED_DBC = INITIAL_DBC.replace(
    ' SG_ Precharge_Request : 0|1@1+ (1,0) [0|1] "" VCU',
    ' SG_ Precharge_Request : 0|1@1+ (1,0) [0|1] "" VCU\n'
    ' SG_ New_Value : 8|8@1+ (1,0) [0|255] "" VCU',
)


def spin_until(executor, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        executor.spin_once(timeout_sec=0.05)
    assert predicate(), "Timed out waiting for ROS integration result"


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ROS_DOMAIN_ID", str(60 + os.getpid() % 30))
    dbc = tmp_path / "runtime.dbc"
    dbc.write_text(INITIAL_DBC, encoding="utf-8")
    params = tmp_path / "params.yaml"
    bag_dir = tmp_path / "bags"
    params.write_text(yaml.safe_dump({
        "can_runtime": {"ros__parameters": {
            "can_interfaces": ["can1"],
            "dbc_paths": [str(dbc)],
            "legacy_prefixes": ["/integration"],
            "publish_legacy": True,
        }},
        "bag_recorder": {"ros__parameters": {"bag_dir": str(bag_dir)}},
    }), encoding="utf-8")
    virtual_channel = "data-station-test-" + uuid.uuid4().hex
    real_bus = can.Bus

    def virtual_bus(*, channel: str, interface: str, **kwargs):
        assert channel == "can1"
        assert interface == "socketcan"
        return real_bus(interface="virtual", channel=virtual_channel, receive_own_messages=False)

    sender = real_bus(interface="virtual", channel=virtual_channel, receive_own_messages=False)
    monkeypatch.setattr(can, "Bus", virtual_bus)
    executor = node = observer = None
    try:
        rclpy.init(args=["--ros-args", "--params-file", str(params)])
        executor = SingleThreadedExecutor()
        node = CanRuntimeNode()
        observer = Node("runtime_integration_observer")
        frames, legacy = [], []
        observer.create_subscription(CanTelemetry, "/telemetry/can", frames.append, 10)
        observer.create_subscription(StartPrecharge, "/integration/start_precharge", legacy.append, 10)
        client = observer.create_client(Trigger, "/can_runtime/reload_dbc")
        executor.add_node(node)
        executor.add_node(observer)
        spin_until(executor, lambda: node._publisher.get_subscription_count() > 0
                   and any(item[1].get_subscription_count() > 0 for item in node._legacy.values()))
        yield SimpleNamespace(node=node, observer=observer, sender=sender, executor=executor,
                              frames=frames, legacy=legacy, client=client, dbc=dbc, bag_dir=bag_dir)
    finally:
        if observer is not None:
            executor.remove_node(observer)
            observer.destroy_node()
        if node is not None:
            executor.remove_node(node)
            node.destroy_node()
        if executor is not None:
            executor.shutdown(timeout_sec=2.0)
        sender.shutdown()
        rclpy.try_shutdown()


def send_until(runtime, message, predicate):
    """Repeat bounded sends while DDS discovers publishers recreated by reload."""
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        runtime.sender.send(message)
        for _ in range(5):
            runtime.executor.spin_once(timeout_sec=0.02)
            if predicate():
                return
    assert predicate(), "Virtual CAN frame did not reach the ROS subscriber"


def reload_dbc(runtime):
    assert runtime.client.wait_for_service(timeout_sec=3.0)
    future = runtime.client.call_async(Trigger.Request())
    spin_until(runtime.executor, future.done)
    return future.result()


def values(frame):
    return {signal.name: signal for signal in frame.signals}


def test_generated_interfaces_roundtrip_preserves_full_integer_range():
    message = CanTelemetry(bus="can1", can_id=0x123, signals=[
        SignalValue(name="minimum", kind=SignalValue.INT64, int_value=-(1 << 63)),
        SignalValue(name="maximum", kind=SignalValue.UINT64, uint_value=(1 << 64) - 1),
        SignalValue(name="scaled", kind=SignalValue.FLOAT64, float_value=-123.456),
    ])
    restored = deserialize_message(serialize_message(message), CanTelemetry)
    assert restored.signals[0].int_value == -(1 << 63)
    assert restored.signals[1].uint_value == (1 << 64) - 1
    assert restored.signals[2].float_value == -123.456


def test_virtual_can_publishes_generic_and_existing_typed_topics(runtime):
    send_until(runtime, can.Message(arbitration_id=131, is_extended_id=False, data=[1, 42]),
               lambda: bool(runtime.frames and runtime.legacy))
    received = next(frame for frame in runtime.frames if frame.can_id == 131)
    assert received.bus == "can1"
    assert received.message == "Start_PreCharge"
    assert bytes(received.data) == b"\x01\x2a"
    assert values(received)["Precharge_Request"].uint_value == 1
    assert runtime.legacy[-1].precharge_request == 1

    send_until(runtime, can.Message(arbitration_id=132, is_extended_id=False, data=[255] * 8),
               lambda: any(frame.can_id == 132 for frame in runtime.frames))
    counter = next(frame for frame in runtime.frames if frame.can_id == 132)
    assert values(counter)["Counter"].kind == SignalValue.UINT64
    assert values(counter)["Counter"].uint_value == (1 << 64) - 1

    send_until(runtime, can.Message(arbitration_id=0x7FF, is_extended_id=False, data=[21]),
               lambda: any(frame.can_id == 0x7FF for frame in runtime.frames))
    unknown = next(frame for frame in runtime.frames if frame.can_id == 0x7FF)
    assert unknown.message == ""
    assert not unknown.signals
    assert bytes(unknown.data) == b"\x15"


def test_reload_adds_generic_signal_without_changing_legacy_interface(runtime):
    original_fields = dict(StartPrecharge.get_fields_and_field_types())
    runtime.dbc.write_text(UPDATED_DBC, encoding="utf-8")
    response = reload_dbc(runtime)
    assert response.success, response.message
    send_until(runtime, can.Message(arbitration_id=131, is_extended_id=False, data=[1, 42]),
               lambda: any("New_Value" in values(frame) for frame in runtime.frames)
               and bool(runtime.legacy))
    received = next(frame for frame in runtime.frames if "New_Value" in values(frame))
    assert values(received)["New_Value"].uint_value == 42
    assert runtime.legacy[-1].precharge_request == 1
    assert StartPrecharge.get_fields_and_field_types() == original_fields
    active_hash = received.dbc_sha256

    runtime.dbc.write_text("invalid DBC", encoding="utf-8")
    response = reload_dbc(runtime)
    assert not response.success
    runtime.frames.clear()
    send_until(runtime, can.Message(arbitration_id=131, is_extended_id=False, data=[1, 99]),
               lambda: any("New_Value" in values(frame)
                           and values(frame)["New_Value"].uint_value == 99 for frame in runtime.frames))
    received = next(frame for frame in runtime.frames if values(frame).get("New_Value")
                    and values(frame)["New_Value"].uint_value == 99)
    assert received.dbc_sha256 == active_hash


def test_late_subscribers_receive_current_trigger_and_dbc_manifest(runtime):
    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                     durability=DurabilityPolicy.TRANSIENT_LOCAL)
    initial = []
    runtime.observer.create_subscription(Bool, "/telemetry/precharge", initial.append, qos)
    spin_until(runtime.executor, lambda: runtime.node._precharge_pub.get_subscription_count() > 0)
    for _ in range(3):
        runtime.executor.spin_once(timeout_sec=0.05)
    assert not initial, "No precharge state may be assumed before a valid CAN sample"
    send_until(runtime, can.Message(arbitration_id=131, is_extended_id=False, data=[1, 0]),
               lambda: bool(initial and initial[-1].data))

    late_trigger, late_manifest = [], []
    runtime.observer.create_subscription(Bool, "/telemetry/precharge", late_trigger.append, qos)
    runtime.observer.create_subscription(String, "/telemetry/dbc_manifest", late_manifest.append, qos)
    spin_until(runtime.executor, lambda: bool(late_trigger and late_manifest))
    assert late_trigger[-1].data is True
    manifest = json.loads(late_manifest[-1].data)
    assert manifest["schema_version"] == 1
    assert manifest["buses"]["can1"]["content"] == INITIAL_DBC
    assert any(item["id"] == "can1/Start_PreCharge/Precharge_Request"
               for item in manifest["catalog"])

    send_until(runtime, can.Message(arbitration_id=131, is_extended_id=False, data=[0, 0]),
               lambda: not late_trigger[-1].data)


def recorder_retry_state():
    # This callback only needs Python state; it never accesses an uninitialized ROS handle.
    recorder = object.__new__(TelemetryRecorderNode)
    callbacks = Mock()
    callbacks.start.return_value = True
    recorder._sm = TriggerStateMachine(callbacks.start, callbacks.stop, callbacks.arm, callbacks.cancel)
    recorder._triggers = RecordingTriggers(recorder._sm.on_trigger)
    return recorder, callbacks


def test_retained_request_retries_failed_recorder_start_without_another_sample():
    recorder, callbacks = recorder_retry_state()
    callbacks.start.side_effect = [False, True]
    recorder._triggers.on_precharge(True)
    assert recorder._sm.state is State.IDLE
    with patch.object(BagRecorderNode, "_check_recorder_alive") as check:
        recorder._check_recorder_alive()
    check.assert_called_once()
    assert recorder._sm.state is State.RECORDING
    assert callbacks.start.call_count == 2
    callbacks.stop.assert_not_called()
    callbacks.arm.assert_not_called()


def test_retained_request_restarts_dead_recorder_without_another_sample():
    recorder, callbacks = recorder_retry_state()
    recorder._triggers.on_precharge(True)
    with patch.object(BagRecorderNode, "_check_recorder_alive",
                      side_effect=recorder._sm.on_recorder_died):
        recorder._check_recorder_alive()
    assert recorder._sm.state is State.RECORDING
    assert callbacks.start.call_count == 2
    callbacks.stop.assert_not_called()
    callbacks.arm.assert_not_called()


def test_periodic_inactive_request_does_not_extend_stop_grace():
    recorder, callbacks = recorder_retry_state()
    with patch.object(BagRecorderNode, "_check_recorder_alive"):
        recorder._check_recorder_alive()
        callbacks.start.assert_not_called()
        recorder._triggers.on_precharge(True)
        recorder._triggers.on_precharge(False)
        recorder._check_recorder_alive()
        recorder._check_recorder_alive()
    assert recorder._sm.state is State.GRACE
    callbacks.arm.assert_called_once()
    callbacks.stop.assert_not_called()


def test_runtime_recorder_finalizes_readable_mcap_with_manifest_and_exact_counter(runtime):
    import rosbag2_py
    from rclpy.duration import Duration

    recorder = TelemetryRecorderNode()
    runtime.executor.add_node(recorder)
    process = None
    try:
        assert recorder._proc is None
        assert not list(runtime.bag_dir.glob("*/*.mcap"))
        send_until(runtime, can.Message(arbitration_id=131, is_extended_id=False, data=[1, 0]),
                   lambda: recorder._proc is not None)
        process = recorder._proc

        def recorder_subscribed():
            assert process.poll() is None, "ros2 bag record exited before topic discovery"
            return (runtime.node._publisher.get_subscription_count() >= 2
                    and runtime.node._manifest_pub.get_subscription_count() >= 1)

        spin_until(runtime.executor, recorder_subscribed, timeout=10.0)
        counter = can.Message(arbitration_id=132, is_extended_id=False, data=[255] * 8)
        send_until(runtime, counter, lambda: any(frame.can_id == 132 for frame in runtime.frames))
        # Repeated live samples allow the recorder process to consume its DDS callbacks before SIGINT.
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            runtime.sender.send(counter)
            runtime.executor.spin_once(timeout_sec=0.02)
        assert runtime.node._publisher.wait_for_all_acked(Duration(seconds=5.0))
    finally:
        runtime.executor.remove_node(recorder)
        recorder.destroy_node()

    assert process is not None and process.returncode == 0
    sessions = list(runtime.bag_dir.glob("*/metadata.yaml"))
    assert len(sessions) == 1
    session = sessions[0].parent
    assert len(list(session.glob("*.mcap"))) == 1
    info = yaml.safe_load(sessions[0].read_text(encoding="utf-8"))["rosbag2_bagfile_information"]
    assert info["storage_identifier"] == "mcap"
    assert len(info["relative_file_paths"]) == 1

    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(session), storage_id="mcap"),
                rosbag2_py.ConverterOptions(input_serialization_format="cdr",
                                            output_serialization_format="cdr"))
    reader.set_filter(rosbag2_py.StorageFilter(topics=["/telemetry/can", "/telemetry/dbc_manifest"]))
    manifests, counters = [], []
    while reader.has_next():
        topic, data, _ = reader.read_next()
        if topic == "/telemetry/dbc_manifest":
            manifests.append(json.loads(deserialize_message(data, String).data))
        elif topic == "/telemetry/can":
            frame = deserialize_message(data, CanTelemetry)
            if frame.can_id == 132:
                counters.append(values(frame)["Counter"].uint_value)
    del reader
    assert manifests and manifests[0]["buses"]["can1"]["content"] == INITIAL_DBC
    assert counters and all(value == (1 << 64) - 1 for value in counters)
