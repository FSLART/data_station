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
        self.subscriptions = {}

    def declare_parameter(self, name, default):
        self.parameters[name] = default

    def get_parameter(self, name):
        return _Parameter(self.parameters[name])

    def create_subscription(self, _msg_type, topic, callback, _qos):
        self.subscriptions[topic] = callback
        return callback

    def create_timer(self, period, callback):
        self.timer = types.SimpleNamespace(period=period, callback=callback)
        return self.timer

    def get_logger(self):
        return _Logger()

    def destroy_node(self):
        pass


class _NeoPixel:
    def __init__(self, spi, count, **_kwargs):
        self.spi = spi
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
    rclpy_qos = types.ModuleType("rclpy.qos")
    rclpy_node.Node = _Node
    rclpy_qos.qos_profile_sensor_data = object()
    std_msgs = types.ModuleType("std_msgs")
    std_msgs_msg = types.ModuleType("std_msgs.msg")
    std_msgs_msg.Float32 = type("Float32", (), {})
    lart_msgs = types.ModuleType("lart_msgs")
    lart_msgs_msg = types.ModuleType("lart_msgs.msg")
    lart_msgs_msg.Inv1Setrelcurrent = type("Inv1Setrelcurrent", (), {})
    lart_msgs_msg.Inv2Setrelcurrent = type("Inv2Setrelcurrent", (), {})
    board = types.ModuleType("board")
    spi_bus = object()
    board.SPI = lambda: spi_bus
    neopixel_spi = types.ModuleType("neopixel_spi")
    neopixel_spi.NeoPixel_SPI = _NeoPixel
    neopixel_spi.GRB = "GRB"

    monkeypatch.setitem(sys.modules, "rclpy", rclpy)
    monkeypatch.setitem(sys.modules, "rclpy.node", rclpy_node)
    monkeypatch.setitem(sys.modules, "rclpy.qos", rclpy_qos)
    monkeypatch.setitem(sys.modules, "std_msgs", std_msgs)
    monkeypatch.setitem(sys.modules, "std_msgs.msg", std_msgs_msg)
    monkeypatch.setitem(sys.modules, "lart_msgs", lart_msgs)
    monkeypatch.setitem(sys.modules, "lart_msgs.msg", lart_msgs_msg)
    monkeypatch.setitem(sys.modules, "board", board)
    monkeypatch.setitem(sys.modules, "neopixel_spi", neopixel_spi)

    sys.modules.pop("led_controller.led_node", None)
    led_node = importlib.import_module("led_controller.led_node")
    node = led_node.LedControllerNode()
    assert node._pixels.spi is spi_bus
    return node


def test_controller_fills_positive_current_from_centre_in_blue(monkeypatch):
    node = _make_controller(monkeypatch)

    node.subscriptions["/pwt/inv1_setrelcurrent"](
        types.SimpleNamespace(inv1_cmd_targetrelativecurrent=50.0)
    )
    node.subscriptions["/pwt/inv2_setrelcurrent"](
        types.SimpleNamespace(inv2_cmd_targetrelativecurrent=50.0)
    )
    node.timer.callback()

    assert node._pixels.values == [(0, 0, 0)] * 8 + [(0, 0, 255)] * 4 + [(0, 0, 0)] * 4
    assert node._pixels.show_count == 1


def test_controller_fills_negative_current_from_centre_in_green(monkeypatch):
    node = _make_controller(monkeypatch)

    node.subscriptions["/pwt/inv1_setrelcurrent"](
        types.SimpleNamespace(inv1_cmd_targetrelativecurrent=-25.0)
    )
    node.subscriptions["/pwt/inv2_setrelcurrent"](
        types.SimpleNamespace(inv2_cmd_targetrelativecurrent=-25.0)
    )
    node.timer.callback()

    assert node._pixels.values == [(0, 0, 0)] * 6 + [(0, 255, 0)] * 2 + [(0, 0, 0)] * 8


def test_negative_average_inverter_request_fills_eight_green_leds(monkeypatch):
    node = _make_controller(monkeypatch)
    node.subscriptions["/pwt/inv1_setrelcurrent"](
        types.SimpleNamespace(inv1_cmd_targetrelativecurrent=-25.0)
    )
    node.subscriptions["/pwt/inv2_setrelcurrent"](
        types.SimpleNamespace(inv2_cmd_targetrelativecurrent=-75.0)
    )

    node.timer.callback()

    assert node._pixels.values == [(0, 0, 0)] * 4 + [(0, 255, 0)] * 4 + [(0, 0, 0)] * 8


def test_controller_turns_off_every_led_on_shutdown(monkeypatch):
    node = _make_controller(monkeypatch)
    node.timer.callback()

    node.destroy_node()

    assert node._pixels.values == [(0, 0, 0)] * 16
    assert node._pixels.show_count == 2
