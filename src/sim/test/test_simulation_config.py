import json
from pathlib import Path
import tempfile
import unittest

import cantools
from sim.simulation_config import driving_state, load_config, save_config
from sim.admin_controls import speed_to_erpm
from sim.can_simulator import _make_signal_value

ROOT = Path(__file__).resolve().parents[3]


class SimulationConfigTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / 'config/can_simulator.cfg')
        self.db = cantools.database.load_file(ROOT / 'dbc_signals/powertrain_t26.dbc')

    def test_save_round_trip_and_invalid_config_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.cfg'
            self.config['simulators']['/example'] = {'signal_controls': {'msg': {'sig': {'mode': 'random', 'min': 10, 'max': 20}}}}
            save_config(self.config, path)
            self.assertEqual(load_config(path), self.config)
            self.config['ranges']['speed_kmh'] = [80, 0]
            path.write_text(json.dumps(self.config))
            with self.assertRaises(ValueError):
                load_config(path)

    def test_drive_cycle_starts_stops_and_has_no_wrap_jump(self):
        for seconds in (0, 2, 70, 79, 80):
            self.assertEqual(driving_state(self.config, seconds), (0, 0, 0))
        self.assertGreater(driving_state(self.config, 10)[1], 0)
        self.assertEqual(driving_state(self.config, 20)[0], .5)
        self.assertGreater(driving_state(self.config, 60)[2], 0)

    def test_erpm_matches_speed_and_faults_stay_zero(self):
        erpm = self.db.get_message_by_name('INV1_ERPM_DUTY_VOLTAGE').get_signal_by_name('INV1_Actual_ERPM')
        fault = self.db.get_message_by_name('INV1_Temperatures').get_signal_by_name('INV1_Actual_FaultCode')
        for seconds in (0, 10, 20, 50, 65, 79):
            fraction = driving_state(self.config, seconds)[0]
            self.assertAlmostEqual(_make_signal_value(erpm, seconds, config=self.config), speed_to_erpm(80 * fraction))
            self.assertEqual(_make_signal_value(fault, seconds, config=self.config), 0)

    def test_custom_temperature_band_used_and_encodable(self):
        sig = self.db.get_message_by_name('INV1_Temperatures').get_signal_by_name('INV1_Actual_TempMotor')
        self.config['ranges']['motor_temperature'] = [50, 60]
        for seconds in range(80):
            value = _make_signal_value(sig, seconds, config=self.config)
            self.assertTrue(50 <= value <= 60)

    def test_inverter_limit_flags_stay_off_during_normal_driving(self):
        for name in ('INV1_MISC', 'INV2_MISC'):
            msg = self.db.get_message_by_name(name)
            flags = [sig.name for sig in msg.signals if sig.name.lower().endswith('_limit')]
            self.assertTrue(flags)
            for seconds in (0, 10, 20, 50, 65, 79):
                values = {sig.name: _make_signal_value(sig, seconds, config=self.config) for sig in msg.signals}
                decoded = msg.decode(msg.encode(values), decode_choices=False)
                for flag in flags:
                    self.assertEqual(decoded[flag], 0, f'{name}/{flag} at {seconds}s')

    def test_failed_save_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.cfg'
            save_config(self.config, path)
            prior = path.read_text()
            self.config['ranges']['speed_kmh'][1] = float('nan')
            with self.assertRaises(ValueError):
                save_config(self.config, path)
            self.assertEqual(path.read_text(), prior)

    def test_ivt_units_and_can_encoding_for_driving_phases(self):
        for seconds in (0, 10, 20, 50, 65, 79):
            decoded = {}
            for name in ('IVT_Msg_Result_U1', 'IVT_Msg_Result_U3', 'IVT_Msg_Result_I', 'INV1_ERPM_DUTY_VOLTAGE'):
                msg = self.db.get_message_by_name(name)
                values = {sig.name: _make_signal_value(sig, seconds, config=self.config) for sig in msg.signals}
                decoded.update(msg.decode(msg.encode(values), decode_choices=False))
            self.assertTrue(500_000 <= decoded['IVT_Result_U1'] <= 600_000)
            self.assertTrue(24_000 <= decoded['IVT_Result_U3'] <= 28_000)
            self.assertTrue(-40_000 <= decoded['IVT_Result_I'] <= 180_000)
            if seconds in (0, 79):
                self.assertEqual(decoded['INV1_Actual_ERPM'], 0)
