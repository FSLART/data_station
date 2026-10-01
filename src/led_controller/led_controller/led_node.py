"""Addressable LED strip controller — relative-current gauge.

Requires adafruit-circuitpython-neopixel-spi + adafruit-blinka:
  pip install adafruit-circuitpython-neopixel-spi

LED behaviour:
  - Red fill shows positive average inverter relative-current request
  - Blue fill shows negative average inverter relative-current request
  - The two directions fill outward from the centre of the strip
  - All LEDs turn off when the node shuts down
"""

import math

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from lart_msgs.msg import Inv1Setrelcurrent, Inv2Setrelcurrent

try:
    import board
    import neopixel_spi
    _HAS_NEOPIXEL_SPI = True
except (ImportError, NotImplementedError):
    _HAS_NEOPIXEL_SPI = False

_COLOR_OFF = (0, 0, 0)
_COLOR_IDLE = (255, 255, 255)
_COLOR_DRIVE = (255, 0, 0)
_COLOR_REGEN = (0, 0, 255)


class LedControllerNode(Node):
    def __init__(self):
        super().__init__('led_controller')

        self.declare_parameter('led_count', 16)
        self.declare_parameter('brightness', 0.15)
        self.declare_parameter('animation_hz', 20.0)

        self._count = int(self.get_parameter('led_count').value)
        brightness = float(self.get_parameter('brightness').value)
        animation_hz = float(self.get_parameter('animation_hz').value)
        self._inv1_percent = 0.0
        self._inv2_percent = 0.0

        if _HAS_NEOPIXEL_SPI:
            self._pixels = neopixel_spi.NeoPixel_SPI(
                board.SPI(),
                self._count,
                brightness=max(0.0, min(brightness, 1.0)),
                auto_write=False,
                pixel_order=neopixel_spi.GRB,
            )
        else:
            self._pixels = None
            self.get_logger().warn(
                'NeoPixel SPI library not found — LED output disabled. '
                'Install: pip install adafruit-circuitpython-neopixel-spi'
            )

        self.create_subscription(
            Inv1Setrelcurrent,
            '/pwt/inv1_setrelcurrent',
            self._on_inv1,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            Inv2Setrelcurrent,
            '/pwt/inv2_setrelcurrent',
            self._on_inv2,
            qos_profile_sensor_data,
        )
        self._timer = self.create_timer(
            1.0 / max(animation_hz, 1.0), self._update_bar
        )
        self.get_logger().info(
            f'LED controller ready — {self._count} LEDs relative-current gauge'
        )

    # ------------------------------------------------------------------

    def _on_inv1(self, msg):
        self._inv1_percent = msg.inv1_cmd_targetrelativecurrent

    def _on_inv2(self, msg):
        self._inv2_percent = msg.inv2_cmd_targetrelativecurrent

    def _update_bar(self):
        if self._pixels is None:
            return

        inverter_percent = (self._inv1_percent + self._inv2_percent) / 2.0
        half_count = self._count // 2
        percent = float(inverter_percent)
        if not math.isfinite(percent):
            percent = 0.0
        percent = max(-100.0, min(percent, 100.0))
        if percent == 0.0:
            center = {7, 8}  # physical LED positions 8 and 9
            self._pixels.fill(_COLOR_OFF)
            for index in center:
                self._pixels[index] = _COLOR_IDLE
            self._pixels.show()
            return

        lit_count = round(abs(percent) * half_count / 100.0)
        if percent < 0.0:
            color = _COLOR_REGEN
            lit_indices = range(half_count, half_count + lit_count)
        else:
            color = _COLOR_DRIVE
            lit_indices = range(half_count - lit_count, half_count)
            
        lit_indices = set(lit_indices)
        self._pixels.fill(_COLOR_OFF)
        for index in lit_indices:
            self._pixels[index] = color
        self._pixels.show()

    # ------------------------------------------------------------------

    def destroy_node(self):
        if self._pixels is not None:
            self._pixels.fill(_COLOR_OFF)
            self._pixels.show()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = LedControllerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
