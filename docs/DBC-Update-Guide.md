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

## Validate before writing generated files

```bash
python3 - <<'PY'
from pathlib import Path
import cantools
for name in ('data_t26', 'powertrain_t26', 'autonomous_t26'):
    cantools.database.load_file(Path('dbc_signals') / f'{name}.dbc')
    print(f'{name}: valid')
PY
```

Resolve overlapping signals and invalid frame lengths with the firmware owner.
Do not bypass strict validation or guess the wire layout. Validate each database
separately; shared IDs between different buses are expected.

## Regenerate and review

Generate C files for each changed DBC (example: data):

```bash
python3 -m cantools generate_c_source \
  -o LART_Car_Dashboard_v1/src/ui/generated dbc_signals/data_t26.dbc
python3 LART_Car_Dashboard_v1/src/ui/generate_dbc_api.py
python3 LART_Car_Dashboard_v1/src/ui/generated/generate_can_bridge.py

git diff --stat
git -C src/lart_msgs diff
```

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
python3 -m pytest -q tests/test_dbc_generation.py tests/test_dbc_api_abi.py
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

## Pending data DBC update (1 October 2026)

The incoming AQT7 definition places `NTC_1` at bits 16–23, overlapping
`SUSP_R` at bits 16–31. `SUSP_L` uses bits 0–15; the frame is four bytes.
The user requires keeping `SUSP_R`, so regeneration is blocked until the
firmware layout specifies a separate position/frame length or multiplexing.
The current generated decoder, ROS interface and dashboard retain `SUSP_R`.
Do not run regeneration against this invalid DBC or use `--no-strict`.

The generator has been repaired to preserve existing ROS package configuration,
field types, headers, constants and dashboard helpers during future updates.
