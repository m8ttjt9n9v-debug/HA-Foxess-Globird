"""Faithful Tesla daily-driving and general charge-limit policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import ceil, floor, isfinite

from .learning import DemandLearningResult, select_protected_cycle_budget


@dataclass(frozen=True, slots=True)
class DrivingSnapshotState:
    """Restorable cumulative-energy snapshot from one free-window boundary."""

    snapshot_date: date | None = None
    lifetime_energy_kwh: float | None = None


@dataclass(frozen=True, slots=True)
class DrivingSnapshotTransition:
    """One boundary snapshot and an optional complete daily-energy sample."""

    state: DrivingSnapshotState
    sample_kwh: float | None


@dataclass(frozen=True, slots=True)
class LearnedChargeLimitDecision:
    """Pilot-compatible outside-window charge-limit evidence."""

    limit_percent: float
    mode: str
    sample_count: int
    p85_daily_energy_kwh: float | None
    usable_capacity_kwh: float
    free_window_soc_gain_percent: float


def snapshot_daily_driving_energy(
    state: DrivingSnapshotState,
    *,
    now: datetime,
    lifetime_energy_kwh: float,
) -> DrivingSnapshotTransition:
    """Port the source's one free-boundary cumulative-energy delta."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("snapshot time must be timezone-aware")
    if not isfinite(lifetime_energy_kwh) or lifetime_energy_kwh < 0:
        raise ValueError("lifetime energy must be finite and non-negative")
    previous = state.lifetime_energy_kwh
    sample = None
    if (
        state.snapshot_date == now.date() - timedelta(days=1)
        and previous is not None
        and previous > 0
        and lifetime_energy_kwh >= previous
    ):
        sample = round(lifetime_energy_kwh - previous, 3)
    return DrivingSnapshotTransition(
        DrivingSnapshotState(now.date(), round(lifetime_energy_kwh, 3)),
        sample,
    )


def estimate_usable_ev_capacity_kwh(
    *, stored_energy_kwh: float, soc_percent: float
) -> float:
    """Port Tessie stored-energy divided by current SoC."""
    if (
        not isfinite(stored_energy_kwh)
        or not isfinite(soc_percent)
        or stored_energy_kwh <= 0
        or soc_percent <= 0
        or soc_percent > 100
    ):
        raise ValueError("stored energy and SoC cannot estimate usable capacity")
    return round(stored_energy_kwh / (soc_percent / 100), 3)


def estimate_free_window_soc_gain_percent(
    *,
    maximum_current_a: float,
    voltage_v: float,
    phase_count: int,
    window_hours: float,
    charge_efficiency_percent: float,
    usable_capacity_kwh: float,
) -> float:
    """Port the modeled maximum one-window SoC gain with phase extension."""
    values = (
        maximum_current_a,
        voltage_v,
        float(phase_count),
        window_hours,
        charge_efficiency_percent,
        usable_capacity_kwh,
    )
    if not all(isfinite(value) for value in values) or (
        maximum_current_a < 0
        or voltage_v <= 0
        or phase_count < 1
        or window_hours < 0
        or not 0 < charge_efficiency_percent <= 100
        or usable_capacity_kwh <= 0
    ):
        raise ValueError("free-window gain inputs are invalid")
    wall_kwh = maximum_current_a * voltage_v * phase_count / 1000 * window_hours
    pack_kwh = wall_kwh * charge_efficiency_percent / 100
    return round(min(pack_kwh / usable_capacity_kwh * 100, 100.0), 3)


def plan_learned_general_charge_limit(
    samples_kwh: list[float],
    *,
    minimum_samples: int,
    arrival_reserve_percent: float,
    free_window_limit_percent: float,
    free_window_soc_gain_percent: float,
    usable_capacity_kwh: float,
    actuator_minimum_percent: float,
    actuator_maximum_percent: float,
    actuator_step_percent: float,
) -> LearnedChargeLimitDecision:
    """Port learning fallback and learned P85 branch/rounding exactly."""
    values = (
        arrival_reserve_percent,
        free_window_limit_percent,
        free_window_soc_gain_percent,
        usable_capacity_kwh,
        actuator_minimum_percent,
        actuator_maximum_percent,
        actuator_step_percent,
    )
    if (
        not all(isfinite(value) for value in values)
        or minimum_samples < 1
        or minimum_samples > 28
        or not 0 <= arrival_reserve_percent <= 100
        or not 0 <= free_window_limit_percent <= 100
        or free_window_soc_gain_percent < 0
        or usable_capacity_kwh <= 0
        or actuator_minimum_percent < 0
        or actuator_maximum_percent < actuator_minimum_percent
        or actuator_step_percent <= 0
    ):
        raise ValueError("learned charge-limit inputs are invalid")
    learning: DemandLearningResult = select_protected_cycle_budget(
        samples_kwh,
        0.0,
        minimum_samples=minimum_samples,
        sample_limit=28,
        percentile=85,
    )
    free_limit = min(
        max(free_window_limit_percent, actuator_minimum_percent),
        actuator_maximum_percent,
    )
    if learning.model == "p85":
        raw = (
            arrival_reserve_percent
            + learning.cycle_budget_kwh / usable_capacity_kwh * 100
            - free_window_soc_gain_percent
        )
        stepped = ceil(raw / actuator_step_percent) * actuator_step_percent
        p85 = learning.cycle_budget_kwh
        mode = "learned_p85"
    else:
        raw = free_limit - free_window_soc_gain_percent
        stepped = floor(raw / actuator_step_percent) * actuator_step_percent
        p85 = None
        mode = "learning_full_window_fallback"
    return LearnedChargeLimitDecision(
        limit_percent=round(
            min(max(stepped, actuator_minimum_percent), free_limit), 3
        ),
        mode=mode,
        sample_count=learning.sample_count,
        p85_daily_energy_kwh=p85,
        usable_capacity_kwh=usable_capacity_kwh,
        free_window_soc_gain_percent=free_window_soc_gain_percent,
    )
