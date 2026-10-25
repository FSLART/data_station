#!/usr/bin/env bash
# One command to start the Qt runtime stack, from a git checkout or an extracted release bundle.
# Installs missing dependencies, builds once if needed, and on a machine without the CAN HAT
# starts the DBC simulators and admin panel on virtual CAN. Extra arguments go to car.launch.py.
set -eo pipefail

WS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WS_DIR"

# Root cannot see the pip --user packages (cantools, PySide6); sudo is used below only where needed.
if [[ $EUID -eq 0 ]]; then
    echo "Run without sudo: bash scripts/run_runtime.sh" >&2
    exit 1
fi

if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
    echo "ROS 2 Jazzy is required: https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html" >&2
    exit 1
fi

APT_PACKAGES=(ros-jazzy-rosbag2-storage-mcap libegl1 libopengl0 libxkbcommon0
              libxcb-cursor0 libxkbcommon-x11-0 fonts-dejavu-core can-utils)
missing=()
for package in "${APT_PACKAGES[@]}"; do
    dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "ok installed" || missing+=("$package")
done
if (( ${#missing[@]} )); then
    echo "Installing system packages: ${missing[*]}"
    sudo apt-get install -y "${missing[@]}"
fi

if ! python3 -c "import cantools, can, PySide6" 2>/dev/null; then
    echo "Installing Python packages from requirements-runtime.txt"
    python3 -m pip install --user --break-system-packages -r requirements-runtime.txt
fi

# A release bundle ships install/; a fresh checkout builds it once.
if [[ ! -f install/setup.bash ]]; then
    git submodule update --init src/lart_msgs
    (source /opt/ros/jazzy/setup.bash && colcon build --base-paths src \
        --packages-up-to data_station_runtime input_handler led_controller sim \
        --parallel-workers 2)
fi

# A real CAN HAT shows "can state" in the link details; a vcan or missing can0 means desktop bench.
if ip -d link show can0 2>/dev/null | grep -q "can state"; then
    for pair in can0:1000000 can1:500000; do
        iface="${pair%%:*}"
        if ! ip link show "$iface" | grep -q '[<,]UP[,>]'; then  # vcan reports "state UNKNOWN" even when up
            sudo ip link set "$iface" up type can bitrate "${pair##*:}"
        fi
    done
    exec bash scripts/start_runtime.sh "$@"
fi

# The Pi release bundle ships no simulator; it is built from source on dev PCs only.
if [[ ! -d install/sim ]]; then
    echo "No CAN HAT on can0 and no simulator installed. Check the HAT, or build sim on a dev PC." >&2
    exit 1
fi
echo "No CAN HAT found: starting the simulators and admin panel on virtual CAN."
for iface in can0 can1 vcan_auto; do
    if ! ip link show "$iface" 2>/dev/null | grep -q '[<,]UP[,>]'; then
        bash scripts/setup_vcan_interfaces.sh "$iface"
    fi
done
export DATA_STATION_WS="$WS_DIR"  # admin panel finds config/can_simulator.cfg here
exec bash scripts/start_runtime.sh sim:=true hardware_io:=false "$@"
