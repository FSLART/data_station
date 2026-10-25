"""Bring up the runtime stack without building or starting the legacy C++ UI."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node


def generate_launch_description():
    share = Path(get_package_share_directory("data_station_runtime"))
    hardware = str(Path(get_package_share_directory("lart_bringup")) /
                   "config" / "rpi_config.yaml")
    dbc_dir = LaunchConfiguration("dbc_dir")
    config = str(share / "config" / "runtime.yaml")
    sim = IfCondition(LaunchConfiguration("sim"))
    # Desktop bench: simulators write straight onto the virtual can0/can1 that runtime_can reads.
    sim_nodes = []
    for label, dbc, interface in (("data", "data_t26.dbc", "can0"),
                                  ("powertrain", "powertrain_t26.dbc", "can1"),
                                  ("autonomous", "autonomous_t26.dbc", "vcan_auto")):
        sim_parameters = [hardware, {"can_interface": interface, "publish_hz": 10.0,
                                     "dbc_path": PathJoinSubstitution([dbc_dir, dbc])}]
        sim_nodes.append(Node(package="sim", executable="can_simulator",
                              name=f"can_simulator_{label}", parameters=sim_parameters,
                              condition=sim, output="screen"))
    # Autonomous data reaches the dashboard over DDS, so only that bus needs the Python bridge.
    sim_nodes.append(Node(package="lart_bringup", executable="can_bridge",
                          name="can_bridge_autonomous", parameters=sim_parameters,
                          condition=sim, output="screen"))
    sim_nodes.append(Node(package="sim", executable="admin_panel",
                          additional_env={"LART_SIM_EXTERNAL": "1"}, condition=sim, output="screen"))
    return LaunchDescription([
        DeclareLaunchArgument("dbc_dir", default_value=str(share / "dbc_signals"),
                              description="Live DBC directory; edits apply after reload_dbc"),
        DeclareLaunchArgument("ui", default_value="true"),
        DeclareLaunchArgument("hardware_io", default_value="true"),
        DeclareLaunchArgument("sim", default_value="false",
                              description="Run DBC simulators and the admin panel on virtual CAN"),
        Node(package="data_station_runtime", executable="runtime_can", name="runtime_can",
             parameters=[config, {"dbc_paths": [
                 [PathJoinSubstitution([dbc_dir, "data_t26.dbc"])],
                 [PathJoinSubstitution([dbc_dir, "powertrain_t26.dbc"])]]}], output="screen"),
        Node(package="data_station_runtime", executable="runtime_recorder", name="runtime_recorder",
             parameters=[config], output="screen"),
        Node(package="data_station_runtime", executable="runtime_dashboard", name="runtime_dashboard",
             parameters=[config, {"autonomous_dbc": PathJoinSubstitution([
                 dbc_dir, "autonomous_t26.dbc"])}], arguments=["--fullscreen"],
             condition=IfCondition(LaunchConfiguration("ui")), output="screen"),
        Node(package="input_handler", executable="input_handler", name="input_handler",
             parameters=[hardware], condition=IfCondition(LaunchConfiguration("hardware_io")),
             output="screen"),
        Node(package="led_controller", executable="led_controller", name="led_controller",
             parameters=[hardware], condition=IfCondition(LaunchConfiguration("hardware_io")),
             output="screen"),
        *sim_nodes,
    ])
