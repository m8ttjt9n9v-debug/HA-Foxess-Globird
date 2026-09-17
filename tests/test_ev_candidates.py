"""Characterization for immutable EV stage candidates."""

from dataclasses import FrozenInstanceError

import pytest

from custom_components.home_energy_orchestrator.planner.ev_candidates import (
    EvStageCandidate,
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
