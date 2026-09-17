"""Pure daily tariff/accounting projection from immutable observations."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..models import EnergyLedger
from .tariff import (
    calculate_daily_financials,
    calculate_tariff_guard,
    calculate_zerohero_credit,
)


@dataclass(frozen=True, slots=True)
class AccountingMeterSnapshot:
    """Daily and windowed meter observations for one coordinator cycle."""

    daily_import_kwh: float | None
    daily_import_source: str
    free_window_import_kwh: float | None
    peak_import_kwh: float
    daily_export_kwh: float | None
    standard_window_export_kwh: float | None
    boosted_window_export_kwh: float | None


@dataclass(frozen=True, slots=True)
class TariffConfiguration:
    """Validated non-negative rates and allowances used by accounting."""

    daily_free_allowance_kwh: float
    zero_import_threshold_kw: float
    minimum_zero_import_minutes: float
    zerohero_daily_credit: float
    peak_rate: float
    offpeak_rate: float
    offpeak_balance_rate: float
    shoulder_rate: float
    daily_charge: float
    boosted_export_allowance_kwh: float
    export_rate: float
    offpeak_export_rate: float
    boosted_export_rate: float


@dataclass(frozen=True, slots=True)
class ZeroHeroWindowEvidence:
    """Clock and import evidence for ZEROHERO qualification."""

    active: bool
    zero_import_minutes: float
    hourly_import_kwh: tuple[float, ...]
    elapsed_hours: float
    complete: bool
    expected_hour_count: int


@dataclass(frozen=True, slots=True)
class AccountingProjectionInputs:
    """Complete immutable input for one daily accounting projection."""

    ledger: EnergyLedger
    meters: AccountingMeterSnapshot
    tariff: TariffConfiguration | None
    zerohero: ZeroHeroWindowEvidence | None


def project_daily_accounting(inputs: AccountingProjectionInputs) -> EnergyLedger:
    """Project tariff guard, charges, credits and export earnings once."""
    ledger = inputs.ledger
    meters = inputs.meters
    export_accounting_available = all(
        value is not None
        for value in (
            meters.daily_export_kwh,
            meters.standard_window_export_kwh,
            meters.boosted_window_export_kwh,
        )
    )
    if meters.daily_import_kwh is None or meters.free_window_import_kwh is None:
        return replace(
            ledger,
            tariff_reason="daily_import_meter_unavailable",
            daily_import_kwh=meters.daily_import_kwh,
            daily_import_source=(
                meters.daily_import_source
                if meters.daily_import_kwh is not None
                else "unavailable"
            ),
            free_window_import_kwh=meters.free_window_import_kwh,
            daily_export_kwh=meters.daily_export_kwh,
            standard_window_export_kwh=meters.standard_window_export_kwh,
            boosted_window_export_kwh=meters.boosted_window_export_kwh,
        )

    tariff = inputs.tariff
    zerohero = inputs.zerohero
    if tariff is None or zerohero is None:
        raise ValueError("available accounting meters require tariff and window inputs")

    decision = calculate_tariff_guard(
        daily_free_allowance_kwh=tariff.daily_free_allowance_kwh,
        imported_today_kwh=meters.free_window_import_kwh,
        requested_free_charge_kwh=max(
            tariff.daily_free_allowance_kwh - meters.free_window_import_kwh,
            0.0,
        ),
        bonus_window_active=zerohero.active,
        grid_import_kw=ledger.grid_import_kw,
        grid_telemetry_valid=ledger.grid_import_kw is not None,
        zero_import_minutes=zerohero.zero_import_minutes,
        zero_import_threshold_kw=tariff.zero_import_threshold_kw,
        minimum_zero_import_minutes=tariff.minimum_zero_import_minutes,
        zerohero_hourly_import_kwh=zerohero.hourly_import_kwh,
        zerohero_window_elapsed_hours=zerohero.elapsed_hours,
    )
    credit = calculate_zerohero_credit(
        hourly_import_kwh=zerohero.hourly_import_kwh,
        expected_hour_count=zerohero.expected_hour_count,
        threshold_kwh_per_hour=tariff.zero_import_threshold_kw,
        configured_credit=tariff.zerohero_daily_credit,
        window_complete=zerohero.complete,
    )
    financials = calculate_daily_financials(
        total_import_kwh=meters.daily_import_kwh,
        free_window_import_kwh=meters.free_window_import_kwh,
        peak_import_kwh=meters.peak_import_kwh,
        free_allowance_kwh=tariff.daily_free_allowance_kwh,
        peak_rate=tariff.peak_rate,
        offpeak_rate=tariff.offpeak_rate,
        offpeak_balance_rate=tariff.offpeak_balance_rate,
        shoulder_rate=tariff.shoulder_rate,
        daily_charge=tariff.daily_charge,
        total_export_kwh=meters.daily_export_kwh or 0.0,
        standard_window_export_kwh=meters.standard_window_export_kwh or 0.0,
        boosted_window_export_kwh=meters.boosted_window_export_kwh or 0.0,
        boosted_export_allowance_kwh=tariff.boosted_export_allowance_kwh,
        export_rate=tariff.export_rate,
        offpeak_export_rate=tariff.offpeak_export_rate,
        boosted_export_rate=tariff.boosted_export_rate,
        zerohero_credit=credit.credit,
    )
    return replace(
        ledger,
        free_energy_remaining_kwh=decision.free_energy_remaining_kwh,
        free_charge_allowed_kwh=decision.free_charge_energy_kwh,
        bonus_zero_import_allowed=decision.bonus_zero_import_allowed,
        tariff_reason=decision.reason,
        daily_import_kwh=meters.daily_import_kwh,
        daily_import_source=meters.daily_import_source,
        free_window_import_kwh=meters.free_window_import_kwh,
        daily_export_kwh=meters.daily_export_kwh,
        standard_window_export_kwh=meters.standard_window_export_kwh,
        boosted_window_export_kwh=meters.boosted_window_export_kwh,
        standard_rate_export_kwh=(
            financials.standard_export_kwh if export_accounting_available else None
        ),
        offpeak_rate_export_kwh=(
            financials.offpeak_export_kwh if export_accounting_available else None
        ),
        boosted_rate_export_kwh=(
            financials.boosted_export_kwh if export_accounting_available else None
        ),
        estimated_energy_cost=financials.gross_cost,
        estimated_import_energy_cost=financials.import_energy_cost,
        daily_supply_charge=financials.supply_charge,
        standard_export_revenue=(
            financials.standard_export_revenue
            if export_accounting_available
            else None
        ),
        offpeak_export_revenue=(
            financials.offpeak_export_revenue
            if export_accounting_available
            else None
        ),
        boosted_bonus_revenue=(
            financials.boosted_bonus_revenue
            if export_accounting_available
            else None
        ),
        estimated_export_revenue=(
            financials.export_revenue if export_accounting_available else None
        ),
        zerohero_credit=credit.credit,
        zerohero_credit_status=credit.status,
        estimated_net_cost=(
            financials.net_cost if export_accounting_available else None
        ),
    )
