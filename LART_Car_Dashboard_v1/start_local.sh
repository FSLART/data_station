#!/bin/bash
# LART Dashboard Local Start Sequence (dev machine, non-Pi)
# Local equivalent of autostart_dashboard.sh — same stages, local paths,
# Simulation is owned by the Python admin panel, started separately.

set -e

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(dirname -- "$PROJECT_DIR")"

echo "Starting LART Dashboard (local) at $(date)"

# 1. Source ROS 2 Environment
source /opt/ros/jazzy/setup.bash 2>/dev/null || true
source "$WS_DIR/install/setup.bash" 2>/dev/null || true

# 2. Export necessary environment variables
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"

# 3. Open a normal desktop window minimized; production launches stay fullscreen.
export LART_UI_START_MINIMIZED=1
echo "CAN simulation starts when you open: ros2 run sim admin_panel"

# 4. Start the precharge-triggered bag recorder (records /can/* topics
# to ~/bags while precharge_request is active; see lart_bringup/bag_recorder.py)
BAG_RECORDER_BIN="$WS_DIR/install/lart_bringup/lib/lart_bringup/bag_recorder"
if [ -x "$BAG_RECORDER_BIN" ]; then
    echo "Starting bag_recorder (bags → ~/bags)..."
    "$BAG_RECORDER_BIN" --ros-args --params-file "$WS_DIR/install/lart_bringup/share/lart_bringup/config/rpi_config.yaml" &
    BAG_RECORDER_PID=$!
    echo "bag_recorder PID: $BAG_RECORDER_PID"
else
    echo "WARNING: bag_recorder not found at $BAG_RECORDER_BIN – CAN data will not be recorded."
fi

# Stop the background recorder when this script exits (Ctrl+C, or UI exit below)
cleanup() {
    echo "Shutting down local stack..."
    if [ -n "$BAG_RECORDER_PID" ]; then
        kill -INT "$BAG_RECORDER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# 5. Build (if needed) and launch the dashboard UI in the foreground
UI_BIN="$PROJECT_DIR/build/ui-build/ui_runner"
if [ ! -x "$UI_BIN" ]; then
    echo "ui_runner not found – building for the first time (this will take a while)..."
    make -C "$PROJECT_DIR" display-local
elif [ "$PROJECT_DIR/src/ui/ui_runner.cpp" -nt "$UI_BIN" ]; then
    echo "Dashboard window settings changed – rebuilding UI..."
    make -C "$PROJECT_DIR" run-ui-local
else
    echo "ui_runner already built – launching directly."
    "$UI_BIN"
fi
