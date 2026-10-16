# Updating a DBC in Data Station

The sources are `dbc_signals/data_t26.dbc`, `powertrain_t26.dbc`, and
`autonomous_t26.dbc`. `aquisition_boards.dbc` is legacy and is not an input to
these generators. Run the commands below from the repository root, using the
project's installed `cantools` dependency.

## When code needs updating

| DBC change | Required action |
| --- | --- |
| Comments or receiver names only | Usually no application change; review generated metadata if regenerating. |
| Units only | Review dashboard/Foxglove labels and conversions; regenerate C metadata. Decoding changes only if scale/offset also change. |
| CAN ID, length, bit position, endian, signedness, scale or offset | Regenerate the C decoder and bridge; review conversions, ranges and simulator values. |
| Signal/message added, removed or renamed | Regenerate ROS interfaces, API and bridge; update every consumer of the old fields/topics. |
| Enum choices changed | Regenerate C definitions/error labels; review hand-written state/mission labels and ROS constants. |
| Bus/database assignment changed | Review launch routes and topic namespaces: `/data`, `/pwt`, `/can`. |

The Python bridge and simulator read DBCs at runtime. The C++ bridge and dashboard
use committed generated sources: changing a DBC alone does not update them.

## Regenerate and review

Initialize the submodules, then run the complete chain from the repository root:

```bash
git submodule update --init --recursive
python3 -m venv /tmp/dbc-venv
/tmp/dbc-venv/bin/pip install -r scripts/requirements-dbc.txt
/tmp/dbc-venv/bin/python scripts/regenerate_dbcs.py

git diff --stat
git -C src/lart_msgs diff
```

This validates all three databases before replacing inputs, then regenerates all
C decoders, ROS messages/CMake entries, the dashboard API/subscribers and CAN
bridge. It detects UTF-8 or legacy CP1252 input and removes generated timestamps
so unchanged inputs produce unchanged outputs. Do not bypass strict validation
or guess the wire layout; shared IDs between different buses are expected.

To import a specific upstream revision, use a clean Git checkout:

```bash
git clone https://github.com/FSLART/T26_DBC.git /tmp/t26-dbc
git -C /tmp/t26-dbc checkout <commit-sha>
/tmp/dbc-venv/bin/python scripts/regenerate_dbcs.py --source-dir /tmp/t26-dbc
```

`dbc_signals/source.json` records the exact upstream commit, SHA-256 of each
input and pinned cantools version. Local edits clear the recorded commit when
input hashes change. Never attribute edited DBC files to an upstream revision.

## CI validation

There is no scheduled DBC sync. Regenerate locally (above) when
**FSLART/T26_DBC** changes, adapt consumers and open the PRs by hand.

The **Validate DBC ARM64 build** workflow (`validate-dbc-arm64.yml`)
runs regeneration, tests and the ARM64 build on dashboard PRs, master pushes,
and pushes to `automate-dbc-regeneration`. It also supports manual dispatch,
uses no publication credentials and publishes no releases.

The API generator updates `dbc_api.h`, `dbc_api.cpp`, `dbc_api_sub_*.cpp`,
`src/lart_msgs/dbc_msgs/*.msg` and the generated CMake interface entries.
It preserves existing ROS field types, headers, constants, custom messages,
services and dependencies. Review existing types/constants manually when a DBC
changes their meaning or range. Removed message files may remain on disk but
are removed from the CMake generated list; remove obsolete files after reviewing
consumers. The bridge generator updates `generated/can_bridge_impl*`.

Search for removed/renamed fields in `screens.c`, `ros2subscriber.cpp`, Python
nodes, simulator overrides and Foxglove layouts. Update dashboard helper logic
in `generate_dbc_api.py`, since it writes the helpers in `dbc_api.cpp` too.
Do not use the obsolete root `dbc2msg.py`: it references another user's path.

`src/lart_msgs` is a Git submodule. Commit/publish its interface changes in that
repository first, then update the parent repository's submodule reference with
the DBC and generated sources. A parent commit alone does not include dirty
submodule files.

## Verify, build and deploy

Run these build commands in Bash (`setup.bash` is Bash-specific):

