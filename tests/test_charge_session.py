"""Tests for the bounded Local Modbus free-window charge session."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.home_energy_orchestrator.planner.charge_session import (
    ChargeSessionState,
    advance_charge_session,
)
from custom_components.home_energy_orchestrator.planner.foxess import FoxessObservation

NOW = datetime(2026, 9, 10, 12, 1, tzinfo=UTC)


def _advance(
    state: ChargeSessionState,
    observation: FoxessObservation,
    **overrides,
):
    values = {
        "now": NOW,
        "source_available": True,
        "window_active": True,
        "eligible_to_start": True,
        "requested_charge_power_kw": 10.0,
        "charge_power_max_kw": 10.0,
    }
    values.update(overrides)
    return advance_charge_session(state, observation, **values)


def test_idle_session_starts_with_bounded_ordered_force_charge_plan() -> None:
    result = _advance(
        ChargeSessionState(),
        FoxessObservation("Force Discharge", 0.0, 5.0),
        requested_charge_power_kw=15.0,
        charge_power_max_kw=10.0,
    )

    assert result.state == ChargeSessionState("starting", 10.0, 1, NOW)
    assert [(command.action, command.value) for command in result.plan.commands] == [
        ("set_discharge_power", 0.0),
        ("set_charge_power", 10.0),
        ("select_mode", "Force Charge"),
    ]


def test_matching_feedback_activates_and_target_change_does_not_flap() -> None:
    starting = ChargeSessionState("starting", 10.0, 1, NOW - timedelta(seconds=5))
    active = _advance(starting, FoxessObservation("Force Charge", 10.0, 0.0))
    assert active.state.phase == "active"

    latched = _advance(
        active.state,
        FoxessObservation("Force Charge", 10.0, 0.0),
        eligible_to_start=False,
    )
    assert latched.state.phase == "active"
    assert latched.reason == "latched"
    assert latched.plan.commands == ()


def test_window_finish_restores_self_use_and_clears_targets() -> None:
    state = ChargeSessionState("active", 10.0, 0, NOW - timedelta(minutes=30))
    result = _advance(
        state,
        FoxessObservation("Force Charge", 10.0, 0.0),
        window_active=False,
        finish_requested=True,
    )

    assert result.state.phase == "stopping"
    assert [(command.action, command.value) for command in result.plan.commands] == [
        ("select_mode", "Self Use"),
        ("set_charge_power", 0.0),
    ]


def test_lost_source_recovers_only_inside_the_window() -> None:
    state = ChargeSessionState("active", 10.0, 0, NOW - timedelta(minutes=30))
    lost = _advance(
        state,
        FoxessObservation("Force Charge", 10.0, 0.0),
        source_available=False,
    )
    assert lost.state.phase == "recovering"
    assert lost.plan.commands == ()

    resumed = _advance(
        lost.state,
        FoxessObservation("Self Use", 0.0, 0.0),
        eligible_to_start=False,
    )
    assert resumed.state.phase == "starting"
    assert resumed.state.requested_power_kw == 10.0

    after_window = _advance(
        lost.state,
        FoxessObservation("Force Charge", 10.0, 0.0),
        window_active=False,
        finish_requested=True,
    )
    assert after_window.state.phase == "stopping"
    assert after_window.plan.commands[0].value == "Self Use"


def test_retry_is_bounded_after_three_attempts() -> None:
    state = ChargeSessionState("starting", 10.0, 3, NOW - timedelta(minutes=1))
    result = _advance(state, FoxessObservation("Self Use", 0.0, 0.0))

    assert result.state == state
    assert result.reason == "max_attempts_exceeded"
    assert result.plan.commands == ()


def test_restoration_has_its_own_three_attempt_budget() -> None:
    exhausted_start = ChargeSessionState(
        "starting", 10.0, 3, NOW - timedelta(minutes=1)
    )
    first_stop = _advance(
        exhausted_start,
        FoxessObservation("Force Charge", 10.0, 0.0),
        window_active=False,
        finish_requested=True,
    )
    assert first_stop.state.phase == "stopping"
    assert first_stop.state.attempts == 1
    assert first_stop.plan.commands[0].value == "Self Use"

    third_stop = ChargeSessionState(
        "stopping", 10.0, 3, NOW - timedelta(minutes=1)
    )
    exhausted_restore = _advance(
        third_stop,
        FoxessObservation("Force Charge", 10.0, 0.0),
        window_active=False,
        finish_requested=True,
    )
    assert exhausted_restore.reason == "max_attempts_exceeded"
    assert exhausted_restore.plan.commands == ()


def test_reduced_native_limit_lowers_a_latched_session_without_raising_it_later() -> None:
    state = ChargeSessionState("active", 10.0, 0, NOW - timedelta(minutes=10))
    reduced = _advance(
        state,
        FoxessObservation("Force Charge", 10.0, 0.0),
        requested_charge_power_kw=6.0,
        charge_power_max_kw=6.0,
    )
    assert reduced.state.requested_power_kw == 6.0
    assert reduced.state.phase == "starting"
    assert reduced.plan.commands[0].action == "set_charge_power"
    assert reduced.plan.commands[0].value == 6.0

    unchanged = _advance(
        ChargeSessionState("active", 6.0, 0, NOW - timedelta(minutes=5)),
        FoxessObservation("Force Charge", 6.0, 0.0),
        requested_charge_power_kw=10.0,
        charge_power_max_kw=10.0,
    )
    assert unchanged.state.requested_power_kw == 6.0
    assert unchanged.plan.commands == ()
