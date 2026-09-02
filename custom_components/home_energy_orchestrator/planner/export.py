"""Deterministic protected export planning primitives."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class ExportPlan:
    """A bounded export plan; it contains no Home Assistant side effects."""

    sellable_energy_kwh: float
    planned_export_energy_kwh: float
    planned_duration_h: float
    reason: str


def calculate_export_plan(
    available_ac_kwh: float,
    protected_house_kwh: float,
    protected_ev_kwh: float,
    allowance_remaining_kwh: float,
    discharge_power_kw: float,
) -> ExportPlan:
    """Apply the legacy protection and allowance rules to one export window."""
    values = (
        available_ac_kwh,
        protected_house_kwh,
        protected_ev_kwh,
        allowance_remaining_kwh,
        discharge_power_kw,
    )
    if not all(isfinite(value) for value in values):
        raise ValueError("export inputs must be finite")
    if any(value < 0 for value in values):
        raise ValueError("export inputs must be non-negative")

    sellable = max(available_ac_kwh - protected_house_kwh - protected_ev_kwh, 0.0)
    planned = min(sellable, allowance_remaining_kwh)
    if discharge_power_kw <= 0:
        return ExportPlan(sellable, 0.0, 0.0, "no_discharge_power")
    if planned <= 0:
        return ExportPlan(sellable, 0.0, 0.0, "no_protected_energy")
    return ExportPlan(sellable, planned, round(planned / discharge_power_kw, 3), "ready")
