"""Tests for the adapter-neutral FoxESS command planner."""

from __future__ import annotations

import pytest

from custom_components.home_energy_orchestrator.planner.control import ControlDecision
from custom_components.home_energy_orchestrator.planner.foxess import (
    FoxessObservation,
    foxess_response_matches,
    plan_foxess_commands,
)


def test_force_charge_orders_power_before_mode_and_clears_opposite_power() -> None:
    plan = plan_foxess_commands(
        ControlDecision("force_charge", 15, "free_window_below_target"),
        FoxessObservation("Self Use", 0, 4),
        charge_power_max_kw=10,
        discharge_power_max_kw=15,
    )
    assert [(command.action, command.value) for command in plan.commands] == [
        ("set_discharge_power", 0.0),
        ("set_charge_power", 10),
        ("select_mode", "Force Charge"),
    ]


def test_restore_orders_mode_then_wait_then_clears_targets() -> None:
    plan = plan_foxess_commands(
        ControlDecision("restore_self_use", 0, "no_active_policy"),
        FoxessObservation("Force Discharge", 0, 8),
        charge_power_max_kw=10,
        discharge_power_max_kw=15,
    )
    assert [(command.action, command.value, command.wait_seconds) for command in plan.commands] == [
        ("select_mode", "Self Use", 5.0),
        ("set_discharge_power", 0.0, 0.0),
    ]


def test_rehearsal_is_an_absolute_no_write_interlock() -> None:
    plan = plan_foxess_commands(
        ControlDecision("restore_self_use", 0, "rehearsal_mode"),
        FoxessObservation("Force Charge", 10, 0),
        rehearsal=True,
        charge_power_max_kw=10,
        discharge_power_max_kw=15,
    )
    assert plan.commands == ()
    assert plan.reason == "rehearsal_mode"


def test_response_verification_requires_mode_and_both_power_targets() -> None:
    decision = ControlDecision("force_discharge", 8, "export_window_ready")
    assert foxess_response_matches(decision, FoxessObservation("Force Discharge", 0, 8.005))
    assert not foxess_response_matches(decision, FoxessObservation("Self Use", 0, 8))
    assert not foxess_response_matches(decision, FoxessObservation("Force Discharge", 1, 8))


def test_invalid_feedback_is_rejected() -> None:
    with pytest.raises(ValueError):
        plan_foxess_commands(
            ControlDecision("hold", 0, "no_active_policy"),
            FoxessObservation("Self Use", -1, 0),
            charge_power_max_kw=10,
            discharge_power_max_kw=15,
        )
