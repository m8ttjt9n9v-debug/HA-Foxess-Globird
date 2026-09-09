"""Configuration-driven daily EV allocation and ready-by backfill policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import floor, isfinite


@dataclass(frozen=True, slots=True)
class DailyBackfillInputs:
    """One ready-by calculation using current, normalized site energy."""

    now: datetime
    ready_at: datetime
    planning_window_start: datetime
    next_free_start: datetime
    available_ac_after_reserve_kwh: float
    protected_house_kwh: float
    protected_ev_allocation_kwh: float
    delivered_this_cycle_kwh: float
    vehicle_wall_room_kwh: float
    inverter_output_limit_kw: float
    outside_inverter_percent: float
    voltage_v: float
    phase_count: int
    current_step_a: float
    charger_minimum_a: float
    charger_maximum_a: float
    planning_buffer_minutes: float = 0.0


@dataclass(frozen=True, slots=True)
class DailyBackfillPlan:
    """Auditable energy categories and a discrete ready-by schedule."""

    remaining_allocation_kwh: float
    protected_house_kwh: float
    discretionary_energy_kwh: float
    proportional_discretionary_kwh: float
    planned_energy_kwh: float
    allocation_shortfall_kwh: float
    current_ceiling_a: float
    power_ceiling_kw: float
    duration_minutes: float
    planned_start: datetime | None
    achievable_by_ready: bool
    phase: str


def calculate_daily_backfill_plan(inputs: DailyBackfillInputs) -> DailyBackfillPlan:
    """Plan wall energy without assuming who controlled the inverter earlier.

    The protected allocation is considered first. Any energy beyond it is a
    time-proportional share of the remaining discretionary battery energy. The
    current is bounded by a configured percentage of inverter output and then
    rounded down to an actuator-supported step.
    """
    _validate(inputs)
    remaining = max(
        inputs.protected_ev_allocation_kwh - inputs.delivered_this_cycle_kwh,
        0.0,
    )
    after_house = max(
        inputs.available_ac_after_reserve_kwh - inputs.protected_house_kwh,
        0.0,
    )
    discretionary = max(after_house - remaining, 0.0)
    hours_to_ready = max((inputs.ready_at - inputs.now).total_seconds() / 3600, 0.0)
    hours_to_free = max((inputs.next_free_start - inputs.now).total_seconds() / 3600, 0.0)
    share = min(hours_to_ready / hours_to_free, 1.0) if hours_to_free > 0 else 0.0
    proportional = discretionary * share
    requested = min(remaining + proportional, after_house, inputs.vehicle_wall_room_kwh)

    raw_power_kw = inputs.inverter_output_limit_kw * inputs.outside_inverter_percent / 100
    raw_current_a = raw_power_kw * 1000 / (inputs.voltage_v * inputs.phase_count)
    stepped_current_a = floor(raw_current_a / inputs.current_step_a) * inputs.current_step_a
    current_a = min(stepped_current_a, inputs.charger_maximum_a)
    if current_a < inputs.charger_minimum_a:
        current_a = 0.0
    power_kw = current_a * inputs.voltage_v * inputs.phase_count / 1000

    shortfall = max(remaining - min(after_house, inputs.vehicle_wall_room_kwh), 0.0)
    duration = requested / power_kw * 60 if requested > 0 and power_kw > 0 else 0.0
    latest = (
        inputs.ready_at
        - timedelta(minutes=duration + inputs.planning_buffer_minutes)
        if duration > 0
        else None
    )
    achievable = shortfall <= 0 and (
        latest is None or latest >= inputs.planning_window_start
    )
    planned_start = max(latest, inputs.planning_window_start) if latest is not None else None

    if inputs.now >= inputs.ready_at:
        phase = "ready_time_passed"
    elif inputs.now < inputs.planning_window_start:
        phase = "before_planning_window"
    elif remaining <= 0:
        phase = "allocation_complete"
    elif inputs.vehicle_wall_room_kwh <= 0:
        phase = "vehicle_target_reached"
    elif after_house <= 0:
        phase = "protected_energy_unavailable"
    elif current_a <= 0:
        phase = "outside_power_ceiling_too_low"
    elif planned_start is not None and inputs.now >= planned_start:
        phase = "charge_now"
    else:
        phase = "waiting_latest_start"

    return DailyBackfillPlan(
        round(remaining, 3),
        round(inputs.protected_house_kwh, 3),
        round(discretionary, 3),
        round(proportional, 3),
        round(requested, 3),
        round(shortfall, 3),
        round(current_a, 3),
        round(power_kw, 3),
        round(duration, 1),
        planned_start,
        achievable,
        phase,
    )


def _validate(inputs: DailyBackfillInputs) -> None:
    values = (
        inputs.available_ac_after_reserve_kwh,
        inputs.protected_house_kwh,
        inputs.protected_ev_allocation_kwh,
        inputs.delivered_this_cycle_kwh,
        inputs.vehicle_wall_room_kwh,
        inputs.inverter_output_limit_kw,
        inputs.outside_inverter_percent,
        inputs.voltage_v,
        inputs.current_step_a,
        inputs.charger_minimum_a,
        inputs.charger_maximum_a,
        inputs.planning_buffer_minutes,
    )
    if not all(isfinite(value) and value >= 0 for value in values):
        raise ValueError("daily backfill inputs must be finite and non-negative")
    if inputs.now.tzinfo is None or any(
        value.tzinfo is None
        for value in (inputs.ready_at, inputs.planning_window_start, inputs.next_free_start)
    ):
        raise ValueError("daily backfill datetimes must be timezone-aware")
    if not inputs.planning_window_start <= inputs.ready_at <= inputs.next_free_start:
        raise ValueError("ready time must fall inside the pre-free planning interval")
    if inputs.phase_count < 1 or inputs.voltage_v <= 0 or inputs.current_step_a <= 0:
        raise ValueError("electrical topology must be commissioned")
    if inputs.charger_maximum_a < inputs.charger_minimum_a:
        raise ValueError("charger maximum cannot be below its minimum")
    if inputs.outside_inverter_percent > 100:
        raise ValueError("outside inverter percentage cannot exceed 100")
