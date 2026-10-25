"""Runtime DBC acquisition; ROS interfaces stay fixed when a DBC changes."""

from collections import deque
from dataclasses import dataclass
import importlib
import json
import math
import re
import threading
import time

from .dbc import DbcRuntime

try:
    from rclpy.node import Node
except ModuleNotFoundError:
    Node = object  # Pure conversion and queue helpers also run without ROS.


def ros_name(raw):
    slug = re.sub(r"[^a-zA-Z0-9_]", "_", raw).strip("_").lower()
    return "val_" + slug if slug and slug[0].isdigit() else slug


def encode_signal(name, value, definition, signal_type):
    """Select a fixed transport field without rounding integer CAN values."""
    out = signal_type()
    out.name = name
    out.unit = definition.get("unit") or ""
    if type(value) is int:
        if value < 0:
            if value < -(1 << 63):
                raise OverflowError(f"{name} does not fit int64")
            out.kind, out.int_value = out.INT64, value
        else:
            if value >= (1 << 64):
                raise OverflowError(f"{name} does not fit uint64")
            out.kind, out.uint_value = out.UINT64, value
    elif type(value) is float:
        out.kind, out.float_value = out.FLOAT64, value
    else:
        raise TypeError(f"Unsupported numeric signal {name}: {type(value).__name__}")
    return out


def legacy_value(value, field_type):
    """Keep the installed compatibility schema, rejecting unsafe conversions."""
    if field_type in ("float", "double", "float32", "float64"):
        return float(value)
    if field_type == "boolean" or field_type == "bool":
        return bool(value)
    match = re.fullmatch(r"(u?)int(8|16|32|64)", field_type)
    if match:
        if not math.isfinite(value) or int(value) != value:
            raise ValueError("Fractional or nonfinite value for legacy integer field")
        converted = int(value)
        bits = int(match[2])
        lower, upper = (0, (1 << bits) - 1) if match[1] else (-(1 << (bits - 1)), (1 << (bits - 1)) - 1)
        if not lower <= converted <= upper:
            raise OverflowError("Value does not fit installed legacy field")
        return converted
    raise TypeError(f"Unsupported legacy field type: {field_type}")


@dataclass(frozen=True)
class ReceivedFrame:
    bus: str
    arbitration_id: int
    data: bytes
    timestamp: float
    received_at: float
    is_extended_id: bool
    is_remote_frame: bool
    is_error_frame: bool
    is_fd: bool
    bitrate_switch: bool
    error_state_indicator: bool
    dlc: int


class FrameInbox:
    """Receive threads only copy frames into a bounded, observable queue."""

    def __init__(self, buses, capacity=4096):
        if capacity <= 0:
            raise ValueError("Queue capacity must be positive")
        self.capacity = capacity
        self._frames = deque()
        self._lock = threading.Lock()
        self.stats = {bus: {"received": 0, "dropped": 0, "io_errors": 0,
                            "last_error": ""} for bus in buses}
        self.reload_discarded = 0

    def capture(self, bus, message):
        with self._lock:
            self.stats[bus]["received"] += 1
            if len(self._frames) >= self.capacity:
                self.stats[bus]["dropped"] += 1
                return
            self._frames.append(ReceivedFrame(
                bus, message.arbitration_id, bytes(message.data), message.timestamp,
                time.monotonic(), message.is_extended_id, message.is_remote_frame,
                message.is_error_frame, message.is_fd, message.bitrate_switch,
                message.error_state_indicator, message.dlc,
            ))

    def error(self, bus, error):
        with self._lock:
            self.stats[bus]["io_errors"] += 1
            self.stats[bus]["last_error"] = str(error)

    def pop(self):
        with self._lock:
            return self._frames.popleft() if self._frames else None

    def switch(self, activate):
        """Activate validated DBCs and discard old-schema bytes at one boundary."""
        with self._lock:
            activate()
            self.reload_discarded += len(self._frames)
            self._frames.clear()

    def status(self):
        with self._lock:
            result = {bus: dict(stats, queue_depth=0) for bus, stats in self.stats.items()}
            for frame in self._frames:
                result[frame.bus]["queue_depth"] += 1
            return {"buses": result, "reload_discarded": self.reload_discarded}


