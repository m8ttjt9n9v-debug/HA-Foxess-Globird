"""Preview calculations for the explicit FoxESS commissioning test surface."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class ManualTestEstimate:
    """Energy and money estimate shown before a test command is submitted."""

    energy_kwh: float
    amount: float
    rate_per_kwh: float
    direction: str


def estimate_charge(
    power_kw: float,
    duration_minutes: float,
    *,
    free_window_active: bool,
    free_energy_remaining_kwh: float,
    offpeak_rate: float,
    offpeak_balance_rate: float,
    current_rate: float,
) -> ManualTestEstimate:
    """Estimate import cost, applying the remaining free-window allowance."""
    energy = _energy(power_kw, duration_minutes)
    _validate_nonnegative(
        free_energy_remaining_kwh,
        offpeak_rate,
        offpeak_balance_rate,
        current_rate,
    )
    if free_window_active:
        free = min(energy, free_energy_remaining_kwh)
        chargeable = max(energy - free, 0.0)
        amount = free * offpeak_rate + chargeable * offpeak_balance_rate
        rate = amount / energy if energy else 0.0
    else:
        amount = energy * current_rate
        rate = current_rate
    return ManualTestEstimate(round(energy, 3), round(amount, 2), round(rate, 4), "cost")


def estimate_discharge(
    power_kw: float,
    duration_minutes: float,
    *,
    export_rate: float,
) -> ManualTestEstimate:
    """Estimate export earnings using the explicitly entered test rate."""
    energy = _energy(power_kw, duration_minutes)
    _validate_nonnegative(export_rate)
    return ManualTestEstimate(
        round(energy, 3), round(energy * export_rate, 2), round(export_rate, 4), "earning"
    )


def _energy(power_kw: float, duration_minutes: float) -> float:
    _validate_nonnegative(power_kw, duration_minutes)
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")
    return power_kw * duration_minutes / 60


def _validate_nonnegative(*values: float) -> None:
    if not all(isfinite(value) for value in values) or any(value < 0 for value in values):
        raise ValueError("manual test values must be finite and non-negative")
