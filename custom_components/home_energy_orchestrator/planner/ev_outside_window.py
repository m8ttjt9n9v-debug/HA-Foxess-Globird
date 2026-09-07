"""Pilot-site solar-spill and latest-start pre-free EV policy.

These functions preserve the source controller's two independent outside-free-
window decisions.  They contain no Home Assistant or actuator side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import floor, isfinite

from .ev import EvCurrentDecision


@dataclass(frozen=True, slots=True)
class SolarSpillInputs:
    """Coherent, normalized inputs to measured-surplus capture."""

    telemetry_valid: bool
    battery_soc_percent: float
    battery_full_threshold_percent: float
    connected: bool
    vehicle_soc_percent: float
    vehicle_soft_limit_percent: float
    in_boosted_export_window: bool
    ev_power_kw: float
    grid_export_kw: float
    battery_charge_kw: float
    voltage_v: float
    phase_count: int
    current_step_a: float
    charger_minimum_a: float
    current_ceiling_a: float


@dataclass(frozen=True, slots=True)
class SolarSpillDecision:
    """One solar-spill target plus its reconstructed measured surplus."""

    current_a: float
    reconstructed_surplus_kw: float
    phase: str


@dataclass(frozen=True, slots=True)
class PreFreePlanInputs:
    """Inputs to the pilot site's back-loaded discretionary-energy plan."""

    discretionary_ac_kwh: float
    vehicle_wall_room_kwh: float
    baseline_a: float
    current_ceiling_a: float
    voltage_v: float
    phase_count: int
    free_window_start: datetime


@dataclass(frozen=True, slots=True)
class PreFreePlan:
    """Energy, maximum additional power, duration, and latest start."""

    planned_energy_kwh: float
    maximum_additional_power_kw: float
    planned_duration_minutes: float
    planned_start: datetime | None


@dataclass(frozen=True, slots=True)
class PreFreeSessionState:
    """Restart-safe phase latch and frozen scheduled start."""

    active: bool = False
    frozen_start: datetime | None = None


@dataclass(frozen=True, slots=True)
class PreFreeSessionTransition:
    """One pre-free latch transition."""

    state: PreFreeSessionState
    phase: str


@dataclass(frozen=True, slots=True)
class PreFreeCurrentInputs:
    """Live inputs used after the latest-start latch has opened."""

    session_active: bool
    planned_energy_kwh: float
    hours_until_free: float
    voltage_v: float
    phase_count: int
    current_step_a: float
    baseline_a: float
    current_ceiling_a: float
    vehicle_soc_percent: float
    vehicle_soft_limit_percent: float


def plan_solar_spill_current(inputs: SolarSpillInputs) -> SolarSpillDecision:
    """Reconstruct spill and floor it to a whole supported current step.

    The source equation is EV power + grid export + signed battery charge.  It
    removes battery discharge and adds energy still being absorbed by a full
    battery, preventing the target from collapsing when EV charging begins.
    """
    _validate_solar_spill(inputs)
    surplus = round(
        max(inputs.ev_power_kw + inputs.grid_export_kw + inputs.battery_charge_kw, 0.0),
        3,
    )
    if not inputs.telemetry_valid:
        return SolarSpillDecision(0.0, surplus, "telemetry_unavailable")
    if inputs.battery_soc_percent < inputs.battery_full_threshold_percent:
        return SolarSpillDecision(0.0, surplus, "battery_not_full")
    if not inputs.connected or inputs.vehicle_soc_percent >= inputs.vehicle_soft_limit_percent:
        return SolarSpillDecision(0.0, surplus, "vehicle_not_eligible")
    if inputs.in_boosted_export_window:
        return SolarSpillDecision(0.0, surplus, "boosted_export_window")
    raw_current = surplus * 1000 / (inputs.voltage_v * inputs.phase_count)
    stepped = floor(raw_current / inputs.current_step_a) * inputs.current_step_a
    if stepped < inputs.charger_minimum_a:
        return SolarSpillDecision(0.0, surplus, "below_charger_minimum")
    return SolarSpillDecision(
        round(min(stepped, inputs.current_ceiling_a), 3),
        surplus,
        "solar_spill",
    )


