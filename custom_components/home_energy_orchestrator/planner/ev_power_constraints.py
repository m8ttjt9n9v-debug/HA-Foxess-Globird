"""Shared electrical constraints for automatic EV charging policies."""

from __future__ import annotations

from math import floor, isfinite


def inverter_backed_current_ceiling(
    *,
    inverter_output_limit_kw: float,
    outside_inverter_percent: float,
    voltage_v: float,
    phase_count: int,
    current_step_a: float,
    charger_maximum_a: float,
) -> float:
    """Return the stepped per-phase EV current allowed from battery power.

    This is the single implementation of the configured outside-window
    inverter-power limit. Scheduling policies may decide *when* to charge, but
    they must all pass through this same electrical constraint.
    """
    values = (
        inverter_output_limit_kw,
        outside_inverter_percent,
        voltage_v,
        current_step_a,
        charger_maximum_a,
    )
    if not all(isfinite(value) and value >= 0 for value in values):
        raise ValueError("EV power-constraint inputs must be finite and non-negative")
    if outside_inverter_percent > 100:
        raise ValueError("outside inverter percentage cannot exceed 100")
    if phase_count < 1 or voltage_v <= 0 or current_step_a <= 0:
        raise ValueError("electrical topology must be commissioned")

    power_kw = inverter_output_limit_kw * outside_inverter_percent / 100
    raw_current_a = power_kw * 1000 / (voltage_v * phase_count)
    stepped_current_a = floor(raw_current_a / current_step_a) * current_step_a
    return round(min(stepped_current_a, charger_maximum_a), 3)
