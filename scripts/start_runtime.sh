#!/usr/bin/env bash
# The launcher owns all processes; closing the UI cannot stop acquisition or recording.
set -eo pipefail

WS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f /opt/ros/jazzy/setup.bash ]]; then
    source /opt/ros/jazzy/setup.bash
elif [[ -f "$HOME/ros2_jazzy/install/setup.bash" ]]; then
    source "$HOME/ros2_jazzy/install/setup.bash"
else
    echo "ROS Jazzy setup not found." >&2
    exit 1
fi
source "$WS_DIR/install/setup.bash"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [[ -z "${WAYLAND_DISPLAY:-}" ]]; then
    export DISPLAY="${DISPLAY:-:0}"
fi
plymouth quit 2>/dev/null || true
exec ros2 launch data_station_runtime car.launch.py dbc_dir:="$WS_DIR/dbc_signals" "$@"
