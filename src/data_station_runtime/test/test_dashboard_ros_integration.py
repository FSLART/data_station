"""Exercise the dashboard's real DDS subscriptions without opening a QML window."""

import json
import os
import time

import pytest

rclpy = pytest.importorskip("rclpy")

from PySide6.QtCore import QCoreApplication
from data_station_msgs.msg import CanTelemetry, SignalValue
from lart_msgs.msg import Jetson
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import (DurabilityPolicy, QoSProfile, ReliabilityPolicy,
                      qos_profile_sensor_data)
from std_msgs.msg import Int32, String

from data_station_runtime.app import Dashboard, create_ros_node
from data_station_runtime.receiver import TelemetryReceiver
from data_station_runtime.telemetry import signal_definition


def spin_until(executor, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        executor.spin_once(timeout_sec=0.05)
    assert predicate(), "Timed out waiting for dashboard DDS delivery"


def test_dashboard_receives_typed_and_generic_dds_and_destroys_cleanly(monkeypatch):
    monkeypatch.setenv("ROS_DOMAIN_ID", str(60 + os.getpid() % 30))
    qt = QCoreApplication.instance() or QCoreApplication([])
    receiver = TelemetryReceiver()
    dashboard = Dashboard(receiver)
    executor = node = publisher_node = None
    rclpy.init(args=[])
    try:
        executor = SingleThreadedExecutor()
        publisher_node = Node("dashboard_integration_publisher")
        retained = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                              durability=DurabilityPolicy.TRANSIENT_LOCAL)
        manifest_pub = publisher_node.create_publisher(String, "/telemetry/dbc_manifest", retained)
        digest = "a" * 64
        manifest_pub.publish(String(data=json.dumps({
            "schema_version": 1,
            "catalog": [signal_definition("can0", "Wide_Counter", "Counter")],
            "buses": {"can0": {"sha256": digest}},
        })))
        can_pub = publisher_node.create_publisher(CanTelemetry, "/telemetry/can", 10)
        jetson_pub = publisher_node.create_publisher(Jetson, "/can/jetson", qos_profile_sensor_data)
        screen_pub = publisher_node.create_publisher(Int32, "/dashboard/set_screen", 10)

        node, update_controls = create_ros_node(receiver, dashboard)
        subscriptions = list(node.subscriptions)
        assert len(subscriptions) == len({id(subscription) for subscription in subscriptions})
        executor.add_node(publisher_node)
        executor.add_node(node)
        spin_until(executor, lambda: receiver.catalog_version >= 2
                   and can_pub.get_subscription_count() > 0
                   and jetson_pub.get_subscription_count() > 0
                   and screen_pub.get_subscription_count() > 0)

        frame = CanTelemetry(bus="can0", message="Wide_Counter", can_id=132,
                             dbc_sha256=digest, signals=[SignalValue(
                                 name="Counter", kind=SignalValue.UINT64,
                                 uint_value=(1 << 64) - 1)])
        frame.header.stamp.sec = 42
        jetson = Jetson()
        jetson.as_state = 2
        jetson.temperature = 73
        jetson.header.stamp.sec = 43
        can_pub.publish(frame)
        jetson_pub.publish(jetson)
        screen_pub.publish(Int32(data=1))

        def delivered():
            update_controls()
            samples = {sample["id"]: sample for sample in receiver.store.snapshot()}
            return (samples.get("can0/Wide_Counter/Counter", {}).get("seen", False)
                    and samples.get("dds/JETSON/TEMPERATURE", {}).get("seen", False)
                    and dashboard.screen == 1)

        spin_until(executor, delivered)
        samples = {sample["id"]: sample for sample in receiver.store.snapshot()}
        counter = samples["can0/Wide_Counter/Counter"]
        assert counter["value"] == (1 << 64) - 1
        assert type(counter["value"]) is int
        assert counter["timestamp"] == 42
        assert samples["dds/JETSON/AS_STATE"]["value"] == 2
        assert samples["dds/JETSON/TEMPERATURE"]["value"] == 73
        assert samples["dds/JETSON/TEMPERATURE"]["timestamp"] == 43
        assert dashboard.screen == 1
        qt.processEvents()
    finally:
        if node is not None:
            executor.remove_node(node)
            node.destroy_node()
        if publisher_node is not None:
            executor.remove_node(publisher_node)
            publisher_node.destroy_node()
        if executor is not None:
            executor.shutdown(timeout_sec=2.0)
        rclpy.try_shutdown()
