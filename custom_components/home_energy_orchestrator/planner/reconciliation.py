"""Bounded FoxESS command reconciliation without Home Assistant side effects.

The planner can describe a safe command sequence, but issuing a command is not
proof that the inverter accepted it. This module keeps the retry/reconcile
policy deterministic so a future active coordinator can issue at most one
bounded attempt per interval and stop after a finite number of failures.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from .control import ControlDecision
from .foxess import FoxessCommand, FoxessCommandPlan, FoxessObservation, foxess_response_matches


@dataclass(frozen=True, slots=True)
class FoxessReconciliation:
    """Result of reconciling one desired FoxESS intent with observed feedback."""

    status: str
    attempts: int
    commands: tuple[FoxessCommand, ...]
    reason: str


def reconcile_foxess_plan(
    plan: FoxessCommandPlan,
    decision: ControlDecision,
    observation: FoxessObservation,
    *,
    attempts: int = 0,
    last_attempt_at: datetime | None = None,
    now: datetime | None = None,
    retry_after: timedelta = timedelta(seconds=30),
    max_attempts: int = 3,
    tolerance_kw: float = 0.01,
) -> FoxessReconciliation:
    """Return a bounded action for a planned command sequence.

    ``issue`` is the only result that permits a future coordinator to call an
    adapter. A matching observation is always terminal for this plan;
    repeated failures become ``failed`` rather than retrying indefinitely.
    """
    if attempts < 0:
        raise ValueError("attempts must be non-negative")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if retry_after < timedelta(0):
        raise ValueError("retry_after must be non-negative")
    if now is None:
        now = datetime.now(UTC)
    if last_attempt_at is not None:
        _validate_datetime(last_attempt_at, "last_attempt_at")
    _validate_datetime(now, "now")

    if not plan.commands:
        return FoxessReconciliation("idle", attempts, (), plan.reason)
    effective_decision = _effective_decision(plan, decision)
    if foxess_response_matches(effective_decision, observation, tolerance_kw=tolerance_kw):
        return FoxessReconciliation("satisfied", attempts, (), "feedback_matches_plan")
    if attempts >= max_attempts:
        return FoxessReconciliation("failed", attempts, (), "max_attempts_exceeded")
    if last_attempt_at is not None and now - last_attempt_at < retry_after:
        return FoxessReconciliation("waiting", attempts, (), "retry_interval_not_elapsed")
    return FoxessReconciliation("issue", attempts + 1, plan.commands, plan.reason)


def _validate_datetime(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _effective_decision(plan: FoxessCommandPlan, decision: ControlDecision) -> ControlDecision:
    """Use the bounded power in the plan when checking inverter feedback."""
    power_action = (
        "set_charge_power" if decision.action == "force_charge" else "set_discharge_power"
    )
    for command in plan.commands:
        if command.action == power_action and isinstance(command.value, (int, float)):
            return replace(decision, power_kw=float(command.value))
    return decision
