"""Phase 6 coordinator-boundary tests."""

from scripts.coordinator_boundary_contract import validate_coordinator_boundary


def test_coordinator_reads_states_only_through_the_telemetry_adapter() -> None:
    validate_coordinator_boundary()
