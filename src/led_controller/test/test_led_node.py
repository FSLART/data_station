import importlib
import sys
import types


class _Parameter:
    def __init__(self, value):
        self.value = value


class _Logger:
    def warn(self, _message):
        pass

    def info(self, _message):
        pass


class _Node:
    def __init__(self, _name):
        self.parameters = {}
        self.timer = None

    def declare_parameter(self, name, default):
        self.parameters[name] = default

    def get_parameter(self, name):
        return _Parameter(self.parameters[name])

    def create_subscription(self, *_args):
        pass

    def create_timer(self, period, callback):
        self.timer = types.SimpleNamespace(period=period, callback=callback)
        return self.timer

    def get_logger(self):
        return _Logger()

    def destroy_node(self):
        pass


class _NeoPixel:
    def __init__(self, _pin, count, **_kwargs):
        self.values = [None] * count
        self.show_count = 0

    def __setitem__(self, index, color):
        self.values[index] = color

    def fill(self, color):
        self.values[:] = [color] * len(self.values)

    def show(self):
        self.show_count += 1


def _make_controller(monkeypatch):
    rclpy = types.ModuleType("rclpy")
    rclpy_node = types.ModuleType("rclpy.node")
    rclpy_node.Node = _Node
    std_msgs = types.ModuleType("std_msgs")
    std_msgs_msg = types.ModuleType("std_msgs.msg")
    std_msgs_msg.Float32 = type("Float32", (), {})
    board = types.ModuleType("board")
    board.D18 = object()
    neopixel = types.ModuleType("neopixel")
    neopixel.NeoPixel = _NeoPixel

    monkeypatch.setitem(sys.modules, "rclpy", rclpy)
    monkeypatch.setitem(sys.modules, "rclpy.node", rclpy_node)
    monkeypatch.setitem(sys.modules, "std_msgs", std_msgs)
    monkeypatch.setitem(sys.modules, "std_msgs.msg", std_msgs_msg)
    monkeypatch.setitem(sys.modules, "board", board)
    monkeypatch.setitem(sys.modules, "neopixel", neopixel)

    sys.modules.pop("led_controller.led_node", None)
    led_node = importlib.import_module("led_controller.led_node")
    return led_node.LedControllerNode()


def test_controller_animates_a_moving_rainbow_on_all_eight_leds(monkeypatch):
    node = _make_controller(monkeypatch)

    assert len(node._pixels.values) == 8
    node.timer.callback()
    first_frame = list(node._pixels.values)

    assert all(
        isinstance(color, tuple)
        and len(color) == 3
        and all(0 <= channel <= 255 for channel in color)
        for color in first_frame
    )
    assert len(set(first_frame)) == 8
    assert node._pixels.show_count == 1

    node.timer.callback()

    assert node._pixels.values != first_frame
    assert node._pixels.show_count == 2


def test_controller_turns_off_every_led_on_shutdown(monkeypatch):
    node = _make_controller(monkeypatch)
    node.timer.callback()

    node.destroy_node()

    assert node._pixels.values == [(0, 0, 0)] * 8
    assert node._pixels.show_count == 2
