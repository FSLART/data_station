"""Record generic CAN telemetry and direct autonomous DDS topics together.

Record while precharge requests HV or Jetson reports READY/DRIVING. Both
requests must explicitly clear before the inherited stop grace period starts.
"""

from lart_msgs.msg import Jetson
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool

from lart_bringup.bag_recorder import BagRecorderNode, _BEST_EFFORT, main as recorder_main
from data_station_runtime.recording_trigger import RecordingTriggers


class TelemetryRecorderNode(BagRecorderNode):
    def _create_trigger_subscriptions(self) -> str:
        self.declare_parameter("precharge_topic", "/telemetry/precharge")
        self.declare_parameter("jetson_topic", "/can/jetson")
        precharge_topic = self.get_parameter("precharge_topic").value
        jetson_topic = self.get_parameter("jetson_topic").value
        self._triggers = RecordingTriggers(self._sm.on_trigger)
        self.create_subscription(
            Bool, precharge_topic, self._on_precharge,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL),
        )
        self.create_subscription(Jetson, jetson_topic, self._on_jetson, _BEST_EFFORT)
        return f"{precharge_topic} OR {jetson_topic} READY/DRIVING"

    def _on_precharge(self, message) -> None:
        self._triggers.on_precharge(message.data)

    def _on_jetson(self, message) -> None:
        self._triggers.on_jetson_state(message.as_state)

    def _check_recorder_alive(self) -> None:
        super()._check_recorder_alive()
        self._sm.on_trigger(self._triggers.active)


def main(args=None):
    recorder_main(args=args, node_class=TelemetryRecorderNode)
