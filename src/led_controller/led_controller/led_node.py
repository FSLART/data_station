"""Addressable LED strip controller — moving rainbow effect.

Requires adafruit-circuitpython-neopixel-spi + adafruit-blinka:
  pip install adafruit-circuitpython-neopixel-spi

LED behaviour:
  - All LEDs display a moving rainbow while the node is running
  - All LEDs turn off when the node shuts down
"""

import rclpy
from rclpy.node import Node

try:
    import board
    import neopixel_spi
    _HAS_NEOPIXEL_SPI = True
except (ImportError, NotImplementedError):
    _HAS_NEOPIXEL_SPI = False

_COLOR_OFF = (0, 0, 0)


def _rainbow_color(position):
    """Return one RGB color from a 0-255 color wheel."""
    position %= 256
    if position < 85:
        return (255 - position * 3, position * 3, 0)
    if position < 170:
        position -= 85
        return (0, 255 - position * 3, position * 3)
    position -= 170
    return (position * 3, 0, 255 - position * 3)


class LedControllerNode(Node):
    def __init__(self):
        super().__init__('led_controller')

        self.declare_parameter('led_count', 8)
        self.declare_parameter('brightness', 0.5)
        self.declare_parameter('animation_hz', 20.0)

        self._count = int(self.get_parameter('led_count').value)
        brightness = float(self.get_parameter('brightness').value)
        animation_hz = float(self.get_parameter('animation_hz').value)
        self._rainbow_offset = 0

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

        self._timer = self.create_timer(
            1.0 / max(animation_hz, 1.0), self._animate_rainbow
        )
        self.get_logger().info(
            f'LED controller ready — {self._count} LEDs moving rainbow'
        )

    # ------------------------------------------------------------------

    def _animate_rainbow(self):
        if self._pixels is None:
            return

        for index in range(self._count):
            position = index * 256 // self._count + self._rainbow_offset
            self._pixels[index] = _rainbow_color(position)
        self._pixels.show()
        self._rainbow_offset = (self._rainbow_offset + 4) % 256

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
