"""Configuration-driven daily EV allocation and ready-by backfill policy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite

from .ev import EvCommand, EvCommandPlan, estimate_vehicle_energy_to_target_kwh
from .ev_power_constraints import inverter_backed_current_ceiling


@dataclass(frozen=True, slots=True)
class DailyBackfillInputs:
    """One ready-by calculation using current, normalized site energy."""

    now: datetime
    ready_at: datetime
    planning_window_start: datetime
    next_free_start: datetime
    available_ac_after_reserve_kwh: float
    protected_house_kwh: float
    sellable_energy_kwh: float
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
class DailyBackfillPlanningEvidence:
    """Primitive live energy and configuration supplied by the HA facade."""

    now: datetime
    ready_at: datetime
    planning_window_start: datetime
    next_free_start: datetime
    available_after_reserve_kwh: float
    discharge_efficiency_percent: float
    protected_house_kwh: float
    sellable_energy_kwh: float
    protected_ev_allocation_kwh: float
    delivered_this_cycle_kwh: float
    stored_vehicle_energy_kwh: float
    vehicle_soc_percent: float
    vehicle_target_soc_percent: float
    vehicle_charge_efficiency_percent: float
    inverter_output_limit_kw: float
    outside_inverter_percent: float
    voltage_v: float
    phase_count: int
    current_step_a: float
    charger_minimum_a: float
    charger_maximum_a: float
    planning_buffer_minutes: float


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


@dataclass(frozen=True, slots=True)
class DailyBackfillEnergyState:
    """Transient samples and accumulated wall energy for one ready cycle."""

    delivered_kwh: float = 0.0
    last_sample_at: datetime | None = None
    last_actual_current_a: float | None = None


@dataclass(frozen=True, slots=True)
class DailyBackfillCycleState:
    """Ready-cycle state needed by the rollover transition."""

    ready_at: datetime | None = None
    energy: DailyBackfillEnergyState = DailyBackfillEnergyState()
    active: bool = False
    session_target_kwh: float = 0.0
    session_start_delivered_kwh: float = 0.0
    frozen_start: datetime | None = None
    stop_pending: bool = False
    stop_attempts: int = 0
    last_stop_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DailyBackfillStopState:
    """Pending direct-EVSE stop feedback and bounded retry state."""

    pending: bool = False
    attempts: int = 0
    last_attempt_at: datetime | None = None
    outside_control_active: bool = False


@dataclass(frozen=True, slots=True)
class DailyBackfillStopTransition:
    """One stop-feedback decision before any adapter execution."""

    state: DailyBackfillStopState
    plan: EvCommandPlan
    save_required: bool = False


@dataclass(frozen=True, slots=True)
class DailyBackfillSessionTransition:
    """Next daily session state and its permitted current ceiling."""

    state: DailyBackfillCycleState
    current_a: float = 0.0


_DAILY_BACKFILL_COMPLETION_PHASES = frozenset(
    {
        "ready_time_passed",
        "vehicle_target_reached",
        "protected_energy_unavailable",
        "sellable_energy_unavailable",
        "outside_power_ceiling_too_low",
    }
)


def evaluate_daily_backfill_plan(
    evidence: DailyBackfillPlanningEvidence,
) -> DailyBackfillPlan:
    """Compose normalized live energy and invoke the retained daily planner."""
    vehicle_room = estimate_vehicle_energy_to_target_kwh(
        stored_energy_kwh=evidence.stored_vehicle_energy_kwh,
        current_soc_percent=evidence.vehicle_soc_percent,
        target_soc_percent=evidence.vehicle_target_soc_percent,
        charge_efficiency_percent=evidence.vehicle_charge_efficiency_percent,
    )
    return calculate_daily_backfill_plan(
        DailyBackfillInputs(
            now=evidence.now,
            ready_at=evidence.ready_at,
            planning_window_start=evidence.planning_window_start,
            next_free_start=evidence.next_free_start,
            available_ac_after_reserve_kwh=(
                max(evidence.available_after_reserve_kwh, 0.0)
                * evidence.discharge_efficiency_percent
                / 100
            ),
            protected_house_kwh=max(evidence.protected_house_kwh, 0.0),
            sellable_energy_kwh=max(evidence.sellable_energy_kwh, 0.0),
            protected_ev_allocation_kwh=evidence.protected_ev_allocation_kwh,
            delivered_this_cycle_kwh=evidence.delivered_this_cycle_kwh,
            vehicle_wall_room_kwh=vehicle_room,
            inverter_output_limit_kw=evidence.inverter_output_limit_kw,
            outside_inverter_percent=evidence.outside_inverter_percent,
            voltage_v=evidence.voltage_v,
            phase_count=evidence.phase_count,
            current_step_a=evidence.current_step_a,
            charger_minimum_a=evidence.charger_minimum_a,
            charger_maximum_a=evidence.charger_maximum_a,
            planning_buffer_minutes=evidence.planning_buffer_minutes,
        )
    )


def advance_daily_backfill_session(
    state: DailyBackfillCycleState,
    plan: DailyBackfillPlan,
    *,
    now: datetime,
    actual_current_a: float | None,
) -> DailyBackfillSessionTransition:
    """Advance the existing start, shrink or completion lifecycle."""
    next_state = state
    session_delivered = max(
        state.energy.delivered_kwh - state.session_start_delivered_kwh,
        0.0,
    )
    if state.active and (
        session_delivered >= state.session_target_kwh
        or plan.phase in _DAILY_BACKFILL_COMPLETION_PHASES
        or plan.planned_energy_kwh <= 0
    ):
        next_state = replace(
            state,
            active=False,
            session_target_kwh=0.0,
            session_start_delivered_kwh=0.0,
            frozen_start=None,
            stop_pending=True,
            stop_attempts=0,
            last_stop_at=None,
        )
    elif not state.active and plan.phase == "charge_now" and plan.planned_energy_kwh > 0:
        next_state = replace(
            state,
            energy=replace(
                state.energy,
                last_sample_at=now,
                last_actual_current_a=actual_current_a,
            ),
            active=True,
            session_target_kwh=plan.planned_energy_kwh,
            session_start_delivered_kwh=state.energy.delivered_kwh,
            frozen_start=plan.planned_start,
            stop_pending=False,
            stop_attempts=0,
            last_stop_at=None,
        )
    if not next_state.active:
        return DailyBackfillSessionTransition(next_state)
    session_delivered = max(
        next_state.energy.delivered_kwh
        - next_state.session_start_delivered_kwh,
        0.0,
    )
    next_state = replace(
        next_state,
        session_target_kwh=min(
            next_state.session_target_kwh,
            session_delivered + plan.planned_energy_kwh,
        ),
    )
    return DailyBackfillSessionTransition(next_state, plan.current_ceiling_a)


def reconcile_daily_backfill_stop(
    state: DailyBackfillStopState,
    *,
    charge_switch_on: bool,
    now: datetime,
    maximum_attempts: int,
    retry_interval: timedelta,
) -> DailyBackfillStopTransition:
    """Plan one bounded stop-feedback cycle without executing a command."""
    if not charge_switch_on:
        return DailyBackfillStopTransition(
            DailyBackfillStopState(),
            EvCommandPlan((), "daily_backfill_stopped"),
            save_required=True,
        )
    if state.attempts >= maximum_attempts:
        return DailyBackfillStopTransition(
            state,
            EvCommandPlan((), "daily_backfill_stop_fault_maximum_attempts"),
        )
    if (
        state.last_attempt_at is not None
        and now - state.last_attempt_at < retry_interval
    ):
        return DailyBackfillStopTransition(
            state,
            EvCommandPlan((), "daily_backfill_stop_awaiting_feedback"),
        )
    return DailyBackfillStopTransition(
        state,
        EvCommandPlan((EvCommand("stop_charging"),), "daily_backfill_complete"),
    )


def record_daily_backfill_stop_attempt(
    state: DailyBackfillStopState,
    now: datetime,
) -> DailyBackfillStopState:
    """Record one successfully issued stop command."""
    return DailyBackfillStopState(
        pending=state.pending,
        attempts=state.attempts + 1,
        last_attempt_at=now,
        outside_control_active=state.outside_control_active,
    )


def roll_daily_backfill_cycle(
    state: DailyBackfillCycleState,
    ready_at: datetime,
) -> DailyBackfillCycleState:
    """Reset cycle-scoped energy and retain any pre-existing stop obligation."""
    if state.ready_at == ready_at:
        return state
    return DailyBackfillCycleState(
        ready_at=ready_at,
        energy=DailyBackfillEnergyState(),
        active=False,
        session_target_kwh=0.0,
        session_start_delivered_kwh=0.0,
        frozen_start=None,
        stop_pending=True if state.active else state.stop_pending,
        stop_attempts=0 if state.active else state.stop_attempts,
        last_stop_at=None if state.active else state.last_stop_at,
    )


def integrate_daily_backfill_energy(
    state: DailyBackfillEnergyState,
    *,
    active: bool,
    now: datetime,
    actual_current_a: float | None,
    voltage_v: float,
    phase_count: int,
    maximum_sample_age_seconds: float,
) -> DailyBackfillEnergyState:
    """Integrate confirmed wall current only while daily backfill owns charging."""
    delivered_kwh = state.delivered_kwh
    previous_at = state.last_sample_at
    previous_current = state.last_actual_current_a
    if (
        active
        and actual_current_a is not None
        and previous_at is not None
        and previous_current is not None
        and now >= previous_at
        and now - previous_at <= timedelta(seconds=maximum_sample_age_seconds)
    ):
        hours = (now - previous_at).total_seconds() / 3600
        average_current = (previous_current + actual_current_a) / 2
        delivered_kwh += average_current * voltage_v * phase_count / 1000 * hours
    return DailyBackfillEnergyState(
        delivered_kwh,
        now if active else None,
        actual_current_a if active else None,
    )


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
    # A ready-by allocation may reserve energy from an earlier export, but it
    # must never manufacture a new charging budget.  The pilot's pre-free
    # controller only spends energy which the live ZEROHERO export ledger still
    # regards as genuinely sellable.  Keep that same boundary here.
    requested = min(
        remaining + proportional,
        after_house,
        inputs.sellable_energy_kwh,
        inputs.vehicle_wall_room_kwh,
    )

    current_a = inverter_backed_current_ceiling(
        inverter_output_limit_kw=inputs.inverter_output_limit_kw,
        outside_inverter_percent=inputs.outside_inverter_percent,
        voltage_v=inputs.voltage_v,
        phase_count=inputs.phase_count,
        current_step_a=inputs.current_step_a,
        charger_maximum_a=inputs.charger_maximum_a,
    )
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
    elif inputs.sellable_energy_kwh <= 0:
        phase = "sellable_energy_unavailable"
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
        inputs.sellable_energy_kwh,
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
    # A live service-headroom ceiling may legitimately fall below the physical
    # charging minimum. That is the planner's fail-closed
    # ``outside_power_ceiling_too_low`` result, not invalid commissioning.
    if inputs.outside_inverter_percent > 100:
        raise ValueError("outside inverter percentage cannot exceed 100")
