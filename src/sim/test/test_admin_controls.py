"""Focused checks for admin controls: python -m unittest discover -s src/sim/test."""
import json
import math
from pathlib import Path
import unittest

import cantools
from sim import admin_controls as controls


class AdminControlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[3]
        cls.db = cantools.database.load_file(root / 'dbc_signals/autonomous_t26.dbc')
        cls.message = cls.db.get_message_by_name('DV_dynamics_1')
        cls.signal = cls.message.get_signal_by_name('Speed_actual')
        cls.config = controls.ControlConfig(cls.db.messages)

    def test_fixed_sweep_random_and_auto(self):
        for mode in ('fixed', 'sweep', 'random', 'auto'):
            settings = {'mode': mode, 'value': 30, 'min': 10, 'max': 40, 'period': 2}
            parsed = self.config.validate(json.dumps({'DV_dynamics_1': {'Speed_actual': settings}}), '{}', 10)
            control = parsed[0]['DV_dynamics_1']['Speed_actual']
            value = controls.control_value(self.signal, control, 1)
            if mode == 'fixed':
                self.assertEqual(value, 30)
            elif mode == 'sweep':
                self.assertEqual(value, 40)
                self.assertEqual(controls.control_value(self.signal, control, 0), 10)
                self.assertEqual(controls.control_value(self.signal, control, 2), 10)
            elif mode == 'random':
                self.assertTrue(10 <= value <= 40)
            else:
                self.assertIsNone(value)

    def test_invalid_updates_rejected(self):
        for setting in ({'mode': 'fixed', 'value': 256}, {'mode': 'fixed', 'value': float('nan')},
                        {'mode': 'sweep', 'min': 40, 'max': 10, 'period': 2},
                        {'mode': 'sweep', 'min': 0, 'max': 20, 'period': 0}, {'mode': 'bad'}):
            with self.assertRaises(ValueError):
                self.config.validate(json.dumps({'DV_dynamics_1': {'Speed_actual': setting}}), '{}', 10)
        for hz in (0, -1, float('inf'), 1001):
            with self.assertRaises(ValueError):
                self.config.validate('{}', '{}', hz)
        with self.assertRaises(ValueError):
            self.config.validate('{}', '{"DV_dynamics_1": 0.5}', 10)
        with self.assertRaises(ValueError):
            self.config.validate('{"unknown": {}}', '{}', 10)

    def test_integer_range_stays_inside_requested_bounds(self):
        settings = {'mode': 'random', 'min': 10.1, 'max': 11.9}
        parsed, _ = self.config.validate(json.dumps({'DV_dynamics_1': {'Speed_actual': settings}}), '{}', 10)
        values = [controls.control_value(self.signal, parsed['DV_dynamics_1']['Speed_actual'], 0) for _ in range(100)]
        self.assertTrue(all(10.1 <= v <= 11.9 for v in values))
        with self.assertRaises(ValueError):
            self.config.validate(json.dumps({'DV_dynamics_1': {'Speed_actual': {'mode': 'random', 'min': 10.1, 'max': 10.2}}}), '{}', 10)

    def test_speed_conversion_round_trip(self):
        for speed in (0, 30, 100, 120):
            erpm = controls.speed_to_erpm(speed)
            actual = erpm / 4 / 14.73 * (2 * math.pi * .2032) * 60 / 1000
            self.assertAlmostEqual(actual, speed)

    def test_script_sequences(self):
        self.assertEqual(controls.scenario_values('City'), [10, 15, 20, 25, 30, 25, 20, 15, 10])
        self.assertEqual(controls.scenario_values('Acceleration'), list(range(0, 101, 10)))
        self.assertEqual(controls.scenario_values('Deceleration'), list(range(100, -1, -10)))
        self.assertEqual(len(controls.scenario_values('Highway')), 35)
        self.assertEqual(len(controls.scenario_values('Random')), 40)

    def test_timer_handles_non_multiple_message_intervals(self):
        self.assertEqual(controls.tick_period(100, {'b': 150}), .05)
        self.assertGreaterEqual(controls.tick_period(1000 / 7, {'b': 150}), .001)

    def test_deadlines_pause_and_no_burst(self):
        clock = controls.MessageSchedule(['a', 'b'], 100, {'b': 200})
        self.assertEqual(clock.advance(0, True), ['a', 'b'])
        self.assertEqual(clock.advance(.1, True), ['a'])
        self.assertEqual(clock.advance(10, False), [])
        self.assertEqual(clock.advance(10.1, True), [])
        self.assertEqual(clock.advance(10.2, True), ['a', 'b'])
        self.assertEqual(clock.advance(20, True), ['a', 'b'])
        self.assertEqual(clock.advance(20, True), [])


if __name__ == '__main__':
    unittest.main()
