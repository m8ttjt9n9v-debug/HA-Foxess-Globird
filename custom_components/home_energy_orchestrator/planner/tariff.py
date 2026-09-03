"""Pure GloBird-style allowance and zero-import engineering guards.

The tariff layer consumes already-normalised measurements. It does not read
Home Assistant state, decide when a daily meter resets, or call services.
Those responsibilities belong to the coordinator/adapter once the policy has
been commissioned for a site.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class TariffGuardDecision:
    """Auditable tariff constraints for one control evaluation."""

    free_energy_remaining_kwh: float
    free_charge_energy_kwh: float
    bonus_zero_import_allowed: bool
    reason: str


def calculate_daily_energy_cost(
    *,
    total_import_kwh: float,
    free_window_import_kwh: float,
    peak_import_kwh: float,
    free_allowance_kwh: float,
    peak_rate: float,
    offpeak_rate: float,
    offpeak_balance_rate: float,
    shoulder_rate: float,
    daily_charge: float,
) -> float:
    """Estimate cost without counting the free-window import twice.

    The free allowance applies only to imports in the configured off-peak
    window. Everything outside that window is classified as peak or shoulder;
    this function receives those windowed counters from the coordinator.
    """
    values = (
        total_import_kwh,
        free_window_import_kwh,
        peak_import_kwh,
        free_allowance_kwh,
        peak_rate,
        offpeak_rate,
        offpeak_balance_rate,
        shoulder_rate,
        daily_charge,
    )
    if not all(isfinite(value) for value in values) or any(value < 0 for value in values):
        raise ValueError("energy-cost inputs must be finite and non-negative")
    chargeable_free = max(free_window_import_kwh - free_allowance_kwh, 0.0)
    shoulder = max(total_import_kwh - free_window_import_kwh - peak_import_kwh, 0.0)
    return (
        daily_charge
        + peak_import_kwh * peak_rate
        + min(free_window_import_kwh, free_allowance_kwh) * offpeak_rate
        + chargeable_free * offpeak_balance_rate
        + shoulder * shoulder_rate
    )


def calculate_tariff_guard(
    *,
    daily_free_allowance_kwh: float,
    imported_today_kwh: float,
    requested_free_charge_kwh: float,
    bonus_window_active: bool,
    grid_import_kw: float | None,
    grid_telemetry_valid: bool,
    zero_import_minutes: float,
    zero_import_threshold_kw: float = 0.05,
    minimum_zero_import_minutes: float = 5.0,
    zerohero_window_import_kwh: float | None = None,
    zerohero_window_elapsed_hours: float | None = None,
    zerohero_hourly_import_kwh: tuple[float, ...] | None = None,
) -> TariffGuardDecision:
    """Bound free charging and evaluate the evening zero-import condition.

    ``imported_today_kwh`` is the import energy counted against the free
    allowance (the coordinator supplies its separate off-peak-window meter).
    Instantaneous power is only used for the local bonus guard; it is not a
    substitute for the retailer's billing meter or a claim that the ZEROHERO
    contract has been met.
    """

    values = (
        daily_free_allowance_kwh,
        imported_today_kwh,
        requested_free_charge_kwh,
        zero_import_minutes,
        zero_import_threshold_kw,
        minimum_zero_import_minutes,
    )
    if zerohero_window_import_kwh is not None:
        values += (zerohero_window_import_kwh,)
    if zerohero_window_elapsed_hours is not None:
        values += (zerohero_window_elapsed_hours,)
    if zerohero_hourly_import_kwh is not None:
        values += tuple(zerohero_hourly_import_kwh)
    if not all(isfinite(value) for value in values):
        raise ValueError("tariff inputs must be finite")
    if any(value < 0 for value in values):
        raise ValueError("tariff inputs must be non-negative")
    if grid_import_kw is not None and (not isfinite(grid_import_kw) or grid_import_kw < 0):
        raise ValueError("grid_import_kw must be finite and non-negative when provided")
    if zerohero_hourly_import_kwh is None and (
        (zerohero_window_import_kwh is None) != (zerohero_window_elapsed_hours is None)
    ):
        raise ValueError("ZEROHERO window energy and elapsed time must be provided together")

    remaining = max(daily_free_allowance_kwh - imported_today_kwh, 0.0)
    free_charge = min(requested_free_charge_kwh, remaining)
    if zerohero_hourly_import_kwh is not None:
        # The supplied wording is expressed per hour: every hourly bucket in
        # the 18:00–21:00 window must remain at or below the threshold.
        bonus_allowed = (
            bonus_window_active
            and grid_telemetry_valid
            and all(bucket <= zero_import_threshold_kw for bucket in zerohero_hourly_import_kwh)
            and zero_import_minutes >= minimum_zero_import_minutes
        )
    elif zerohero_window_import_kwh is not None and zerohero_window_elapsed_hours is not None:
        # The supplied contract threshold is expressed as 0.03 kWh/hour. A
        # three-hour window therefore permits 0.09 kWh in total, with a
        # running limit scaled by the elapsed part of that window.
        allowed_to_date = zero_import_threshold_kw * zerohero_window_elapsed_hours
        bonus_allowed = (
            bonus_window_active
            and grid_telemetry_valid
            and zerohero_window_import_kwh <= allowed_to_date
            and zero_import_minutes >= minimum_zero_import_minutes
        )
    else:
        bonus_allowed = (
            bonus_window_active
            and grid_telemetry_valid
            and grid_import_kw is not None
            and grid_import_kw <= zero_import_threshold_kw
            and zero_import_minutes >= minimum_zero_import_minutes
        )
    if not bonus_window_active:
        reason = "bonus_window_inactive"
    elif not grid_telemetry_valid or grid_import_kw is None:
        reason = "grid_telemetry_unavailable"
    elif zerohero_hourly_import_kwh is not None and any(
        bucket > zero_import_threshold_kw for bucket in zerohero_hourly_import_kwh
    ):
        reason = "zerohero_hourly_import_exceeded"
    elif zerohero_window_import_kwh is not None and zerohero_window_elapsed_hours is not None and (
        zerohero_window_import_kwh
        > zero_import_threshold_kw * zerohero_window_elapsed_hours
    ):
        reason = "zerohero_window_import_exceeded"
    elif grid_import_kw is not None and grid_import_kw > zero_import_threshold_kw:
        reason = "grid_import_detected"
    elif zero_import_minutes < minimum_zero_import_minutes:
        reason = "zero_import_not_sustained"
    else:
        reason = "zero_import_qualified"
    return TariffGuardDecision(remaining, free_charge, bonus_allowed, reason)
