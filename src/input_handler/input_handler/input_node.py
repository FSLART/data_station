"""Input handler node — buttons and rotary encoders via GPIO.

Requires python-gpiod >= 2.0  (apt install python3-gpiod on RPi OS Bookworm).
On RPi 5 the GPIO chip is /dev/gpiochip4; falls back to /dev/gpiochip0.

When sim_mode=true (or gpiod is not installed), the node starts successfully
but publishes no events — useful for home testing without hardware.

Published topics:
  none (events are logged at DEBUG; ButtonEvent/EncoderDelta were removed upstream)

Wiring: every input goes to GND, internal pull-ups are enabled (pressed = LOW).
Encoders are decoded as quadrature on both CLK and DT edges (see quadrature.py);
one detent = one step of +1 (CW) / -1 (CCW). Set encoder_reverse if a
physical encoder turns the wrong way round.
"""

import datetime
import threading

import rclpy
from rclpy.node import Node

from input_handler.quadrature import Quadrature

try:
    import gpiod
    from gpiod.line import Bias, Direction, Edge
    _HAS_GPIOD = True
except ImportError:
    _HAS_GPIOD = False


class InputHandlerNode(Node):
    def __init__(self):
        super().__init__('input_handler')

        self.declare_parameter('button_a', 17)
        self.declare_parameter('button_b', 27)
        self.declare_parameter('encoder_a_clk', 22)
        self.declare_parameter('encoder_a_dt', 23)
        self.declare_parameter('encoder_b_clk', 24)
        self.declare_parameter('encoder_b_dt', 25)
        self.declare_parameter('debounce_ms', 50)
        self.declare_parameter('encoder_debounce_us', 2000)  # tune if encoders are noisy/slow
        self.declare_parameter('encoder_steps_per_detent', 4)  # 4 for most, 2 for some
        self.declare_parameter('encoder_reverse', False)
        self.declare_parameter('sim_mode', False)

        sim_mode = self.get_parameter('sim_mode').value
        if sim_mode or not _HAS_GPIOD:
            if not _HAS_GPIOD:
                self.get_logger().warn(
                    'python-gpiod not found — input_handler in no-op mode. '
                    'Install: apt install python3-gpiod'
                )
            else:
                self.get_logger().info('input_handler in sim_mode — no GPIO events')
            return

        debounce = datetime.timedelta(milliseconds=self.get_parameter('debounce_ms').value)
        enc_debounce = datetime.timedelta(
            microseconds=self.get_parameter('encoder_debounce_us').value)
        steps = self.get_parameter('encoder_steps_per_detent').value
        self._reverse = self.get_parameter('encoder_reverse').value

        btn_pins = {
            0: self.get_parameter('button_a').value,
            1: self.get_parameter('button_b').value,
        }
        # enc_id -> (clk_pin, dt_pin)
        enc_pins = {
            0: (self.get_parameter('encoder_a_clk').value,
                self.get_parameter('encoder_a_dt').value),
            1: (self.get_parameter('encoder_b_clk').value,
                self.get_parameter('encoder_b_dt').value),
        }

        def line(deb):
            return gpiod.LineSettings(
                direction=Direction.INPUT, bias=Bias.PULL_UP,
                edge_detection=Edge.BOTH, debounce_period=deb)

        cfg = {pin: line(debounce) for pin in btn_pins.values()}
        for clk, dt in enc_pins.values():
            cfg[clk] = line(enc_debounce)
            cfg[dt] = line(enc_debounce)

        chip_path = self._detect_chip()
        # One request for every line: a single wait/read loop, fails fast if a pin is busy.
        self._req = gpiod.request_lines(chip_path, consumer='lart_input', config=cfg)

        self._btn_pin_to_id = {v: k for k, v in btn_pins.items()}
        self._pin_to_enc = {}   # pin -> (enc_id, 'clk' | 'dt')
        self._levels = {}       # pin -> 0/1 (last known level, updated on every edge)
        self._quad = {}
        for enc_id, (clk, dt) in enc_pins.items():
            self._pin_to_enc[clk] = (enc_id, 'clk')
            self._pin_to_enc[dt] = (enc_id, 'dt')
            self._levels[clk] = int(self._req.get_value(clk) == gpiod.line.Value.ACTIVE)
            self._levels[dt] = int(self._req.get_value(dt) == gpiod.line.Value.ACTIVE)
            self._quad[enc_id] = Quadrature(self._levels[clk], self._levels[dt], steps)

        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        self.get_logger().info(
            f'input_handler started on chip {chip_path} | '
            f'btns={list(btn_pins.values())} encoders(clk,dt)={list(enc_pins.values())}'
        )

    # ------------------------------------------------------------------

    def _detect_chip(self) -> str:
        import os
        for path in ('/dev/gpiochip4', '/dev/gpiochip0'):
            if os.path.exists(path):
                return path
        raise RuntimeError('No gpiochip device found')

    def _poll_loop(self):
        timeout = datetime.timedelta(milliseconds=50)
        while self._running:
            if self._req.wait_edge_events(timeout):
                for ev in self._req.read_edge_events():
                    if ev.line_offset in self._btn_pin_to_id:
                        self._handle_button(ev)
                    else:
                        self._handle_encoder(ev)

    def _handle_button(self, ev) -> None:
        # pull-up + switch to GND: pressed = falling edge
        pressed = ev.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE
        self.get_logger().debug(f'button {self._btn_pin_to_id[ev.line_offset]} pressed={pressed}')

    def _handle_encoder(self, ev) -> None:
        enc_id, _ = self._pin_to_enc[ev.line_offset]
        self._levels[ev.line_offset] = int(ev.event_type == gpiod.EdgeEvent.Type.RISING_EDGE)
        clk_pin = next(p for p, (i, w) in self._pin_to_enc.items() if i == enc_id and w == 'clk')
        dt_pin = next(p for p, (i, w) in self._pin_to_enc.items() if i == enc_id and w == 'dt')
        delta = self._quad[enc_id].update(self._levels[clk_pin], self._levels[dt_pin])
        if not delta:
            return
        self.get_logger().debug(f'encoder {enc_id} delta={-delta if self._reverse else delta}')

    # ------------------------------------------------------------------

    def destroy_node(self):
        self._running = False
        if hasattr(self, '_thread'):
            self._thread.join(timeout=1.0)
        req = getattr(self, '_req', None)
        if req is not None:
            req.release()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = InputHandlerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
