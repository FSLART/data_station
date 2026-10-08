#!/usr/bin/env python3
"""Start the CAN admin panel without manually sourcing ROS."""
import os
from pathlib import Path
import subprocess
import sys


def prepare_can(workspace):
    interfaces = (['vcan_data', 'vcan_pwt', 'vcan_auto']
                  if os.environ.get('DBC_FILE', 'all').lower() == 'all' else ['vcan0'])
    try:
        if all(int((Path('/sys/class/net') / name / 'flags').read_text().strip(), 16) & 1
               for name in interfaces):
            return True
    except OSError:
        pass
    print('Preparing virtual CAN interfaces; sudo may ask for your password.', file=sys.stderr, flush=True)
    try:
        subprocess.run(['bash', str(workspace / 'scripts/setup_vcan_interfaces.sh'), *interfaces], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f'CAN setup failed: {exc}. Admin panel was not started.', file=sys.stderr)
        return False
    return True


def main():
    workspace = Path(__file__).resolve().parent
    ros_setup = Path('/opt/ros/jazzy/setup.bash')
    workspace_setup = workspace / 'install/setup.bash'
    for setup in (ros_setup, workspace_setup):
        if not setup.is_file():
            print(f'Missing setup file: {setup}', file=sys.stderr)
            if setup == workspace_setup:
                print('Build the ROS workspace first with colcon build.', file=sys.stderr)
            return 1
    if not prepare_can(workspace):
        return 1
    os.environ.setdefault('ROS_DOMAIN_ID', '42')
    os.environ.setdefault('DATA_STATION_WS', str(workspace))
    os.chdir(workspace)
    os.execv('/bin/bash', [
        'bash', '--noprofile', '--norc', '-c',
        'source "$1" && source "$2" && exec ros2 run sim admin_panel',
        'start_admin_panel', str(ros_setup), str(workspace_setup),
    ])


if __name__ == '__main__':
    sys.exit(main())
