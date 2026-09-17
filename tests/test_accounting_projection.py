from __future__ import annotations

import pytest

from custom_components.home_energy_orchestrator.models import EnergyLedger
from custom_components.home_energy_orchestrator.planner.accounting import (
    AccountingMeterSnapshot,
    AccountingProjectionInputs,
    TariffConfiguration,
    ZeroHeroWindowEvidence,
    project_daily_accounting,
)


def _ledger() -> EnergyLedger:
    return EnergyLedger(
        battery_energy_kwh=10.0,
        battery_potential_capacity_kwh=20.0,
        floor_energy_kwh=2.0,
        available_after_floor_kwh=8.0,
        available_after_reserve_kwh=5.0,
        grid_import_kw=0.0,
        grid_export_kw=1.0,
        house_load_kw=0.5,
        ev_max_power_kw=7.0,
        reason="ready",
    )


def _tariff() -> TariffConfiguration:
    return TariffConfiguration(
        daily_free_allowance_kwh=50.0,
        zero_import_threshold_kw=0.03,
        minimum_zero_import_minutes=5.0,
        zerohero_daily_credit=1.0,
        peak_rate=0.57,
        offpeak_rate=0.0,
        offpeak_balance_rate=0.30,
        shoulder_rate=0.46,
        daily_charge=2.04,
        boosted_export_allowance_kwh=15.0,
        export_rate=0.05,
        offpeak_export_rate=0.02,
        boosted_export_rate=0.10,
    )


def _zerohero() -> ZeroHeroWindowEvidence:
    return ZeroHeroWindowEvidence(
        active=False,
        zero_import_minutes=0.0,
        hourly_import_kwh=(0.01, 0.02, 0.03),
        elapsed_hours=3.0,
        complete=True,
        expected_hour_count=3,
    )


def test_unavailable_meter_projection_preserves_partial_evidence() -> None:
    result = project_daily_accounting(
        AccountingProjectionInputs(
            ledger=_ledger(),
            meters=AccountingMeterSnapshot(
                daily_import_kwh=None,
                daily_import_source="internal_accumulator",
                free_window_import_kwh=None,
                peak_import_kwh=0.0,
                daily_export_kwh=3.0,
                standard_window_export_kwh=2.0,
                boosted_window_export_kwh=1.0,
            ),
            tariff=None,
            zerohero=None,
        )
    )

    assert result.tariff_reason == "daily_import_meter_unavailable"
    assert result.daily_import_source == "unavailable"
    assert result.daily_export_kwh == 3.0
    assert result.estimated_energy_cost is None


def test_projection_returns_guard_credit_and_non_double_counted_financials() -> None:
    result = project_daily_accounting(
        AccountingProjectionInputs(
            ledger=_ledger(),
            meters=AccountingMeterSnapshot(
                daily_import_kwh=10.0,
                daily_import_source="internal_accumulator",
                free_window_import_kwh=5.0,
                peak_import_kwh=2.0,
                daily_export_kwh=20.0,
                standard_window_export_kwh=4.0,
                boosted_window_export_kwh=18.0,
            ),
            tariff=_tariff(),
            zerohero=_zerohero(),
        )
    )

    assert result.free_energy_remaining_kwh == 45.0
    assert result.daily_import_source == "internal_accumulator"
    assert result.standard_rate_export_kwh == 4.0
    assert result.offpeak_rate_export_kwh == 16.0
    assert result.boosted_rate_export_kwh == 15.0
    assert result.zerohero_credit == 1.0
    assert result.zerohero_credit_status == "earned"
    assert result.estimated_energy_cost == pytest.approx(4.56)
    assert result.estimated_export_revenue == pytest.approx(2.02)
    assert result.estimated_net_cost == pytest.approx(1.54)


def test_available_meters_require_explicit_tariff_and_window_inputs() -> None:
    with pytest.raises(ValueError):
        project_daily_accounting(
            AccountingProjectionInputs(
                ledger=_ledger(),
                meters=AccountingMeterSnapshot(
                    daily_import_kwh=0.0,
                    daily_import_source="internal_accumulator",
                    free_window_import_kwh=0.0,
                    peak_import_kwh=0.0,
                    daily_export_kwh=None,
                    standard_window_export_kwh=None,
                    boosted_window_export_kwh=None,
                ),
                tariff=None,
                zerohero=None,
            )
        )
