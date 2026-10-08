import copy
import unittest
from sim import admin_panel


class PanelHelpersTest(unittest.TestCase):
    def test_updates_preserve_unrelated_fields(self):
        from types import SimpleNamespace
        message = SimpleNamespace(inv1_actual_erpm=0, inv1_actual_duty=25, inv1_actual_inputvoltage=550)
        changed = admin_panel.updated_message(message, 'inv1_actual_erpm', 1000)
        self.assertEqual(changed.inv1_actual_erpm, 1000)
        self.assertEqual(changed.inv1_actual_duty, 25)
        self.assertEqual(changed.inv1_actual_inputvoltage, 550)
        self.assertEqual(message.inv1_actual_erpm, 0)

    def test_generated_integer_fields_keep_ros_types(self):
        from lart_msgs.msg import Inv1ErpmDutyVoltage
        message = Inv1ErpmDutyVoltage(inv1_actual_erpm=0, inv1_actual_duty=25.0, inv1_actual_inputvoltage=550)
        changed = admin_panel.updated_message(message, 'inv1_actual_erpm', 1000.0)
        self.assertEqual(changed.inv1_actual_erpm, 1000)
        from rclpy.serialization import serialize_message
        self.assertTrue(serialize_message(changed))
        self.assertEqual(changed.inv1_actual_duty, 25.0)
        self.assertEqual(changed.inv1_actual_inputvoltage, 550)

    def test_duplicate_nodes_rejected(self):
        with self.assertRaises(ValueError):
            admin_panel.simulator_names([('can_simulator_powertrain', '/'), ('can_simulator_powertrain', '/')])
        self.assertEqual(admin_panel.simulator_names([('can_simulator', '/'), ('other', '/')]), ['/can_simulator'])

    def test_field_names_match_bridge(self):
        self.assertEqual(admin_panel.ros_name('INV1_Actual_ERPM'), 'inv1_actual_erpm')
        self.assertEqual(admin_panel.ros_name('DV_dynamics_1'), 'dv_dynamics_1')


class TemporaryControlsTest(unittest.TestCase):
    def setUp(self):
        import cantools
        from pathlib import Path
        from sim.admin_controls import ControlConfig
        import queue
        root = Path(__file__).resolve().parents[3]
        db = cantools.database.load_file(root / 'dbc_signals/powertrain_t26.dbc')
        self.backend = admin_panel.Backend.__new__(admin_panel.Backend)
        self.backend.profiles = {'/can_simulator_powertrain': {'db': db, 'validator': ControlConfig(db.messages),
            'params': {'enabled': False, 'signal_controls': '{}'}}}
        self.backend.session = None
        self.backend.events = queue.Queue()
        self.backend.read = lambda name, fields: {key: self.backend.profiles[name]['params'][key] for key in fields}
        self.backend.set = lambda name, **values: self.backend.profiles[name]['params'].update(values)

    def test_can_scenario_cancel_restores_prior_config_and_pause(self):
        import json
        import time
        backend = self.backend
        backend.scenario('Custom', 30, 500, 'CAN simulation')
        backend.tick_session(time.monotonic())
        config = json.loads(backend.profiles['/can_simulator_powertrain']['params']['signal_controls'])
        self.assertIn('INV1_Actual_ERPM', config['INV1_ERPM_DUTY_VOLTAGE'])
        self.assertTrue(backend.profiles['/can_simulator_powertrain']['params']['enabled'])
        backend.end_test()
        self.assertEqual(backend.profiles['/can_simulator_powertrain']['params'], {'enabled': False, 'signal_controls': '{}'})

    def test_precharge_shortcut_clears_actual_message_override(self):
        import json
        backend = self.backend
        backend.profiles['/can_simulator_powertrain']['params']['signal_controls'] = json.dumps(
            {'Master_PreCharge_ID_1': {'precharge_state': {'mode': 'fixed', 'value': 5}}})
        backend.precharge()
        params = backend.profiles['/can_simulator_powertrain']['params']
        self.assertEqual(params['precharge_state_value'], 19.0)
        self.assertNotIn('precharge_state', json.loads(params['signal_controls'])['Master_PreCharge_ID_1'])

    def test_ranges_and_intervals_reload_without_saving_temporary_scenarios(self):
        import json
        import tempfile
        import time
        from pathlib import Path
        from sim.simulation_config import load_config, save_config
        name = '/can_simulator_powertrain'
        backend = self.backend
        params = backend.profiles[name]['params']
        params.update(dbc_path='powertrain_t26.dbc', message_intervals_ms='{}', publish_hz=10.0)
        with tempfile.TemporaryDirectory() as directory:
            backend.config_file = Path(directory) / 'test.cfg'
            save_config(load_config(), backend.config_file)
            control = {'mode': 'sweep', 'min': 40, 'max': 65, 'period': 60}
            backend.apply(name, 'INV1_Temperatures', 'INV1_Actual_TempMotor', control, 'CAN simulation')
            backend.timing(name, 'INV1_Temperatures', 100, 250)
            saved = backend.config_file.read_text()
            params.update(signal_controls='{}', message_intervals_ms='{}', publish_hz=20.0)
            backend.load_settings(name)
            self.assertEqual(json.loads(params['signal_controls'])['INV1_Temperatures']['INV1_Actual_TempMotor'], control)
            self.assertEqual(json.loads(params['message_intervals_ms'])['INV1_Temperatures'], 250)
            self.assertEqual(params['publish_hz'], 10)
            backend.scenario('Custom', 30, 500, 'CAN simulation')
            backend.tick_session(time.monotonic())
            with self.assertRaises(ValueError):
                backend.save_settings()
            backend.end_test()
            self.assertEqual(backend.config_file.read_text(), saved)

    def test_invalid_saved_range_is_rejected_before_runtime_changes(self):
        import tempfile
        from pathlib import Path
        from sim.simulation_config import load_config, save_config
        name = '/can_simulator_powertrain'
        backend = self.backend
        params = backend.profiles[name]['params']
        params.update(dbc_path='powertrain_t26.dbc', message_intervals_ms='{}', publish_hz=10.0)
        prior = dict(params)
        with tempfile.TemporaryDirectory() as directory:
            backend.config_file = Path(directory) / 'test.cfg'
            data = load_config()
            data['simulators'] = {name: {'dbc_file': 'powertrain_t26.dbc', 'publish_hz': 10,
                'message_intervals_ms': {}, 'signal_controls': {'INV1_Temperatures': {
                    'INV1_Actual_TempMotor': {'mode': 'random', 'min': 60, 'max': 20}}}}}
            save_config(data, backend.config_file)
            with self.assertRaises(ValueError):
                backend.load_settings(name)
            self.assertEqual(params, prior)


if __name__ == '__main__':
    unittest.main()
