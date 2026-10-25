"""Checks for vehicle calibration, freshness, and runtime signal inspection."""

import math

import pytest

from data_station_runtime.presentation import DashboardModel


def sample(identity, value, *, valid=True, seen=True, **extra):
    return {"id": identity, "value": value, "valid": valid, "seen": seen,
            "timestamp": 100.0, "age": 0.1, **extra}


def test_unseen_fields_never_look_like_received_zero():
    model = DashboardModel([{"id": "can0/NewMessage/NewSignal"}])
    assert model.state["driver"]["speed"]["text"] == "—"
    assert model.state["ready"] == "UNKNOWN"
    assert model.state["unseenCount"] == 1
    assert model.state["signals"][0]["status"] == "UNSEEN"


def test_vehicle_calibration_pedals_and_lv_fallback():
    model = DashboardModel()
    state = model.update([
        sample("can1/INV1_ERPM_DUTY_VOLTAGE/INV1_Actual_ERPM", 40000),
        sample("can0/AQT1/Throtle_Percentage", 120),
        sample("dds/ASF_SIGNALS/Brake_Pressure_Front", 40),
        sample("dds/VCU_HV/Brake_pressure_Rear", 78),
        sample("can0/PDM_LV/LV_Voltage_mV", 0),
        sample("can1/IVT_Msg_Result_U3/IVT_Result_U3", 25100),
        sample("can1/VCU_states/vcu_state", 6),
    ])
    driver = state["driver"]
    assert driver["rpm"]["value"] == 10000
    assert driver["speed"]["value"] == pytest.approx(10000 / 14.73 * 2 * math.pi * 0.2032 * 0.06)
    assert driver["apps"]["value"] == 100
    assert driver["brake"]["value"] == 78
    assert driver["lv"]["value"] == pytest.approx(25.1)
    assert state["ready"] == "READY"


def test_stale_values_remain_inspectable_but_leave_driver_metrics():
    state = DashboardModel().update([
        sample("can1/INV1_ERPM_DUTY_VOLTAGE/INV1_Actual_ERPM", 40000, valid=False, age=2),
        sample("can1/VCU_states/vcu_state", 6, valid=False, age=2),
    ])
    assert state["driver"]["speed"]["value"] is None
    assert state["ready"] == "UNKNOWN"
    assert state["staleCount"] == 2
    assert state["signals"][0]["displayValue"] == "40000"
    assert state["signals"][0]["status"] == "STALE"


def test_alert_hysteresis_and_second_inverter_are_preserved():
    model = DashboardModel()

    def update(lv, soc, motor):
        return {alert["id"] for alert in model.update([
            sample("can0/PDM_LV/LV_Voltage_mV", lv),
            sample("can1/Master_SOC_Accumulator/SOC_Float", soc),
            sample("can1/INV2_Temperatures/INV2_Actual_TempMotor", motor),
        ])["alerts"]}

    assert {"lv", "soc", "motor"} <= update(24.5, 15, 100)
    assert {"lv", "soc", "motor"} <= update(24.8, 17, 95)
    assert not ({"lv", "soc", "motor"} & update(24.81, 17.01, 94.99))


def test_both_battery_sources_contribute_to_temperature_warning():
    state = DashboardModel().update([
        sample("can0/Master_MSC_ID_3/overall_maximum_temperature", 30),
        sample("can1/Master_MSC_ID_3/overall_maximum_temperature", 56),
    ])
    assert any(alert["id"] == "battery" for alert in state["alerts"])


def test_autonomous_fields_use_direct_dds_and_acu_mission_priority():
    state = DashboardModel().update([
        sample("dds/ACU/Mission_select", 2),
        sample("dds/JETSON/AS_MISSION", 3),
        sample("dds/ACU/ACU_STATE", 5),
        sample("dds/JETSON/TEMPERATURE", 47),
        sample("dds/SLAM_STATS_CAN/Lap_counter", 8),
        sample("dds/DV_dynamics_1/Speed_target", 35),
    ])
    metrics = {metric["label"]: metric for metric in state["autonomous"]}
    assert metrics["MISSION"]["text"] == "SKIDPAD"
    assert metrics["ACU STATE"]["text"] == "DRIVING"
    assert metrics["JETSON TEMP"]["value"] == 47
    assert metrics["LAPS"]["value"] == 8
    assert metrics["SPEED TARGET"]["value"] == 35


def test_new_signals_and_large_integers_need_no_model_change():
    identity = "can0/RuntimeAdded/ArticleNumber"
    model = DashboardModel([{"id": identity, "unit": "", "choices": {}}])
    value = 2**56 - 1
    state = model.update([sample(identity, value)])
    assert state["signals"][0]["displayValue"] == str(value)
    assert state["signals"][0]["value"] == str(value)
    assert state["freshCount"] == 1
    model.set_catalog([{"id": "can0/NewReplacement/NewSignal"}])
    assert model.update([])["signals"][0]["id"] == "can0/NewReplacement/NewSignal"


def test_precharge_uses_current_dbc_labels_and_hv_notification_duration():
    identity = "can1/Master_PreCharge_ID_1/precharge_state"
    model = DashboardModel([{"id": identity, "choices": {9: "VERIFY_BUS_VOLT"}}])
    state = model.update([sample(identity, 9)], now=10)
    assert state["precharge"]["text"] == "VERIFY BUS VOLT"
    assert state["precharge"]["visible"]
    assert not model.update([sample(identity, 9)], now=10.6)["precharge"]["visible"]
    state = model.update([sample(identity, 16)], now=11)
    assert state["precharge"]["hvOn"]
    assert model.update([sample(identity, 16)], now=14.9)["precharge"]["visible"]
    assert not model.update([sample(identity, 16)], now=15.1)["precharge"]["visible"]


def test_dbc_choices_control_generic_fault_labels():
    identity = "can0/NewMessage/Fault"
    model = DashboardModel([{"id": identity, "choices": {0: "NO FAULT", 1: "SENSOR LOST"}}])
    assert not model.update([sample(identity, 0)])["alerts"]
    alerts = model.update([sample(identity, 1)])["alerts"]
    assert alerts == [{"id": identity, "text": "can0 / NewMessage / Fault: SENSOR LOST", "severity": "error"}]


def test_hidden_inspector_omits_rows_but_keeps_counts_and_fault_checks():
    identity = "can0/NewMessage/Fault"
    model = DashboardModel([{"id": identity}, {"id": "can0/NewMessage/Unseen"}])
    state = model.update([sample(identity, 1)], include_signals=False)
    assert state["signals"] == []
    assert state["signalCount"] == 2
    assert state["freshCount"] == 1
    assert state["unseenCount"] == 1
    assert state["alerts"][0]["id"] == identity
    assert model.update([sample(identity, 1)])["signals"][0]["displayValue"] == "1"
