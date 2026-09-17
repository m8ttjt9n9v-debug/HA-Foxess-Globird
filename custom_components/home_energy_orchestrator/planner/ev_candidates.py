"""Immutable EV stage candidates composed from retained policy decisions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvStageCandidate:
    """One stage's eligibility, target intent and persistence obligation."""

    stage: str
    eligible: bool
    reason: str
    target_current_a: float | None = None
    target_limit_percent: float | None = None
    command_intent: tuple[str, ...] = ()
    persistence_transition: str = "none"
