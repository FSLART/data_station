# Runtime architecture and migration

## Decision

Use Qt Quick/QML for the 800 × 480 interface and Python for runtime DBC decoding.
Acquisition, recording and display are separate ROS processes. A fixed generic
transport replaces per-DBC application code generation. The legacy C++/LVGL
stack remains available for bench comparison.

The earlier build-cache proposal was superseded. Caching alone does not remove
the source-level dependency between a DBC and generated C++ interfaces. The new
primary build has no DBC-generated C++ application, and adding a CAN field does
not require changing `lart_msgs`.

## Boundaries

| Component | Inputs | Outputs | Requires compilation after CAN DBC edit? |
| --- | --- | --- | --- |
| `DbcRuntime` | One live DBC per bus, raw frames | Exact numeric values, catalog, source hashes | No |
| `runtime_can` | SocketCAN, runtime catalog | Fixed `CanTelemetry`, manifest, diagnostics, precharge request | No |
| Compatibility adapter | Runtime values, installed frozen `lart_msgs` | Existing `/data/*` and `/pwt/*` topics | No, for fields already present |
| `runtime_dashboard` | Generic CAN, direct autonomous DDS | Qt Quick display | No |
| `runtime_recorder` | Compact precharge Bool, Jetson state | One MCAP session plus rosbag metadata | No |
| External ROS schema | Deliberate interface changes | New typed fields for Jetson/Foxglove consumers | Yes |

`SignalValue` carries one of signed 64-bit, unsigned 64-bit or double precision
values. `CanTelemetry` contains raw CAN data and flags, source timestamp, bus,
message name, DBC hash and decoded values. No handwritten CDR serializer is used.
ROS generates type support for these two fixed message definitions.

`lart_msgs` stays at the checked-in submodule revision. Compatibility publication
uses its installed type support, maps matching fields and reports fields that
are available only through the generic transport. This preserves old topic
names; it does not promise unchanged semantics if a DBC changes units or meaning.

## Runtime behavior

- A DBC is validated strictly before any SocketCAN interface opens. Duplicate
  message identities within one bus fail startup. IDs may repeat across buses
  and between standard and extended frame formats.
- `/runtime_can/reload_dbc` validates all files before swapping schemas. Invalid
  input leaves acquisition on the old schema. Queued old-schema frames are
  discarded at a successful swap and counted explicitly.
- Receive callbacks only copy into a bounded queue. ROS publication happens on
  the executor thread. Per-bus diagnostics expose queue overflow, receive errors,
  failed decoding and failed publication. Unknown or invalid payloads still
  reach generic raw capture.
- The retained `/telemetry/dbc_manifest` contains the exact validated source
  text, its encoding, SHA-256 and catalog. It uses transient-local durability,
  so a recorder started later receives it. Each frame identifies its schema by
  hash. The UI buffers a bounded set of frames if their manifest arrives later.
- Staleness uses local monotonic time, independently for multiplexed signals.
  Unseen, stale and nonfinite values are visibly invalid. Large integers become
  strings only at the QML display boundary, preserving every bit in transport
  and storage.
- The interface receives direct autonomous topics using the installed ROS
  message definitions and maps their numeric fields to the same registry. It
  does not interpret autonomous DDS traffic as CAN frames.
- The driver and autonomous views avoid converting the hidden signal inspector
  into QML every frame. They refresh at approximately 30 Hz; the inspector is
  limited to 10 Hz. Acquisition and rosbag recording retain their own rates.
- Recording starts for precharge or Jetson READY/DRIVING. A compact reliable,
  retained Bool avoids searching the full CAN stream for a rare trigger.
  Both trigger sources must explicitly clear before the stop grace period.
  Publisher silence keeps the last request; a lost publisher cannot stop a bag.
- Recording keeps topic discovery and hidden topics enabled, excludes `/zed/*`,
  explicitly uses MCAP, finalizes with SIGINT and attempts to reindex incomplete
  sessions on startup. Power loss can still lose buffered data or damage a file.

## Driver behavior retained

Motor RPM remains ERPM divided by 4. Speed uses the existing 14.73 ratio and
0.2032 m wheel radius. Low-LV hysteresis remains 24.5/24.8 V; low-SOC hysteresis
remains 15/17%. Motor, inverter and battery temperature thresholds remain
100/80/55 °C with 5 °C clearing hysteresis. Both inverters and both available
battery-temperature sources contribute to warnings. Pedal indications,
precharge transitions and autonomous values remain visible.

The current DBC's precharge labels take precedence over the older generated
labels. Dynamic signal inspection replaces the disabled, generated debug pages.
Qt layouts are edited directly as QML; EEZ remains associated with the legacy UI.

## Build and deployment

The primary workflows check out only the external ROS interface submodule and
build under `src/` with `--packages-up-to data_station_runtime input_handler
led_controller sim`. This excludes the nested LVGL CMake package and the second
standalone UI build. The fixed generic interfaces and frozen external interfaces
still need an initial ROS build. No cache is required for DBC edits to work.

Release packaging keeps the existing asset/tag conventions and includes the ROS
install tree with the QML files and installed DBC copies. The boot launcher uses
the checkout's DBC directory so explicit reload reads edited files directly.
Launching without `dbc_dir` uses installed copies instead. Python dependencies
are installed on the target separately, as with the previous Python services.

The old autostart path remains selectable with `LART_LEGACY_UI=1`, provided its
C++ binary has been built separately. The old simulators and admin panel remain
on their existing launch paths. The existing GPIO handler still logs events;
it does not currently publish UI navigation commands.

## Validation and limits

Local tests exercise actual project DBCs, 64-bit values, multiplexing, bus and
extended-ID isolation, malformed input, atomic reload, freshness, recording
triggers, calibration and QML startup. ROS-only tests exercise generated type
serialization, virtual CAN publication, legacy compatibility and live reload
after `colcon build` in ARM64 CI.

Desktop rendering with 1,240 registered signals exposed excessive conversion of
hidden signal rows. After gating those rows, the measured driver refresh plus
software rendering fell from about 38 ms to about 6 ms on that Windows host.
These measurements do not establish Raspberry Pi latency or capture capacity.

Before switching the physical car, validate Qt's graphics platform, CAN throughput
on both buses at the expected peak load, queue/drop counters, actual GPIO and LED
behavior, recording/finalization, power-loss recovery and Foxglove import. ROS,
SocketCAN and the Pi GPU are unavailable on the local Windows development host.
The implementation includes those CI checks; a local unit-test pass is not an
ARM64 or vehicle test result.