def calculate_pre_free_plan(inputs: PreFreePlanInputs) -> PreFreePlan:
    """Port the energy cap, maximum-additional-power, and latest-start plan."""
    _validate_pre_free_plan(inputs)
    energy = round(min(inputs.discretionary_ac_kwh, inputs.vehicle_wall_room_kwh), 3)
    additional_a = max(inputs.current_ceiling_a - inputs.baseline_a, 0.0)
    power = round(additional_a * inputs.voltage_v * inputs.phase_count / 1000, 3)
    if energy <= 0 or power <= 0:
        return PreFreePlan(energy, power, 0.0, None)
    duration = round(energy / power * 60, 1)
    return PreFreePlan(
        energy,
        power,
        duration,
        inputs.free_window_start - timedelta(minutes=duration),
    )


def advance_pre_free_session(
    state: PreFreeSessionState,
    *,
    now: datetime,
    in_pre_free_window: bool,
    connected: bool,
    export_session_active: bool,
    planned_energy_kwh: float,
    vehicle_soc_percent: float,
    vehicle_soft_limit_percent: float,
    planned_start: datetime | None,
) -> PreFreeSessionTransition:
    """Latch only the phase at latest start and clear on lost eligibility."""
    _validate_session_inputs(
        state,
        now,
        planned_energy_kwh,
        vehicle_soc_percent,
        vehicle_soft_limit_percent,
        planned_start,
    )
    eligible = (
        in_pre_free_window
        and connected
        and not export_session_active
        and planned_energy_kwh > 0
        and vehicle_soc_percent < vehicle_soft_limit_percent
        and planned_start is not None
    )
    if not eligible:
        return PreFreeSessionTransition(PreFreeSessionState(), "not_eligible")
    if state.active:
        return PreFreeSessionTransition(state, "active")
    if planned_start is not None and now >= planned_start:
        return PreFreeSessionTransition(PreFreeSessionState(True, planned_start), "started")
    return PreFreeSessionTransition(PreFreeSessionState(), "waiting_latest_start")


def plan_pre_free_current(inputs: PreFreeCurrentInputs) -> EvCurrentDecision:
    """Spend no more than the live protected budget by the free boundary."""
    _validate_pre_free_current(inputs)
    if (
        not inputs.session_active
        or inputs.hours_until_free <= 0
        or inputs.planned_energy_kwh <= 0
        or inputs.vehicle_soc_percent >= inputs.vehicle_soft_limit_percent
    ):
        return EvCurrentDecision(round(inputs.baseline_a, 3), "pre_free_inactive")
    raw_additional = (
        inputs.planned_energy_kwh
        * 1000
        / inputs.hours_until_free
        / inputs.voltage_v
        / inputs.phase_count
    )
    stepped_additional = floor(raw_additional / inputs.current_step_a) * inputs.current_step_a
    maximum_additional = max(inputs.current_ceiling_a - inputs.baseline_a, 0.0)
    safe_additional = min(stepped_additional, maximum_additional)
    return EvCurrentDecision(
        round(min(inputs.baseline_a + safe_additional, inputs.current_ceiling_a), 3),
        "pre_free_live_current",
    )


def select_outside_window_current(
    *,
    baseline_a: float,
    current_ceiling_a: float,
    charger_minimum_a: float,
    pre_free_active: bool,
    pre_free_current_a: float,
    solar_spill_current_a: float,
) -> EvCurrentDecision:
    """Preserve source ordering: active backfill max spill, then spill, then baseline."""
    values = (
        baseline_a,
        current_ceiling_a,
        charger_minimum_a,
        pre_free_current_a,
        solar_spill_current_a,
    )
    if not all(isfinite(value) and value >= 0 for value in values):
        raise ValueError("outside-window currents must be finite and non-negative")
    if baseline_a > current_ceiling_a:
        raise ValueError("baseline cannot exceed current ceiling")
    if pre_free_active:
        return EvCurrentDecision(
            round(min(max(pre_free_current_a, solar_spill_current_a), current_ceiling_a), 3),
            "pre_free_or_solar_spill",
        )
    if solar_spill_current_a >= charger_minimum_a:
        return EvCurrentDecision(
            round(min(solar_spill_current_a, current_ceiling_a), 3),
            "solar_spill",
        )
    return EvCurrentDecision(round(baseline_a, 3), "protected_baseline")


