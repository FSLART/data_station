"""Decode fixed CAN payloads with the committed C implementation, without ROS."""
import ctypes
from pathlib import Path
import subprocess

import pytest


class Aqt7(ctypes.Structure):
    _fields_ = [("susp_l", ctypes.c_int16), ("susp_r", ctypes.c_int16),
                ("ntc_1", ctypes.c_uint8)]


class MasterMscId3(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint16) for name in (
        "overall_maximum_voltage", "overall_maximum_temperature",
        "overall_minimum_voltage", "overall_minimum_temperature",
    )]


class Aqt4(ctypes.Structure):
    _fields_ = [("st_angle", ctypes.c_int16), ("susp_l", ctypes.c_int16),
                ("susp_r", ctypes.c_int16), ("inertia", ctypes.c_uint8),
                ("emergency", ctypes.c_uint8)]


class VcuStates(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint8) for name in (
        "vcu_state", "throttle_status", "tc_state", "tv_state",
        "front_wheel_speed_ok", "steering_angle_ok", "front_left_speed",
        "front_right_speed", "tc_factor_rear_left", "tc_factor_rear_right",
    )] + [("tv_shift", ctypes.c_int8), ("road_wheel_angle", ctypes.c_int8),
         ("vcu_states_counter", ctypes.c_uint8)]


@pytest.fixture(scope="module")
def decoders(tmp_path_factory):
    generated = (Path(__file__).resolve().parents[1]
                 / "LART_Car_Dashboard_v1/src/ui/generated")
    library = tmp_path_factory.mktemp("dbc-decoding") / "decoders.so"
    subprocess.run([
        "cc", "-std=c99", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
        str(generated / "data_t26.c"), str(generated / "autonomous_t26.c"),
        str(generated / "powertrain_t26.c"),
        "-o", str(library),
    ], check=True)
    return ctypes.CDLL(str(library))


def unpack(decoders, name, message_type, payload):
    function = getattr(decoders, f"{name}_unpack")
    function.argtypes = [ctypes.POINTER(message_type),
                         ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]
    function.restype = ctypes.c_int
    raw = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
    message = message_type()
    result = function(ctypes.byref(message), raw, len(payload))
    return result, message


def physical(decoders, name, message):
    values = []
    for field, raw_type in message._fields_:
        function = getattr(decoders, f"{name}_{field}_decode")
        function.argtypes = [raw_type]
        function.restype = ctypes.c_double
        values.append(function(getattr(message, field)))
    return values


@pytest.mark.parametrize(("payload", "expected"), [
    # Little endian raw: -1234, +2345, 77; trailing padding is unrelated.
    ("2e fb 29 09 4d a5 5a ff", [-123.4, 234.5, 77.0]),
    # Both signed suspension limits and an unsigned temperature above 127.
    ("ff 7f 00 80 ff 00 00 00", [3276.7, -3276.8, 255.0]),
])
def test_aqt7_decodes_suspension_and_separate_temperature(decoders, payload, expected):
    result, message = unpack(decoders, "data_t26_aqt7", Aqt7,
                             bytes.fromhex(payload))
    assert result == 0
    assert physical(decoders, "data_t26_aqt7", message) == pytest.approx(expected)


def test_aqt7_rejects_previous_four_byte_payload(decoders):
    result, _ = unpack(decoders, "data_t26_aqt7", Aqt7,
                       bytes.fromhex("2e fb 29 09"))
    assert result == -22  # EINVAL: the current wire frame requires eight bytes.


def test_data_master_msc_id_3_decodes_physical_voltage_and_temperature(decoders):
    # Raw 4200, 4512, 3150, 2735 => volts x0.001, temperatures x0.01.
    result, message = unpack(decoders, "data_t26_master_msc_id_3", MasterMscId3,
                             bytes.fromhex("68 10 a0 11 4e 0c af 0a"))
    assert result == 0
    assert physical(decoders, "data_t26_master_msc_id_3", message) == pytest.approx(
        [4.2, 45.12, 3.15, 27.35])


def test_autonomous_aqt4_decodes_signed_suspension(decoders):
    # Raw steering +123, suspension -1000 / -1, inertia on, emergency off.
    result, message = unpack(decoders, "autonomous_t26_aqt4", Aqt4,
                             bytes.fromhex("7b 00 18 fc ff ff 01"))
    assert result == 0
    assert physical(decoders, "autonomous_t26_aqt4", message) == pytest.approx(
        [12.3, -100.0, -0.1, 1.0, 0.0])


