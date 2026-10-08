"""DBC validation and simulation controls, independent of ROS and Tk."""
import json
import math
import random


def encodable_range(signal):
    if signal.is_float:
        return (signal.minimum if signal.minimum is not None else -1e30,
                signal.maximum if signal.maximum is not None else 1e30)
    low = -(2 ** (signal.length - 1)) if signal.is_signed else 0
    high = 2 ** (signal.length - (1 if signal.is_signed else 0)) - 1
    ends = [signal.conversion.raw_to_scaled(x, decode_choices=False) for x in (low, high)]
    return (max(min(ends), signal.minimum) if signal.minimum is not None else min(ends),
            min(max(ends), signal.maximum) if signal.maximum is not None else max(ends))


def quantize(signal, value):
    raw = signal.conversion.numeric_scaled_to_raw(value)
    return float(signal.conversion.raw_to_scaled(raw, decode_choices=False))


def discrete_values(signal, message=None):
    if signal.is_multiplexer and message is not None:
        raw = sorted({i for s in message.signals if s.multiplexer_signal == signal.name
                      for i in (s.multiplexer_ids or [])})
    else:
        raw = sorted(signal.choices or {})
    return [float(signal.conversion.raw_to_scaled(x, decode_choices=False)) for x in raw]


def finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    return float(value)


class ControlConfig:
    def __init__(self, messages):
        self.messages = {m.name: m for m in messages}

    def validate(self, signals_json, intervals_json, hz):
        hz = finite(hz, 'Frequency')
        if not 0 < hz <= 1000:
            raise ValueError('Frequency must be > 0 and <= 1000 Hz')
        try:
            signals = json.loads(signals_json)
            intervals = json.loads(intervals_json)
        except (ValueError, TypeError) as exc:
            raise ValueError(f'Invalid control JSON: {exc}') from exc
        if not isinstance(signals, dict) or not isinstance(intervals, dict):
            raise ValueError('Controls and intervals must be JSON objects')
        for name, interval in intervals.items():
            if name not in self.messages:
                raise ValueError(f'Unknown message: {name}')
            if finite(interval, 'Interval') < 1:
                raise ValueError('Message interval must be at least 1 ms')
        for name, entries in signals.items():
            if name not in self.messages or not isinstance(entries, dict):
                raise ValueError(f'Unknown message or invalid controls: {name}')
            message = self.messages[name]
            for signal_name, control in entries.items():
                try:
                    signal = message.get_signal_by_name(signal_name)
                except KeyError as exc:
                    raise ValueError(f'Unknown signal: {name}/{signal_name}') from exc
                if not isinstance(control, dict):
                    raise ValueError('Signal control must be an object')
                mode = control.get('mode', 'auto')
                if mode not in ('auto', 'fixed', 'sweep', 'random'):
                    raise ValueError(f'Unknown mode: {mode}')
                if mode == 'auto':
                    continue
                low, high = encodable_range(signal)
                allowed = discrete_values(signal, message)
                values = [finite(control.get('value'), 'Value')] if mode == 'fixed' else [
                    finite(control.get('min'), 'Minimum'), finite(control.get('max'), 'Maximum')]
                if any(x < low or x > high or not low <= quantize(signal, x) <= high for x in values):
                    raise ValueError(f'{name}/{signal_name} must be within [{low}, {high}]')
                if mode == 'fixed' and allowed and quantize(signal, values[0]) not in allowed:
                    raise ValueError(f'Allowed values: {allowed}')
                if mode in ('sweep', 'random'):
                    if values[0] > values[1]:
                        raise ValueError('Minimum must not exceed maximum')
                    if not signal.is_float and not allowed:
                        raw_ends = [(v - signal.offset) / signal.scale for v in values]
                        first = math.ceil(min(raw_ends) - 1e-9)
                        last = math.floor(max(raw_ends) + 1e-9)
                        if first > last:
                            raise ValueError('Range contains no encodable values')
                        ends = [signal.conversion.raw_to_scaled(v, decode_choices=False) for v in (first, last)]
                        control = {**control, '_min': min(ends), '_max': max(ends)}
                        entries[signal_name] = control
                    if mode == 'sweep':
                        if allowed or signal.is_multiplexer:
                            raise ValueError('Discrete signals support Fixed or Random, not Sweep')
                        if finite(control.get('period'), 'Sweep duration') <= 0:
                            raise ValueError('Sweep duration must be positive')
                    if mode == 'random' and allowed:
                        choices = [v for v in allowed if values[0] <= v <= values[1]]
                        if not choices:
                            raise ValueError('Range contains no valid choices')
                        control = {**control, '_choices': choices}
                        entries[signal_name] = control
        return signals, intervals


def control_value(signal, control, elapsed):
    mode = control.get('mode', 'auto')
    if mode == 'auto':
        return None
    low, high = control.get('_min', control.get('min')), control.get('_max', control.get('max'))
    if mode == 'fixed':
        value = control['value']
    elif mode == 'random':
        value = random.choice(control['_choices']) if control.get('_choices') else random.uniform(low, high)
    else:
        phase = (elapsed % control['period']) / control['period']
        value = low + (high - low) * (1 - abs(2 * phase - 1))
    return quantize(signal, value)


def tick_period(default_ms, intervals):
    # A 100 ms and a 150 ms message need 50 ms ticks, not 100 ms ticks.
    # ponytail: 1 ms scheduler resolution; use individual deadline timers below 1 ms.
    nanoseconds = [round(v * 1_000_000) for v in [default_ms, *intervals.values()]]
    return max(.001, math.gcd(*nanoseconds) / 1_000_000_000)


class MessageSchedule:
    """Simulation time excludes pauses; delayed ticks send each message once."""
    def __init__(self, names, default_ms, intervals):
        self.names = list(names)
        self.default_ms = default_ms
        self.intervals = intervals
        self.deadlines = dict.fromkeys(self.names, 0.0)
        self.elapsed = 0.0
        self.previous = None
        self.was_enabled = True

    def advance(self, now, enabled):
        if self.previous is not None and enabled and self.was_enabled:
            self.elapsed += max(0, now - self.previous)
        self.previous = now
        self.was_enabled = enabled
        if not enabled:
            return []
        due = []
        for name in self.names:
            if self.elapsed + 1e-9 >= self.deadlines[name]:
                due.append(name)
                self.deadlines[name] = self.elapsed + self.intervals.get(name, self.default_ms) / 1000
        return due


def speed_to_erpm(speed):
    return speed * 1000 / (2 * math.pi * .2032 * 60) * 14.73 * 4


def scenario_values(name, custom=0):
    scenarios = {'Idle': [0], 'City': [10, 15, 20, 25, 30, 25, 20, 15, 10],
                 'Highway': [70, 80, 90, 100, 90, 80, 70] * 5,
                 'Acceleration': list(range(0, 101, 10)),
                 'Deceleration': list(range(100, -1, -10)), 'Custom': [custom]}
    if name == 'Random':
        return [random.randint(0, 100) for _ in range(40)]
    return scenarios[name]
