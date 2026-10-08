import importlib.util
import os
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('start_admin_panel', ROOT / 'start_admin_panel.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class AdminLauncherTest(unittest.TestCase):
    def test_sources_absolute_paths_and_preserves_ros_domain(self):
        for domain in (None, '123'):
            with self.subTest(domain=domain), patch.dict(os.environ, {}, clear=True):
                if domain:
                    os.environ['ROS_DOMAIN_ID'] = domain
                with patch.object(Path, 'is_file', return_value=True), \
                        patch.object(launcher, 'prepare_can', return_value=True, create=True), \
                        patch.object(os, 'chdir') as chdir, patch.object(os, 'execv') as execute:
                    launcher.main()
                    chdir.assert_called_once_with(ROOT)
                    binary, args = execute.call_args.args
                    self.assertEqual(binary, '/bin/bash')
                    self.assertIn('exec ros2 run sim admin_panel', args[4])
                    self.assertEqual(args[-2:], ['/opt/ros/jazzy/setup.bash', str(ROOT / 'install/setup.bash')])
                    self.assertEqual(os.environ['ROS_DOMAIN_ID'], domain or '42')

    def test_missing_setup_does_not_launch(self):
        with patch.object(Path, 'is_file', return_value=False), \
                patch.object(os, 'execv') as execute, patch('sys.stderr'):
            self.assertEqual(launcher.main(), 1)
            execute.assert_not_called()

    def test_can_setup_skipped_when_interfaces_are_up(self):
        with patch.object(Path, 'read_text', return_value='0x1'), patch('subprocess.run') as run:
            self.assertTrue(launcher.prepare_can(ROOT))
            run.assert_not_called()

    def test_missing_or_down_can_is_prepared_before_launch(self):
        for dbc, interfaces in [('all', ['vcan_data', 'vcan_pwt', 'vcan_auto']),
                                ('powertrain_t26.dbc', ['vcan0'])]:
            with self.subTest(dbc=dbc), patch.dict(os.environ, {'DBC_FILE': dbc}), \
                    patch.object(Path, 'read_text', return_value='0x0'), \
                    patch('subprocess.run') as run:
                self.assertTrue(launcher.prepare_can(ROOT))
                run.assert_called_once_with(['bash', str(ROOT / 'scripts/setup_vcan_interfaces.sh'), *interfaces], check=True)

    def test_can_setup_failure_does_not_start_panel(self):
        with patch.object(Path, 'is_file', return_value=True), \
                patch.object(Path, 'read_text', side_effect=FileNotFoundError), \
                patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'setup')), \
                patch.object(os, 'execv') as execute, patch('sys.stderr'):
            self.assertEqual(launcher.main(), 1)
            execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
