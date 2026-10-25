"""Run the real Qt entry point, including QVariant conversion and QML bindings."""

import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest


@pytest.mark.parametrize("screen,scenario", [(0, "normal"), (1, "normal"),
                                            (2, "normal"), (0, "fault"),
                                            (0, "precharge")])
def test_demo_renders_each_screen_without_qml_binding_errors(tmp_path, screen, scenario):
    pytest.importorskip("PySide6.QtQuick")
    package = Path(__file__).resolve().parents[1]
    target = tmp_path / f"screen-{screen}-{scenario}.png"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QT_QUICK_CONTROLS_STYLE="Basic")
    env["PYTHONPATH"] = str(package) + os.pathsep + env.get("PYTHONPATH", "")
    setup = "from data_station_runtime.demo import SAMPLES; "
    if scenario == "fault":
        setup += ("SAMPLES['can1','INV1_Temperatures']['INV1_Actual_FaultCode'] = 1; "
                  "SAMPLES['can1','INV2_Temperatures']['INV2_Actual_FaultCode'] = 7; ")
    elif scenario == "precharge":
        setup += "SAMPLES['can1','Master_PreCharge_ID_1'] = {'precharge_state': 16}; "
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; from PySide6.QtCore import qInstallMessageHandler; "
         "qInstallMessageHandler(lambda kind, context, message: print(message, file=sys.stderr)); " + setup +
         "from data_station_runtime.app import main; raise SystemExit(main())", "--demo",
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

    if screen == 0:
        from PySide6.QtGui import QImage
        image = QImage(str(target))
        # Anchor the original 800x480 gauge, rather than a support-screen layout.
        assert image.pixelColor(0, 0).name() == "#050505"
        assert image.pixelColor(400, 7).name() == "#444444"
        assert image.pixelColor(400, 120).name() == "#030303"
        assert image.pixelColor(590, 260).name() == "#e51b23"
        assert image.pixelColor(300, 200).name() == "#161616"
        if scenario == "fault":
            assert image.pixelColor(7, 460).name() == "#ff272e"
        elif scenario == "precharge":
            banner = image.pixelColor(400, 365)
            assert banner.red() > 190 and banner.green() < 20 and banner.blue() < 20
