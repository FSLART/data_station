"""Evaluate the actual launch parameters using Jazzy's substitution rules."""

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("launch_ros")
from launch import LaunchContext
from launch_ros.actions import Node
from launch_ros.utilities import evaluate_parameters


def test_launch_keeps_the_two_dbc_paths_separate():
    path = Path(__file__).resolve().parents[1] / "launch" / "car.launch.py"
    spec = importlib.util.spec_from_file_location("runtime_car_launch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = LaunchContext()
    context.launch_configurations["dbc_dir"] = "/tmp/live dbcs"
    found = []
    for entity in module.generate_launch_description().entities:
        if isinstance(entity, Node):
            # Node has no public accessor for its normalized parameter dictionaries.
            dictionaries = [value for value in entity._Node__parameters if isinstance(value, dict)]
            for parameters in evaluate_parameters(context, dictionaries):
                if "dbc_paths" in parameters:
                    found.append(parameters["dbc_paths"])
    assert found == [("/tmp/live dbcs/data_t26.dbc", "/tmp/live dbcs/powertrain_t26.dbc")]
