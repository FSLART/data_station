# CAN admin panel verification

The Python panel and simulator controls passed 37 focused unittest checks,
including persistent ranges/timing, rejected invalid saved ranges, atomic saves,
temporary scenario isolation, drive cycle phases, speed/ERPM agreement, IVT
mV/mA units, and configured temperature bands.
The Error tests checks validate all 15 presets against the current DBCs,
combined faults, conflicting/missing targets, rollback on update failure,
restoration of prior controls and pause state, and direct ROS delegation.
Virtual CAN checks decoded injected inverter fault code 1 and SOC 10% and
confirmed restoration. A virtual-display Tk test exercised the separate tab,
multi-selection, signal preview, Apply, and Clear commands.
The local launcher check also passed. The dashboard `ui_runner` CMake target
rebuilt successfully with the minimized-window startup change. The full repository run reported
92 passed and four failures in unchanged code:

- `src/led_controller/test/test_led_node.py::test_controller_fills_positive_current_from_centre_in_blue`
- `src/led_controller/test/test_led_node.py::test_controller_fills_negative_current_from_centre_in_green`
- `src/led_controller/test/test_led_node.py::test_negative_average_inverter_request_fills_eight_green_leds`
- `tests/test_arm64_workflows.py::Arm64WorkflowTests::test_fast_build_preserves_each_version_and_updates_latest`

The LED assertions disagree with the current LED implementation. The workflow
check expects `.github/workflows/build-arm64-faster.yml`, which is absent.
Those implementation/test files were not changed by this task.

An isolated ROS/Tk smoke check exercised real simulator parameter services,
DBC encoding, the Python CAN bridge, and current generated ROS message types
using an in-memory CAN transport. It verified:

- Discovery and display of all 763 powertrain DBC signals.
- CAN and direct ROS speed scenarios, preserving unrelated message fields.
- Simulator pause and restoration on cancellation.
- Publication of all three production screen commands.
- A short rosbag recording, finalized with metadata.
- Tk rendering and panel shutdown.

The focused runtime checks also cover multiplexed payloads and extended frames,
including an extended CAN ID below `0x7ff`, through the bridge's ROS publisher.
The local launcher was exercised with an isolated fake dashboard binary: it
makes no simulator launch calls and exports `LART_UI_START_MINIMIZED=1`.

Run the Python checks from a sourced workspace:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ROS_LOG_DIR=/tmp/lart-admin-tests ROS_DOMAIN_ID=143 python3 -m pytest -q
```
