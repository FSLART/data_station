"""Vehicle display rules, independent of Qt, CAN, and ROS."""

import math
import time


MISSIONS = {0: "MANUAL", 1: "ACCEL", 2: "SKIDPAD", 3: "TRACKDRIVE",
            4: "BRAKE TEST", 5: "INSPECTION", 6: "AUTOCROSS"}
AS_STATES = ("INIT", "MISSION SELECT", "JETSON WAITING", "INIT SEQUENCE",
             "READY", "DRIVING", "EBS ERROR", "EMERGENCY", "FINISHED", "MANUAL")
PRECHARGE_STATES = (
    "START", "OPEN ALL", "SWITCH HV NEG", "WAIT FOR AIR NEG TO CLOSE",
    "CHECKING AIR NEG IS CLOSED", "SWITCH PRECHARGE", "WAIT FOR PRECHARGE TO CLOSE",
    "CHECKING PRECHARGE IS CLOSED", "VERIFY CURRENT", "VERIFY BUS VOLTAGE",
    "SWITCH HV POS", "WAIT FOR AIR POS TO CLOSE", "CHECKING AIR POS IS CLOSED",
    "TURN OFF PRECHARGE", "WAIT FOR PRECHARGE TO OPEN", "CHECKING PRECHARGE IS OPEN",
    "HV ON", "WRONG", "KILL", "RX CAN",
)
INVERTER_FAULTS = (
    "NO FAULT", "HV INPUT VOLTAGE TOO HIGH", "HV INPUT VOLTAGE TOO LOW",
    "GATE DRIVER FAULT", "MOTOR PHASE OVERCURRENT", "INVERTER OVERHEAT",
    "MOTOR OVERHEAT", "POSITION SENSOR WIRING FAULT", "POSITION SENSOR READ ERROR",
    "CAN COMMAND OUT OF RANGE",
)
SAFE_CHOICES = {"none", "empty", "no fault", "ok", "normal", "off",
                "deactivated", "no open wire", "false"}


def _metric(label, value, unit="", source="", decimals=1):
    valid = value is not None
    text = f"{value:.{decimals}f}" if isinstance(value, (int, float)) else str(value)
    return {"label": label, "value": value, "text": text if valid else "—",
            "unit": unit, "valid": valid, "source": source}


