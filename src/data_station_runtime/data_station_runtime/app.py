"""Qt dashboard; CAN acquisition and recording run in independent processes."""

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow  # Register the concrete grabWindow() wrapper.

from .dbc import DbcRuntime
from .presentation import DashboardModel
from .receiver import TelemetryReceiver, health_summary, ros_name, ros_type_name
from .telemetry import TelemetryStore


class Dashboard(QObject):
    stateChanged = Signal()
    screenChanged = Signal()
    healthChanged = Signal()

    def __init__(self, receiver):
        super().__init__()
        self.receiver = receiver
        self.model = DashboardModel()
        self._version = -1
        self._screen = 0
        self._health = "Waiting for telemetry"
        self._last_status = None

    @Property("QVariantMap", notify=stateChanged)
    def state(self):
        return self.model.state

    @Property(int, notify=screenChanged)
    def screen(self):
        return self._screen

    @Property(str, notify=healthChanged)
    def health(self):
        return self._health

    @Slot(int)
    def selectScreen(self, index):
        index %= 3
        if index != self._screen:
            self._screen = index
            self.screenChanged.emit()

    def refresh(self):
        now = time.monotonic()
        if self._screen == 2 and now - getattr(self, "_last_signal_refresh", -1) < 0.1:
            return
        self._last_signal_refresh = now
        if self._version != self.receiver.catalog_version:
            self._version = self.receiver.catalog_version
            self.model.set_catalog(self.receiver.store.catalog())
        if self._last_status is not None and time.monotonic() - self._last_status > 3:
            if self._health != "Acquisition disconnected":
                self._health = "Acquisition disconnected"
                self.healthChanged.emit()
        self.model.update(self.receiver.store.snapshot(), include_signals=self._screen == 2)
        self.stateChanged.emit()


