import copy
import json
from pathlib import Path
import queue
import unittest

import cantools
from sim.admin_controls import ControlConfig
from sim.admin_panel import Backend
from sim.fault_tests import FAULT_PRESETS


class FaultTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[3]
        self.backend = Backend.__new__(Backend)
        b = self.backend
        b.session, b.events, b.profiles = None, queue.Queue(), {}
        for name in ('data', 'powertrain', 'autonomous'):
            db = cantools.database.load_file(root / f'dbc_signals/{name}_t26.dbc')
            b.profiles[name] = {'db': db, 'validator': ControlConfig(db.messages),
                'params': {'enabled': False, 'signal_controls': '{}', 'dbc_path': f'{name}_t26.dbc'}}
        b.read = lambda name, fields: {k: b.profiles[name]['params'][k] for k in fields}
        b.set = lambda name, **values: b.profiles[name]['params'].update(values)
        self.prior = copy.deepcopy({n: p['params'] for n, p in b.profiles.items()})

    def test_every_preset_is_encodable_and_restores_previous_settings(self):
        for preset in FAULT_PRESETS:
            with self.subTest(preset=preset):
                self.backend.fault([preset], 'CAN simulation')
                self.assertIsNotNone(self.backend.session)
                for profile in self.backend.profiles.values():
                    entries = json.loads(profile['params']['signal_controls'])
                    profile['validator'].validate(json.dumps(entries), '{}', 10)
                    for name, controls in entries.items():
                        msg = profile['db'].get_message_by_name(name)
                        for sig, control in controls.items():
                            raw = msg.get_signal_by_name(sig).conversion.numeric_scaled_to_raw(control['value'])
                            self.assertIsNotNone(raw)
                self.backend.end_test()
                self.assertEqual({n: p['params'] for n, p in self.backend.profiles.items()}, self.prior)

    def test_combined_faults_preserve_unrelated_override_and_block_save(self):
        b = self.backend
        prior = {'INV1_ERPM_DUTY_VOLTAGE': {'INV1_Actual_ERPM': {'mode': 'fixed', 'value': 500}}}
        b.profiles['powertrain']['params']['signal_controls'] = json.dumps(prior)
        b.fault(['Low LV voltage', 'Low SOC', 'Motor overtemperature'], 'CAN simulation')
        entries = json.loads(b.profiles['powertrain']['params']['signal_controls'])
        self.assertEqual(entries['INV1_ERPM_DUTY_VOLTAGE'], prior['INV1_ERPM_DUTY_VOLTAGE'])
        self.assertEqual(entries['Master_SOC_Accumulator']['SOC_Float']['value'], 10)
        with self.assertRaises(ValueError):
            b.save_settings()
        b.end_test()
        self.assertEqual(json.loads(b.profiles['powertrain']['params']['signal_controls']), prior)

    def test_conflicting_or_missing_targets_do_not_change_any_bus(self):
        b = self.backend
        for presets in ([], ['unknown'], ['Motor overtemperature', 'Motor undertemperature']):
            with self.assertRaises(ValueError):
                b.fault(presets, 'CAN simulation')
            self.assertIsNone(b.session)
            self.assertEqual({n: p['params'] for n, p in b.profiles.items()}, self.prior)
        del b.profiles['data']
        with self.assertRaises(ValueError):
            b.fault(['Low LV voltage'], 'CAN simulation')
        self.assertIsNone(b.session)
        self.assertEqual(b.profiles['powertrain']['params'], self.prior['powertrain'])

    def test_failed_apply_rolls_back_earlier_buses(self):
        b = self.backend
        setter = b.set
        def fail(name, **values):
            if name == 'powertrain' and values.get('enabled') is True:
                raise RuntimeError('disconnected')
            setter(name, **values)
        b.set = fail
        with self.assertRaises(RuntimeError):
            b.fault(['Low LV voltage'], 'CAN simulation')
        self.assertIsNone(b.session)
        self.assertEqual({n: p['params'] for n, p in b.profiles.items()}, self.prior)

    def test_direct_ros_uses_existing_preserving_injection(self):
        b = self.backend
        captured = []
        b.begin_direct = lambda targets: captured.extend(targets)
        b.fault(['Low SOC'], 'Direct ROS')
        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0][3], {'mode': 'fixed', 'value': 10})
