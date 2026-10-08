"""can_simulator.py — Virtual CAN traffic generator for DBC-based testing.

Creates a vcan interface (vcan0 by default), loads a DBC file with cantools,
and periodically sends realistic CAN frames so that can_bridge can exercise
the full decode pipeline without any real hardware.

Parameters (rpi_config.yaml → can_simulator):
  can_interface   — vcan interface name (default: vcan0)
  dbc_path        — absolute path to DBC file (required)
  publish_hz      — frame injection rate in Hz (default: 10.0)
  message_ids     — list of CAN IDs to simulate; empty = all messages in DBC

Setup performed automatically at startup:
  sudo modprobe vcan
  sudo ip link add <iface> type vcan   (idempotent — ignored if already exists)
  sudo ip link set <iface> up
"""

import math
import random
import subprocess
import time

import can
import cantools
import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import SetParametersResult

from .admin_controls import ControlConfig, MessageSchedule, control_value, tick_period, speed_to_erpm
from .simulation_config import load_config, driving_state

# ---------------------------------------------------------------------------
# Real-world FS-EV magnitudes.
#
# Many DBC signals leave physical min/max unset ([0|0], which cantools reads
# as "not specified"), so without these targets the simulator falls back to
# the raw bit-width range — e.g. a 16-bit cell voltage (scale 0.001) would
# swing up to 65V instead of a real Li-ion cell's ~3.0-4.2V.
# ---------------------------------------------------------------------------
# Physical bands and the drive cycle live in config/can_simulator.cfg.
PRECHARGE_SEQUENCE_STEP_SECONDS = 0.5
PRECHARGE_TEST_SEQUENCE = (19, *range(17))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def setup_vcan(iface: str, logger=None) -> bool:
    """Create and bring up a virtual CAN interface.

    Returns True on success, False if anything fails.
    Errors are non-fatal so the node can still start and report the problem.
    """
    def _log(msg: str) -> None:
        if logger:
            logger.info(msg)
        else:
            print(msg)

    def _err(msg: str) -> None:
        if logger:
            logger.error(msg)
        else:
            print(f"ERROR: {msg}")

    import os
    iface_exists = os.path.exists(f'/sys/class/net/{iface}')
    if iface_exists:
        _log(f'Virtual CAN interface {iface} already exists.')
        try:
            with open(f'/sys/class/net/{iface}/operstate', 'r') as f:
                state = f.read().strip()
            if state in ('up', 'unknown'):
                _log(f'Virtual CAN interface {iface} is already UP.')
                return True
        except Exception:
            pass
    else:
        # Try to load the vcan kernel module.
        # Inside Docker the module files are absent from the container's
        # /lib/modules, but the host may have already loaded vcan — in that case
        # modprobe will fail yet `ip link add … type vcan` will still succeed.
        # We therefore treat a modprobe failure as a warning, not a hard error.
        r = _run(['modprobe', 'vcan'])
        if r.returncode != 0:
            _log(f'modprobe vcan skipped (will try ip link anyway): {r.stderr.strip()}')
        else:
            _log('vcan kernel module loaded.')

        # Create the interface (idempotent — ignore "File exists" / "already exists")
        r = _run(['ip', 'link', 'add', iface, 'type', 'vcan'])
        if r.returncode != 0 and not any(kw in r.stderr for kw in ('File exists', 'already exists', 'RTNETLINK answers: File exists')):
            _err(f'Failed to create {iface}: {r.stderr.strip()}')
            return False

    # Bring the interface up
    r = _run(['ip', 'link', 'set', iface, 'up'])
    if r.returncode != 0:
        if iface_exists:
            _log(f'Warning: Could not set {iface} up, but it already exists. Proceeding anyway.')
            return True
        _err(f'Failed to bring up {iface}: {r.stderr.strip()}')
        return False

    _log(f'Virtual CAN interface {iface} is UP.')
    return True


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _precharge_sequence_value(elapsed_seconds: float) -> float:
    """Return the test precharge state for time elapsed since RX_CAN."""
    step = int(max(0.0, elapsed_seconds) / PRECHARGE_SEQUENCE_STEP_SECONDS)
    step = min(step, len(PRECHARGE_TEST_SEQUENCE) - 1)
    return float(PRECHARGE_TEST_SEQUENCE[step])


