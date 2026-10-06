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


if __name__ == '__main__':
    unittest.main()
