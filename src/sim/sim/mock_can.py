"""Mock CAN publisher for home / bench testing.

Simulates ECU CAN traffic without any real hardware.
Publishes synthetic RPM values for downstream nodes.

Published topics:
  /vehicle/rpm  (std_msgs/Float32)

Simulation cycle (configurable via parameters):
  0 – 2 s  : idle RPM
  2 – 7 s  : linear sweep idle → rpm_max
  7 – 8 s  : hold rpm_max
  repeat

The RPM sweep matches the default can_bridge.rpm_start_byte /
rpm_length_bytes settings.
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32


class MockCanNode(Node):
    def __init__(self):
        super().__init__('mock_can')

        self.declare_parameter('rpm_can_id', 291)        # 0x123
        self.declare_parameter('rpm_idle', 1000.0)
        self.declare_parameter('rpm_max', 12500.0)
        self.declare_parameter('rpm_shift', 11500.0)
        self.declare_parameter('sweep_period_s', 5.0)
        self.declare_parameter('publish_hz', 100.0)

        self._rpm_can_id = self.get_parameter('rpm_can_id').value
        self._rpm_idle = self.get_parameter('rpm_idle').value
        self._rpm_max = self.get_parameter('rpm_max').value
        self._sweep_s = self.get_parameter('sweep_period_s').value

        hz = self.get_parameter('publish_hz').value
        self._dt = 1.0 / hz
        self._t = 0.0

        self._rpm_pub = self.create_publisher(Float32, '/vehicle/rpm', 10)

        self.create_timer(self._dt, self._tick)
        self.get_logger().info(
            f'Mock CAN publisher running at {hz:.0f} Hz '
            f'(RPM ID=0x{self._rpm_can_id:03X})'
        )

    # ------------------------------------------------------------------

    def _tick(self) -> None:
        self._t += self._dt
        rpm = self._compute_rpm(self._t)

        rpm_msg = Float32()
        rpm_msg.data = float(rpm)
        self._rpm_pub.publish(rpm_msg)

    def _compute_rpm(self, t: float) -> float:
        """Cycle: 2 s idle | sweep_period_s sweep | 1 s hold max | repeat."""
        cycle = 2.0 + self._sweep_s + 1.0
        phase = t % cycle
        if phase < 2.0:
            return self._rpm_idle
        elif phase < 2.0 + self._sweep_s:
            frac = (phase - 2.0) / self._sweep_s
            return self._rpm_idle + (self._rpm_max - self._rpm_idle) * frac
        else:
            return self._rpm_max


def main(args=None):
    rclpy.init(args=args)
    node = MockCanNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
