"""Deterministic dashboard sample; never publishes onto the vehicle network."""


SAMPLES = {
    ("can1", "INV1_ERPM_DUTY_VOLTAGE"): {"INV1_Actual_ERPM": 56000},
    ("can1", "INV1_Temperatures"): {
        "INV1_Actual_TempController": 46.2, "INV1_Actual_TempMotor": 68.4,
        "INV1_Actual_FaultCode": 0},
    ("can1", "INV2_Temperatures"): {
        "INV2_Actual_TempController": 47.1, "INV2_Actual_TempMotor": 67.9,
        "INV2_Actual_FaultCode": 0},
    ("can1", "Master_SOC_Accumulator"): {"SOC_Float": 78},
    ("can0", "PDM_LV"): {"LV_Voltage_mV": 25.7},
    ("can0", "AQT1"): {"Throtle_Percentage": 42},
    ("can0", "ICD_Result"): {"ICD_Current": 4.65},
    ("can0", "ICD_Response"): {"ICD_ArticleNumber": 72057594037927935},
    ("can1", "IVT_Msg_Result_I"): {"IVT_Result_I": 48000},
    ("can1", "Master_MSC_ID_3"): {"overall_maximum_temperature": 34.2},
    ("can1", "VCU_states"): {"vcu_state": 6},
    ("dds", "JETSON"): {"AS_STATE": 3, "AS_MISSION": 3, "TEMPERATURE": 51,
                         "CPU": 36, "GPU": 22, "EMERGENCY_CAUSE": 0},
    ("dds", "ACU"): {"ACU_STATE": 5, "Mission_select": 3, "ASMS": 1,
                      "EMERGENCY": 0, "EMERGENCY_cause": 0, "ACU_CPU_TEMP": 43},
    ("dds", "ASF_SIGNALS"): {"Brake_Pressure_Front": 0, "Brake_Pressure_Rear": 0},
    ("dds", "SLAM_STATS_CAN"): {"Lap_counter": 4, "Cones_count_actual": 36,
                                 "Cones_count_all": 142},
    ("dds", "DV_dynamics_1"): {"Speed_target": 70},
}


def populate_demo(receiver):
    if not getattr(receiver, "_demo_registered", False):
        for (bus, message), values in SAMPLES.items():
            receiver.store.register(bus, message, {name: {} for name in values})
        receiver.catalog_version += 1
        receiver._demo_registered = True
    for (bus, message), values in SAMPLES.items():
        receiver.store.update(bus, message, values)
