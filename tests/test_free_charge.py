"""Tests for dynamic free-window charging limits."""

from __future__ import annotations

import pytest

from custom_components.home_energy_orchestrator.planner.free_charge import (
    calculate_free_charge_power,
)


def test_paces_fifty_kwh_across_three_hours_with_margin() -> None:
    plan = calculate_free_charge_power(
        allowance_remaining_kwh=50,
        hours_remaining=3,
        house_load_kw=0,
        pv_generation_kw=0,
        inverter_charge_limit_kw=15,
        safety_margin_kw=1,
    )
    assert plan.allowance_rate_kw == pytest.approx(16.667, abs=0.001)
    assert plan.target_grid_import_kw == pytest.approx(15.667, abs=0.001)
    assert plan.target_charge_power_kw == pytest.approx(15, abs=0.001)


def test_house_load_reduces_battery_target() -> None:
    plan = calculate_free_charge_power(
        allowance_remaining_kwh=45,
        hours_remaining=3,
        house_load_kw=4,
        pv_generation_kw=0,
        inverter_charge_limit_kw=15,
        safety_margin_kw=1,
    )
    assert plan.target_grid_import_kw == pytest.approx(14, abs=0.001)
    assert plan.target_charge_power_kw == pytest.approx(10, abs=0.001)


def test_ac_coupled_pv_increases_charge_without_increasing_grid_target() -> None:
    plan = calculate_free_charge_power(
        allowance_remaining_kwh=45,
        hours_remaining=3,
        house_load_kw=4,
        pv_generation_kw=3,
        inverter_charge_limit_kw=15,
        safety_margin_kw=1,
    )
    assert plan.target_grid_import_kw == pytest.approx(14, abs=0.001)
    assert plan.target_charge_power_kw == pytest.approx(13, abs=0.001)


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


def test_target_is_clamped_when_house_load_is_low_and_pv_is_high() -> None:
    plan = calculate_free_charge_power(
        allowance_remaining_kwh=50,
        hours_remaining=3,
        house_load_kw=0,
        pv_generation_kw=10,
        inverter_charge_limit_kw=15,
    )
    assert plan.target_charge_power_kw == 15


def test_invalid_minimum_is_rejected() -> None:
    with pytest.raises(ValueError, match="minimum charge"):
        calculate_free_charge_power(
            allowance_remaining_kwh=1,
            hours_remaining=1,
            house_load_kw=0,
            pv_generation_kw=0,
            inverter_charge_limit_kw=10,
            minimum_charge_power_kw=11,
        )
