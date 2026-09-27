from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.home_energy_orchestrator.planner.control_supervision import (
    ControlSupervisionState,
    evaluate_control_supervision,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def test_supervision_waits_for_five_continuous_minutes_before_one_repair():
    first = evaluate_control_supervision(
        ControlSupervisionState(),
        now=NOW,
        issue_key="battery_free_charge_not_active",
        repair_allowed=True,
    )
    early = evaluate_control_supervision(
        first.state,
        now=NOW + timedelta(minutes=4, seconds=59),
        issue_key="battery_free_charge_not_active",
        repair_allowed=True,
    )
    due = evaluate_control_supervision(
        early.state,
        now=NOW + timedelta(minutes=5),
        issue_key="battery_free_charge_not_active",
        repair_allowed=True,
    )
    repeated = evaluate_control_supervision(
        due.state,
        now=NOW + timedelta(minutes=6),
        issue_key="battery_free_charge_not_active",
        repair_allowed=True,
    )

    assert first.status == early.status == "pending"
    assert due.status == "issue"
    assert due.should_repair is True
    assert due.should_notify is True
    assert repeated.should_repair is False
    assert repeated.should_notify is False


def test_unattributed_force_discharge_alerts_without_automatic_repair():
    pending = evaluate_control_supervision(
        ControlSupervisionState(),
        now=NOW,
        issue_key="battery_unattributed_force_discharge",
        repair_allowed=False,
    )
    due = evaluate_control_supervision(
        pending.state,
        now=NOW + timedelta(minutes=5),
        issue_key="battery_unattributed_force_discharge",
        repair_allowed=False,
    )

    assert due.status == "issue"
    assert due.should_notify is True
    assert due.should_repair is False


def test_supervision_requires_a_new_full_grace_when_issue_changes():
    old = ControlSupervisionState(
        issue_key="ev_target_not_applied",
        first_seen_at=NOW - timedelta(minutes=10),
        last_repair_at=NOW - timedelta(minutes=5),
        last_notified_at=NOW - timedelta(minutes=5),
    )

    changed = evaluate_control_supervision(
        old,
        now=NOW,
        issue_key="battery_not_self_use",
        repair_allowed=True,
    )

    assert changed.status == "pending"
    assert changed.state.first_seen_at == NOW
    assert changed.should_repair is False


def test_supervision_reports_recovery_and_clears_episode():
    active = ControlSupervisionState(
        issue_key="ev_target_not_applied",
        first_seen_at=NOW - timedelta(minutes=6),
        last_repair_at=NOW - timedelta(minutes=1),
        last_notified_at=NOW - timedelta(minutes=1),
    )

    recovered = evaluate_control_supervision(
        active,
        now=NOW,
        issue_key=None,
        repair_allowed=False,
    )

    assert recovered.status == "healthy"
    assert recovered.recovered_issue == "ev_target_not_applied"
    assert recovered.state == ControlSupervisionState()
