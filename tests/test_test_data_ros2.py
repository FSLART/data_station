import os
from pathlib import Path
import shutil
import subprocess
import signal
import time

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "LART_Car_Dashboard_v1/test_data_ros2.sh"


@pytest.mark.parametrize(
    "nodes,selection,expected",
    [
        ("/can_simulator_data\n/can_simulator_powertrain\n/can_simulator_autonomous", "e\n\n0\n",
         ["/can_simulator_powertrain precharge_state_value -1.0", "/can_simulator_powertrain precharge_state_value 19.0"]),
        ("/can_simulator", "e\n\n0\n",
         ["/can_simulator precharge_state_value -1.0", "/can_simulator precharge_state_value 19.0"]),
        ("/can_simulator_powertrain\n/can_simulator_autonomous", "c\n4\n\n0\n",
         ["/can_simulator_autonomous mission_select_value 4.0"]),
        ("/can_simulator_powertrain\n/can_simulator_autonomous", "d\n3\n\n0\n",
         ["/can_simulator_autonomous as_mission_value 3.0"]),
        ("/can_simulator_powertrain\n/can_simulator_powertrain", "e\n\n0\n", []),
    ],
)
def test_simulator_controls_target_the_correct_bus(tmp_path, nodes, selection, expected):
    # Run the real menu in isolation from installed ROS setups and live simulators.
    script = tmp_path / "test_data_ros2.sh"
    shutil.copyfile(SCRIPT, script)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls"
    ros2 = fake_bin / "ros2"
    ros2.write_text(
        '#!/bin/bash\n'
        'if [[ "$1 $2" == "node list" ]]; then printf "%s\\n" "$TEST_NODES"; exit 0; fi\n'
        'if [[ "$1 $2" == "param set" ]]; then\n'
        '  printf "%s %s %s\\n" "$3" "$4" "$5" >> "$TEST_CALLS"\n'
        '  if ! printf "%s\\n" "$TEST_NODES" | grep -Fxq -- "$3"; then echo "Node not found"; exit 1; fi\n'
        '  echo "Set parameter successful"; exit 0\n'
        'fi\nexit 1\n'
    )
    ros2.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
           "TEST_NODES": nodes, "TEST_CALLS": str(calls)}
    result = subprocess.run(["bash", str(script)], input=selection, text=True,
                            capture_output=True, env=env, timeout=10)
    if not expected:
        assert result.returncode != 0
        assert "Duplicate" in result.stdout + result.stderr
        assert not calls.exists()
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.read_text().splitlines() == expected


def test_menu_cleanup_stops_simulator_children(tmp_path):
    cleanup = SCRIPT.read_text().split("cleanup_background() {", 1)[1].split(
        "trap cleanup_background EXIT", 1
    )[0]
    leader_file = tmp_path / "leader"
    child_file = tmp_path / "child"
    harness = "cleanup_background() {" + cleanup + '''
BAG_RECORD_PID=""
setsid bash -c 'sleep 60 & echo $! > "$1"; wait' _ "$TEST_CHILD" &
CAN_SIM_PID=$!
echo "$CAN_SIM_PID" > "$TEST_LEADER"
while [ ! -s "$TEST_CHILD" ]; do sleep 0.01; done
cleanup_background
wait "$CAN_SIM_PID" 2>/dev/null || true
'''
    try:
        result = subprocess.run(
            ["bash", "-c", harness], capture_output=True, text=True, timeout=5,
            env={**os.environ, "TEST_CHILD": str(child_file), "TEST_LEADER": str(leader_file)},
        )
        assert result.returncode == 0, result.stderr
        child = int(child_file.read_text())
        stat = Path(f"/proc/{child}/stat")
        for _ in range(50):
            if not stat.exists() or stat.read_text().split()[2] == "Z":
                break
            time.sleep(0.01)
        else:
            pytest.fail("Simulator child is still running after menu cleanup")
    finally:
        if leader_file.exists():
            try:
                os.killpg(int(leader_file.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass
