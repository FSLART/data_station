"""Shared, editable simulator defaults and persistent panel settings (JSON)."""
import json
import os
from pathlib import Path
import tempfile

from .admin_controls import finite


def config_path():
    workspace = Path(os.environ.get('DATA_STATION_WS', Path(__file__).resolve().parents[3]))
    return Path(os.environ.get('LART_SIM_CONFIG', workspace / 'config/can_simulator.cfg')).expanduser()


def load_config(path=None):
    path = Path(path) if path else config_path()
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError(f'{path}: expected configuration version 1')
    required = {'speed_kmh', 'pack_voltage', 'cell_voltage', 'lv_voltage', 'battery_temperature',
                'inverter_temperature', 'motor_temperature', 'other_temperature', 'current',
                'brake_pressure', 'tank_pressure', 'steering_rad', 'soc_percent'}
    ranges = data.get('ranges')
    if not isinstance(ranges, dict) or required - ranges.keys():
        raise ValueError('Configuration must contain all normal telemetry ranges')
    for name, bounds in ranges.items():
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError(f'{name}: expected [minimum, maximum]')
        if finite(bounds[0], name) > finite(bounds[1], name):
            raise ValueError(f'{name}: minimum exceeds maximum')
    if data['ranges']['speed_kmh'][0] != 0 or data['ranges']['speed_kmh'][1] <= 0:
        raise ValueError('Speed range must start at 0 with a positive maximum')
    points = data.get('drive_cycle')
    if not isinstance(points, list) or len(points) < 2 or any(not isinstance(p, list) or len(p) != 2 for p in points):
        raise ValueError('Drive cycle must contain [seconds, speed_fraction] points')
    if points[0] != [0, 0] or points[-1][1] != 0:
        raise ValueError('Drive cycle must start at [0, 0] and finish stopped')
    previous = -1
    for seconds, fraction in points:
        if finite(seconds, 'Cycle seconds') <= previous or not 0 <= finite(fraction, 'Speed fraction') <= 1:
            raise ValueError('Drive cycle times must increase; speed fractions must be 0–1')
        previous = seconds
    if not isinstance(data.get('simulators', {}), dict):
        raise ValueError('simulators must be an object')
    return data


def save_config(data, path=None):
    path = Path(path) if path else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(data, stream, indent=2, allow_nan=False)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def driving_state(config, elapsed):
    """Continuous speed fraction and correlated pedals; no jump at cycle wrap."""
    points = config['drive_cycle']
    phase = elapsed % points[-1][0]
    for (start, low), (end, high) in zip(points, points[1:]):
        if start <= phase < end:
            fraction = low + (high - low) * (phase - start) / (end - start)
            throttle = 65 if high > low else (20 if fraction > 0 else 0)
            brake = 50 if high < low else 0
            if brake:
                throttle = 0
            return fraction, throttle, brake
