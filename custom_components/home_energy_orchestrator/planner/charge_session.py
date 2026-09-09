"""Latched, bounded Local Modbus free-window charge session.

This is the charge-direction counterpart to the proven ZEROHERO session. It
plans transitions only; Home Assistant service calls remain in the shared
fail-closed FoxESS adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .foxess import (
    ControlDecision,
    FoxessCommandPlan,
    FoxessObservation,
    foxess_response_matches,
    plan_foxess_commands,
)


@dataclass(frozen=True, slots=True)
class ChargeSessionState:
    """Persistable free-window charge-session state."""

    phase: str = "idle"
    requested_power_kw: float = 0.0
    attempts: int = 0
    last_command_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ChargeSessionTransition:
    """The next state and optional adapter-neutral command plan."""

    state: ChargeSessionState
    plan: FoxessCommandPlan
    reason: str


def advance_charge_session(
    state: ChargeSessionState,
    observation: FoxessObservation,
    *,
    now: datetime,
    source_available: bool,
    window_active: bool,
    eligible_to_start: bool,
    requested_charge_power_kw: float,
    charge_power_max_kw: float,
    finish_requested: bool = False,
    acceptance_timeout: timedelta = timedelta(seconds=30),
    retry_after: timedelta = timedelta(seconds=30),
    max_attempts: int = 3,
    tolerance_kw: float = 0.01,
) -> ChargeSessionTransition:
    """Advance one fixed-power schedule with bounded restart recovery.

    SoC eligibility is intentionally a start condition only. Once started, the
    session remains latched for the whole window so target-boundary changes do
    not flap the inverter between Force Charge and Self Use.
    """
    _validate_inputs(
        state,
        now,
        requested_charge_power_kw,
        charge_power_max_kw,
        acceptance_timeout,
        retry_after,
        max_attempts,
    )
    new_session_desired = (
        source_available
        and window_active
        and eligible_to_start
        and not finish_requested
        and requested_charge_power_kw > 0
    )
    requested = round(min(requested_charge_power_kw, charge_power_max_kw), 3)
    if (
        state.phase in {"starting", "active", "recovering"}
        and 0 < requested < state.requested_power_kw
    ):
        # A reduced commissioned or native entity limit takes effect during a
        # running session. An increased limit never raises the frozen request.
        state = replace(
            state,
            phase="starting",
            requested_power_kw=requested,
            attempts=0,
            last_command_at=None,
        )
    if not source_available:
        if state.phase in {"starting", "active", "stopping", "recovering"}:
            return ChargeSessionTransition(
                replace(state, phase="recovering"),
                FoxessCommandPlan((), "source_unavailable"),
                "source_unavailable",
            )
        return ChargeSessionTransition(
            replace(state, phase="idle", attempts=0, last_command_at=None),
            FoxessCommandPlan((), "source_unavailable"),
            "source_unavailable",
        )

    if state.phase == "recovering":
        if window_active and not finish_requested and state.requested_power_kw > 0:
            return _start(
                replace(state, phase="idle", attempts=0, last_command_at=None),
                observation,
                now,
                state.requested_power_kw,
                charge_power_max_kw,
                tolerance_kw,
            )
        return _stop(state, observation, now, tolerance_kw)

    if state.phase == "idle":
        if not new_session_desired or requested <= 0:
            return _idle("not_eligible")
        return _start(state, observation, now, requested, charge_power_max_kw, tolerance_kw)

    if state.phase == "starting":
        decision = ControlDecision(
            "force_charge", state.requested_power_kw, "free_window_ready"
        )
        if not window_active or finish_requested:
            return _stop(state, observation, now, tolerance_kw)
        if foxess_response_matches(decision, observation, tolerance_kw=tolerance_kw):
            return ChargeSessionTransition(
                replace(state, phase="active", attempts=0),
                FoxessCommandPlan((), "feedback_matches_plan"),
                "active",
            )
        if _within_retry(state, now, acceptance_timeout):
            return ChargeSessionTransition(
                state, FoxessCommandPlan((), "awaiting_feedback"), "awaiting_feedback"
            )
        if state.attempts >= max_attempts:
            return ChargeSessionTransition(
                state,
                FoxessCommandPlan((), "max_attempts_exceeded"),
                "max_attempts_exceeded",
            )
        return _start(
            state,
            observation,
            now,
            state.requested_power_kw,
            charge_power_max_kw,
            tolerance_kw,
        )

    if state.phase == "active":
        if not window_active or finish_requested:
            return _stop(state, observation, now, tolerance_kw)
        decision = ControlDecision(
            "force_charge", state.requested_power_kw, "free_window_ready"
        )
        if foxess_response_matches(decision, observation, tolerance_kw=tolerance_kw):
            return ChargeSessionTransition(state, FoxessCommandPlan((), "latched"), "latched")
        if _within_retry(state, now, retry_after):
            return ChargeSessionTransition(
                state, FoxessCommandPlan((), "awaiting_feedback"), "awaiting_feedback"
            )
        if state.attempts >= max_attempts:
            return ChargeSessionTransition(
                state,
                FoxessCommandPlan((), "max_attempts_exceeded"),
                "max_attempts_exceeded",
            )
        return _start(
            replace(state, phase="starting"),
            observation,
            now,
            state.requested_power_kw,
            charge_power_max_kw,
            tolerance_kw,
        )

    if state.phase == "stopping":
        if new_session_desired:
            return _start(
                replace(state, phase="idle", attempts=0),
                observation,
                now,
                requested,
                charge_power_max_kw,
                tolerance_kw,
            )
        decision = ControlDecision("restore_self_use", 0.0, "free_window_finished")
        if foxess_response_matches(decision, observation, tolerance_kw=tolerance_kw):
            return _idle("restored_self_use")
        if _within_retry(state, now, acceptance_timeout):
            return ChargeSessionTransition(
                state, FoxessCommandPlan((), "awaiting_feedback"), "awaiting_feedback"
            )
        if state.attempts >= max_attempts:
            return ChargeSessionTransition(
                state,
                FoxessCommandPlan((), "max_attempts_exceeded"),
                "max_attempts_exceeded",
            )
        return _stop(state, observation, now, tolerance_kw)

    raise ValueError(f"unsupported charge session phase: {state.phase}")


def _start(state, observation, now, requested, maximum, tolerance):
    bounded = round(min(requested, maximum), 3)
    decision = ControlDecision("force_charge", bounded, "free_window_ready")
    if foxess_response_matches(decision, observation, tolerance_kw=tolerance):
        return ChargeSessionTransition(
            replace(state, phase="active", requested_power_kw=bounded, attempts=0),
            FoxessCommandPlan((), "feedback_matches_plan"),
            "active",
        )
    plan = plan_foxess_commands(
        decision,
        observation,
        charge_power_max_kw=maximum,
        discharge_power_max_kw=maximum,
    )
    return ChargeSessionTransition(
        ChargeSessionState("starting", bounded, state.attempts + 1, now),
        plan,
        "start_requested",
    )


def _stop(state, observation, now, tolerance):
    decision = ControlDecision("restore_self_use", 0.0, "free_window_finished")
    if foxess_response_matches(decision, observation, tolerance_kw=tolerance):
        return _idle("restored_self_use")
    plan = plan_foxess_commands(
        decision,
        observation,
        charge_power_max_kw=max(state.requested_power_kw, 0.0),
        discharge_power_max_kw=max(state.requested_power_kw, 0.0),
    )
    attempts = state.attempts if state.phase == "stopping" else 0
    return ChargeSessionTransition(
        ChargeSessionState("stopping", state.requested_power_kw, attempts + 1, now),
        plan,
        "stop_requested",
    )


def _within_retry(state: ChargeSessionState, now: datetime, interval: timedelta) -> bool:
    return state.last_command_at is not None and now - state.last_command_at < interval


def _idle(reason: str) -> ChargeSessionTransition:
    return ChargeSessionTransition(ChargeSessionState(), FoxessCommandPlan((), reason), reason)


def _validate_inputs(state, now, requested, maximum, acceptance_timeout, retry_after, max_attempts):
    if state.phase not in {"idle", "starting", "active", "stopping", "recovering"}:
        raise ValueError(f"unsupported charge session phase: {state.phase}")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if state.last_command_at is not None and (
        state.last_command_at.tzinfo is None or state.last_command_at.utcoffset() is None
    ):
        raise ValueError("last_command_at must be timezone-aware")
    if requested < 0 or maximum < 0:
        raise ValueError("requested and maximum power must be non-negative")
    if acceptance_timeout < timedelta(0) or retry_after < timedelta(0):
        raise ValueError("timeouts must be non-negative")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