@pytest.mark.parametrize(("payload", "expected"), [
    # Packed status flags, byte-crossing speeds/factors, signed shift and angle.
    ("96 fa bd 64 15 f9 bd 9a",
     [6, 1, 5, 6, 1, 1, 61.5, 100.5, 42, 100, -17, -21.25, 9]),
    ("ff df 7f 00 00 19 08 f8",
     [15, 7, 7, 7, 0, 1, 127.5, 0, 0, 100, -64, -32, 15]),
    ("00 20 80 7f 32 e0 f7 07",
     [0, 0, 0, 0, 1, 0, 0, 127.5, 100, 0, 63, 31.75, 0]),
])
def test_powertrain_vcu_states_decodes_packed_debug_signals(decoders, payload, expected):
    result, message = unpack(decoders, "powertrain_t26_vcu_states", VcuStates,
                             bytes.fromhex(payload))
    assert result == 0
    assert physical(decoders, "powertrain_t26_vcu_states", message) == pytest.approx(expected)


def test_powertrain_vcu_states_rejects_truncated_frame(decoders):
    result, _ = unpack(decoders, "powertrain_t26_vcu_states", VcuStates,
                       bytes.fromhex("96 fa bd 64 15 f9 bd"))
    assert result == -22


@pytest.mark.parametrize(("name", "fields", "raw_type", "payload", "expected"), [
    ("imu_acceleration", "acceleration_x acceleration_y acceleration_z",
     ctypes.c_int16, "2e fb 29 09 00 80", [-12.34, 23.45, -327.68]),
    ("imu_angular_velocity", "angular_velocity_x angular_velocity_y angular_velocity_z",
     ctypes.c_int16, "2e fb 29 09 ff 7f", [-1.234, 2.345, 32.767]),
    ("imu_gnss_position", "latitude longitude", ctypes.c_int32,
     "80 74 d2 1a 00 17 5b ca", [45, -90]),
    ("imu_gnss_altitude", "altitude", ctypes.c_int32,
     "c0 1d fe ff", [-123.456]),
    ("imu_orientation", "quaternion_w quaternion_x quaternion_y quaternion_z",
     ctypes.c_int16, "10 27 78 ec c4 09 00 00", [1, -0.5, 0.25, 0]),
    ("imu_velocity", "velocity_x velocity_y velocity_z", ctypes.c_int16,
     "2e fb 29 09 00 80", [-12.34, 23.45, -327.68]),
    ("imu_euler", "roll pitch yaw", ctypes.c_int16,
     "b0 b9 28 23 50 46", [-180, 90, 180]),
    ("imu_temperature", "temperature", ctypes.c_int16,
     "2e fb", [-12.34]),
    ("imu_filter_velocity", "velocity_x velocity_y velocity_z", ctypes.c_int16,
     "2e fb 29 09 00 80", [-12.34, 23.45, -327.68]),
    ("imu_free_acceleration", "free_acceleration_x free_acceleration_y free_acceleration_z",
     ctypes.c_int16, "2e fb 29 09 ff 7f", [-12.34, 23.45, 327.67]),
])
def test_autonomous_imu_physical_values_and_frame_lengths(
        decoders, name, fields, raw_type, payload, expected):
    message_type = type(name, (ctypes.Structure,), {
        "_fields_": [(field, raw_type) for field in fields.split()],
    })
    decoder = f"autonomous_t26_{name}"
    raw = bytes.fromhex(payload)
    result, message = unpack(decoders, decoder, message_type, raw)
    assert result == 0
    assert physical(decoders, decoder, message) == pytest.approx(expected)
    result, _ = unpack(decoders, decoder, message_type, raw[:-1])
    assert result == -22


def test_autonomous_imu_status_preserves_device_bit_layout(decoders):
    fields = (
        "self_test filter_valid gnss_fix no_rotation_update_status "
        "representative_motion clock_bias_estimation clip_acc_x clip_acc_y "
        "clip_acc_z clip_gyr_x clip_gyr_y clip_gyr_z clip_mag_x clip_mag_y "
        "clip_mag_z clipping_indication sync_in_marker sync_out_marker "
        "filter_mode gnss_time_pulse rtk_status"
    ).split()
    message_type = type("ImuStatus", (ctypes.Structure,), {
        "_fields_": [(field, ctypes.c_uint8) for field in fields],
    })
    # Bits 0, 2, 4, 6, 8, 10, 12, 14, 16, 19, 21, 24, 26, 28.
    result, message = unpack(decoders, "autonomous_t26_imu_status", message_type,
                             bytes.fromhex("55 55 29 15"))
    assert result == 0
    assert physical(decoders, "autonomous_t26_imu_status", message) == [
        1, 0, 1, 2, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 2, 1, 2,
    ]
    result, _ = unpack(decoders, "autonomous_t26_imu_status", message_type,
                       bytes.fromhex("55 55 29"))
    assert result == -22
