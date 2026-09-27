"""Pure delayed-conformance policy for battery and EV control feedback."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class ControlSupervisionState:
    """Retained evidence for one continuously observed control mismatch."""

    issue_key: str | None = None
    first_seen_at: datetime | None = None
    last_repair_at: datetime | None = None
    last_notified_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ControlSupervisionDecision:
    """Next state plus side effects the Home Assistant facade may perform."""

    state: ControlSupervisionState
    status: str
    should_repair: bool = False
    should_notify: bool = False
    recovered_issue: str | None = None


def evaluate_control_supervision(
    state: ControlSupervisionState,
    *,
    now: datetime,
    issue_key: str | None,
    repair_allowed: bool,
    grace: timedelta = timedelta(minutes=5),
    notification_repeat: timedelta = timedelta(minutes=30),
) -> ControlSupervisionDecision:
    """Require a continuous mismatch before one repair and a deduplicated alert."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if grace < timedelta(0) or notification_repeat <= timedelta(0):
        raise ValueError("supervision intervals must be positive")

    if issue_key is None:
        recovered = state.issue_key if state.first_seen_at is not None else None
        return ControlSupervisionDecision(
            ControlSupervisionState(),
            "healthy",
            recovered_issue=recovered,
        )

    if state.issue_key != issue_key or state.first_seen_at is None:
        return ControlSupervisionDecision(
            ControlSupervisionState(issue_key=issue_key, first_seen_at=now),
            "pending",
        )

    if now - state.first_seen_at < grace:
        return ControlSupervisionDecision(state, "pending")

    should_repair = repair_allowed and state.last_repair_at is None
    should_notify = (
        state.last_notified_at is None
        or now - state.last_notified_at >= notification_repeat
    )
    next_state = replace(
        state,
        last_repair_at=now if should_repair else state.last_repair_at,
        last_notified_at=now if should_notify else state.last_notified_at,
    )
    return ControlSupervisionDecision(
        next_state,
        "issue",
        should_repair=should_repair,
        should_notify=should_notify,
    )
