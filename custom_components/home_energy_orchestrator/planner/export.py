"""Deterministic protected export planning primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
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
    window_hours: float | None = None,
) -> ExportPlan:
    """Apply the legacy protection and allowance rules to one export window."""
    values = (
        available_ac_kwh,
        protected_house_kwh,
        protected_ev_kwh,
        allowance_remaining_kwh,
        discharge_power_kw,
    )
    if window_hours is not None:
        values += (window_hours,)
    if not all(isfinite(value) for value in values):
        raise ValueError("export inputs must be finite")
    if any(value < 0 for value in values):
        raise ValueError("export inputs must be non-negative")

    sellable = max(available_ac_kwh - protected_house_kwh - protected_ev_kwh, 0.0)
    window_capacity_kwh = (
        discharge_power_kw * window_hours if window_hours is not None else float("inf")
    )
    planned = min(sellable, allowance_remaining_kwh, window_capacity_kwh)
    if discharge_power_kw <= 0:
        return ExportPlan(sellable, 0.0, 0.0, "no_discharge_power")
    if planned <= 0:
        return ExportPlan(sellable, 0.0, 0.0, "no_protected_energy")
    return ExportPlan(sellable, planned, round(planned / discharge_power_kw, 3), "ready")


def calculate_export_start(
    window_start: datetime, finish: datetime, planned_duration_h: float
) -> datetime | None:
    """Return Mangerton's latest bounded start, or no start after the finish."""
    if window_start.tzinfo is None or finish.tzinfo is None:
        raise ValueError("export boundaries must be timezone-aware")
    if finish <= window_start:
        raise ValueError("export finish must be after window start")
    if not isfinite(planned_duration_h) or planned_duration_h < 0:
        raise ValueError("planned_duration_h must be finite and non-negative")
    if planned_duration_h <= 0:
        return None
    return max(window_start, finish - timedelta(hours=planned_duration_h))