class _PrechargeSequence:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._started_at = None
        self._trigger_consumed = False

    def value(self, override: float, now: float) -> float:
        if override != 19.0:
            self.reset()
            return override

        if not self._trigger_consumed:
            self._started_at = now
            self._trigger_consumed = True

        return _precharge_sequence_value(now - self._started_at)


def _raw_to_physical(raw: float, signal: cantools.db.Signal) -> float:
    """Apply scale and offset to convert a raw integer to physical value."""
    scale = signal.scale if signal.scale is not None else 1.0
    offset = signal.offset if signal.offset is not None else 0.0
    return raw * scale + offset


def _encodable_range(signal: cantools.db.Signal) -> tuple[float, float]:
    """Return the (min, max) physical values that can be encoded without overflow.

    Derives the range from the signal's bit length, sign, scale, and offset so
    that the value is always representable as a raw integer inside the frame —
    regardless of whether the DBC author populated the min/max fields.
    """
    if signal.is_signed:
        raw_min = -(2 ** (signal.length - 1))
        raw_max = 2 ** (signal.length - 1) - 1
    else:
        raw_min = 0
        raw_max = 2 ** signal.length - 1

    scale = signal.scale if signal.scale is not None else 1.0
    offset = signal.offset if signal.offset is not None else 0.0

    phys_a = raw_min * scale + offset
    phys_b = raw_max * scale + offset
    enc_min = min(phys_a, phys_b)
    enc_max = max(phys_a, phys_b)

    # Also honour the DBC-defined physical limits when present
    if signal.minimum is not None:
        enc_min = max(enc_min, signal.minimum)
    if signal.maximum is not None:
        enc_max = min(enc_max, signal.maximum)

    # Guard against degenerate ranges
    if enc_max <= enc_min:
        if signal.maximum is not None and signal.minimum is not None and signal.maximum == signal.minimum:
            pass
        else:
            enc_max = enc_min + abs(scale) if scale else enc_min + 1.0

    return enc_min, enc_max


