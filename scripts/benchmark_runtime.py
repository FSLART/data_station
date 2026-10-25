"""Measure runtime costs on the target host; this does not measure CAN/DDS loss."""

import argparse
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "data_station_runtime"))
from data_station_runtime.dbc import DbcRuntime
from data_station_runtime.presentation import DashboardModel


def measure(callback, iterations):
    for _ in range(5):
        callback()
    start = perf_counter()
    for _ in range(iterations):
        callback()
    return round((perf_counter() - start) * 1000 / iterations, 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dbc-dir", type=Path, default=ROOT / "dbc_signals")
    parser.add_argument("--iterations", type=int, default=10000)
    parser.add_argument("--ui-iterations", type=int, default=100)
    parser.add_argument("--qt", action="store_true", help="Include rendering on the selected Qt platform")
    args = parser.parse_args()
    if min(args.iterations, args.ui_iterations) <= 0:
        parser.error("Iteration counts must be positive")
    runtime = DbcRuntime({bus: args.dbc_dir / name for bus, name in (
        ("can0", "data_t26.dbc"), ("can1", "powertrain_t26.dbc"),
        ("dds", "autonomous_t26.dbc"))}, stale_after=3600)
    catalog = runtime.store.catalog()
    for item in catalog:
        runtime.store.update(item["bus"], item["message"], {item["signal"]: 0})
    model = DashboardModel(catalog)
    result = {"host": platform.platform(), "python": platform.python_version(),
              "signals": len(catalog), "unit": "mean milliseconds per operation"}
    result["ICD_Result_decode_and_store"] = measure(
        lambda: runtime.decode("can0", 0x502, bytes.fromhex("a0fffe1dc0303900")), args.iterations)
    for include in (False, True):
        result["snapshot_and_" + ("inspector" if include else "driver")] = measure(
            lambda: model.update(runtime.store.snapshot(), include_signals=include), args.ui_iterations)
    if args.qt:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine
        from data_station_runtime.app import Dashboard
        from data_station_runtime.receiver import TelemetryReceiver
        app = QGuiApplication([])
        receiver = TelemetryReceiver(stale_after=3600)
        receiver.store = runtime.store
        receiver.catalog_version += 1
        dashboard = Dashboard(receiver)
        dashboard.refresh()
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("dashboard", dashboard)
        engine.load(QUrl.fromLocalFile(str(ROOT / "src/data_station_runtime/data_station_runtime/qml/Main.qml")))
        if not engine.rootObjects():
            raise RuntimeError("QML did not load")
        window = engine.rootObjects()[0]
        def render():
            dashboard._last_signal_refresh = -1  # Measure full inspector work, bypassing the 10 Hz limit.
            dashboard.refresh()
            app.processEvents()
            window.grabWindow()
        for screen in range(3):
            dashboard.selectScreen(screen)
            result[f"qt_screen_{screen}_refresh_render_readback"] = measure(render, args.ui_iterations)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
