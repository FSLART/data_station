# LART Data Station — current project context

The primary architecture is Python runtime DBC decoding, fixed generic ROS
transport, independent MCAP recording and a Qt Quick/QML interface. Start with
[README.md](README.md), [architecture details](docs/Data-Station-Restructure-Plan.md)
and [DBC update guide](docs/DBC-Update-Guide.md).

## Runtime source map

- `src/data_station_msgs`: two fixed ROS interfaces, `SignalValue` and
  `CanTelemetry`. DBC edits do not alter these message definitions.
- `src/data_station_runtime/data_station_runtime/dbc.py`: strict, isolated
  per-bus DBC loading, exact decoding, metadata and atomic reload.
- `telemetry.py`: thread-safe signal registry and monotonic freshness.
- `can_node.py`: SocketCAN receive queue, generic publication, retained DBC
  manifest, diagnostics, compact precharge trigger and optional compatibility
  publication using the installed `lart_msgs` schema.
- `receiver.py`: generic transport/catalog consumption and direct DDS values.
- `presentation.py`: calibrated driver conversions, states and alert hysteresis.
- `qml/`: 800 × 480 Driver, Autonomous and searchable Signals views.
- `app.py`: Qt event loop and a separate ROS executor thread. ROS callbacks
  update Python data; Qt objects are accessed only on the Qt thread.
- `recorder.py` and `recording_trigger.py`: precharge OR Jetson READY/DRIVING
  recording. The existing `lart_bringup/bag_recorder.py` owns rosbag process
  management, grace, SIGINT finalization and recovery attempts.
- `launch/car.launch.py`, `config/runtime.yaml`: primary bringup and runtime
  parameters. `scripts/start_runtime.sh` selects the checkout's live DBCs.

Paths above without a full prefix are inside the runtime Python package.

## Hardware and contracts

The target is a Pi 5 with 8 GB RAM, Ubuntu 24.04, ROS Jazzy and an 800 × 480
display. `can0` is data at 1 Mbit/s with `data_t26.dbc`; `can1` is powertrain at
500 kbit/s with `powertrain_t26.dbc`. Shared IDs between buses are expected.
Jetson and ACU publish direct DDS topics; `autonomous_t26.dbc` supplies names
and display metadata for those installed external types.

Generic CAN topic: `/telemetry/can`. Signal identity:
`<bus>/<raw DBC message>/<raw DBC signal>`. Direct DDS identity:
`dds/<raw DBC message>/<raw DBC signal>`. Keep raw names and integer precision.
Never cast all values to float. Values above JavaScript's exact integer range
become strings at the QML boundary only.

`/telemetry/precharge` is a reliable retained Bool; there is no assumed initial
false. Recording keeps a request until that source explicitly clears it.
`/telemetry/dbc_manifest` retains exact validated sources and their hashes for
late subscribers and recordings. `/telemetry/status` exposes queue and failure
counters. Reload with `/runtime_can/reload_dbc`; failure leaves old decoding
active. Successful reload explicitly counts discarded queued frames.

External `lart_msgs` remains frozen at its submodule revision. The adapter maps
known fields into the old `/data/*` and `/pwt/*` topics. New fields immediately
work in the generic topic and signal inspector. New typed external interfaces
still require an explicit schema update and rebuild on all consumers.

## Build and checks

Build with `colcon build --base-paths src --packages-up-to data_station_runtime
input_handler led_controller sim`. The restricted base path is intentional: root
discovery also finds the legacy nested CMake UI. The primary ARM64 workflows
build the runtime packages and run pure, QML and ROS integration checks.

No generation step is required for normal CAN DBC edits. The legacy generators
remain available when deliberately maintaining the old stack or external typed
contracts. Preserve driver calibration, strict validation, bus separation,
recording lifecycle and exact integers during changes.

The local Windows host can run pure tests and offscreen QML. ROS, real
SocketCAN, Pi graphics, GPIO and peak-load recording require Linux/target
validation. `scripts/benchmark_runtime.py --qt` measures local decoding and
display costs; it does not measure losses on the acquisition/recording path.

## Legacy and unchanged tools

`LART_Car_Dashboard_v1/` contains the old C++/LVGL/EEZ UI and generators.
`LART_LEGACY_UI=1` selects its old autostart path when its binary exists.
Simulators, the Tk admin panel, GPIO handler, LED controller and Foxglove upload
remain. The GPIO handler currently logs events without publishing navigation.

[Historical context](docs/Legacy-Project-Context.md) documents the earlier stack;
do not use it as the primary runtime contract.
