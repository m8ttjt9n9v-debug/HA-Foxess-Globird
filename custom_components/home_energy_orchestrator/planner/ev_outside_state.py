"""Pure lifecycle transitions shared by outside-window EV policies."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .ev_candidates import EvStageCandidate, build_ev_stage_candidate
from .ev_daily_backfill import DailyBackfillCycleState
from .ev_outside_window import PreFreeSessionState


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
