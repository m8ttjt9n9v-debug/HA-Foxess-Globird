"""Tests for the latched FoxESS export-session state machine."""

from datetime import UTC, datetime, timedelta

from custom_components.home_energy_orchestrator.planner.export_session import (
    ExportSessionState,
    advance_export_session,
)
from custom_components.home_energy_orchestrator.planner.foxess import FoxessObservation

NOW = datetime(2026, 9, 3, 18, 0, tzinfo=UTC)
IDLE_OBSERVATION = FoxessObservation("Self Use", 0, 0)


def _advance(state, observation=IDLE_OBSERVATION, **kwargs):
    return advance_export_session(
        state,
        observation,
        now=kwargs.pop("now", NOW),
        source_available=kwargs.pop("source_available", True),
        window_active=kwargs.pop("window_active", True),
        eligible=kwargs.pop("eligible", True),
        requested_discharge_power_kw=kwargs.pop("requested_discharge_power_kw", 8),
        discharge_power_max_kw=kwargs.pop("discharge_power_max_kw", 10),
        **kwargs,
    )


def test_idle_starts_with_ordered_plan_and_latches() -> None:
    result = _advance(ExportSessionState())
    assert result.state.phase == "starting"
    assert result.state.attempts == 1
    assert [command.action for command in result.plan.commands] == [
        "set_discharge_power",
        "select_mode",
    ]


def test_starting_waits_then_accepts_feedback() -> None:
    started = _advance(ExportSessionState())
    waiting = _advance(
        started.state,
        FoxessObservation("Self Use", 0, 0),
        now=NOW + timedelta(seconds=10),
    )
    assert waiting.reason == "awaiting_feedback"
    active = _advance(
        waiting.state,
        FoxessObservation("Force Discharge", 0, 8),
        now=NOW + timedelta(seconds=15),
    )
    assert active.state.phase == "active"
    assert active.plan.commands == ()


def test_active_session_remains_latched_when_telemetry_is_eligible() -> None:
    state = ExportSessionState("active", 8, 0)
    result = _advance(state, FoxessObservation("Force Discharge", 0, 8))
    assert result.state.phase == "active"
    assert result.reason == "latched"
    assert result.plan.commands == ()


def test_window_finish_restores_self_use() -> None:
    state = ExportSessionState("active", 8, 0)
    result = _advance(state, FoxessObservation("Force Discharge", 0, 8), window_active=False)
    assert result.state.phase == "stopping"
    assert [command.action for command in result.plan.commands] == [
        "select_mode",
        "set_discharge_power",
    ]


def test_source_loss_enters_recovery_without_writing() -> None:
    result = _advance(ExportSessionState("active", 8, 0), source_available=False)
    assert result.state.phase == "recovering"
    assert result.plan.commands == ()


def test_retries_are_bounded() -> None:
    state = ExportSessionState("starting", 8, 3, NOW - timedelta(seconds=31))
    result = _advance(state)
    assert result.state.phase == "recovering"
    assert result.plan.commands == ()
