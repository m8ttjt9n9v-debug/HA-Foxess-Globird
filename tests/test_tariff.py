from __future__ import annotations

import pytest

from custom_components.home_energy_orchestrator.planner.tariff import (
    calculate_daily_energy_cost,
    calculate_tariff_guard,
)


def test_daily_free_allowance_is_cumulative_and_caps_requested_energy() -> None:
    decision = calculate_tariff_guard(
        daily_free_allowance_kwh=50,
        imported_today_kwh=47.5,
        requested_free_charge_kwh=10,
        bonus_window_active=False,
        grid_import_kw=2,
        grid_telemetry_valid=True,
        zero_import_minutes=0,
    )
    assert decision.free_energy_remaining_kwh == 2.5
    assert decision.free_charge_energy_kwh == 2.5
    assert not decision.bonus_zero_import_allowed


def test_bonus_requires_sustained_qualified_zero_import() -> None:
    qualified = calculate_tariff_guard(
        daily_free_allowance_kwh=50,
        imported_today_kwh=0,
        requested_free_charge_kwh=0,
        bonus_window_active=True,
        grid_import_kw=0.02,
        grid_telemetry_valid=True,
        zero_import_minutes=5,
    )
    assert qualified.bonus_zero_import_allowed
    assert qualified.reason == "zero_import_qualified"

    transient = calculate_tariff_guard(
        daily_free_allowance_kwh=50,
        imported_today_kwh=0,
        requested_free_charge_kwh=0,
        bonus_window_active=True,
        grid_import_kw=0.02,
        grid_telemetry_valid=True,
        zero_import_minutes=4.9,
    )
    assert not transient.bonus_zero_import_allowed
    assert transient.reason == "zero_import_not_sustained"


def test_bonus_stops_when_import_is_detected_or_telemetry_is_stale() -> None:
    imported = calculate_tariff_guard(
        daily_free_allowance_kwh=50,
        imported_today_kwh=0,
        requested_free_charge_kwh=0,
        bonus_window_active=True,
        grid_import_kw=0.2,
        grid_telemetry_valid=True,
        zero_import_minutes=10,
    )
    stale = calculate_tariff_guard(
        daily_free_allowance_kwh=50,
        imported_today_kwh=0,
        requested_free_charge_kwh=0,
        bonus_window_active=True,
        grid_import_kw=None,
        grid_telemetry_valid=False,
        zero_import_minutes=10,
    )
    assert imported.reason == "grid_import_detected"
    assert stale.reason == "grid_telemetry_unavailable"
    assert not imported.bonus_zero_import_allowed
    assert not stale.bonus_zero_import_allowed


def test_zerohero_uses_window_energy_rate_when_available() -> None:
    qualified = calculate_tariff_guard(
        daily_free_allowance_kwh=50,
        imported_today_kwh=0,
        requested_free_charge_kwh=0,
        bonus_window_active=True,
        grid_import_kw=0.2,
        grid_telemetry_valid=True,
        zero_import_minutes=5,
        zero_import_threshold_kw=0.03,
        zerohero_window_import_kwh=0.02,
        zerohero_window_elapsed_hours=1,
    )
    assert qualified.bonus_zero_import_allowed

    exceeded = calculate_tariff_guard(
        daily_free_allowance_kwh=50,
        imported_today_kwh=0,
        requested_free_charge_kwh=0,
        bonus_window_active=True,
        grid_import_kw=0,
        grid_telemetry_valid=True,
        zero_import_minutes=5,
        zero_import_threshold_kw=0.03,
        zerohero_window_import_kwh=0.04,
        zerohero_window_elapsed_hours=1,
    )
    assert not exceeded.bonus_zero_import_allowed
    assert exceeded.reason == "zerohero_window_import_exceeded"


def test_zerohero_rejects_one_hour_even_when_three_hour_total_is_under_limit() -> None:
    decision = calculate_tariff_guard(
        daily_free_allowance_kwh=50,
        imported_today_kwh=0,
        requested_free_charge_kwh=0,
        bonus_window_active=True,
        grid_import_kw=0,
        grid_telemetry_valid=True,
        zero_import_minutes=5,
        zero_import_threshold_kw=0.03,
        zerohero_hourly_import_kwh=(0.01, 0.02, 0.04),
    )
    assert not decision.bonus_zero_import_allowed
    assert decision.reason == "zerohero_hourly_import_exceeded"


def test_tariff_guard_rejects_negative_meter_values() -> None:
    with pytest.raises(ValueError):
        calculate_tariff_guard(
            daily_free_allowance_kwh=50,
            imported_today_kwh=-1,
            requested_free_charge_kwh=0,
            bonus_window_active=False,
            grid_import_kw=0,
            grid_telemetry_valid=True,
            zero_import_minutes=0,
        )


def test_daily_energy_cost_applies_free_window_allowance_once() -> None:
    cost = calculate_daily_energy_cost(
        total_import_kwh=70,
        free_window_import_kwh=55,
        peak_import_kwh=10,
        free_allowance_kwh=50,
        peak_rate=0.594,
        offpeak_rate=0.0,
        offpeak_balance_rate=0.308,
        shoulder_rate=0.528,
        daily_charge=2.035,
    )
    # 10 kWh peak + 5 kWh above the free-window allowance + 5 kWh shoulder.
    assert cost == pytest.approx(10 * 0.594 + 5 * 0.308 + 5 * 0.528 + 2.035)