class CanRuntimeNode(Node):
    def __init__(self):
        import can
        from data_station_msgs.msg import CanTelemetry, SignalValue
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import Bool, String
        from std_srvs.srv import Trigger

        super().__init__("can_runtime")
        self._buses, self._notifiers, self._legacy = [], [], {}
        self._closed = False
        self.declare_parameter("can_interfaces", ["can0", "can1"])
        self.declare_parameter("dbc_paths", ["data_t26.dbc", "powertrain_t26.dbc"])
        self.declare_parameter("legacy_prefixes", ["/data", "/pwt"])
        self.declare_parameter("publish_legacy", True)
        self.declare_parameter("stale_after", 1.0)
        self.declare_parameter("precharge_bus", "can1")
        self.declare_parameter("precharge_message", "Start_PreCharge")
        self.declare_parameter("precharge_signal", "Precharge_Request")
        self._precharge_key = tuple(self.get_parameter(name).value for name in (
            "precharge_bus", "precharge_message", "precharge_signal"))
        interfaces = list(self.get_parameter("can_interfaces").value)
        paths = list(self.get_parameter("dbc_paths").value)
        prefixes = list(self.get_parameter("legacy_prefixes").value)
        if not interfaces or len(set(interfaces)) != len(interfaces) or not all(interfaces):
            raise ValueError("can_interfaces must contain unique, nonempty interfaces")
        if len(paths) != len(interfaces) or len(prefixes) != len(interfaces):
            raise ValueError("can_interfaces, dbc_paths and legacy_prefixes must have equal lengths")
        if not all(prefix.startswith("/") and prefix != "/" for prefix in prefixes):
            raise ValueError("legacy_prefixes must be absolute ROS namespaces")
        self._paths = dict(zip(interfaces, paths))
        self._prefixes = dict(zip(interfaces, prefixes))
        self._stale_after = float(self.get_parameter("stale_after").value)
        # Validate every bus before opening sockets or starting receive threads.
        self._runtime = DbcRuntime(self._paths, self._stale_after)
        self._inbox = FrameInbox(interfaces)
        self._counts = {bus: {"published": 0, "decode_errors": 0, "legacy_errors": 0,
                              "publish_errors": 0, "unknown_frames": 0} for bus in interfaces}
        self._frame_type, self._signal_type, self._string_type = CanTelemetry, SignalValue, String
        self._bool_type = Bool
        self._qos = QoSProfile(depth=4096, reliability=ReliabilityPolicy.RELIABLE)
        self._publisher = self.create_publisher(CanTelemetry, "/telemetry/can", self._qos)
        self._manifest_pub = self.create_publisher(String, "/telemetry/dbc_manifest", QoSProfile(
            depth=1, reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self._precharge_pub = self.create_publisher(Bool, "/telemetry/precharge", QoSProfile(
            depth=1, reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self._status_pub = self.create_publisher(String, "/telemetry/status", 10)
        self._prepare_schema()
        self._publish_manifest()
        self.create_service(Trigger, "~/reload_dbc", self._reload)
        self.create_timer(0.002, self._drain)
        self.create_timer(1.0, self._publish_status)
        try:
            for interface in interfaces:
                bus = can.Bus(channel=interface, interface="socketcan", fd=True)
                self._buses.append(bus)
                inbox = self._inbox

                class Listener(can.Listener):
                    def __init__(self, name):
                        self.name = name

                    def on_message_received(self, message):
                        inbox.capture(self.name, message)

                    def on_error(self, error):
                        inbox.error(self.name, error)
                        # A persistent socket error otherwise spins the receive thread.
                        time.sleep(0.05)

                self._notifiers.append(can.Notifier(bus, [Listener(interface)], timeout=0.2))
        except Exception:
            self._close_can()
            super().destroy_node()
            raise
        self.get_logger().info("Runtime CAN acquisition: " + ", ".join(interfaces))

    def _prepare_schema(self):
        self._manifest = self._runtime.manifest()
        self._descriptions = {}
        catalog = self._runtime.store.catalog()
        if not any((item["bus"], item["message"], item["signal"]) == self._precharge_key
                   for item in catalog):
            self.get_logger().warning(
                f"Precharge trigger {'/'.join(self._precharge_key)} missing from DBCs; "
                "retaining the last recording request")
        for item in catalog:
            key = item["bus"], item["frame_id"], item["is_extended_id"]
            if key not in self._descriptions:
                self._descriptions[key] = self._runtime.describe_frame(*key)
        self._legacy.clear()
        if not self.get_parameter("publish_legacy").value:
            return
        try:
            module = importlib.import_module("lart_msgs.msg")
        except ImportError:
            self.get_logger().warning("lart_msgs unavailable; generic telemetry remains active")
            return
        for key, definition in self._descriptions.items():
            slug = ros_name(definition["message"])
            class_name = "".join(word.capitalize() for word in slug.split("_") if word)
            message_type = getattr(module, class_name, None)
            if message_type is None:
                self.get_logger().warning(f"No legacy class {class_name}; use /telemetry/can")
                continue
            fields = message_type.get_fields_and_field_types()
            mapped = {item["signal"]: ros_name(item["signal"]) for item in definition["signals"]
                      if ros_name(item["signal"]) in fields}
            missing = [item["signal"] for item in definition["signals"] if item["signal"] not in mapped]
            if missing:
                self.get_logger().warning(f"{key[0]}/{definition['message']}: generic-only signals {missing}")
            topic = self._prefixes[key[0]].rstrip("/") + "/" + slug
            try:
                publisher = self.create_publisher(message_type, topic, self._qos)
                self._legacy[key] = message_type, publisher, fields, mapped
            except Exception as error:
                self.get_logger().warning(f"Legacy publisher {topic} unavailable: {error}")

    def _publish_manifest(self):
        out = self._string_type()
        out.data = json.dumps({"schema_version": 1, "catalog": self._runtime.store.catalog(),
                               "buses": self._manifest}, allow_nan=False)
        self._manifest_pub.publish(out)

    def _reload(self, request, response):
        try:
            candidate = DbcRuntime(self._paths, self._stale_after)
        except Exception as error:
            response.success = False
            response.message = f"DBC validation failed; active schema unchanged: {error}"
            return response
        old_publishers = [item[1] for item in self._legacy.values()]
        self._inbox.switch(lambda: setattr(self, "_runtime", candidate))
        for publisher in old_publishers:
            self.destroy_publisher(publisher)
        self._prepare_schema()
        self._publish_manifest()
        response.success, response.message = True, "All DBCs reloaded; queued old-schema frames discarded"
        return response

    def _drain(self):
        for _ in range(256):
            frame = self._inbox.pop()
            if frame is None:
                break
            self._publish_frame(frame)

    def _publish_frame(self, frame):
        key = frame.bus, frame.arbitration_id, frame.is_extended_id
        definition = self._descriptions.get(key)
        if definition is None:
            definition = self._runtime.describe_frame(*key)
            if definition is not None:
                self._descriptions[key] = definition
        values = {}
        if not frame.is_remote_frame and not frame.is_error_frame:
            try:
                values = self._runtime.decode(frame.bus, frame.arbitration_id, frame.data,
                    is_extended_id=frame.is_extended_id, timestamp=frame.timestamp,
                    received_at=frame.received_at)
            except Exception as error:
                self._counts[frame.bus]["decode_errors"] += 1
                self.get_logger().warning(f"DBC decode {frame.bus}/0x{frame.arbitration_id:X}: {error}",
                                          throttle_duration_sec=5.0)
                values = {}
        if definition is None:
            self._counts[frame.bus]["unknown_frames"] += 1
        elif values:
            self._publish_precharge(frame.bus, definition["message"], values)
        out = self._frame_type()
        timestamp = frame.timestamp
        if not math.isfinite(timestamp) or not 0 <= timestamp < (1 << 31) - 1:
            timestamp = self.get_clock().now().nanoseconds / 1e9
        nanos = round(timestamp * 1e9)
        out.header.stamp.sec, out.header.stamp.nanosec = divmod(nanos, 1_000_000_000)
        out.header.frame_id = frame.bus
        out.bus, out.message = frame.bus, definition["message"] if definition else ""
        out.can_id, out.is_extended = frame.arbitration_id, frame.is_extended_id
        out.is_remote, out.is_error, out.is_fd = frame.is_remote_frame, frame.is_error_frame, frame.is_fd
        out.bitrate_switch, out.error_state_indicator = frame.bitrate_switch, frame.error_state_indicator
        out.dlc, out.data = frame.dlc, list(frame.data)
        out.dbc_sha256 = self._manifest[frame.bus]["sha256"]
        metadata = {item["signal"]: item for item in definition["signals"]} if definition else {}
        try:
            out.signals = [encode_signal(name, value, metadata[name], self._signal_type)
                           for name, value in (values or {}).items()]
        except (TypeError, OverflowError) as error:
            self._counts[frame.bus]["decode_errors"] += 1
            self.get_logger().warning(f"Signal encoding: {error}", throttle_duration_sec=5.0)
        try:
            self._publisher.publish(out)
            self._counts[frame.bus]["published"] += 1
        except Exception as error:
            self._counts[frame.bus]["publish_errors"] += 1
            self.get_logger().error(f"CAN publication failed: {error}", throttle_duration_sec=5.0)
        if values and key in self._legacy:
            self._publish_legacy(key, values, out.header.stamp)

    def _publish_precharge(self, bus, message, values):
        expected_bus, expected_message, signal = self._precharge_key
        if (bus, message) != (expected_bus, expected_message) or signal not in values:
            return
        value = values[signal]
        if type(value) not in (int, float) or not math.isfinite(value):
            return
        out = self._bool_type()
        out.data = value >= 0.5
        try:
            # Repeat active requests so a recorder can retry a failed process start.
            self._precharge_pub.publish(out)
        except Exception as error:
            self._counts[bus]["publish_errors"] += 1
            self.get_logger().error(f"Precharge publication failed: {error}", throttle_duration_sec=5.0)

    def _publish_legacy(self, key, values, stamp):
        message_type, publisher, fields, mapped = self._legacy[key]
        try:
            out = message_type()
            if "header" in fields:
                out.header.stamp = stamp
            for name, value in values.items():
                field = mapped.get(name)
                if field is not None:
                    setattr(out, field, legacy_value(value, fields[field]))
            publisher.publish(out)
        except Exception as error:
            self._counts[key[0]]["legacy_errors"] += 1
            self.get_logger().warning(f"Legacy publication {key}: {error}", throttle_duration_sec=5.0)

    def _publish_status(self):
        status = self._inbox.status()
        for bus, counts in self._counts.items():
            status["buses"][bus].update(counts)
        out = self._string_type()
        out.data = json.dumps(status)
        self._status_pub.publish(out)

    def _close_can(self):
        if self._closed:
            return
        self._closed = True
        for notifier in self._notifiers:
            try:
                notifier.stop()
            except Exception as error:
                self.get_logger().warning(f"CAN notifier shutdown: {error}")
        for bus in self._buses:
            try:
                bus.shutdown()
            except Exception as error:
                self.get_logger().warning(f"CAN socket shutdown: {error}")

    def destroy_node(self):
        self._close_can()
        return super().destroy_node()


def main(args=None):
    import rclpy
    rclpy.init(args=args)
    node = None
    try:
        node = CanRuntimeNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()