def create_ros_node(receiver, dashboard):
    import importlib

    from ament_index_python.packages import get_package_share_directory
    from rclpy.node import Node
    from rclpy.qos import (QoSProfile, ReliabilityPolicy, DurabilityPolicy,
                          qos_profile_sensor_data)
    from data_station_msgs.msg import CanTelemetry
    from std_msgs.msg import Int32, String

    class DashboardNode(Node):
        def __init__(self):
            super().__init__("runtime_dashboard")
            self.declare_parameter("autonomous_dbc", str(Path(
                get_package_share_directory("data_station_runtime")) /
                "dbc_signals" / "autonomous_t26.dbc"))
            self.declare_parameter("autonomous_prefix", "/can")
            self.declare_parameter("stale_after", 1.0)
            receiver.store = TelemetryStore(float(self.get_parameter("stale_after").value))
            self._last_warning = {}
            self._subscriptions = []
            self._subscriptions.append(self.create_subscription(
                CanTelemetry, "/telemetry/can", self._frame, qos_profile_sensor_data))
            self._subscriptions.append(self.create_subscription(
                String, "/telemetry/dbc_manifest", self._manifest,
                QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                           durability=DurabilityPolicy.TRANSIENT_LOCAL)))
            self._subscriptions.append(self.create_subscription(
                Int32, "/dashboard/set_screen", lambda msg: screen_requests.append(msg.data), 10))
            self._subscriptions.append(self.create_subscription(
                String, "/telemetry/status", self._status, 10))
            self._autonomous()

        def _guard(self, key, callback):
            import time
            try:
                callback()
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                now = time.monotonic()
                if now - self._last_warning.get(key, -10) >= 5:
                    self.get_logger().warning(f"{key}: {exc}")
                    self._last_warning[key] = now

        def _frame(self, msg):
            self._guard("CAN telemetry", lambda: receiver.frame(msg))

        def _manifest(self, msg):
            self._guard("DBC manifest", lambda: receiver.manifest(msg.data))

        def _status(self, msg):
            self._guard("Acquisition status", lambda: health_messages.append(health_summary(msg.data)))

        def _autonomous(self):
            runtime = DbcRuntime({"dds": self.get_parameter("autonomous_dbc").value})
            catalog = runtime.store.catalog()
            receiver.register_dds(catalog)
            module = importlib.import_module("lart_msgs.msg")
            prefix = self.get_parameter("autonomous_prefix").value.rstrip("/")
            groups = {}
            for item in catalog:
                groups.setdefault(item["message"], []).append(item)
            for message_name, definitions in groups.items():
                message_type = getattr(module, ros_type_name(message_name), None)
                if message_type is None:
                    self.get_logger().warning(f"No external ROS type for {message_name}")
                    continue
                available = message_type.get_fields_and_field_types()
                fields = {item["signal"]: ros_name(item["signal"]) for item in definitions
                          if ros_name(item["signal"]) in available}
                missing = [item["signal"] for item in definitions if item["signal"] not in fields]
                if missing:
                    self.get_logger().warning(f"{message_name}: external schema lacks {missing}")
                def receive(msg, name=message_name, mapping=fields):
                    self._guard(name, lambda: receiver.dds(name, mapping, msg))
                self._subscriptions.append(self.create_subscription(
                    message_type, f"{prefix}/{ros_name(message_name)}", receive,
                    qos_profile_sensor_data))

    # ROS callbacks only update data. All Qt objects stay on the Qt thread.
    from collections import deque
    screen_requests = deque(maxlen=1)
    health_messages = deque(maxlen=1)
    node = DashboardNode()

    def update_controls():
        if screen_requests:
            dashboard.selectScreen(screen_requests.pop())
        if health_messages:
            dashboard._health = health_messages.pop()
            dashboard._last_status = time.monotonic()
            dashboard.healthChanged.emit()

    return node, update_controls


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Run without ROS or CAN")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--screenshot", type=Path, help="Save one frame and exit (demo only)")
    parser.add_argument("--screen", type=int, default=0, choices=range(3))
    options, ros_args = parser.parse_known_args(args)
    if options.screenshot and not options.demo:
        parser.error("--screenshot requires --demo")

    app = QGuiApplication([sys.argv[0]])
    receiver = TelemetryReceiver()
    dashboard = Dashboard(receiver)
    dashboard.selectScreen(options.screen)
    node = executor = worker = None
    update_controls = lambda: None
    if options.demo:
        from .demo import populate_demo
        update_controls = lambda: populate_demo(receiver)
        update_controls()
        dashboard._health = "DEMO · no live vehicle connection"
    else:
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        rclpy.init(args=ros_args)
        try:
            node, update_controls = create_ros_node(receiver, dashboard)
            executor = SingleThreadedExecutor()
            executor.add_node(node)
        except Exception:
            rclpy.try_shutdown()
            raise
        worker = threading.Thread(target=executor.spin, name="dashboard-dds", daemon=True)
        worker.start()

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("dashboard", dashboard)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Main.qml")))
    if not engine.rootObjects():
        if executor:
            executor.shutdown()
        if node:
            node.destroy_node()
            rclpy.try_shutdown()
        return 1
    window = engine.rootObjects()[0]
    if options.fullscreen:
        window.showFullScreen()

    timer = QTimer()
    timer.setInterval(33)
    def refresh():
        update_controls()
        dashboard.refresh()
    timer.timeout.connect(refresh)
    refresh()
    timer.start()
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    if options.screenshot:
        def screenshot():
            options.screenshot.parent.mkdir(parents=True, exist_ok=True)
            saved = window.grabWindow().save(str(options.screenshot))
            app.exit(0 if saved else 1)
        QTimer.singleShot(500, screenshot)
    try:
        return app.exec()
    finally:
        timer.stop()
        if executor:
            executor.shutdown(timeout_sec=5)
        if worker:
            worker.join(timeout=5)
        if node:
            node.destroy_node()
            rclpy.try_shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
