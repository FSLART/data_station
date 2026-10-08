"""Temporary fault presets using current DBC message/signal names and units."""

# Each preset supplies a description and (message, signal, physical value) edits.
FAULT_PRESETS = {
    'Motor overtemperature': ('120 °C; Driver Gauge temperature advisory starts at 100 °C.', [
        ('INV1_Temperatures', 'INV1_Actual_TempMotor', 120),
        ('INV2_Temperatures', 'INV2_Actual_TempMotor', 120)]),
    'Motor undertemperature': ('−20 °C; tests cold telemetry. Driver Gauge has no cold-temperature advisory.', [
        ('INV1_Temperatures', 'INV1_Actual_TempMotor', -20),
        ('INV2_Temperatures', 'INV2_Actual_TempMotor', -20)]),
    'Inverter overtemperature': ('100 °C; Driver Gauge inverter advisory starts at 80 °C.', [
        ('INV1_Temperatures', 'INV1_Actual_TempController', 100),
        ('INV2_Temperatures', 'INV2_Actual_TempController', 100)]),
    'Inverter undertemperature': ('−20 °C controller telemetry. No dedicated cold advisory in Driver Gauge.', [
        ('INV1_Temperatures', 'INV1_Actual_TempController', -20),
        ('INV2_Temperatures', 'INV2_Actual_TempController', -20)]),
    'Battery overtemperature': ('65 °C plus BMS overtemperature code 2; gauge advisory starts at 55 °C.', [
        ('Master_MSC_ID_3', 'overall_maximum_temperature', 65),
        ('Master_MSC_ID_2', 'fault1_code', 2),
        ('Master_MSC_ID_1', 'fault_counter', 1)]),
    'Battery undertemperature': ('0 °C plus BMS undertemperature code 3. This DBC cannot encode negative battery temperatures.', [
        ('Master_MSC_ID_3', 'overall_minimum_temperature', 0),
        ('Master_MSC_ID_3', 'overall_maximum_temperature', 0),
        ('Master_MSC_ID_2', 'fault1_code', 3),
        ('Master_MSC_ID_1', 'fault_counter', 1)]),
    'INV1 drivetrain fault': ('Generic nonzero inverter fault code 1; tests the drivetrain warning and fault display.', [
        ('INV1_Temperatures', 'INV1_Actual_FaultCode', 1)]),
    'INV2 drivetrain fault': ('Generic nonzero inverter fault code 1 on inverter 2.', [
        ('INV2_Temperatures', 'INV2_Actual_FaultCode', 1)]),
    'Thermal derating': ('Asserts the inverter motor/IGBT/capacitor temperature-limit flags.', [
        ('INV1_MISC', 'INV1_Motor_temp_limit', 1),
        ('INV1_MISC', 'INV1_IGBT_temp_limit', 1),
        ('INV1_MISC', 'INV1_Capacitor_temp_limit', 1)]),
    'Low LV voltage': ('22 V on PDM LV and 22000 mV on IVT U3; gauge advisory starts at 24.5 V.', [
        ('PDM_LV', 'LV_Voltage_mV', 22),
        ('IVT_Msg_Result_U3', 'IVT_Result_U3', 22000)]),
    'Low SOC': ('10% on both SOC fields; gauge advisory starts at 15%.', [
        ('Master_SOC_Accumulator', 'SOC_Float', 10),
        ('Master_SOC_Accumulator', 'SOC_Integer', 10)]),
    'Low cell voltage': ('2.8 V minimum cell reading plus BMS undervoltage code 1.', [
        ('Master_MSC_ID_3', 'overall_minimum_voltage', 2.8),
        ('Master_MSC_ID_2', 'fault1_code', 1),
        ('Master_MSC_ID_1', 'fault_counter', 1)]),
    'Overcurrent / current limit': ('400 A inverter current and DC current-limit flag.', [
        ('INV1_AC_DC_current', 'INV1_Actual_ACCurrent', 400),
        ('INV1_AC_DC_current', 'INV1_Actual_DCCurrent', 400),
        ('INV1_MISC', 'INV1_DC_current_limit', 1)]),
    'Steering actuator fault': ('CubeMars DRIVER-FAULT code 3.', [
        ('CubeMars_Feedback', 'Error_Code', 3)]),
    'Emergency / shutdown': ('ACU emergency flag with SDC_OPEN cause; inspect the dashboard error list.', [
        ('ACU', 'EMERGENCY', 1), ('ACU', 'EMERGENCY_cause', 1)]),
}

# Some messages also appear in the data DBC; the dashboard reads these from /pwt.
FAULT_BUSES = {message: 'powertrain_t26' for _, edits in FAULT_PRESETS.values() for message, _, _ in edits}
FAULT_BUSES.update(PDM_LV='data_t26', CubeMars_Feedback='autonomous_t26', ACU='autonomous_t26')
