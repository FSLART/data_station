#!/bin/bash
# LART Dashboard Local Start Sequence (dev machine, non-Pi)
# Local equivalent of autostart_dashboard.sh — same stages, local paths,
# plus vcan0 setup + DBC simulator (no real CAN hardware on a dev box).

set -e

WS_DIR="/home/sintra/dev/data_station"
PROJECT_DIR="$WS_DIR/LART_Car_Dashboard_v1"

echo "Starting LART Dashboard (local) at $(date)"

# 1. Source ROS 2 Environment
source /opt/ros/jazzy/setup.bash 2>/dev/null || true
source "$WS_DIR/install/setup.bash" 2>/dev/null || true

# 2. Export necessary environment variables
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"

# 3. Setup isolated virtual CAN buses — needs sudo once; idempotent if up
"$WS_DIR/scripts/setup_vcan_interfaces.sh" vcan_data vcan_pwt vcan_auto

# 4. Start the DBC simulation stack in the background
#    (isolated simulators/bridges → /data/*, /pwt/*, /can/*)
echo "Starting DBC simulation stack (can_simulator + can_bridge + dashboard_state_bridge)..."
SIM_NODES="$(ros2 node list)"
if printf '%s\n' "$SIM_NODES" | grep -Eq '^/can_simulator(_(data|powertrain|autonomous))?$'; then
    echo "ERROR: A CAN simulation stack is already running. Stop it before starting another local stack."
    exit 1
fi
setsid ros2 launch lart_bringup dbc_sim.launch.py &
SIM_STACK_PID=$!
echo "DBC simulation stack PID: $SIM_STACK_PID"

# 5. Start the precharge-triggered bag recorder (records /can/* topics
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

# Stop the background stack when this script exits (Ctrl+C, or UI exit below)
cleanup() {
    echo "Shutting down local stack..."
    if [ -n "$SIM_STACK_PID" ]; then
        kill -TERM -- "-$SIM_STACK_PID" 2>/dev/null || true
        wait "$SIM_STACK_PID" 2>/dev/null || true
    fi
    if [ -n "$BAG_RECORDER_PID" ]; then
        kill -INT "$BAG_RECORDER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# 6. Build (if needed) and launch the dashboard UI in the foreground
UI_BIN="$PROJECT_DIR/build/ui-build/ui_runner"
if [ ! -x "$UI_BIN" ]; then
    echo "ui_runner not found – building for the first time (this will take a while)..."
    make -C "$PROJECT_DIR" display-local
else
    echo "ui_runner already built – launching directly."
    "$UI_BIN"
fi
