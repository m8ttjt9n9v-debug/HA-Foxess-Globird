"""Composite EV persistence-state characterization tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from custom_components.home_energy_orchestrator.planner.ev_persistence import (
    EvPersistenceState,
)

NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)


def complete_payload() -> dict[str, object]:
    sample_at = NOW - timedelta(days=1)
    return {
        "grid_average": None,
        "ev_average": None,
        "driving_history": {
            "samples": [{"observed_at": sample_at.isoformat(), "energy_kwh": 18.5}]
        },
        "driving_snapshot": {
            "snapshot_date": sample_at.date().isoformat(),
            "lifetime_energy_kwh": 1018.5,
        },
        "daily_driving_energy_kwh": 18.5,
        "reconciliation": {
            "target_current_a": 16.0,
            "target_limit_percent": 90.0,
            "attempts": 2,
            "last_command_at": (NOW - timedelta(seconds=30)).isoformat(),
            "phase": "awaiting_feedback",
        },
        "pre_free_session": {
            "active": True,
            "frozen_start": (NOW - timedelta(hours=1)).isoformat(),
        },
        "daily_backfill": {
            "cycle_ready_at": (NOW + timedelta(hours=20)).isoformat(),
            "delivered_kwh": 2.25,
            "active": True,
            "session_target_kwh": 4.0,
            "session_start_delivered_kwh": 1.0,
            "frozen_start": (NOW - timedelta(hours=2)).isoformat(),
            "stop_pending": True,
            "stop_attempts": 2,
            "last_stop_at": (NOW - timedelta(seconds=30)).isoformat(),
        },
        "charge_to_full_started_at": (NOW - timedelta(hours=1)).isoformat(),
        "outside_control_active": True,
        "smart_recovery": {
            "attempted": True,
            "phase": "recovered",
            "phase_started_at": (NOW - timedelta(minutes=1)).isoformat(),
            "recovery_current_a": 6.0,
        },
    }


def test_ev_persistence_state_round_trips_complete_existing_payload() -> None:
    payload = complete_payload()

    state = EvPersistenceState.from_payload(payload, NOW)

    assert state.to_payload() == payload


def test_ev_persistence_state_retains_driving_evidence_when_control_block_is_bad() -> None:
    payload = deepcopy(complete_payload())
    payload["reconciliation"]["phase"] = "invalid"

    state = EvPersistenceState.from_payload(payload, NOW)

    assert [sample.energy_kwh for sample in state.driving_history.samples] == [18.5]
    assert state.driving_snapshot.lifetime_energy_kwh == 1018.5
    assert state.reconciliation.phase == "idle"
    assert state.pre_free_session.active is False
    assert state.daily_backfill.active is False
    assert state.smart_recovery.phase == "idle"
