"""Characterization for immutable EV stage candidates."""

from dataclasses import FrozenInstanceError

import pytest

from custom_components.home_energy_orchestrator.planner.ev_candidates import (
    EvStageCandidate,
    OutsideStageCandidateInputs,
    build_outside_stage_candidates,
    reject_ev_stage_candidate,
)


def test_stage_candidate_is_lossless_and_immutable() -> None:
    candidate = EvStageCandidate(
        stage="free_window",
        eligible=True,
        reason="ev_priority",
        target_current_a=16,
        target_limit_percent=92,
        command_intent=("reconcile_current", "reconcile_charge_limit"),
        persistence_transition="none",
    )

    assert candidate == EvStageCandidate(
        "free_window",
        True,
        "ev_priority",
        16,
        92,
        ("reconcile_current", "reconcile_charge_limit"),
        "none",
    )
    with pytest.raises(FrozenInstanceError):
        candidate.reason = "changed"  # type: ignore[misc]


def test_rejected_candidate_has_no_target_command_or_persistence_intent() -> None:
    assert reject_ev_stage_candidate("free_window", "ev_soc_unavailable") == (
        EvStageCandidate("free_window", False, "ev_soc_unavailable")
    )


def test_outside_builder_preserves_simultaneous_stage_eligibility() -> None:
    candidates = build_outside_stage_candidates(
        OutsideStageCandidateInputs(
            charge_to_full=True,
            service_ceiling_a=16,
            daily_enabled=True,
            daily_active=True,
            daily_reason="charge_now",
            daily_current_a=6,
            daily_stop_pending=False,
            solar_current_a=10,
            solar_reason="solar_spill",
            pre_free_active=True,
            pre_free_reason="started",
            pre_free_current_a=12,
            protected_baseline_a=1,
            physical_minimum_a=1,
        )
    )

    assert tuple(candidate.stage for candidate in candidates) == (
        "charge_to_full",
        "daily_ready",
        "solar_spill",
        "pre_free",
        "protected_baseline",
    )
    assert all(candidate.eligible for candidate in candidates)
    assert tuple(candidate.target_current_a for candidate in candidates) == (
        16,
        6,
        10,
        12,
        1,
    )
    assert candidates[1].persistence_transition == "daily_backfill_active"
    assert candidates[3].persistence_transition == "pre_free_session_active"


def test_outside_builder_distinguishes_disabled_from_unavailable_daily_stage() -> None:
    common = dict(
        charge_to_full=False,
        service_ceiling_a=16,
        daily_active=False,
        daily_reason="inputs_unavailable",
        daily_current_a=0,
        daily_stop_pending=False,
        solar_current_a=0,
        solar_reason="disabled",
        pre_free_active=False,
        pre_free_reason="disabled",
        pre_free_current_a=0,
        protected_baseline_a=0,
        physical_minimum_a=1,
    )

    disabled = build_outside_stage_candidates(
        OutsideStageCandidateInputs(daily_enabled=False, **common)
    )
    unavailable = build_outside_stage_candidates(
        OutsideStageCandidateInputs(daily_enabled=True, **common)
    )

    assert disabled[1].reason == "disabled"
    assert unavailable[1].reason == "inputs_unavailable"
    assert not any(candidate.eligible for candidate in disabled)
