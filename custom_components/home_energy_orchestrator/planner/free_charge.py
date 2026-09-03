"""Dynamic free-window battery charging limits.

The GloBird allowance is energy (kWh) accumulated across the window. This
planner turns the remaining allowance and time into an instantaneous grid
target, then backs out measured house demand and AC-coupled PV to produce a
bounded FoxESS battery-charge target. It has no Home Assistant side effects.
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


def calculate_free_charge_power(
    *,
    allowance_remaining_kwh: float,
    hours_remaining: float,
    house_load_kw: float,
    pv_generation_kw: float,
    inverter_charge_limit_kw: float,
    safety_margin_kw: float = 1.0,
    minimum_charge_power_kw: float = 0.0,
) -> FreeChargePowerPlan:
    """Calculate a charge target that paces the remaining energy allowance.

    The instantaneous target is ``allowance_remaining / hours_remaining`` less
    the safety margin. With measured AC-coupled PV, charging power can rise by
    the PV contribution without raising grid import. House load reduces the
    battery target. Every result is clamped to the inverter's commissioned
    charge limit.
    """
    values = (
        allowance_remaining_kwh,
        hours_remaining,
        house_load_kw,
        pv_generation_kw,
        inverter_charge_limit_kw,
        safety_margin_kw,
        minimum_charge_power_kw,
    )
    if not all(isfinite(value) for value in values):
        raise ValueError("free-charge inputs must be finite")
    if any(value < 0 for value in values):
        raise ValueError("free-charge inputs must be non-negative")
    if minimum_charge_power_kw > inverter_charge_limit_kw:
        raise ValueError("minimum charge power cannot exceed inverter limit")
    if allowance_remaining_kwh <= 0:
        return FreeChargePowerPlan(0.0, 0.0, 0.0, "allowance_exhausted")
    if hours_remaining <= 0:
        return FreeChargePowerPlan(0.0, 0.0, 0.0, "window_finished")

    allowance_rate = allowance_remaining_kwh / hours_remaining
    target_grid = max(allowance_rate - safety_margin_kw, 0.0)
    raw_charge = target_grid - house_load_kw + pv_generation_kw
    target_charge = min(max(raw_charge, minimum_charge_power_kw), inverter_charge_limit_kw)
    return FreeChargePowerPlan(
        round(target_charge, 3),
        round(target_grid, 3),
        round(allowance_rate, 3),
        "paced" if raw_charge > 0 else "house_load_exceeds_target",
    )

