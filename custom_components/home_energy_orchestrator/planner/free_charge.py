"""Free-window battery charging decisions.

The GloBird allowance is energy (kWh) accumulated across the window. The
allowance is a stop condition, not a reason to throttle the battery below its
commissioned charge limit. This planner therefore requests the full
commissioned battery rate while allowance remains; the coordinator limits the
allowance to the configured cutoff before calling it. It has no Home
Assistant side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class FreeChargePowerPlan:
    """Auditable dynamic charge target for one free-window evaluation."""

    target_charge_power_kw: float
    target_grid_import_kw: float
    allowance_rate_kw: float
    reason: str


@dataclass(frozen=True, slots=True)
class FreeChargeCompletion:
    """Mode outcome when a free-window charge session is complete."""

    action: str
    reason: str


def decide_free_charge_completion(
    *,
    imported_kwh: float,
    battery_soc: float,
    daily_allowance_kwh: float = 50.0,
    full_battery_import_threshold_kwh: float = 49.0,
    full_soc_percent: float = 100.0,
) -> FreeChargeCompletion:
    """Choose the safe mode after free-window charging reaches a stop point.

    A full battery below the configured import threshold is restored to
    ``Backup`` so the remaining free allowance can be used by the house.
    Once the threshold is reached, ``Self Use`` prevents further deliberate
    grid import. Equality belongs to the self-use side of the boundary.
    """
    values = (
        imported_kwh,
        battery_soc,
        daily_allowance_kwh,
        full_battery_import_threshold_kwh,
        full_soc_percent,
    )
    if not all(isfinite(value) for value in values):
        raise ValueError("free-charge completion inputs must be finite")
    if any(value < 0 for value in values):
        raise ValueError("free-charge completion inputs must be non-negative")
    if daily_allowance_kwh <= 0:
        raise ValueError("daily allowance must be positive")
    if full_battery_import_threshold_kwh > daily_allowance_kwh:
        raise ValueError("full-battery threshold cannot exceed daily allowance")
    if imported_kwh >= daily_allowance_kwh:
        return FreeChargeCompletion("self_use", "free_allowance_exhausted")
    if imported_kwh >= full_battery_import_threshold_kwh:
        return FreeChargeCompletion("self_use", "free_allowance_cutoff_reached")
    if battery_soc < full_soc_percent:
        return FreeChargeCompletion("continue", "battery_below_full")
    return FreeChargeCompletion("backup", "battery_full_before_import_threshold")


def calculate_free_charge_power(
    *,
    allowance_remaining_kwh: float,
    hours_remaining: float,
    house_load_kw: float,
    pv_generation_kw: float,
    inverter_charge_limit_kw: float,
) -> FreeChargePowerPlan:
    """Request the commissioned maximum while the free allowance remains.

    ``hours_remaining`` is retained as an input so a finished window is a
    deterministic no-op and ``allowance_rate_kw`` remains available as an
    audit value. House load and AC-coupled PV are used only to estimate the
    resulting grid import; they do not throttle the battery target.
    """
    values = (
        allowance_remaining_kwh,
        hours_remaining,
        house_load_kw,
        pv_generation_kw,
        inverter_charge_limit_kw,
    )
    if not all(isfinite(value) for value in values):
        raise ValueError("free-charge inputs must be finite")
    if any(value < 0 for value in values):
        raise ValueError("free-charge inputs must be non-negative")
    if allowance_remaining_kwh <= 0:
        return FreeChargePowerPlan(0.0, 0.0, 0.0, "allowance_exhausted")
    if hours_remaining <= 0:
        return FreeChargePowerPlan(0.0, 0.0, 0.0, "window_finished")

    allowance_rate = allowance_remaining_kwh / hours_remaining
    target_charge = inverter_charge_limit_kw
    target_grid = max(target_charge + house_load_kw - pv_generation_kw, 0.0)
    return FreeChargePowerPlan(
        round(target_charge, 3),
        round(target_grid, 3),
        round(allowance_rate, 3),
        "full_rate",
    )
