"""M2 - PLC Controller.

Runs the control logic for the beverage line: a start/stop state machine,
per-stage on/off + simple proportional control, and fault detection that
turns abnormal sensor patterns into alarm codes.

This module reads the plant's sensor + feedback pins and the operator buttons,
and produces actuator command pins plus an alarm code and PLC state. It never
touches physics directly - that is M1's job.

Port specification (see README section 5):
    inputs : tank_level, pasteur_temp, cooler_temp, flow_rate, bottle_present,
             pump_feedback, valve_feedback, operator_start, operator_stop
    outputs: pump_cmd, inlet_valve_cmd, heater_power_cmd, cooling_valve_cmd,
             conveyor_cmd, fill_valve_cmd, capper_cmd, alarm_code, plc_state
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set

import config


@dataclass
class PLCController:
    """Scan-cycle controller. Call :meth:`step` once per update period."""

    state: str = config.PLC_IDLE
    alarm_code: int = config.ALARM_NONE

    # --- proportional heater control memory ---
    heater_power_cmd: float = 0.0

    # --- proportional cooling control memory ---
    cooling_valve_cmd: float = 0.0

    # --- discrete fill control memory ---
    _fill_timer: int = field(default=0, repr=False)

    # last pump command issued (used by the no-flow fault detector) ---
    last_pump_cmd: int = field(default=0, repr=False)

    # --- fault-detection debounce counters ---
    _temp_stuck_count: int = field(default=0, repr=False)
    _no_flow_count: int = field(default=0, repr=False)
    _temp_range_count: int = field(default=0, repr=False)
    _prev_temp: float = field(default=-999.0, repr=False)
    # True once the pasteurizer has reached the safe band at least once; used so
    # the normal warm-up ramp (temp below safe-min) does not raise a false alarm.
    _warmed_up: bool = field(default=False, repr=False)

    def reset(self) -> None:
        self.state = config.PLC_IDLE
        self.alarm_code = config.ALARM_NONE
        self.heater_power_cmd = 0.0
        self.cooling_valve_cmd = 0.0
        self._fill_timer = 0
        self.last_pump_cmd = 0
        self._temp_stuck_count = 0
        self._no_flow_count = 0
        self._temp_range_count = 0
        self._prev_temp = -999.0
        self._warmed_up = False

    # ------------------------------------------------------------------
    def step(self, sensors: Dict,
             manual_actuators: Optional[Set[str]] = None) -> Dict:
        """One scan cycle: update the state machine, run control, detect faults."""
        if manual_actuators is None:
            manual_actuators = set()
        operator_start = int(sensors.get("operator_start", 0))
        operator_stop = int(sensors.get("operator_stop", 0))
        data_stale = int(sensors.get("data_stale_flag", 0))

        # 1. State machine ----------------------------------------------
        self._update_state(operator_start, operator_stop)

        # 2. Fault detection (runs whenever the line is active) ----------
        self._detect_faults(sensors, data_stale, manual_actuators)

        # 3. Control logic ----------------------------------------------
        running = self.state in (config.PLC_RUNNING, config.PLC_STARTING)
        if self.alarm_code in (config.ALARM_PUMP_NO_FLOW,
                               config.ALARM_TEMP_OUT_OF_RANGE,
                               config.ALARM_SENSOR_TEMP_STUCK):
            # Safety: on a serious alarm move to FAULT and shed dangerous outputs.
            self.state = config.PLC_FAULT
            running = False

        if running:
            cmds = self._run_control(sensors)
        else:
            cmds = self._safe_outputs()

        cmds["alarm_code"] = self.alarm_code
        cmds["plc_state"] = self.state
        return cmds

    # ------------------------------------------------------------------
    def _update_state(self, operator_start: int, operator_stop: int) -> None:
        if operator_stop:
            self.state = config.PLC_STOPPING
        if self.state == config.PLC_STOPPING:
            self.state = config.PLC_IDLE
            return

        if self.state == config.PLC_FAULT:
            # Stay in FAULT until the alarm clears (operator fixed/reset the fault).
            if self.alarm_code == config.ALARM_NONE:
                self.state = config.PLC_IDLE
            return

        if operator_start and self.state == config.PLC_IDLE:
            self.state = config.PLC_STARTING
        elif self.state == config.PLC_STARTING:
            self.state = config.PLC_RUNNING

    # ------------------------------------------------------------------
    def _run_control(self, sensors: Dict) -> Dict:
        """Per-stage control law, executed only while the line runs."""
        tank_level = float(sensors.get("tank_level", 0.0))
        pasteur_temp = float(sensors.get("pasteur_temp", 0.0))
        cooler_temp = float(sensors.get("cooler_temp", 0.0))
        bottle_present = int(sensors.get("bottle_present", 0))

        # S1 Raw tank: hysteresis level control on the inlet valve (0-100% proportional).
        inlet_valve_cmd = 100.0 if tank_level < config.TANK_LEVEL_LOW else 0.0
        if tank_level >= config.TANK_LEVEL_HIGH:
            inlet_valve_cmd = 0.0

        # Feed pump: run at 100% while there is liquid to move.
        pump_cmd = 100.0 if tank_level > config.TANK_LEVEL_MIN_PUMP else 0.0

        # S2 Pasteurizer: proportional heater control toward the set-point.
        error = config.PASTEUR_SETPOINT - pasteur_temp
        self.heater_power_cmd = _clamp(self.heater_power_cmd + 4.0 * error, 0.0, 100.0)
        heater_power_cmd = round(self.heater_power_cmd, 1)

        # S3 Cooler: proportional-integral cooling toward the set-point.
        cool_error = cooler_temp - config.COOLER_SETPOINT  # positive when too warm
        self.cooling_valve_cmd = _clamp(
            self.cooling_valve_cmd + 4.0 * cool_error, 0.0, 100.0)
        cooling_valve_cmd = round(self.cooling_valve_cmd, 1)

        # S4 Filler + S5 Conveyor/Capper: only run when BOTH pasteurization
        # and cooling are complete — no bottling of unready or
        # uncooled product.
        ready = pasteur_temp >= config.PASTEUR_SAFE_MIN
        cooled = cooler_temp <= config.COOLER_MAX_BOTTLING
        ready = ready and cooled

        # S4 Filler: open the fill valve for a fixed time when a bottle is present.
        if bottle_present and ready:
            self._fill_timer = config.FILL_DURATION_TICKS
        fill_valve_cmd = 1 if (self._fill_timer > 0 and ready) else 0
        if self._fill_timer > 0:
            self._fill_timer -= 1

        # S5 Conveyor + capper
        conveyor_cmd = 100.0 if ready else 0.0
        capper_cmd = 1 if ready else 0

        self.last_pump_cmd = pump_cmd
        return {
            "pump_cmd": pump_cmd,
            "inlet_valve_cmd": inlet_valve_cmd,
            "heater_power_cmd": heater_power_cmd,
            "cooling_valve_cmd": cooling_valve_cmd,
            "conveyor_cmd": conveyor_cmd,
            "fill_valve_cmd": fill_valve_cmd,
            "capper_cmd": capper_cmd,
        }

    def _safe_outputs(self) -> Dict:
        """All actuators off - used in IDLE / STOPPING / FAULT."""
        self.heater_power_cmd = 0.0
        self.cooling_valve_cmd = 0.0
        self._fill_timer = 0
        self.last_pump_cmd = 0
        return {
            "pump_cmd": 0.0,
            "inlet_valve_cmd": 0.0,
            "heater_power_cmd": 0.0,
            "cooling_valve_cmd": 0.0,
            "conveyor_cmd": 0.0,
            "fill_valve_cmd": 0,
            "capper_cmd": 0,
        }

    # ------------------------------------------------------------------
    def _detect_faults(self, sensors: Dict, data_stale: int,
                        manual_actuators: Set[str]) -> None:
        """Translate abnormal sensor patterns into a latched alarm code."""
        pasteur_temp = float(sensors.get("pasteur_temp", 0.0))
        flow_rate = float(sensors.get("flow_rate", 0.0))
        pump_feedback = int(sensors.get("pump_feedback", 0))
        running = self.state in (config.PLC_RUNNING, config.PLC_STARTING)
        heater_manual = "heater_power_cmd" in manual_actuators

        # Infrastructure fault: stale data takes priority.
        if data_stale:
            self.alarm_code = config.ALARM_DATA_STALE
            return

        # Track warm-up so the normal ramp (temp < safe-min) is not flagged.
        if not running:
            self._warmed_up = False
        elif pasteur_temp >= config.PASTEUR_SAFE_MIN:
            self._warmed_up = True

        # Sensor fault: a live temperature always carries process noise, so a
        # perfectly constant reading across cycles means the sensor is stuck.
        if running and pasteur_temp == self._prev_temp:
            self._temp_stuck_count += 1
        else:
            self._temp_stuck_count = 0

        # Equipment fault: pump commanded on but no feedback and no flow.
        if self.last_pump_cmd and pump_feedback == 0 and flow_rate <= 0.1:
            self._no_flow_count += 1
        else:
            self._no_flow_count = 0

        # Process fault: pasteurization temperature outside the safe band, but
        # only once the line is running and has finished warming up.
        # Skip when the heater is under manual control — the operator is
        # responsible for maintaining safe temperature.
        out_of_range = (pasteur_temp > config.PASTEUR_SAFE_MAX
                        or pasteur_temp < config.PASTEUR_SAFE_MIN)
        if running and self._warmed_up and out_of_range and not heater_manual:
            self._temp_range_count += 1
        else:
            self._temp_range_count = 0

        # Auto-clear TEMP_OUT_OF_RANGE when temperature returns to the safe band
        # (hardware faults like PUMP_NO_FLOW and SENSOR_TEMP_STUCK stay latched).
        if self.alarm_code == config.ALARM_TEMP_OUT_OF_RANGE and not out_of_range:
            self.alarm_code = config.ALARM_NONE
            self._temp_range_count = 0
            if self.state == config.PLC_FAULT:
                self.state = config.PLC_IDLE

        # Latch the first alarm that exceeds its debounce threshold.
        if self.alarm_code == config.ALARM_NONE:
            if self._no_flow_count >= config.ALARM_DEBOUNCE_TICKS:
                self.alarm_code = config.ALARM_PUMP_NO_FLOW
            elif self._temp_stuck_count >= config.ALARM_DEBOUNCE_TICKS:
                self.alarm_code = config.ALARM_SENSOR_TEMP_STUCK
            elif self._temp_range_count >= config.ALARM_DEBOUNCE_TICKS:
                self.alarm_code = config.ALARM_TEMP_OUT_OF_RANGE

        self._prev_temp = pasteur_temp

    def acknowledge(self) -> None:
        """Operator acknowledges / clears the current alarm."""
        self.alarm_code = config.ALARM_NONE
        self._temp_stuck_count = 0
        self._no_flow_count = 0
        self._temp_range_count = 0
        if self.state == config.PLC_FAULT:
            self.state = config.PLC_IDLE


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
