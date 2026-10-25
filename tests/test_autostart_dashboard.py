from pathlib import Path


AUTOSTART = (
    Path(__file__).resolve().parents[1]
    / "LART_Car_Dashboard_v1"
    / "autostart_dashboard.sh"
)


def test_autostart_launches_led_controller_with_shared_config():
    script = AUTOSTART.read_text()

    assert 'LED_CONTROLLER_BIN="/home/lart2026/GIT/data_station/install/led_controller/lib/led_controller/led_controller"' in script
    assert '"$LED_CONTROLLER_BIN" --ros-args --params-file "$RPI_CONFIG" &' in script
    assert "LED_CONTROLLER_PID=$!" in script


def test_autostart_selects_runtime_before_legacy_processes():
    script = AUTOSTART.read_text()
    assert '${LART_LEGACY_UI:-0}' in script
    assert 'exec bash "$SCRIPT_DIR/../scripts/start_runtime.sh"' in script
    assert script.index('scripts/start_runtime.sh') < script.index('BAG_RECORDER_BIN=')
