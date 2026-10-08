"""Exercise the local launcher without ROS processes or a display."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_local_launcher_leaves_simulator_to_panel_and_requests_minimized_window(tmp_path):
    project = tmp_path / 'LART_Car_Dashboard_v1'
    project.mkdir()
    script = project / 'start_local.sh'
    script.write_text((ROOT / 'LART_Car_Dashboard_v1/start_local.sh').read_text())
    binary = project / 'build/ui-build/ui_runner'
    binary.parent.mkdir(parents=True)
    binary.write_text('#!/bin/bash\nprintf "%s" "${LART_UI_START_MINIMIZED:-unset}" > "$TEST_WINDOW_FLAG"\n')
    binary.chmod(0o755)
    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    ros2 = fake_bin / 'ros2'
    ros2.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$TEST_ROS_CALLS"\n')
    ros2.chmod(0o755)
    env = {**os.environ, 'PATH': f'{fake_bin}:{os.environ["PATH"]}',
           'TEST_WINDOW_FLAG': str(tmp_path / 'flag'), 'TEST_ROS_CALLS': str(tmp_path / 'ros_calls')}
    result = subprocess.run(['bash', str(script)], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / 'flag').read_text() == '1'
    assert not (tmp_path / 'ros_calls').exists()
