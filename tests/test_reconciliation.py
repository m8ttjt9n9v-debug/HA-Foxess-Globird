"""Tests for bounded FoxESS command reconciliation."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.control import ControlDecision
from custom_components.home_energy_orchestrator.planner.foxess import (
    FoxessObservation,
    plan_foxess_commands,
)
from custom_components.home_energy_orchestrator.planner.reconciliation import (
    reconcile_foxess_plan,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
DECISION = ControlDecision("force_charge", 8, "free_window_below_target")
OBSERVATION = FoxessObservation("Self Use", 0, 0)


def _plan():
    return plan_foxess_commands(
        DECISION,
        OBSERVATION,
        charge_power_max_kw=10,
        discharge_power_max_kw=10,
    )


def test_reconciliation_issues_first_attempt() -> None:
    result = reconcile_foxess_plan(_plan(), DECISION, OBSERVATION, now=NOW)
    assert result.status == "issue"
    assert result.attempts == 1
    assert result.commands


def test_reconciliation_waits_between_attempts() -> None:
    result = reconcile_foxess_plan(
        _plan(),
        DECISION,
        OBSERVATION,
        attempts=1,
        last_attempt_at=NOW,
        now=NOW + timedelta(seconds=29),
    )
    assert result.status == "waiting"
    assert result.attempts == 1
    assert result.commands == ()


def test_reconciliation_issues_retry_after_interval() -> None:
    result = reconcile_foxess_plan(
        _plan(),
        DECISION,
        OBSERVATION,
        attempts=1,
        last_attempt_at=NOW,
        now=NOW + timedelta(seconds=30),
    )
    assert result.status == "issue"
    assert result.attempts == 2


def test_reconciliation_stops_after_bounded_attempts() -> None:
    result = reconcile_foxess_plan(
        _plan(), DECISION, OBSERVATION, attempts=3, now=NOW, max_attempts=3
    )
    assert result.status == "failed"
    assert result.commands == ()


def test_reconciliation_accepts_matching_feedback_without_writing() -> None:
    observed = FoxessObservation("Force Charge", 8.005, 0)
    result = reconcile_foxess_plan(_plan(), DECISION, observed, attempts=1, now=NOW)
    assert result.status == "satisfied"
    assert result.commands == ()


def test_reconciliation_checks_the_plans_bounded_power() -> None:
    oversized = ControlDecision("force_charge", 15, "free_window_below_target")
    plan = plan_foxess_commands(
        oversized,
        OBSERVATION,
        charge_power_max_kw=10,
        discharge_power_max_kw=10,
    )
    result = reconcile_foxess_plan(
        plan,
        oversized,
        FoxessObservation("Force Charge", 10, 0),
        attempts=1,
        now=NOW,
    )
    assert result.status == "satisfied"


def test_reconciliation_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        reconcile_foxess_plan(_plan(), DECISION, OBSERVATION, now=datetime(2026, 9, 3))
