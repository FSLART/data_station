"""Run the real Qt entry point, including QVariant conversion and QML bindings."""

import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest


@pytest.mark.parametrize("screen", [0, 1, 2])
def test_demo_renders_each_screen_without_qml_binding_errors(tmp_path, screen):
    pytest.importorskip("PySide6.QtQuick")
    package = Path(__file__).resolve().parents[1]
    target = tmp_path / f"screen-{screen}.png"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
    env["PYTHONPATH"] = str(package) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "data_station_runtime.app", "--demo",
         "--screenshot", str(target), "--screen", str(screen)],
        cwd=package, env=env, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for error in ("ReferenceError", "TypeError", "Unable to assign", "Binding loop",
                  "QQmlApplicationEngine failed", "Error:"):
        assert error not in result.stderr, result.stderr
    png = target.read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", png[16:24]) == (800, 480)
