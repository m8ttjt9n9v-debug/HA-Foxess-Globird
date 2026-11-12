"""Composite EV persistence-state characterization tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.ev_persistence import (
    EvPersistenceState,
    EvReservationSocRecord,
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
        "measured_solar_adjustment": {
            "phase": "solar_spill",
            "target_current_a": 10.0,
            "changed_at": (NOW - timedelta(minutes=15)).isoformat(),
            "pending_current_a": 8.0,
            "pending_since": (NOW - timedelta(minutes=5)).isoformat(),
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

    assert state.reservation_soc is None
    assert state.to_payload() == payload


@pytest.mark.parametrize("value", [0, 37.25, 100])
def test_verified_reservation_soc_keeps_its_original_clock_across_restart(value: float) -> None:
    observed_at = NOW - timedelta(days=20)
    binding = ("tessie", "synthetic-vehicle-binding")
    record = EvReservationSocRecord(value, observed_at, binding)
    existing = EvPersistenceState.from_payload(complete_payload(), NOW)

    saved = replace(existing, reservation_soc=record).validated_for_storage().to_payload()
    restored = EvPersistenceState.from_payload(saved, NOW + timedelta(days=1))

    assert saved["reservation_soc"] == {
        "value_percent": value,
        "observed_at": observed_at.isoformat(),
        "binding": list(binding),
    }
    assert restored.reservation_soc == record
    assert replace(restored, reservation_soc=None).to_payload() == existing.to_payload()


@pytest.mark.parametrize("changes", [
    {"value_percent": -1}, {"value_percent": 101}, {"value_percent": True},
    {"value_percent": float("nan")}, {"value_percent": float("inf")},
    {"value_percent": "90"}, {"value_percent": 10**400}, {"value_percent": None},
    {"observed_at": "invalid"}, {"observed_at": "2026-09-17T12:00:00"},
    {"observed_at": "2026-09-17T12:00:00.000001+00:00"}, {"observed_at": 42},
    {"observed_at": "0001-01-01T00:00:00+14:00"},
    {"binding": "synthetic-vehicle-binding"}, {"binding": []}, {"binding": [" "]},
    {"binding": [True]}, {"binding": ["a" * 257]}, {"binding": ["a"] * 9},
])
def test_malformed_reservation_soc_leaves_other_journal_fields_intact(changes) -> None:
    original = complete_payload()
    payload = {**original, "reservation_soc": {
        "value_percent": 48,
        "observed_at": NOW.isoformat(),
        "binding": ["synthetic-vehicle-binding"],
        **changes,
    }}

    restored = EvPersistenceState.from_payload(payload, NOW)

    assert restored.reservation_soc is None
    assert restored.to_payload() == original


@pytest.mark.parametrize("changes", [
    {"value_percent": False},
    {"observed_at": NOW + timedelta(microseconds=1)},
    {"observed_at": NOW.replace(tzinfo=None)},
    {"binding": ()},
])
def test_invalid_runtime_reservation_soc_is_omitted_when_serializing(changes) -> None:
    record = replace(EvReservationSocRecord(48, NOW, ("synthetic-binding",)), **changes)
    existing = EvPersistenceState.from_payload(complete_payload(), NOW)
    state = replace(existing, reservation_soc=record)

    assert state.to_payload() == existing.to_payload()
    assert state.validated_for_storage().reservation_soc is None


def test_zero_baseline_stop_retry_survives_more_than_three_attempts() -> None:
    payload = complete_payload()
    payload["daily_backfill"]["stop_attempts"] = 48

    state = EvPersistenceState.from_payload(payload, NOW)

    assert state.daily_backfill.stop_attempts == 48
    assert state.validated_for_storage().to_payload() == payload


def test_ev_persistence_retains_stable_feedback_wait_across_restart() -> None:
    payload = complete_payload()
    payload["reconciliation"]["phase"] = "awaiting_stable_current_feedback"

    state = EvPersistenceState.from_payload(payload, NOW)

    assert state.to_payload() == payload


def test_ev_persistence_migrates_old_payload_without_measured_solar_hold() -> None:
    payload = complete_payload()
    payload.pop("measured_solar_adjustment")

    state = EvPersistenceState.from_payload(payload, NOW)

    assert state.measured_solar_adjustment.phase is None
    assert state.measured_solar_adjustment.target_current_a is None


@pytest.mark.parametrize("battery_current", [0.0, 1.0, 4.25])
def test_combined_morning_budget_and_active_pre_free_round_trip(battery_current: float) -> None:
    """A reload retains cadence and budget without introducing a new phase."""
    payload = complete_payload()
    payload["measured_solar_adjustment"].update(
        phase="morning_solar", battery_current_a=battery_current
    )

    state = EvPersistenceState.from_payload(payload, NOW)

    assert state.pre_free_session.active is True
    assert state.measured_solar_adjustment.phase == "morning_solar"
    assert state.measured_solar_adjustment.battery_current_a == battery_current
    assert state.to_payload() == payload
    assert state.validated_for_storage().to_payload() == payload


def test_legacy_measured_solar_payload_does_not_gain_optional_budget_key() -> None:
    payload = complete_payload()
    original = deepcopy(payload)

    state = EvPersistenceState.from_payload(payload, NOW)

    assert state.measured_solar_adjustment.battery_current_a is None
    assert state.to_payload() == original
    assert state.validated_for_storage().to_payload() == original
    assert "battery_current_a" not in state.to_payload()["measured_solar_adjustment"]
    assert payload == original


def test_missing_measured_solar_payload_keeps_legacy_evidence_without_budget() -> None:
    payload = complete_payload()
    payload.pop("measured_solar_adjustment")

    state = EvPersistenceState.from_payload(payload, NOW)

    assert state.pre_free_session.active is True
    assert state.reconciliation.phase == "awaiting_feedback"
    assert state.daily_backfill.delivered_kwh == 2.25
    assert state.measured_solar_adjustment.battery_current_a is None
    assert "battery_current_a" not in state.to_payload()["measured_solar_adjustment"]


@pytest.mark.parametrize(
    "battery_current",
    [
        -1, float("nan"), float("inf"), float("-inf"),
        True, False, "invalid", {}, [], 10**400,
    ],
)
def test_malformed_combined_morning_budget_fails_closed(battery_current) -> None:
    payload = complete_payload()
    payload["measured_solar_adjustment"].update(
        phase="morning_solar", battery_current_a=battery_current
    )

    state = EvPersistenceState.from_payload(payload, NOW)

    assert state.measured_solar_adjustment.battery_current_a is None
    assert state.measured_solar_adjustment.phase is None
    assert state.pre_free_session.active is False
    assert state.reconciliation.phase == "idle"
    assert state.daily_backfill.active is False
    assert state.outside_control_active is False
    assert state.charge_to_full_started_at is None
    assert state.driving_snapshot.lifetime_energy_kwh == 1018.5


def test_orphaned_combined_budget_does_not_authorize_a_solar_hold() -> None:
    payload = complete_payload()
    payload["measured_solar_adjustment"] = {
        "phase": None,
        "target_current_a": None,
        "changed_at": None,
        "pending_current_a": None,
        "pending_since": None,
        "battery_current_a": 2.0,
    }

    state = EvPersistenceState.from_payload(payload, NOW)

    assert state.measured_solar_adjustment.phase is None
    assert state.measured_solar_adjustment.battery_current_a is None
    assert state.pre_free_session.active is False


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


def test_ev_persistence_storage_validation_preserves_complete_payload() -> None:
    payload = complete_payload()
    state = EvPersistenceState.from_payload(payload, NOW)

    assert state.validated_for_storage().to_payload() == payload


def test_ev_persistence_storage_validation_retains_grouped_safe_fallback() -> None:
    state = EvPersistenceState.from_payload(complete_payload(), NOW)
    invalid = replace(
        state,
        reconciliation=replace(state.reconciliation, attempts=-1),
    )

    validated = invalid.validated_for_storage()

    assert [sample.energy_kwh for sample in validated.driving_history.samples] == [18.5]
    assert validated.driving_snapshot.lifetime_energy_kwh == 1018.5
    assert validated.reconciliation.phase == "idle"
    assert validated.pre_free_session.active is False
    assert validated.daily_backfill.active is False
    assert validated.charge_to_full_started_at is None
    assert validated.outside_control_active is False
    assert validated.smart_recovery.phase == "idle"


def test_ev_persistence_retains_retry_count_above_legacy_three_attempt_limit() -> None:
    state = EvPersistenceState.from_payload(complete_payload(), NOW)
    retrying = replace(
        state,
        reconciliation=replace(state.reconciliation, attempts=7),
    )

    validated = retrying.validated_for_storage()

    assert validated.reconciliation.attempts == 7
    assert validated.reconciliation.phase == "awaiting_feedback"