```bash
/tmp/dbc-venv/bin/python -m pytest -q tests
source /opt/ros/jazzy/setup.bash
colcon build --packages-select lart_msgs --parallel-workers 2
source install/setup.bash
cmake -S LART_Car_Dashboard_v1/src/ui -B LART_Car_Dashboard_v1/build/ui-build \
  -DCMAKE_BUILD_TYPE=Release
cmake --build LART_Car_Dashboard_v1/build/ui-build --target ui_runner can_bridge --parallel 2
```

Rebuild/restart every publisher and subscriber using a changed ROS interface.
Use `ros2 interface show lart_msgs/msg/Aqt7` and `ros2 topic echo /data/aqt7` to
confirm the new fields. Compare a known raw frame against decoded physical
values; then verify the dashboard labels and values using simulation or the car.

## Current DBC update (6 October 2026)

The AQT7 overlap has been resolved in the source DBC. The frame is eight bytes:
signed `SUSP_L` uses bits 0–15, signed `SUSP_R` uses bits 16–31, and unsigned
`NTC_1` uses bits 32–39. Both suspension fields remain in the ROS interface and
dashboard; `ntc_1` is added to the ROS interface, API and bridge. Rebuild all
AQT7 publishers/subscribers together. The decoder now requires the full
eight-byte frame and rejects the old four-byte payload.

The data DBC also adds `Master_MSC_ID_3` at CAN ID `0x750`, exposed as
`/data/master_msc_id_3` alongside the existing powertrain topic. These frames
retain their own bus-specific decoding, including the powertrain `VCU_states`
frame that shares CAN ID `0x750`.

The autonomous DBC removes the old AQT2/AQT3 wheel-speed frames and makes AQT4
`SUSP_L`/`SUSP_R` signed. Regenerate the data and autonomous C decoders, then
the API and bridge. The powertrain decoder is already current. Use the complete regeneration command to preserve the encoding of each input.

The generator has been repaired to preserve existing ROS package configuration,
field types, headers, constants and dashboard helpers during future updates.

## Powertrain DBC update (9 October 2026)

`VCU_states` at CAN ID `0x750` now packs `vcu_state` into the low four bits
instead of the whole first byte. The eight-byte frame also carries throttle,
traction-control and torque-vectoring states, sensor-validity flags, front wheel
speeds, rear traction-control factors, signed torque shift and road wheel angle,
and a four-bit frame counter. Wheel speeds use 0.5 km/h per bit and road wheel
angle uses 0.25 degrees per bit.

The regenerated powertrain decoder, `VcuStates.msg`, dashboard API and bridge
expose these fields on `/pwt/vcu_states`. Rebuild and restart its publishers and
subscribers together. Existing ready-state values 6 and 7 remain unchanged.

## Autonomous DBC update (13 October 2026)

The autonomous DBC adds eight IMU frames at CAN IDs `0x530`–`0x537`:
acceleration, angular velocity, GNSS position, GNSS altitude, quaternion
orientation, velocity, Euler angles and device status. The regenerated decoder,
ROS interfaces, dashboard API and bridge expose them on `/can/imu_*` topics.
Acceleration includes gravity; Euler angles use degrees with an ENU reference.
The status frame preserves the Xsens device bit layout, including RTK status.
Rebuild `lart_msgs`, the dashboard and the bridge together before restarting
publishers and subscribers.

## Autonomous DBC update (14 October 2026)

The autonomous decoder, ROS interfaces, dashboard API and bridge now include
`IMU_Temperature` (`0x538`, two bytes), `IMU_Filter_Velocity` (`0x539`, six
bytes) and `IMU_Free_Acceleration` (`0x53A`, six bytes). All signals are signed
16-bit values with a scale of 0.01. The new `/can/imu_temperature`,
`/can/imu_filter_velocity` and `/can/imu_free_acceleration` topics use degrees
Celsius, m/s and m/s² respectively. Filter velocity and free acceleration use
ENU coordinates; free acceleration has gravity removed. Rebuild `lart_msgs`,
the dashboard and the bridge together before restarting publishers and
subscribers.
