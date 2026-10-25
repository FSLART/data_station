# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

LART DataStation: Formula Student dashboard for a Raspberry Pi 5 with a dual-channel CAN HAT. ROS 2 Jazzy, Python nodes, and an LVGL C++ dashboard. `README.md`, `context.md` and `docs/DBC-Update-Guide.md` hold the long-form detail. `context.md` predates the CI workflows and `scripts/regenerate_dbcs.py`, so trust the code and the DBC guide where they disagree.

## Commands

```bash
# Python tests (root tests need cantools; DBC venv mirrors CI)
python3 -m venv /tmp/dbc-venv && /tmp/dbc-venv/bin/pip install -r scripts/requirements-dbc.txt
/tmp/dbc-venv/bin/python -m pytest -q tests
/tmp/dbc-venv/bin/python -m pytest -q tests/test_dbc_decoding.py::<test_name>

# Package tests (need ROS sourced + package paths)
source /opt/ros/jazzy/setup.bash && source install/setup.bash
PYTHONPATH=src/sim:src/lart_bringup:src/led_controller python3 -m pytest -q src/sim/test src/lart_bringup/test src/input_handler/test

# ROS 2 workspace
colcon build --symlink-install                       # all packages
colcon build --symlink-install --packages-select sim lart_bringup

# Dashboard (ui_runner) and C++ can_bridge
cmake -S LART_Car_Dashboard_v1/src/ui -B LART_Car_Dashboard_v1/build/ui-build -DCMAKE_BUILD_TYPE=Release
cmake --build LART_Car_Dashboard_v1/build/ui-build --target ui_runner can_bridge --parallel 2

# Regenerate everything derived from the DBCs (needs submodules initialised)
git submodule update --init --recursive
/tmp/dbc-venv/bin/python scripts/regenerate_dbcs.py [--source-dir /path/to/T26_DBC]

# Simulation
ros2 launch lart_bringup sim.launch.py               # mock vehicle
python3 start_admin_panel.py                         # Tk CAN admin panel; sets up vcan_data/vcan_pwt/vcan_auto
```

Keep `--parallel 2` for the dashboard build: the generated `dbc_api_sub_*.cpp` units are memory-heavy and OOM a Pi at higher parallelism (Makefile `UI_BUILD_JOBS`).

## Architecture

Two independent stacks live in this repo. They don't share a CAN bridge.

- **Path A (production, on the car):** systemd runs `LART_Car_Dashboard_v1/autostart_dashboard.sh`, which execs two instances of the C++ `can_bridge` (`can0` at 1 Mbit/s for data, `can1` at 500 kbit/s for powertrain) plus `ui_runner`. `can_bridge` decodes frames through the generated DBC dispatcher and publishes one `std_msgs/Float32` topic per signal. `ros2subscriber.cpp` inside `ui_runner` subscribes to those topics and writes into `TelemetryData` (guarded by `g_telemetry_mutex`; hot values are atomics). The 5 ms LVGL tick loop reads that struct. Never call LVGL APIs, including `ui_add_notification`, from the ROS spin thread.
- **Path B (native ROS launch):** `ros2 launch lart_bringup car.launch.py|sim.launch.py|dbc_sim.launch.py` runs the Python packages in `src/`: the `lart_bringup` CAN bridge, dashboard state bridge, bag recorder, `input_handler`, `led_controller`, and the `sim` simulators and admin panel. The Python bridge and simulator parse DBCs at runtime. `src/lart_bringup/config/rpi_config.yaml` configures path B only.
- **Autonomous data:** the Jetson/ACU stack publishes its own ROS topics over DDS, not over CAN. The dashboard subscribes to them directly.
- **Topic namespaces follow the DBC/bus:** `/data` (`data_t26.dbc`), `/pwt` (`powertrain_t26.dbc`), `/can` (`autonomous_t26.dbc`). See `lart_bringup/topic_names.py`.
- **`ROS_DOMAIN_ID`:** the car and the admin panel use `42`; Docker Compose and the launch files default to `0`. A mismatch shows up as missing topics.

## DBC pipeline

`dbc_signals/{data,powertrain,autonomous}_t26.dbc` are the sources of truth. `aquisition_boards.dbc` is legacy and not a generator input. `scripts/regenerate_dbcs.py` validates all three strictly, then regenerates:

- the C decoders
- the ROS messages and CMake entries in the `src/lart_msgs` submodule (FSLART/lart_msgs)
- the dashboard API and subscribers (`dbc_api*.{h,cpp}`, `generated/`)
- the C++ bridge

`dbc_signals/source.json` records the upstream commit and input hashes. Generated output is committed: editing a DBC alone does not change the C++ side.

Never hand-edit generated files: `dbc_api*.cpp/h`, `LART_Car_Dashboard_v1/src/ui/generated/*`, EEZ Studio output (`ui.c`, `eez-flow.cpp`, edited via `LART_car_dashboard_v1.eez-project`), or `lart_msgs` generated messages. Shared CAN IDs across different buses are expected. Don't bypass validation or guess a wire layout.

For which consumer changes a given DBC edit requires, see the table in `docs/DBC-Update-Guide.md`.

## CI

- `build-arm64.yml`: builds the workspace and `ui_runner` on every push to `master` and publishes `arm64-<sha>` / `latest-arm64` releases. The Pi pulls them with `scripts/pull_arm64_build.sh` instead of compiling.
- `release.yml`: on `v*` tags (or manual dispatch), builds a self-contained Raspberry Pi bundle (`install/` without `sim`, DBCs, start scripts) and publishes it as a release. Pi builds never include the simulator.
- `validate-dbc-arm64.yml`: regenerates, tests and builds on PRs without publishing releases.
- No scheduled DBC sync: when FSLART/T26_DBC changes, regenerate locally and open the `lart_msgs` PR first, then the dashboard PR. Workflow behaviour is pinned by `tests/test_dbc_sync_workflow.py` and `test_arm64_workflows.py`. Update those tests when you edit the workflows.

## Deployment

On the Pi, the workspace lives at `/home/lart2026/GIT/data_station/`, and several scripts hardcode that path. `deploy/` holds the Foxglove bag-upload systemd timer.

## Agent rules

`AGENTS.md`, `.github/copilot-instructions.md` and the `.cursor` / `.windsurf` / `.clinerules` files contain only a terse-response style rule (caveman). Code, comments, commits and docs are written normally.

## Save the limit
- Hand quick, mechanical work to the haiku-helper subagent: finding files, grep searches, reading logs,
listing folders, renames, one-line edits, running a command and reporting the output.
- Batch several small lookups into one haiku-helper call.
- Keep planning, debugging, architecture and multi-file changes for yourself.