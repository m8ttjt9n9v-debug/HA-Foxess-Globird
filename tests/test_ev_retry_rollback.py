"""The compatibility rehearsal must exercise new optional journal evidence."""

from datetime import UTC, datetime

from custom_components.home_energy_orchestrator.planner.ev_persistence import EvPersistenceState
from scripts.previous_release_rehearsal import _current_rollback_bundle


def test_rollback_rehearsal_includes_valid_additive_current_proof():
    bundle = _current_rollback_bundle()
    raw = bundle["stores"]["ev_control"]
    state = EvPersistenceState.from_payload(raw, datetime(2020, 1, 2, 3, 4, tzinfo=UTC))

    assert state.reconciliation.current_proof.armed
    assert state.reconciliation.current_retry.attempts == 2
    assert state.daily_backfill.stop_pending
    assert state.daily_backfill.stop_attempts == 2

    # Simulate the old codec discarding only its unknown nested extension.
    raw["reconciliation"].pop("retry_channels")
    legacy = EvPersistenceState.from_payload(raw, state.restored_at)
    assert legacy.reconciliation.attempts == 2
    assert not legacy.reconciliation.current_proof.armed
    assert legacy.daily_backfill == state.daily_backfill
