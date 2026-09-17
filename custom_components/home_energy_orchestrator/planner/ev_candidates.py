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


@dataclass(frozen=True, slots=True)
class OutsideStageCandidateInputs:
    """Retained outside-stage results required to describe every candidate."""

    charge_to_full: bool
    service_ceiling_a: float
    daily_enabled: bool
    daily_active: bool
    daily_reason: str
    daily_current_a: float
    daily_stop_pending: bool
    solar_current_a: float
    solar_reason: str
    pre_free_active: bool
    pre_free_reason: str
    pre_free_current_a: float
    protected_baseline_a: float
    physical_minimum_a: float


def build_ev_stage_candidate(
    stage: str,
    *,
    eligible: bool,
    reason: str,
    target_current_a: float | None = None,
    target_limit_percent: float | None = None,
    command_intent: tuple[str, ...] = (),
    persistence_transition: str = "none",
) -> EvStageCandidate:
    """Build one immutable description without policy or side effects."""
    return EvStageCandidate(
        stage=stage,
        eligible=eligible,
        reason=reason,
        target_current_a=target_current_a,
        target_limit_percent=target_limit_percent,
        command_intent=command_intent,
        persistence_transition=persistence_transition,
    )


def reject_ev_stage_candidate(stage: str, reason: str) -> EvStageCandidate:
    """Build the common unavailable-input candidate."""
    return build_ev_stage_candidate(stage, eligible=False, reason=reason)


def build_outside_stage_candidates(
    inputs: OutsideStageCandidateInputs,
) -> tuple[EvStageCandidate, ...]:
    """Describe retained outside stages without selecting among them."""
    command_intent = ("reconcile_current", "reconcile_charge_limit")
    solar_eligible = inputs.solar_current_a >= inputs.physical_minimum_a
    return (
        build_ev_stage_candidate(
            "charge_to_full",
            eligible=inputs.charge_to_full,
            reason=(
                "charge_to_full_paid_grid_override"
                if inputs.charge_to_full
                else "disabled"
            ),
            target_current_a=(
                inputs.service_ceiling_a if inputs.charge_to_full else None
            ),
            command_intent=command_intent if inputs.charge_to_full else (),
        ),
        build_ev_stage_candidate(
            "daily_ready",
            eligible=inputs.daily_active,
            reason=(inputs.daily_reason if inputs.daily_enabled else "disabled"),
            target_current_a=(inputs.daily_current_a if inputs.daily_active else None),
            command_intent=command_intent if inputs.daily_active else (),
            persistence_transition=(
                "daily_backfill_active"
                if inputs.daily_active
                else "daily_backfill_stop_pending"
                if inputs.daily_stop_pending
                else "none"
            ),
        ),
        build_ev_stage_candidate(
            "solar_spill",
            eligible=solar_eligible,
            reason=inputs.solar_reason,
            target_current_a=(inputs.solar_current_a if solar_eligible else None),
            command_intent=command_intent if solar_eligible else (),
        ),
        build_ev_stage_candidate(
            "pre_free",
            eligible=inputs.pre_free_active,
            reason=inputs.pre_free_reason,
            target_current_a=(
                inputs.pre_free_current_a if inputs.pre_free_active else None
            ),
            command_intent=command_intent if inputs.pre_free_active else (),
            persistence_transition=(
                "pre_free_session_active" if inputs.pre_free_active else "none"
            ),
        ),
        build_ev_stage_candidate(
            "protected_baseline",
            eligible=inputs.protected_baseline_a > 0,
            reason=(
                "protected_baseline"
                if inputs.protected_baseline_a > 0
                else "disabled"
            ),
            target_current_a=(
                inputs.protected_baseline_a
                if inputs.protected_baseline_a > 0
                else None
            ),
            command_intent=(
                command_intent if inputs.protected_baseline_a > 0 else ()
            ),
        ),
    )
