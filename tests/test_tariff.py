from __future__ import annotations

import pytest

from custom_components.home_energy_orchestrator.planner.tariff import (
    calculate_daily_energy_cost,
    calculate_daily_financials,
    calculate_tariff_guard,
    calculate_zerohero_credit,
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


def test_daily_financials_count_boosted_export_once_and_report_net_cost() -> None:
    summary = calculate_daily_financials(
        total_import_kwh=70,
        free_window_import_kwh=55,
        peak_import_kwh=10,
        free_allowance_kwh=50,
        peak_rate=0.594,
        offpeak_rate=0.0,
        offpeak_balance_rate=0.308,
        shoulder_rate=0.528,
        daily_charge=2.035,
        total_export_kwh=20,
        standard_window_export_kwh=20,
        boosted_window_export_kwh=18,
        boosted_export_allowance_kwh=15,
        export_rate=0.05,
        boosted_export_rate=0.10,
    )

    import_energy_cost = 10 * 0.594 + 5 * 0.308 + 5 * 0.528
    export_revenue = 20 * 0.05 + 15 * 0.10
    assert summary.import_energy_cost == pytest.approx(import_energy_cost)
    assert summary.gross_cost == pytest.approx(2.035 + import_energy_cost)
    assert summary.standard_export_kwh == pytest.approx(20)
    assert summary.boosted_export_kwh == pytest.approx(15)
    assert summary.export_revenue == pytest.approx(export_revenue)
    assert summary.net_cost == pytest.approx(2.035 + import_energy_cost - export_revenue)


def test_daily_financials_clamp_window_export_to_measured_daily_total() -> None:
    summary = calculate_daily_financials(
        total_import_kwh=0,
        free_window_import_kwh=0,
        peak_import_kwh=0,
        free_allowance_kwh=50,
        peak_rate=0.594,
        offpeak_rate=0.0,
        offpeak_balance_rate=0.308,
        shoulder_rate=0.528,
        daily_charge=2.035,
        total_export_kwh=4,
        standard_window_export_kwh=15,
        boosted_window_export_kwh=15,
        boosted_export_allowance_kwh=15,
        export_rate=0.05,
        boosted_export_rate=0.10,
    )

    assert summary.boosted_export_kwh == pytest.approx(4)
    assert summary.standard_export_kwh == pytest.approx(4)
    assert summary.export_revenue == pytest.approx(0.6)
    assert summary.net_cost == pytest.approx(1.435)


def test_daily_financials_add_standard_and_first_fifteen_kwh_boost() -> None:
    summary = calculate_daily_financials(
        total_import_kwh=0,
        free_window_import_kwh=0,
        peak_import_kwh=0,
        free_allowance_kwh=50,
        peak_rate=0.594,
        offpeak_rate=0.0,
        offpeak_balance_rate=0.308,
        shoulder_rate=0.528,
        daily_charge=2.035,
        total_export_kwh=20,
        standard_window_export_kwh=20,
        boosted_window_export_kwh=20,
        boosted_export_allowance_kwh=15,
        export_rate=0.02,
        boosted_export_rate=0.08,
    )

    assert summary.standard_export_kwh == pytest.approx(20)
    assert summary.boosted_export_kwh == pytest.approx(15)
    assert summary.export_revenue == pytest.approx(20 * 0.02 + 15 * 0.08)
    assert summary.net_cost == pytest.approx(2.035 - 1.6)


def test_daily_financials_apply_standard_rate_outside_boosted_window() -> None:
    summary = calculate_daily_financials(
        total_import_kwh=0,
        free_window_import_kwh=0,
        peak_import_kwh=0,
        free_allowance_kwh=50,
        peak_rate=0.594,
        offpeak_rate=0.0,
        offpeak_balance_rate=0.308,
        shoulder_rate=0.528,
        daily_charge=2.035,
        total_export_kwh=10,
        standard_window_export_kwh=10,
        boosted_window_export_kwh=0,
        boosted_export_allowance_kwh=15,
        export_rate=0.05,
        boosted_export_rate=0.10,
    )

    assert summary.standard_export_kwh == pytest.approx(10)
    assert summary.boosted_export_kwh == pytest.approx(0)
    assert summary.export_revenue == pytest.approx(0.5)


def test_daily_financials_reject_invalid_export_inputs() -> None:
    with pytest.raises(ValueError):
        calculate_daily_financials(
            total_import_kwh=0,
            free_window_import_kwh=0,
            peak_import_kwh=0,
            free_allowance_kwh=50,
            peak_rate=0.594,
            offpeak_rate=0.0,
            offpeak_balance_rate=0.308,
            shoulder_rate=0.528,
            daily_charge=2.035,
            total_export_kwh=-1,
            standard_window_export_kwh=0,
            boosted_window_export_kwh=0,
            boosted_export_allowance_kwh=15,
            export_rate=0.05,
            boosted_export_rate=0.10,
        )


def test_daily_financials_apply_each_export_rate_only_to_its_window() -> None:
    summary = calculate_daily_financials(
        total_import_kwh=0,
        free_window_import_kwh=0,
        peak_import_kwh=0,
        free_allowance_kwh=50,
        peak_rate=0.594,
        offpeak_rate=0.0,
        offpeak_balance_rate=0.308,
        shoulder_rate=0.528,
        daily_charge=2.035,
        total_export_kwh=10,
        standard_window_export_kwh=4,
        boosted_window_export_kwh=3,
        boosted_export_allowance_kwh=15,
        export_rate=0.05,
        boosted_export_rate=0.10,
    )

    assert summary.standard_export_kwh == pytest.approx(4)
    assert summary.boosted_export_kwh == pytest.approx(3)
    assert summary.export_revenue == pytest.approx(4 * 0.05 + 3 * 0.10)


def test_zerohero_credit_is_applied_once_only_after_complete_qualified_window() -> None:
    pending = calculate_zerohero_credit(
        hourly_import_kwh=(0.01, 0.02),
        expected_hour_count=3,
        threshold_kwh_per_hour=0.03,
        configured_credit=1.0,
        window_complete=False,
    )
    earned = calculate_zerohero_credit(
        hourly_import_kwh=(0.01, 0.02, 0.03),
        expected_hour_count=3,
        threshold_kwh_per_hour=0.03,
        configured_credit=1.0,
        window_complete=True,
    )
    assert pending.status == "pending_window_completion"
    assert pending.credit == 0
    assert earned.status == "earned"
    assert earned.credit == 1.0


def test_zerohero_credit_fails_closed_on_excess_or_missing_hour() -> None:
    exceeded = calculate_zerohero_credit(
        hourly_import_kwh=(0.01, 0.031, 0.0),
        expected_hour_count=3,
        threshold_kwh_per_hour=0.03,
        configured_credit=1.0,
        window_complete=True,
    )
    incomplete = calculate_zerohero_credit(
        hourly_import_kwh=(0.0, 0.0),
        expected_hour_count=3,
        threshold_kwh_per_hour=0.03,
        configured_credit=1.0,
        window_complete=True,
    )
    assert exceeded.status == "threshold_exceeded"
    assert exceeded.credit == 0
    assert incomplete.status == "window_evidence_incomplete"
    assert incomplete.credit == 0
