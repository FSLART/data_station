"""Real simulator encoding/parameter callbacks over python-can's in-memory bus."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import can
import cantools
import rclpy
from rclpy.parameter import Parameter
from sim.can_simulator import CanSimulatorNode

ROOT = Path(__file__).resolve().parents[3]


class SimulatorRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / 'dbc_signals/autonomous_t26.dbc'
        rclpy.init(args=['--ros-args', '-p', f'dbc_path:={cls.path}', '-p', 'message_ids:=[1280]'])

    @classmethod
    def tearDownClass(cls):
        rclpy.try_shutdown()

    def setUp(self):
        channel = self.id()
        sender = can.Bus(interface='virtual', channel=channel)
        self.receiver = can.Bus(interface='virtual', channel=channel)
        with patch('sim.can_simulator.setup_vcan', return_value=True), patch('sim.can_simulator.can.interface.Bus', return_value=sender):
            self.node = CanSimulatorNode()

    def tearDown(self):
        self.node.destroy_node()
        self.receiver.shutdown()

    def set_params(self, **values):
        return self.node.set_parameters_atomically([Parameter(name, value=value) for name, value in values.items()])

    def test_live_override_encodes_frame_and_pause_stops_it(self):
        config = json.dumps({'DV_dynamics_1': {'Speed_actual': {'mode': 'fixed', 'value': 30}}})
        self.assertTrue(self.set_params(signal_controls=config).successful)
        self.node._tick()
        frame = self.receiver.recv(.1)
        self.assertIsNotNone(frame)
        message = self.node._db.get_message_by_frame_id(frame.arbitration_id)
        self.assertEqual(message.decode(frame.data)['Speed_actual'], 30)
        self.assertTrue(self.set_params(enabled=False).successful)
        self.node._tick()
        self.assertIsNone(self.receiver.recv(.01))
        self.assertTrue(self.set_params(enabled=True, publish_hz=20.0).successful)
        self.node._tick()
        self.assertIsNotNone(self.receiver.recv(.1))

    def test_invalid_atomic_update_preserves_all_prior_parameters(self):
        result = self.set_params(enabled=False, publish_hz=0.0)
        self.assertFalse(result.successful)
        self.assertTrue(self.node.get_parameter('enabled').value)
        self.assertEqual(self.node.get_parameter('publish_hz').value, 10.0)

    def test_timing_override_changes_timer_and_can_be_reset(self):
        self.assertTrue(self.set_params(message_intervals_ms='{"DV_dynamics_1": 25}').successful)
        self.assertEqual(self.node._timer.timer_period_ns, 25_000_000)
        self.assertTrue(self.set_params(message_intervals_ms='{}').successful)
        self.assertEqual(self.node._timer.timer_period_ns, 100_000_000)

    def test_error_presets_encode_inverter_fault_and_soc_then_restore(self):
        import queue
        from sim.admin_panel import Backend
        from sim.admin_controls import ControlConfig, MessageSchedule
        db = cantools.database.load_file(ROOT / 'dbc_signals/powertrain_t26.dbc')
        self.node._db = db
        self.node._messages = [db.get_message_by_name(name) for name in
                               ('INV1_Temperatures', 'Master_SOC_Accumulator', 'INV1_MISC', 'INV2_MISC')]
        self.node._controls = ControlConfig(self.node._messages)
        self.node._schedule = MessageSchedule([m.name for m in self.node._messages], 100, {})
        b = Backend.__new__(Backend)
        b.session, b.events = None, queue.Queue()
        b.profiles = {'powertrain': {'db': db, 'validator': ControlConfig(db.messages),
                                    'params': {'dbc_path': 'powertrain_t26.dbc'}}}
        b.read = lambda name, fields: {field: self.node.get_parameter(field).value for field in fields}
        def set_values(name, **values):
            result = self.set_params(**values)
            if not result.successful:
                raise ValueError(result.reason)
        b.set = set_values
        b.fault(['INV1 drivetrain fault', 'Low SOC', 'Thermal derating'], 'CAN simulation')
        self.node._tick()
        values = {}
        for _ in self.node._messages:
            frame = self.receiver.recv(.1)
            self.assertIsNotNone(frame)
            values.update(db.get_message_by_frame_id(frame.arbitration_id).decode(frame.data, decode_choices=False))
        self.assertEqual(values['INV1_Actual_FaultCode'], 1)
        self.assertEqual(values['SOC_Float'], 10)
        for prefix in ('Motor', 'IGBT', 'Capacitor'):
            self.assertEqual(values[f'INV1_{prefix}_temp_limit'], 1)
            self.assertEqual(values[f'INV2_{prefix}_temp_limit'], 0)
        b.end_test()
        self.assertEqual(self.node.get_parameter('signal_controls').value, '{}')
        with patch('sim.can_simulator.time.monotonic', return_value=self.node._schedule.previous + .1):
            self.node._tick()
        for _ in self.node._messages:
            frame = self.receiver.recv(.1)
            self.assertIsNotNone(frame)
            decoded = db.get_message_by_frame_id(frame.arbitration_id).decode(frame.data, decode_choices=False)
            for name, value in decoded.items():
                if name.lower().endswith('_limit'):
                    self.assertEqual(value, 0, name)

    def test_extended_frame_with_low_id_keeps_dbc_frame_type(self):
        from sim.admin_controls import ControlConfig, MessageSchedule
        message = self.node._db.get_message_by_name('CubeMars_position_loop')
        self.node._messages = [message]
        self.node._controls = ControlConfig([message])
        self.node._schedule = MessageSchedule([message.name], 100, {})
        self.node._tick()
        frame = self.receiver.recv(.1)
        self.assertIsNotNone(frame)
        self.assertTrue(frame.is_extended_id)

    def test_bridge_filters_include_extended_dbc_frames(self):
        from lart_bringup.can_bridge import CanBridgeNode
        reader = can.Bus(interface='virtual', channel=self.id())
        with patch('lart_bringup.can_bridge.can.interface.Bus', return_value=reader):
            bridge = CanBridgeNode()
        try:
            message = self.node._db.get_message_by_name('CubeMars_position_loop')
            self.assertIn({'can_id': message.frame_id, 'can_mask': 0x1FFFFFFF, 'extended': True}, reader.filters)
            seen = []
            info = bridge._dbc_pubs[message.frame_id]
            subscription = bridge.create_subscription(info['class'], '/can/cubemars_position_loop', lambda msg: seen.append(msg), rclpy.qos.qos_profile_sensor_data)
            import time
            deadline = time.monotonic() + 3
            while info['pub'].get_subscription_count() == 0 and time.monotonic() < deadline:
                rclpy.spin_once(bridge, timeout_sec=.01)
            payload = message.encode({s.name: 0 for s in message.signals}, strict=False)
            bridge._on_message(can.Message(arbitration_id=message.frame_id, data=payload, is_extended_id=True))
            while not seen and time.monotonic() < deadline:
                rclpy.spin_once(bridge, timeout_sec=.01)
            self.assertTrue(seen, 'Extended CAN frame must reach the current aggregated ROS topic')
        finally:
            bridge.destroy_node()

    def test_multiplexed_control_encodes_only_selected_branch(self):
        db = cantools.database.load_file(ROOT / 'dbc_signals/data_t26.dbc')
        for message in db.messages:
            if not message.is_multiplexed():
                continue
            mux = next(s for s in message.signals if s.is_multiplexer)
            ids = sorted({i for s in message.signals for i in (s.multiplexer_ids or [])})
            self.node._messages = [message]
            from sim.admin_controls import ControlConfig, MessageSchedule
            self.node._controls = ControlConfig([message])
            self.node._schedule = MessageSchedule([message.name], 100, {})
            self.node._msg_mux_valid_ids = {message.name: {mux.name: ids}}
            config = json.dumps({message.name: {mux.name: {'mode': 'fixed', 'value': ids[0]}}})
            self.assertTrue(self.set_params(signal_controls=config).successful)
            self.node._tick()
            frame = self.receiver.recv(.1)
            self.assertIsNotNone(frame, message.name)
            decoded = message.decode(frame.data, decode_choices=False)
            self.assertEqual(decoded[mux.name], ids[0])


if __name__ == '__main__':
    unittest.main()