def _validate_solar_spill(inputs: SolarSpillInputs) -> None:
    values = (
        inputs.battery_soc_percent,
        inputs.battery_full_threshold_percent,
        inputs.vehicle_soc_percent,
        inputs.vehicle_soft_limit_percent,
        inputs.ev_power_kw,
        inputs.grid_export_kw,
        inputs.battery_charge_kw,
        inputs.voltage_v,
        inputs.current_step_a,
        inputs.charger_minimum_a,
        inputs.current_ceiling_a,
    )
    if not all(isfinite(value) for value in values):
        raise ValueError("solar-spill inputs must be finite")
    nonnegative = (
        inputs.battery_soc_percent,
        inputs.battery_full_threshold_percent,
        inputs.vehicle_soc_percent,
        inputs.vehicle_soft_limit_percent,
        inputs.ev_power_kw,
        inputs.grid_export_kw,
        inputs.voltage_v,
        inputs.current_step_a,
        inputs.charger_minimum_a,
        inputs.current_ceiling_a,
    )
    if any(value < 0 for value in nonnegative) or inputs.phase_count < 1:
        raise ValueError("solar-spill inputs must be non-negative")
    if inputs.voltage_v <= 0 or inputs.current_step_a <= 0:
        raise ValueError("solar-spill voltage and current step must be positive")


def _validate_pre_free_plan(inputs: PreFreePlanInputs) -> None:
    values = (
        inputs.discretionary_ac_kwh,
        inputs.vehicle_wall_room_kwh,
        inputs.baseline_a,
        inputs.current_ceiling_a,
        inputs.voltage_v,
    )
    if not all(isfinite(value) and value >= 0 for value in values):
        raise ValueError("pre-free plan inputs must be finite and non-negative")
    if inputs.phase_count < 1 or inputs.voltage_v <= 0:
        raise ValueError("pre-free topology must be positive")
    if inputs.baseline_a > inputs.current_ceiling_a:
        raise ValueError("pre-free baseline cannot exceed current ceiling")
    _aware(inputs.free_window_start, "free-window start")


def _validate_session_inputs(
    state: PreFreeSessionState,
    now: datetime,
    planned_energy_kwh: float,
    vehicle_soc_percent: float,
    vehicle_soft_limit_percent: float,
    planned_start: datetime | None,
) -> None:
    _aware(now, "session time")
    if state.frozen_start is not None:
        _aware(state.frozen_start, "frozen start")
    if state.active != (state.frozen_start is not None):
        raise ValueError("active pre-free state requires exactly one frozen start")
    if planned_start is not None:
        _aware(planned_start, "planned start")
    if not all(
        isfinite(value) and value >= 0
        for value in (planned_energy_kwh, vehicle_soc_percent, vehicle_soft_limit_percent)
    ):
        raise ValueError("pre-free session inputs must be finite and non-negative")


def _validate_pre_free_current(inputs: PreFreeCurrentInputs) -> None:
    values = (
        inputs.planned_energy_kwh,
        inputs.hours_until_free,
        inputs.voltage_v,
        inputs.current_step_a,
        inputs.baseline_a,
        inputs.current_ceiling_a,
        inputs.vehicle_soc_percent,
        inputs.vehicle_soft_limit_percent,
    )
    if not all(isfinite(value) and value >= 0 for value in values):
        raise ValueError("pre-free current inputs must be finite and non-negative")
    if inputs.phase_count < 1 or inputs.voltage_v <= 0 or inputs.current_step_a <= 0:
        raise ValueError("pre-free current topology must be positive")
    if inputs.baseline_a > inputs.current_ceiling_a:
        raise ValueError("pre-free baseline cannot exceed current ceiling")


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
