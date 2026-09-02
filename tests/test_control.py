"""Tests for the side-effect-free FoxESS control decision layer."""

from __future__ import annotations

import pytest

from custom_components.home_energy_orchestrator.planner.control import (
    ControlInputs,
    decide_control,
)


def inputs(**changes) -> ControlInputs:
    values = dict(
        rehearsal=False,
        ready=True,
        automatic_charge=True,
        automatic_export=False,
        free_window_active=True,
        export_window_active=False,
        current_mode="Self Use",
        battery_soc=60,
        charge_target_soc=100,
        requested_charge_power_kw=15,
        charge_power_max_kw=10,
        planned_export_energy_kwh=0,
        grid_import_kw=0,
        export_import_limit_kw=0.2,
        minimum_grid_soc=10,
        configured_export_rate_c_kwh=15,
        minimum_export_rate_c_kwh=15,
        requested_discharge_power_kw=8,
        discharge_power_max_kw=6,
    )
    values.update(changes)
    return ControlInputs(**values)


def test_free_charge_is_bounded_by_writable_maximum() -> None:
    decision = decide_control(inputs())
    assert (decision.action, decision.power_kw, decision.reason) == (
        "force_charge",
        10,
        "free_window_below_target",
    )


def test_export_is_blocked_by_import_guard() -> None:
    decision = decide_control(
        inputs(
            automatic_charge=False,
            automatic_export=True,
            free_window_active=False,
            export_window_active=True,
            planned_export_energy_kwh=5,
            grid_import_kw=0.3,
        )
    )
    assert decision == decision.__class__("hold", 0, "no_active_policy")


def test_forced_mode_is_restored_when_window_ends() -> None:
    decision = decide_control(inputs(free_window_active=False, current_mode="Force Charge"))
    assert decision.action == "restore_self_use"
    assert decision.reason == "no_active_policy"


def test_rehearsal_never_requests_a_write() -> None:
    decision = decide_control(inputs(rehearsal=True, current_mode="Force Charge"))
    assert decision.action == "restore_self_use"
    assert decision.reason == "rehearsal_mode"


def test_active_export_is_bounded_by_writable_maximum() -> None:
    decision = decide_control(
        inputs(
            automatic_charge=False,
            automatic_export=True,
            free_window_active=False,
            export_window_active=True,
            planned_export_energy_kwh=5,
        )
    )
    assert decision.action == "force_discharge"
    assert decision.power_kw == 6


def test_invalid_control_input_is_rejected() -> None:
    with pytest.raises(ValueError):
        decide_control(inputs(grid_import_kw=-1))
