"""Pure lifecycle transitions shared by outside-window EV policies."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .ev_candidates import EvStageCandidate, build_ev_stage_candidate
from .ev_daily_backfill import DailyBackfillCycleState
from .ev_outside_window import PreFreeSessionState, SolarSpillDecision


@dataclass(frozen=True, slots=True)
class BatteryFloorAbortTransition:
    """Complete state produced when automatic paid charging hits reserve."""

    daily_state: DailyBackfillCycleState
    pre_free_state: PreFreeSessionState
    pre_free_phase: str
    target_current_a: float
    target_limit_percent: float
    decision_phase: str
    allowance_phase: str
    outside_target_active: bool
    outside_stop_requested: bool
    outside_control_active: bool
    candidates: tuple[EvStageCandidate, ...]
    continue_reconciliation: bool
    last_reason: str | None


@dataclass(frozen=True, slots=True)
class DisconnectedEvCleanupTransition:
    """Controller state cleared when the EV is no longer eligible at home."""

    daily_state: DailyBackfillCycleState
    pre_free_state: PreFreeSessionState
    pre_free_phase: str
    charge_to_full_started_at: None
    clear_charge_to_full_config: bool
    outside_control_active: bool
    outside_target_active: bool
    solar_spill: SolarSpillDecision


@dataclass(frozen=True, slots=True)
class ChargeToFullTransition:
    """Next paid-grid override timer, stop latch and config-write intent."""

    daily_state: DailyBackfillCycleState
    started_at: datetime | None
    clear_config: bool


@dataclass(frozen=True, slots=True)
class FreeWindowOutsideCleanupTransition:
    """Pre-free and outside ownership retained or cleared at window entry."""

    pre_free_state: PreFreeSessionState
    outside_control_active: bool
    outside_target_active: bool
    changed: bool


def cleanup_outside_ownership_for_free_window(
    *,
    in_free_window: bool,
    pre_free_state: PreFreeSessionState,
    outside_control_active: bool,
    outside_target_active: bool,
) -> FreeWindowOutsideCleanupTransition:
    """Clear outside ownership only for an active pre-free session at entry."""
    changed = in_free_window and pre_free_state.active
    if changed:
        return FreeWindowOutsideCleanupTransition(
            pre_free_state=PreFreeSessionState(),
            outside_control_active=False,
            outside_target_active=False,
            changed=True,
        )
    return FreeWindowOutsideCleanupTransition(
        pre_free_state=pre_free_state,
        outside_control_active=outside_control_active,
        outside_target_active=outside_target_active,
        changed=False,
    )


def advance_charge_to_full(
    daily_state: DailyBackfillCycleState,
    *,
    requested: bool,
    started_at: datetime | None,
    now: datetime,
    vehicle_soc_percent: float | None,
    maximum_limit_percent: float,
    maximum_duration: timedelta,
    protected_baseline_a: float,
) -> ChargeToFullTransition:
    """Advance start, completion, timeout or manual cancellation exactly once."""
    effective_start = started_at
    completed = False
    if requested:
        effective_start = effective_start or now
        completed = (
            vehicle_soc_percent is not None
            and vehicle_soc_percent >= maximum_limit_percent
        ) or now - effective_start >= maximum_duration

    ended_owned_session = completed or (not requested and started_at is not None)
    next_daily = daily_state
    if ended_owned_session and protected_baseline_a <= 0:
        next_daily = replace(
            daily_state,
            stop_pending=True,
            stop_attempts=0,
            last_stop_at=None,
        )
    return ChargeToFullTransition(
        daily_state=next_daily,
        started_at=None if completed or not requested else effective_start,
        clear_config=completed,
    )


def cleanup_disconnected_ev(
    daily_state: DailyBackfillCycleState,
    *,
    charge_to_full_started: bool,
    solar_spill_enabled: bool,
) -> DisconnectedEvCleanupTransition:
    """Clear retained outside-window ownership without issuing an actuator command."""
    return DisconnectedEvCleanupTransition(
        daily_state=replace(
            daily_state,
            active=False,
            session_target_kwh=0.0,
            session_start_delivered_kwh=0.0,
            frozen_start=None,
            stop_pending=False,
            stop_attempts=0,
            last_stop_at=None,
        ),
        pre_free_state=PreFreeSessionState(),
        pre_free_phase="not_eligible",
        charge_to_full_started_at=None,
        clear_charge_to_full_config=charge_to_full_started,
        outside_control_active=False,
        outside_target_active=False,
        solar_spill=SolarSpillDecision(
            0.0,
            0.0,
            "vehicle_not_eligible" if solar_spill_enabled else "disabled",
        ),
    )


def abort_outside_charge_at_battery_floor(
    daily_state: DailyBackfillCycleState,
    *,
    charge_switch_on: bool,
    charge_limit_percent: float,
) -> BatteryFloorAbortTransition:
    """Preserve the retained battery-floor abort and stop-latch semantics."""
    next_daily = replace(
        daily_state,
        active=False,
        session_target_kwh=0.0,
        session_start_delivered_kwh=0.0,
        frozen_start=None,
        stop_pending=(True if charge_switch_on else daily_state.stop_pending),
        stop_attempts=(0 if charge_switch_on else daily_state.stop_attempts),
        last_stop_at=(None if charge_switch_on else daily_state.last_stop_at),
    )
    candidate = build_ev_stage_candidate(
        "battery_floor",
        eligible=charge_switch_on,
        reason="battery_floor_reached",
        target_current_a=0.0,
        target_limit_percent=charge_limit_percent,
        command_intent=("stop_charging",) if charge_switch_on else (),
        persistence_transition=(
            "daily_backfill_stop_pending" if charge_switch_on else "none"
        ),
    )
    return BatteryFloorAbortTransition(
        daily_state=next_daily,
        pre_free_state=PreFreeSessionState(),
        pre_free_phase="battery_floor_reached",
        target_current_a=0.0,
        target_limit_percent=charge_limit_percent,
        decision_phase="battery_floor_reached",
        allowance_phase="outside_free_window",
        outside_target_active=False,
        outside_stop_requested=charge_switch_on,
        outside_control_active=charge_switch_on,
        candidates=(candidate,),
        continue_reconciliation=charge_switch_on,
        last_reason=None if charge_switch_on else "battery_floor_reached",
    )