def _make_signal_value(signal: cantools.db.Signal, t: float, mission_override: float | None = None, config=None) -> float:
    """Generate a realistic, time-varying value for a DBC signal.

    Values are guaranteed to lie within the encodable physical range so that
    cantools.encode_message never raises an out-of-range error.
    """
    enc_min, enc_max = _encodable_range(signal)
    name_lower = signal.name.lower()
    config = config if config is not None else load_config()
    speed_factor, accel_pct, brake_pct = driving_state(config, t)

    def band(name):
        low, high = config['ranges'][name]
        return _clamp(low, enc_min, enc_max), _clamp(high, enc_min, enc_max)


    if signal.name in ('Mission_select', 'AS_MISSION'):
        # Held constant (not auto-cycled) — the dashboard's mission display
        # falls back through Mission_select -> AS_MISSION -> ami_state, so
        # both must be pinned or the UI keeps showing AS_MISSION's drift.
        # Set manually via the can_simulator "mission_select_value" /
        # "as_mission_value" ROS parameters (see test_data_ros2.sh).
        val = mission_override if mission_override is not None else enc_min
        return _clamp(val, enc_min, enc_max)

    # Limit flags report derating/fault conditions, not a healthy enabled state.
    if 'fault' in name_lower or 'error' in name_lower or (signal.length == 1 and name_lower.endswith('_limit')):
        return _clamp(0, enc_min, enc_max)

    if name_lower in ('soc_integer', 'soc_float'):
        low, high = band('soc_percent')
        return max(low, high - t * .01)

    if name_lower == 'lv_voltage_mv':
        low, high = band('lv_voltage')
        return high - (high - low) * .15

    if name_lower in ('ivt_result_u1', 'ivt_result_u2', 'ivt_result_u3'):
        low, high = config['ranges']['lv_voltage' if name_lower.endswith('u3') else 'pack_voltage']
        val = (high - (high - low) * (.1 + .1 * accel_pct / 100)) * 1000
        return _clamp(val, enc_min, enc_max)

    if name_lower in ('ivt_result_i', 'ivt_result_w'):
        low, high = config['ranges']['current']
        current = low * brake_pct / 100 if brake_pct else high * accel_pct / 100
        factor = 1000 if name_lower.endswith('_i') else sum(config['ranges']['pack_voltage']) / 2
        return _clamp(current * factor, enc_min, enc_max)

    if name_lower == 'ivt_result_t':
        low, high = config['ranges']['other_temperature']
        return _clamp((low + high) / 2, enc_min, enc_max)

    # Trigger/command signals (e.g. precharge_request) are driven by an
    # external actor (VCU/operator), not the simulated vehicle bus — hold
    # them at a constant "off" so they don't spuriously fire downstream
    # consumers like bag_recorder's precharge trigger. Checked before the
    # discrete-choice branch below since these signals often carry DBC
    # choice labels (e.g. 0: open/de-energize, 1: close/energize) that
    # would otherwise cycle them on/off like a real state signal.
    if 'request' in name_lower:
        return 0.0

    # 1. Discrete Choice / State Signals — held constant (first choice) so
    # downstream screens/state indicators don't flip on their own.
    if getattr(signal, 'choices', None) is not None and len(signal.choices) > 0:
        keys = sorted(list(signal.choices.keys()))
        return float(keys[0])

    # 2. Boolean/Discrete Flags — held constant (no cycling) for the same reason.
    unit = (signal.unit or "").strip()

    boolean_keywords = ['ign', 'r2d', 'button', 'emergency', 'switch', 'bots', 'enable', 'ok', 'fail', 'error', 'active', 'state', 'status']
    is_boolean = signal.length == 1 or any(x in name_lower for x in boolean_keywords) or ('res' in name_lower and 'result' not in name_lower)
    if is_boolean:
        if enc_max - enc_min == 1:
            return 1.0
        elif enc_max - enc_min <= 10:
            return float(int(enc_min))

    # Shared stop/accelerate/cruise/brake sequence across all simulated buses.
    speed_low, speed_high = config['ranges']['speed_kmh']
    speed_kmh = speed_low + (speed_high - speed_low) * speed_factor
    steer_factor = math.sin(t * .15) if 0 < speed_factor < .5 else 0.0

    # Identify the quantity category and scale to its physical bounds

    # Category A: Percentage / Pedals / Torque / Duty cycles
    is_percentage = (unit == '%' or
                     any(x in name_lower for x in ['apps', 'pedal', 'brake_hydr', 'torque', 'moment', 'percent', 'pct', 'duty', 'throttle']))

    # Category B: Speed / RPM / Velocity — split so electrical RPM, mechanical
    # RPM and road speed (km/h) each get their own realistic magnitude instead
    # of all sharing whatever the raw bit width happens to allow.
    is_erpm = 'erpm' in name_lower
    is_rpm = (not is_erpm) and 'rpm' in name_lower
    is_kph_speed = (not is_erpm and not is_rpm and
                    any(x in name_lower for x in ['speed', 'spd', 'vel', 'kph']))

    # Category C: Pressure
    is_pressure = any(x in name_lower for x in ['press', 'pressure', 'bar'])

    # Category D: Temperature — split by subsystem so battery, inverter and
    # motor each get their own realistic range instead of sharing one band.
    is_temp = any(x in name_lower for x in ['temp', 'temperature', 'ntc'])
    is_temp_batt = is_temp and any(x in name_lower for x in ['batt', 'bms', 'acc', 'cell', 'pack'])
    is_temp_motor = is_temp and (not is_temp_batt) and any(x in name_lower for x in ['mot', 'motor'])
    is_temp_inv = is_temp and (not is_temp_batt) and (not is_temp_motor) and any(x in name_lower for x in ['inv', 'inverter'])
    is_temp_other = is_temp and not (is_temp_batt or is_temp_inv or is_temp_motor)

    # Category D2: Lap counter — bounded to a realistic 1-4 lap race distance
    is_lap = 'lap' in name_lower

    # Category E: Current
    is_current = any(x in name_lower for x in ['current', 'curr', 'amp'])

    # Category F: Voltage — split cell-level, module-level and LV-rail
    # readings from the main HV pack/bus, since they differ by two orders
    # of magnitude and would otherwise all be driven by the same raw range.
    is_cell_volt = ('cell_voltage' in name_lower or
                    any(name_lower.endswith(f'module_voltage_{x}') or f'module_voltage_{x}' in name_lower
                        for x in ('avg', 'min', 'max')) or
                    'overall_maximum_voltage' in name_lower or 'overall_minimum_voltage' in name_lower)
    is_module_volt_sum = 'module_voltage_sum' in name_lower
    is_lv_volt = (not is_cell_volt and not is_module_volt_sum and
                  'lv' in name_lower and any(x in name_lower for x in ['volt', 'v_']))
    is_pack_volt = (not is_cell_volt and not is_module_volt_sum and not is_lv_volt and
                    any(x in name_lower for x in ['voltage', 'volt', 'v_']))

    # Category G: Steering angle
    is_steering = any(x in name_lower for x in ['steering', 'steer', 'wheel_angle', 'st_angle'])

    if is_percentage:
        min_val = max(0.0, enc_min)
        max_val = min(100.0, enc_max)
        if 'brake' in name_lower or 'brk' in name_lower:
            val = min_val + (max_val - min_val) * (brake_pct / 100.0)
        else:
            val = min_val + (max_val - min_val) * (accel_pct / 100.0)

    elif is_kph_speed:
        val = speed_kmh

    elif is_rpm:
        val = speed_to_erpm(speed_kmh) / 4

    elif is_erpm:
        val = speed_to_erpm(speed_kmh)

    elif is_pressure:
        min_val, max_val = band('brake_pressure' if 'brake' in name_lower or 'brk' in name_lower else 'tank_pressure')
        val = min_val + (max_val - min_val) * (brake_pct / 100 if 'brake' in name_lower or 'brk' in name_lower else .9)

    elif is_temp_batt or is_temp_inv or is_temp_motor or is_temp_other:
        # Temperature rises slowly with speed/RPM. Battery, inverter and motor
        # each run at a different realistic band.
        category = ('battery_temperature' if is_temp_batt else 'motor_temperature' if is_temp_motor
                    else 'inverter_temperature' if is_temp_inv else 'other_temperature')
        min_val, max_val = band(category)
        val = min_val + (max_val - min_val) * (0.35 + 0.45 * speed_factor + 0.1 * math.sin(t * 0.02))

    elif is_lap:
        # Lap counter — cycles 1 through 4, incrementing once per drive cycle.
        lap_min = max(1.0, enc_min)
        lap_max = min(4.0, enc_max)
        if lap_max <= lap_min:
            lap_min, lap_max = enc_min, enc_max
        num_laps = int(lap_max - lap_min) + 1
        val = lap_min + (int(t // config['drive_cycle'][-1][0]) % num_laps)

    elif is_current:
        min_val, max_val = band('current')
        val = min_val * brake_pct / 100 if brake_pct else max_val * accel_pct / 100

    elif is_cell_volt:
        # Single Li-ion cell (or per-cell module stat) — small per-cell
        # spread via a name-hashed phase so the 12+ cells in a module don't
        # all report the identical value, sagging slightly under load.
        phase = (hash(signal.name) % 100) / 100.0
        min_val, max_val = band('cell_voltage')
        base = max_val - (max_val - min_val) * (0.05 + 0.1 * (accel_pct / 100.0))
        val = base - (max_val - min_val) * 0.05 * phase
        val += random.uniform(-0.01, 0.01) * (max_val - min_val)

    elif is_module_volt_sum:
        # Sum of a 12s cell module
        cell_min, cell_max = config['ranges']['cell_voltage']
        min_val, max_val = _clamp(cell_min * 12, enc_min, enc_max), _clamp(cell_max * 12, enc_min, enc_max)
        val = max_val - (max_val - min_val) * (0.1 + 0.1 * (accel_pct / 100.0))
        val += random.uniform(-0.005, 0.005) * (max_val - min_val)

    elif is_lv_volt:
        min_val, max_val = band('lv_voltage')
        val = max_val - (max_val - min_val) * (0.1 + 0.1 * (accel_pct / 100.0))
        val += random.uniform(-0.005, 0.005) * (max_val - min_val)

    elif is_pack_volt:
        # HV accumulator / DC bus — sags slightly under high acceleration
        min_val, max_val = band('pack_voltage')
        val = max_val - (max_val - min_val) * (0.1 + 0.1 * (accel_pct / 100.0))
        val += random.uniform(-0.005, 0.005) * (max_val - min_val)

    elif is_steering:
        # Steering is centered at 0 or mid-point, and turns positive/negative
        min_val, max_val = band('steering_rad')
        val = (min_val + max_val) / 2 + (max_val - min_val) / 2 * steer_factor
        
    else:
        # Default fallback: slow sine wave matching the signal's range
        mid = (enc_min + enc_max) / 2.0
        half = (enc_max - enc_min) / 2.0
        phase = hash(signal.name) % 100 / 100.0 * 2 * math.pi
        val = mid + half * 0.8 * math.sin(t * 0.5 + phase)
        val += random.uniform(-half * 0.05, half * 0.05)

    return _clamp(val, enc_min, enc_max)


# ---------------------------------------------------------------------------
# ROS 2 Node
# ---------------------------------------------------------------------------

class CanSimulatorNode(Node):
    def __init__(self):
        super().__init__('can_simulator')
        self._config = load_config()

        self.declare_parameter('can_interface', 'vcan0')
        self.declare_parameter('dbc_path', '')
        self.declare_parameter('publish_hz', 10.0)
        self.declare_parameter('enabled', True)
        self.declare_parameter('signal_controls', '{}')
        self.declare_parameter('message_intervals_ms', '{}')
        self.declare_parameter('message_ids', rclpy.parameter.Parameter.Type.INTEGER_ARRAY)
        # Manual override for Mission_select (see test_data_ros2.sh) — raw
        # 3-bit value, 0-7, no DBC-defined labels. Change live with:
        #   ros2 param set /can_simulator mission_select_value <0-7>
        self.declare_parameter('mission_select_value', 0.0)
        # Manual override for AS_MISSION — the dashboard falls back to this
        # signal when Mission_select is 0. Change live with:
        #   ros2 param set /can_simulator as_mission_value <0-7>
        self.declare_parameter('as_mission_value', 0.0)
        # Manual override for Master_PreCharge precharge_state. -1 keeps the
        # normal generated value. Setting 19 starts the dashboard test sequence
        # RX_CAN -> START -> ... -> HV_ON, advancing every 0.5 seconds.
        self.declare_parameter('precharge_state_value', -1.0)

        iface = self.get_parameter('can_interface').value
        dbc_path = self.get_parameter('dbc_path').value
        hz = self.get_parameter('publish_hz').value

        try:
            ids_param = self.get_parameter('message_ids').value
            _filter_ids = set(ids_param) if ids_param else set()
        except Exception:
            _filter_ids = set()

        # --- Setup vcan ---
        if not setup_vcan(iface, logger=self.get_logger()):
            self.get_logger().fatal(
                f'Cannot set up virtual CAN interface "{iface}". '
                'Make sure you have sudo rights and the vcan module is available.'
            )
            raise RuntimeError(f'vcan setup failed for {iface}')

        # --- Load DBC ---
        if not dbc_path:
            self.get_logger().fatal('Parameter "dbc_path" is empty. Cannot simulate without a DBC file.')
            raise RuntimeError('dbc_path parameter is required for can_simulator')

        import glob
        import os
        self._db = None
        if os.path.isdir(dbc_path):
            self.get_logger().info(f'Loading all DBC files from directory: {dbc_path}')
            dbc_files = sorted(glob.glob(os.path.join(dbc_path, '*.dbc')))
        else:
            self.get_logger().info(f'Loading single DBC file: {dbc_path}')
            dbc_files = [dbc_path]

        for df in dbc_files:
            try:
                if self._db is None:
                    self._db = cantools.database.load_file(df)
                else:
                    self._db.add_dbc_file(df)
                self.get_logger().info(f'  Loaded DBC: {os.path.basename(df)}')
            except Exception as exc:
                self.get_logger().error(f'Failed to load DBC file "{df}": {exc}')

        if self._db is None:
            self._db = cantools.database.Database()

        # Filter messages: skip extended frames >0x7FF if they overflow SocketCAN
        # (cantools may include 29-bit IDs > 0x7FF which are valid extended frames)
        self._messages = [
            m for m in self._db.messages
            if (not _filter_ids or m.frame_id in _filter_ids)
            and m.frame_id <= 0x1FFFFFFF  # valid CAN extended ID upper bound
        ]

        if not self._messages:
            self.get_logger().warn('No simulatable messages found in DBC after filtering.')

        self.get_logger().info(
            f'Simulating {len(self._messages)} DBC messages on {iface} at {hz:.1f} Hz'
        )
        for m in self._messages:
            self.get_logger().info(
                f'  0x{m.frame_id:03X} ({m.frame_id:>5d})  {m.name}  '
                f'[{len(m.signals)} signal(s)]'
            )

        # --- Open CAN bus ---
        try:
            self._bus = can.interface.Bus(channel=iface, interface='socketcan')
        except Exception as exc:
            self.get_logger().fatal(f'Cannot open SocketCAN bus "{iface}": {exc}')
            raise

        # --- Pre-compute multiplexer info for each message ---
        self._msg_mux_valid_ids = {}
        for m in self._messages:
            mux_valid_ids = {}
            for sig in m.signals:
                if getattr(sig, 'is_multiplexer', False):
                    valid_ids = set()
                    for other_sig in m.signals:
                        if getattr(other_sig, 'multiplexer_signal', None) == sig.name and other_sig.multiplexer_ids:
                            valid_ids.update(other_sig.multiplexer_ids)
                    if valid_ids:
                        mux_valid_ids[sig.name] = sorted(list(valid_ids))
            if mux_valid_ids:
                self._msg_mux_valid_ids[m.name] = mux_valid_ids

        self._controls = ControlConfig(self._messages)
        self._signal_controls, intervals = self._controls.validate(
            self.get_parameter('signal_controls').value,
            self.get_parameter('message_intervals_ms').value, hz)
        self._schedule = MessageSchedule([m.name for m in self._messages], 1000 / hz, intervals)
        self._t = 0.0
        self.add_on_set_parameters_callback(self._validate_parameters)
        self._precharge_sequence = _PrechargeSequence()
        self.add_post_set_parameters_callback(self._on_parameters_set)

        self._timer = self.create_timer(tick_period(1000 / hz, intervals), self._tick)
        self.get_logger().info('CAN simulator running — sending frames to ' + iface)

    # -----------------------------------------------------------------------

    def _validate_parameters(self, parameters):
        values = {p.name: p.value for p in parameters}
        try:
            if any(name in values for name in ('can_interface', 'dbc_path', 'message_ids')):
                raise ValueError('Interface, DBC and message filter require restarting the simulator')
            if 'enabled' in values and not isinstance(values['enabled'], bool):
                raise ValueError('enabled must be boolean')
            self._controls.validate(
                values.get('signal_controls', self.get_parameter('signal_controls').value),
                values.get('message_intervals_ms', self.get_parameter('message_intervals_ms').value),
                values.get('publish_hz', self.get_parameter('publish_hz').value))
        except (ValueError, TypeError) as exc:
            return SetParametersResult(successful=False, reason=str(exc))
        return SetParametersResult(successful=True)

    def _on_parameters_set(self, parameters) -> None:
        names = {p.name for p in parameters}
        if names & {'publish_hz', 'signal_controls', 'message_intervals_ms'}:
            hz = self.get_parameter('publish_hz').value
            self._signal_controls, intervals = self._controls.validate(
                self.get_parameter('signal_controls').value,
                self.get_parameter('message_intervals_ms').value, hz)
            self._schedule.default_ms = 1000 / hz
            self._schedule.intervals = intervals
            if names & {'publish_hz', 'message_intervals_ms'}:
                self._schedule.deadlines = dict.fromkeys(self._schedule.names, self._schedule.elapsed)
                self.destroy_timer(self._timer)
                self._timer = self.create_timer(tick_period(1000 / hz, intervals), self._tick)
        if 'enabled' in names:
            self._schedule.previous = time.monotonic()
            self._schedule.was_enabled = self.get_parameter('enabled').value
        # Rearm immediately after an accepted request, even when -1 -> 19
        # happens between CAN ticks or 19 is requested again directly.
        if any(parameter.name == 'precharge_state_value' for parameter in parameters):
            self._precharge_sequence.reset()

    def _tick(self) -> None:
        due = set(self._schedule.advance(time.monotonic(), self.get_parameter('enabled').value))
        self._t = self._schedule.elapsed
        if not due:
            return

        for dbc_msg in self._messages:
            if dbc_msg.name not in due:
                continue
            # Build signal values dict
            signals: dict[str, float] = {}

            # Get pre-computed multiplexer IDs for this message
            mux_valid_ids = self._msg_mux_valid_ids.get(dbc_msg.name, {})

            for sig in dbc_msg.signals:
                override = control_value(sig, self._signal_controls.get(dbc_msg.name, {}).get(sig.name, {}), self._t)
                if override is not None:
                    signals[sig.name] = override
                elif sig.name in mux_valid_ids:
                    # Cycle through the valid multiplexer IDs based on t
                    valid_list = mux_valid_ids[sig.name]
                    idx = int(self._t * 0.5) % len(valid_list)
                    signals[sig.name] = float(valid_list[idx])
                elif sig.name == 'Mission_select':
                    mission_val = self.get_parameter('mission_select_value').value
                    signals[sig.name] = _make_signal_value(sig, self._t, mission_override=mission_val, config=self._config)
                elif sig.name == 'AS_MISSION':
                    as_mission_val = self.get_parameter('as_mission_value').value
                    signals[sig.name] = _make_signal_value(sig, self._t, mission_override=as_mission_val, config=self._config)
                elif sig.name == 'precharge_state':
                    precharge_val = self.get_parameter('precharge_state_value').value
                    precharge_val = self._precharge_sequence.value(precharge_val, self._t)

                    if precharge_val >= 0.0:
                        enc_min, enc_max = _encodable_range(sig)
                        signals[sig.name] = _clamp(precharge_val, enc_min, enc_max)
                    else:
                        signals[sig.name] = _make_signal_value(sig, self._t, config=self._config)
                else:
                    signals[sig.name] = _make_signal_value(sig, self._t, config=self._config)

            # Encode to bytes using cantools.
            # scaling=True  → values are physical (scale+offset applied automatically).
            # padding=True  → zero-pad frames whose signals don't fill all bytes.
            try:
                data = dbc_msg.encode(
                    signals, scaling=True, padding=True, strict=False
                )
            except Exception as exc:
                self.get_logger().warn(
                    f'Encode error for 0x{dbc_msg.frame_id:03X} ({dbc_msg.name}): {exc}'
                )
                continue

            # Extended DBC frames may also have IDs below 0x7FF.
            is_extended = dbc_msg.is_extended_frame

            frame = can.Message(
                arbitration_id=dbc_msg.frame_id,
                data=data,
                is_extended_id=is_extended,
                timestamp=time.time(),
            )

            try:
                self._bus.send(frame)
            except Exception as exc:
                self.get_logger().warn(f'CAN send error: {exc}')

    # -----------------------------------------------------------------------

    def destroy_node(self):
        self._bus.shutdown()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CanSimulatorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
