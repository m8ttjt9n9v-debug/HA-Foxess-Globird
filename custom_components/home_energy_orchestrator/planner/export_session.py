"""Latched, bounded FoxESS export-session state machine.

This module only plans transitions. It deliberately has no Home Assistant
service dependency; an active coordinator must persist the returned state and
give the command plan to the fail-closed FoxESS adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .control import ControlDecision
from .foxess import (
    FoxessCommandPlan,
    FoxessObservation,
    foxess_response_matches,
    plan_foxess_commands,
)


@dataclass(frozen=True, slots=True)
class ExportSessionState:
    """Persistable export-session state."""

    phase: str = "idle"
    requested_power_kw: float = 0.0
    attempts: int = 0
    last_command_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ExportSessionTransition:
    """The next state and optional adapter-neutral command plan."""

    state: ExportSessionState
    plan: FoxessCommandPlan
    reason: str


def advance_export_session(
    state: ExportSessionState,
    observation: FoxessObservation,
    *,
    now: datetime,
    source_available: bool,
    window_active: bool,
    eligible: bool,
    requested_discharge_power_kw: float,
    discharge_power_max_kw: float,
    finish_requested: bool = False,
    acceptance_timeout: timedelta = timedelta(seconds=30),
    retry_after: timedelta = timedelta(seconds=30),
    max_attempts: int = 3,
    tolerance_kw: float = 0.01,
) -> ExportSessionTransition:
    """Advance a latched session with bounded writes and restart recovery."""
    _validate_inputs(
        state,
        now,
        requested_discharge_power_kw,
        discharge_power_max_kw,
        acceptance_timeout,
        retry_after,
        max_attempts,
    )
    desired = (
        source_available
        and window_active
        and eligible
        and not finish_requested
        and requested_discharge_power_kw > 0
    )
    requested = round(min(requested_discharge_power_kw, discharge_power_max_kw), 3)
    if not source_available:
        if state.phase in {"starting", "active", "stopping"}:
            return ExportSessionTransition(
                replace(state, phase="recovering"),
                FoxessCommandPlan((), "source_unavailable"),
                "source_unavailable",
            )
        return ExportSessionTransition(
            replace(state, phase="idle", attempts=0, last_command_at=None),
            FoxessCommandPlan((), "source_unavailable"),
            "source_unavailable",
        )

    if state.phase == "recovering":
        state = replace(state, phase="idle", attempts=0, last_command_at=None)

    if state.phase == "idle":
        if not desired or requested <= 0:
            return _idle("not_eligible")
        return _start(state, observation, now, requested, discharge_power_max_kw, tolerance_kw)

    if state.phase == "starting":
        decision = ControlDecision(
            "force_discharge", state.requested_power_kw, "export_window_ready"
        )
        if foxess_response_matches(decision, observation, tolerance_kw=tolerance_kw):
            return ExportSessionTransition(
                replace(state, phase="active", attempts=0),
                FoxessCommandPlan((), "feedback_matches_plan"),
                "active",
            )
        if not desired:
            return _stop(state, observation, now, tolerance_kw)
        if _within_retry(state, now, acceptance_timeout):
            return ExportSessionTransition(
                state, FoxessCommandPlan((), "awaiting_feedback"), "awaiting_feedback"
            )
        if state.attempts >= max_attempts:
            return ExportSessionTransition(
                replace(state, phase="recovering"),
                FoxessCommandPlan((), "max_attempts_exceeded"),
                "max_attempts_exceeded",
            )
        return _start(
            replace(state, requested_power_kw=requested),
            observation,
            now,
            requested,
            discharge_power_max_kw,
            tolerance_kw,
        )

    if state.phase == "active":
        if not desired:
            return _stop(state, observation, now, tolerance_kw)
        decision = ControlDecision(
            "force_discharge", state.requested_power_kw, "export_window_ready"
        )
        if foxess_response_matches(decision, observation, tolerance_kw=tolerance_kw):
            return ExportSessionTransition(state, FoxessCommandPlan((), "latched"), "latched")
        if _within_retry(state, now, retry_after):
            return ExportSessionTransition(
                state, FoxessCommandPlan((), "awaiting_feedback"), "awaiting_feedback"
            )
        if state.attempts >= max_attempts:
            return ExportSessionTransition(
                replace(state, phase="recovering"),
                FoxessCommandPlan((), "max_attempts_exceeded"),
                "max_attempts_exceeded",
            )
        return _start(
            replace(state, phase="starting", requested_power_kw=requested),
            observation,
            now,
            requested,
            discharge_power_max_kw,
            tolerance_kw,
        )

    if state.phase == "stopping":
        if desired:
            return _start(
                replace(state, phase="idle", attempts=0),
                observation,
                now,
                requested,
                discharge_power_max_kw,
                tolerance_kw,
            )
        decision = ControlDecision("restore_self_use", 0.0, "no_active_policy")
        if foxess_response_matches(decision, observation, tolerance_kw=tolerance_kw):
            return _idle("restored_self_use")
        if _within_retry(state, now, acceptance_timeout):
            return ExportSessionTransition(
                state, FoxessCommandPlan((), "awaiting_feedback"), "awaiting_feedback"
            )
        if state.attempts >= max_attempts:
            return ExportSessionTransition(
                replace(state, phase="recovering"),
                FoxessCommandPlan((), "max_attempts_exceeded"),
                "max_attempts_exceeded",
            )
        return _stop(replace(state, attempts=state.attempts), observation, now, tolerance_kw)

    raise ValueError(f"unsupported export session phase: {state.phase}")


def _start(state, observation, now, requested, maximum, tolerance):
    decision = ControlDecision("force_discharge", requested, "export_window_ready")
    if foxess_response_matches(decision, observation, tolerance_kw=tolerance):
        return ExportSessionTransition(
            replace(state, phase="active", requested_power_kw=requested, attempts=0),
            FoxessCommandPlan((), "feedback_matches_plan"),
            "active",
        )
    plan = plan_foxess_commands(
        decision,
        observation,
        charge_power_max_kw=maximum,
        discharge_power_max_kw=maximum,
    )
    return ExportSessionTransition(
        ExportSessionState("starting", requested, state.attempts + 1, now), plan, "start_requested"
    )


def _stop(state, observation, now, tolerance):
    decision = ControlDecision("restore_self_use", 0.0, "no_active_policy")
    if foxess_response_matches(decision, observation, tolerance_kw=tolerance):
        return _idle("restored_self_use")
    plan = plan_foxess_commands(
        decision,
        observation,
        charge_power_max_kw=max(state.requested_power_kw, 0.0),
        discharge_power_max_kw=max(state.requested_power_kw, 0.0),
    )
    return ExportSessionTransition(
        ExportSessionState("stopping", state.requested_power_kw, state.attempts + 1, now),
        plan,
        "stop_requested",
    )


def _within_retry(state: ExportSessionState, now: datetime, interval: timedelta) -> bool:
    return state.last_command_at is not None and now - state.last_command_at < interval


def _idle(reason: str) -> ExportSessionTransition:
    return ExportSessionTransition(ExportSessionState(), FoxessCommandPlan((), reason), reason)


def _validate_inputs(state, now, requested, maximum, acceptance_timeout, retry_after, max_attempts):
    if state.phase not in {"idle", "starting", "active", "stopping", "recovering"}:
        raise ValueError(f"unsupported export session phase: {state.phase}")
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
