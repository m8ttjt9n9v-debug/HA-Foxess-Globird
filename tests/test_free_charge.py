"""Tests for dynamic free-window charging limits."""

from __future__ import annotations

import pytest

from custom_components.home_energy_orchestrator.planner.free_charge import (
    calculate_free_charge_power,
    decide_free_charge_completion,
)


def test_requests_commissioned_maximum_while_allowance_remains() -> None:
    plan = calculate_free_charge_power(
        allowance_remaining_kwh=50,
        hours_remaining=3,
        house_load_kw=0,
        pv_generation_kw=0,
        inverter_charge_limit_kw=15,
    )
    assert plan.allowance_rate_kw == pytest.approx(16.667, abs=0.001)
    assert plan.target_grid_import_kw == pytest.approx(15, abs=0.001)
    assert plan.target_charge_power_kw == pytest.approx(15, abs=0.001)
    assert plan.reason == "full_rate"


def test_house_load_does_not_reduce_battery_target() -> None:
    plan = calculate_free_charge_power(
        allowance_remaining_kwh=45,
        hours_remaining=3,
        house_load_kw=4,
        pv_generation_kw=0,
        inverter_charge_limit_kw=15,
    )
    assert plan.target_grid_import_kw == pytest.approx(19, abs=0.001)
    assert plan.target_charge_power_kw == pytest.approx(15, abs=0.001)


def test_ac_coupled_pv_reduces_estimated_grid_import_only() -> None:
    plan = calculate_free_charge_power(
        allowance_remaining_kwh=45,
        hours_remaining=3,
        house_load_kw=4,
        pv_generation_kw=3,
        inverter_charge_limit_kw=15,
    )
    assert plan.target_grid_import_kw == pytest.approx(16, abs=0.001)
    assert plan.target_charge_power_kw == pytest.approx(15, abs=0.001)


def test_exhausted_allowance_and_finished_window_are_noops() -> None:
    exhausted = calculate_free_charge_power(
        allowance_remaining_kwh=0,
        hours_remaining=3,
        house_load_kw=0,
        pv_generation_kw=0,
        inverter_charge_limit_kw=15,
    )
    finished = calculate_free_charge_power(
        allowance_remaining_kwh=10,
        hours_remaining=0,
        house_load_kw=0,
        pv_generation_kw=0,
        inverter_charge_limit_kw=15,
    )
    assert exhausted.reason == "allowance_exhausted"
    assert finished.reason == "window_finished"
    assert exhausted.target_charge_power_kw == finished.target_charge_power_kw == 0


def test_target_remains_at_commissioned_maximum_when_pv_is_high() -> None:
    plan = calculate_free_charge_power(
        allowance_remaining_kwh=50,
        hours_remaining=3,
        house_load_kw=0,
        pv_generation_kw=10,
        inverter_charge_limit_kw=15,
    )
    assert plan.target_charge_power_kw == 15


def test_full_battery_before_import_threshold_uses_backup() -> None:
    completion = decide_free_charge_completion(imported_kwh=48.9, battery_soc=100)
    assert completion == completion.__class__(
        "backup", "battery_full_before_import_threshold"
    )


def test_full_battery_at_import_threshold_uses_self_use() -> None:
    completion = decide_free_charge_completion(imported_kwh=49, battery_soc=100)
    assert completion == completion.__class__(
        "self_use", "free_allowance_cutoff_reached"
    )


def test_import_cutoff_uses_self_use_even_if_battery_is_not_full() -> None:
    completion = decide_free_charge_completion(imported_kwh=49, battery_soc=80)
    assert completion == completion.__class__(
        "self_use", "free_allowance_cutoff_reached"
    )


def test_allowance_exhaustion_uses_self_use_even_if_battery_is_not_full() -> None:
    completion = decide_free_charge_completion(imported_kwh=50, battery_soc=80)
    assert completion == completion.__class__("self_use", "free_allowance_exhausted")