class DashboardModel:
    """Present fresh samples while retaining every catalog field for inspection."""

    def __init__(self, catalog=()):
        self._warnings = {}
        self._previous_precharge = None
        self._precharge_until = 0.0
        self._precharge_sequence = False
        self._precharge_text = ""
        self.set_catalog(catalog)
        self.state = self.update([])

    def set_catalog(self, catalog):
        self._catalog = {row["id"]: dict(row) for row in catalog}

    def update(self, samples, now=None, *, include_signals=True):
        now = time.monotonic() if now is None else now
        rows = {key: dict(row, value=None, valid=False, seen=False, age=None)
                for key, row in self._catalog.items()}
        for sample in samples:
            rows.setdefault(sample["id"], {}).update(sample)

        def number(*identities):
            for identity in identities:
                row = rows.get(identity, {})
                value = row.get("value")
                if row.get("valid") and type(value) in (int, float) and math.isfinite(value):
                    return value, identity
            return None, ""

        def can(message, signal, bus="can1"):
            return number(f"{bus}/{message}/{signal}")

        def external(message, signal, raw_signal=None):
            return number(f"dds/{message.upper()}/{raw_signal or signal}",
                          f"dds/{message}/{signal}",
                          f"can0/{message.upper()}/{raw_signal or signal}")

        def autonomous_value(message, signal):
            return number(f"dds/{message}/{signal}",
                          f"dds/{message.lower()}/{signal.lower()}",
                          f"can0/{message}/{signal}")

        def direct(label, message, signal, unit="", bus="can1", scale=1, decimals=1):
            value, source = can(message, signal, bus)
            return _metric(label, value * scale if value is not None else None,
                           unit, source, decimals)

        erpm, erpm_source = can("INV1_ERPM_DUTY_VOLTAGE", "INV1_Actual_ERPM")
        rpm = erpm / 4 if erpm is not None else None
        # Preserve the installed drivetrain calibration; ERPM is divided by four.
        speed = max(0, rpm / 14.73 * (2 * math.pi * 0.2032) * 60 / 1000) if rpm is not None else None
        battery, battery_source = number("can0/Master_MSC_ID_3/overall_maximum_temperature",
                                         "can1/Master_MSC_ID_3/overall_maximum_temperature")
        driver = {
            "speed": _metric("SPEED", speed, "km/h", erpm_source, 0),
            "rpm": _metric("MOTOR", rpm, "rpm", erpm_source, 0),
            "soc": direct("ACCUMULATOR", "Master_SOC_Accumulator", "SOC_Float", "%", decimals=0),
            "tempMotor": direct("MOTOR TEMP", "INV1_Temperatures", "INV1_Actual_TempMotor", "°C"),
            "tempInverter": direct("INVERTER TEMP", "INV1_Temperatures", "INV1_Actual_TempController", "°C"),
            "tempBattery": _metric("BATTERY TEMP", battery, "°C", battery_source),
            "lvCurrent": direct("LV CURRENT", "ICD_Result", "ICD_Current", "A", "can0"),
            "hvCurrent": direct("HV CURRENT", "IVT_Msg_Result_I", "IVT_Result_I", "A", scale=0.001),
        }
        lv, lv_source = None, ""
        for message, signal, bus, scale in (
            ("PDM_LV", "LV_Voltage_mV", "can0", 1),
            ("IVT_Msg_Result_U3", "IVT_Result_U3", "can1", 0.001),
            ("Master_MSC_ID_1", "mcu_vref", "can1", 1),
        ):
            value, source = can(message, signal, bus)
            if value is not None and 5 <= value * scale <= 30:
                lv, lv_source = value * scale, source
                break
        driver["lv"] = _metric("LV BATTERY", lv, "V", lv_source)
        apps, apps_source = can("AQT1", "Throtle_Percentage", "can0")
        driver["apps"] = _metric("APPS", max(0, min(100, int(apps))) if apps is not None else None,
                                 "%", apps_source, 0)
        brakes = [number(identity) for identity in (
            "dds/ASF_SIGNALS/Brake_Pressure_Front", "dds/ASF_SIGNALS/Brake_Pressure_Rear",
            "dds/VCU_HV/Brake_pressure_Front", "dds/VCU_HV/Brake_pressure_Rear",
            "can0/ASF_SIGNALS/Brake_Pressure_Front", "can0/ASF_SIGNALS/Brake_Pressure_Rear",
            "can0/VCU_HV/Brake_pressure_Front", "can0/VCU_HV/Brake_pressure_Rear",
            "can1/INV1_MISC/INV1_Actual_Brake",
        )]
        brake, brake_source = max((item for item in brakes if item[0] is not None),
                                  default=(None, ""), key=lambda item: item[0])
        driver["brake"] = _metric("BRAKE", max(0, min(100, int(brake))) if brake is not None else None,
                                  "%", brake_source, 0)
        vcu_state, _ = can("VCU_states", "vcu_state")
        ready = "UNKNOWN" if vcu_state is None else "READY" if vcu_state in (6, 7) else "NOT READY"

        missions = [external("acu", "mission_select", "Mission_select"),
                    external("jetson", "as_mission", "AS_MISSION"),
                    autonomous_value("DV_status", "AMI_state")]
        mission, mission_source = next((item for item in missions if item[0] is not None and item[0] > 0),
                                       next((item for item in missions if item[0] is not None), (None, "")))
        acu_state, acu_source = external("acu", "acu_state", "ACU_STATE")
        as_name = AS_STATES[int(acu_state)] if acu_state is not None and acu_state in range(len(AS_STATES)) else None
        autonomous = [
            _metric("MISSION", MISSIONS.get(mission, "UNKNOWN") if mission is not None else None, source=mission_source),
            _metric("ACU STATE", as_name, source=acu_source),
        ]
        for label, message, signal, raw_signal, unit in (
            ("ASMS", "acu", "asms", "ASMS", ""),
            ("EMERGENCY", "acu", "emergency", "EMERGENCY", ""),
            ("ACU TEMP", "acu", "acu_cpu_temp", "ACU_CPU_TEMP", "°C"),
            ("JETSON TEMP", "jetson", "temperature", "TEMPERATURE", "°C"),
            ("CPU", "jetson", "cpu", "CPU", "%"),
            ("GPU", "jetson", "gpu", "GPU", "%"),
            ("JETSON STATE", "jetson", "as_state", "AS_STATE", ""),
            ("EMERGENCY CAUSE", "acu", "emergency_cause", "EMERGENCY_cause", ""),
        ):
            value, source = external(message, signal, raw_signal)
            autonomous.append(_metric(label, value, unit, source, 0))
        for label, message, signal in (
            ("LAPS", "SLAM_STATS_CAN", "Lap_counter"),
            ("CONES / LAP", "SLAM_STATS_CAN", "Cones_count_actual"),
            ("CONES TOTAL", "SLAM_STATS_CAN", "Cones_count_all"),
            ("SPEED TARGET", "DV_dynamics_1", "Speed_target"),
        ):
            value, source = autonomous_value(message, signal)
            autonomous.append(_metric(label, value, "km/h" if signal == "Speed_target" else "", source, 0))

        alerts = []

        def alert(identity, text, severity="warning"):
            alerts.append({"id": identity, "text": text, "severity": severity})

        for inverter in (1, 2):
            code, _ = can(f"INV{inverter}_Temperatures", f"INV{inverter}_Actual_FaultCode")
            if code is not None and code > 0:
                description = INVERTER_FAULTS[int(code)] if code in range(len(INVERTER_FAULTS)) else "UNKNOWN INVERTER FAULT"
                alert(f"inv{inverter}", f"INV{inverter} ERROR {code:g}: {description}", "error")
        for key, signal, limit, text in (
            ("motor", "TempMotor", 100, "MOTOR TEMPERATURE HIGH"),
            ("inverter", "TempController", 80, "INVERTER TEMPERATURE HIGH"),
            ("battery", None, 55, "BATTERY TEMPERATURE HIGH"),
        ):
            values = [can(f"INV{i}_Temperatures", f"INV{i}_Actual_{signal}")[0] for i in (1, 2)] if signal else [
                number(f"{bus}/Master_MSC_ID_3/overall_maximum_temperature")[0] for bus in ("can0", "can1")]
            hottest = max((value for value in values if value is not None), default=None)
            active = hottest is not None and hottest >= limit - (5 if self._warnings.get(key) else 0)
            self._warnings[key] = active
            if active:
                alert(key, text)
        thermal_limit = any(can(f"INV{i}_MISC", f"INV{i}_{name}_limit")[0] == 1
                            for i in (1, 2) for name in
                            ("Motor_temp", "IGBT_temp", "Capacitor_temp", "Motor_accel", "IGBT_accel"))
        if thermal_limit:
            alert("thermalLimit", "DRIVE TEMPERATURE LIMIT")
        for key, value, on, clear, maximum, text in (
            ("lv", lv, 24.5, 24.8, 30, "LOW LV BATTERY VOLTAGE"),
            ("soc", driver["soc"]["value"], 15, 17, 100, "LOW ACCUMULATOR SOC"),
        ):
            active = value is not None and 0 <= value <= maximum and value <= (clear if self._warnings.get(key) else on)
            self._warnings[key] = active
            if active:
                alert(key, text)

        signal_rows = []
        fresh_count = stale_count = unseen_count = 0
        for identity, row in rows.items():
            bus, message, signal = identity.split("/", 2)
            value = row.get("value")
            choices = row.get("choices") or {}
            choice = choices.get(value, choices.get(str(value), ""))
            seen, valid = bool(row.get("seen")), bool(row.get("valid"))
            fresh_count += valid
            stale_count += seen and not valid
            unseen_count += not seen
            display = str(value) if isinstance(value, int) else f"{value:.8g}" if isinstance(value, float) else "—"
            if include_signals:
                age = row.get("age")
                signal_rows.append({"id": identity, "bus": bus, "message": message, "signal": signal,
                                    "unit": row.get("unit") or "", "displayValue": display,
                                    "value": str(value) if isinstance(value, int) and abs(value) > 2**53 - 1 else value,
                                    "choice": str(choice), "seen": seen, "valid": valid,
                                    "status": "LIVE" if valid else "STALE" if seen else "UNSEEN",
                                    "ageText": f"{age:.1f}s" if age is not None else "—"})
            if valid and any(word in signal.lower() for word in ("error", "fault", "emergency", "fail")):
                unsafe = str(choice).lower() not in SAFE_CHOICES if choice else value is not None and value > 0.5
                if unsafe:
                    alert(identity, f"{bus} / {message} / {signal}: {choice or display}", "error")
        signal_rows.sort(key=lambda row: row["id"])

        precharge, _ = can("Master_PreCharge_ID_1", "precharge_state")
        if precharge is not None and precharge in range(len(PRECHARGE_STATES)) and precharge != self._previous_precharge:
            if precharge <= 15 or precharge == 19:
                self._precharge_sequence = True
            if self._precharge_sequence or precharge == 16:
                definition = rows.get("can1/Master_PreCharge_ID_1/precharge_state", {})
                choices = definition.get("choices") or {}
                label = choices.get(precharge, choices.get(str(precharge)))
                self._precharge_text = str(label).replace("_", " ") if label else PRECHARGE_STATES[int(precharge)]
                self._precharge_until = now + (4 if precharge == 16 else 0.5)
            if precharge == 16:
                self._precharge_sequence = False
        self._previous_precharge = precharge
        self.state = {
            "driver": driver, "autonomous": autonomous, "ready": ready,
            "alerts": alerts, "warning": " | ".join(item["text"] for item in alerts),
            "precharge": {"text": self._precharge_text,
                          "hvOn": precharge == 16,
                          "visible": precharge is not None and now < self._precharge_until},
            "signals": signal_rows, "signalCount": len(rows),
            "freshCount": fresh_count, "staleCount": stale_count,
            "unseenCount": unseen_count,
        }
        return self.state
