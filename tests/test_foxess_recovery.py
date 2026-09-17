"""Characterization tests for unavailable-feedback recovery planning."""

from datetime import UTC, datetime

import pytest

from custom_components.home_energy_orchestrator.planner.charge_session import (
    ChargeSessionState,
)
from custom_components.home_energy_orchestrator.planner.export_session import (
    ExportSessionState,
)
from custom_components.home_energy_orchestrator.planner.foxess_recovery import (
    mark_foxess_source_unavailable,
)

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
EARLIER = datetime(2026, 9, 17, 11, 59, tzinfo=UTC)


def test_idle_sessions_remain_unwritten() -> None:
    result = mark_foxess_source_unavailable(
        ChargeSessionState(),
        ExportSessionState(),
        NOW,
    )

    assert result.charge_session == ChargeSessionState()
    assert result.export_session == ExportSessionState()
    assert result.save_charge is False
    assert result.save_export is False


@pytest.mark.parametrize("phase", ["starting", "active", "stopping", "recovering"])
def test_charge_obligation_becomes_recovering_and_is_always_saved(phase: str) -> None:
    original = ChargeSessionState(phase, 8.0, 2, EARLIER)

    result = mark_foxess_source_unavailable(
        original,
        ExportSessionState(),
        NOW,
    )

    assert result.charge_session == ChargeSessionState(
        "recovering", 8.0, 2, EARLIER
    )
    assert result.save_charge is True
    assert result.save_export is False


@pytest.mark.parametrize("phase", ["starting", "active", "stopping", "recovering"])
def test_export_obligation_becomes_recovering_and_is_always_saved(phase: str) -> None:
    original = ExportSessionState(phase, 9.0, 1, None)

    result = mark_foxess_source_unavailable(
        ChargeSessionState(),
        original,
        NOW,
    )

    assert result.export_session == ExportSessionState("recovering", 9.0, 1, NOW)
    assert result.save_export is True
    assert result.save_charge is False


def test_charge_unknown_phase_is_unchanged_while_nonidle_export_rule_is_broad() -> None:
    charge = ChargeSessionState("unexpected", 4.0, 0, EARLIER)
    export = ExportSessionState("unexpected", 5.0, 0, EARLIER)

    result = mark_foxess_source_unavailable(charge, export, NOW)

    assert result.charge_session is charge
    assert result.save_charge is False
    assert result.export_session == ExportSessionState(
        "recovering", 5.0, 0, EARLIER
    )
    assert result.save_export is True
