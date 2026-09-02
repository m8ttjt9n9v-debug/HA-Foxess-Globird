"""Pure house-demand learning primitives.

The learner mirrors the legacy controller's protected-cycle policy without
depending on Home Assistant history or persistence APIs. The coordinator will
own sampling and persistence when this module is wired into the HACS runtime.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import floor, isfinite
from typing import Any


@dataclass(frozen=True, slots=True)
class DemandLearningResult:
    """The selected protected-cycle budget and its evidence."""

    cycle_budget_kwh: float
    sample_count: int
    model: str


@dataclass(frozen=True, slots=True)
class DemandCycleSample:
    """One completed protected-demand cycle."""

    observed_at: datetime
    energy_kwh: float


@dataclass(slots=True)
class DemandHistory:
    """Persistable rolling history for completed protected-demand cycles."""

    samples: list[DemandCycleSample]
    max_age_days: int = 35
    sample_limit: int = 28

    @classmethod
    def from_payload(
        cls, payload: Any, now: datetime, *, max_age_days: int = 35, sample_limit: int = 28
    ) -> DemandHistory:
        """Decode storage data, discarding malformed or expired rows."""
        raw_samples = payload.get("samples", []) if isinstance(payload, dict) else []
        decoded: list[DemandCycleSample] = []
        if isinstance(raw_samples, list):
            for raw in raw_samples:
                if not isinstance(raw, dict):
                    continue
                try:
                    decoded.append(
                        DemandCycleSample(
                            datetime.fromisoformat(str(raw["observed_at"])),
                            float(raw["energy_kwh"]),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    continue
        retained = retain_demand_samples(
            decoded, now, max_age_days=max_age_days, sample_limit=sample_limit
        )
        return cls(list(retained), max_age_days, sample_limit)

    def add(self, observed_at: datetime, energy_kwh: float) -> None:
        """Add a completed cycle and retain only valid recent samples."""
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        retention_now = max(
            observed_at,
            max((sample.observed_at for sample in self.samples), default=observed_at),
        )
        self.samples = list(
            retain_demand_samples(
                [*self.samples, DemandCycleSample(observed_at, energy_kwh)],
                retention_now,
                max_age_days=self.max_age_days,
                sample_limit=self.sample_limit,
            )
        )

    def to_payload(self) -> dict[str, list[dict[str, str | float]]]:
        """Return a JSON-safe Home Assistant storage payload."""
        return {
            "samples": [
                {"observed_at": sample.observed_at.isoformat(), "energy_kwh": sample.energy_kwh}
                for sample in self.samples
            ]
        }

    def select(self, fallback_kwh: float) -> DemandLearningResult:
        """Select the current budget from the retained history."""
        return select_protected_cycle_budget(
            [sample.energy_kwh for sample in self.samples],
            fallback_kwh,
            minimum_samples=7,
            sample_limit=self.sample_limit,
            percentile=80,
        )


@dataclass(slots=True)
class DemandCycleSampler:
    """Integrate non-free-window house power into completed daily cycles."""

    free_window_start: time
    free_window_end: time
    max_gap: timedelta = timedelta(minutes=10)
    _last_at: datetime | None = None
    _last_power_kw: float | None = None
    _cycle_started: bool = False
    _cycle_energy_kwh: float = 0.0

    def __post_init__(self) -> None:
        if self.free_window_start == self.free_window_end:
            raise ValueError("free window must not be empty")
        if self.max_gap <= timedelta(0):
            raise ValueError("max_gap must be positive")

    def observe(self, observed_at: datetime, house_power_kw: float) -> DemandCycleSample | None:
        """Accept one power reading and return a sample when a cycle completes."""
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if not isfinite(house_power_kw) or house_power_kw < 0:
            self._reset(observed_at, None)
            return None
        if self._last_at is None or self._last_power_kw is None:
            self._last_at = observed_at
            self._last_power_kw = house_power_kw
            if self._is_window_start(observed_at):
                self._cycle_started = True
            return None
        if observed_at <= self._last_at or observed_at - self._last_at > self.max_gap:
            self._reset(observed_at, house_power_kw)
            return None

        starts = self._window_starts_between(self._last_at, observed_at)
        cuts = self._window_boundaries_between(self._last_at, observed_at)
        result: DemandCycleSample | None = None
        for begin, finish in zip(cuts, cuts[1:]):
            midpoint = begin + (finish - begin) / 2
            if not self._in_free_window(midpoint):
                energy = self._trapezoid_energy(begin, finish, observed_at, house_power_kw)
                self._cycle_energy_kwh += energy if self._cycle_started else 0.0
            if finish in starts:
                if self._cycle_started:
                    result = DemandCycleSample(finish, self._cycle_energy_kwh)
                self._cycle_started = True
                self._cycle_energy_kwh = 0.0

        self._last_at = observed_at
        self._last_power_kw = house_power_kw
        return result

    def _reset(self, observed_at: datetime, house_power_kw: float | None) -> None:
        self._last_at = observed_at
        self._last_power_kw = house_power_kw
        self._cycle_started = False
        self._cycle_energy_kwh = 0.0

    def _trapezoid_energy(
        self, begin: datetime, finish: datetime, observed_at: datetime, observed_power_kw: float
    ) -> float:
        assert self._last_at is not None
        assert self._last_power_kw is not None
        total_seconds = (observed_at - self._last_at).total_seconds()
        begin_fraction = (begin - self._last_at).total_seconds() / total_seconds
        finish_fraction = (finish - self._last_at).total_seconds() / total_seconds
        begin_power = self._last_power_kw + (
            observed_power_kw - self._last_power_kw
        ) * begin_fraction
        finish_power = self._last_power_kw + (
            observed_power_kw - self._last_power_kw
        ) * finish_fraction
        return (begin_power + finish_power) / 2 * (finish - begin).total_seconds() / 3600

    def _window_bounds(self, day: date, tzinfo) -> tuple[datetime, datetime]:
        start = datetime.combine(day, self.free_window_start, tzinfo=tzinfo)
        finish = datetime.combine(day, self.free_window_end, tzinfo=tzinfo)
        if finish <= start:
            finish += timedelta(days=1)
        return start, finish

    def _window_starts_between(self, begin: datetime, finish: datetime) -> set[datetime]:
        starts: set[datetime] = set()
        day = begin.date() - timedelta(days=2)
        last_day = finish.date() + timedelta(days=2)
        while day <= last_day:
            candidate, _ = self._window_bounds(day, begin.tzinfo)
            if begin < candidate <= finish:
                starts.add(candidate)
            day += timedelta(days=1)
        return starts

    def _window_boundaries_between(self, begin: datetime, finish: datetime) -> list[datetime]:
        boundaries = {begin, finish}
        day = begin.date() - timedelta(days=2)
        last_day = finish.date() + timedelta(days=2)
        while day <= last_day:
            window_start, window_finish = self._window_bounds(day, begin.tzinfo)
            if begin < window_start < finish:
                boundaries.add(window_start)
            if begin < window_finish < finish:
                boundaries.add(window_finish)
            day += timedelta(days=1)
        return sorted(boundaries)

    def _in_free_window(self, value: datetime) -> bool:
        day = value.date() - timedelta(days=1)
        for _ in range(3):
            window_start, window_finish = self._window_bounds(day, value.tzinfo)
            if window_start <= value < window_finish:
                return True
            day += timedelta(days=1)
        return False

    def _is_window_start(self, value: datetime) -> bool:
        day = value.date() - timedelta(days=1)
        for _ in range(3):
            window_start, _ = self._window_bounds(day, value.tzinfo)
            if window_start == value:
                return True
            day += timedelta(days=1)
        return False


def retain_demand_samples(
    samples: Iterable[DemandCycleSample],
    now: datetime,
    *,
    max_age_days: int = 35,
    sample_limit: int = 28,
) -> tuple[DemandCycleSample, ...]:
    """Keep valid, recent cycle samples in chronological order."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if max_age_days < 1 or sample_limit < 1:
        raise ValueError("sample limits must be positive")
    cutoff = now - timedelta(days=max_age_days)
    valid = [
        sample
        for sample in samples
        if sample.observed_at.tzinfo is not None
        and cutoff <= sample.observed_at <= now
        and isfinite(sample.energy_kwh)
        and sample.energy_kwh >= 0
    ]
    return tuple(sorted(valid, key=lambda sample: sample.observed_at)[-sample_limit:])


def _percentile(values: list[float], percentile: float) -> float:
    """Return a linearly interpolated percentile for sorted values."""
    if not values:
        raise ValueError("at least one value is required")
    if not 0 <= percentile <= 100:
        raise ValueError("percentile must be between 0 and 100")
    position = (len(values) - 1) * percentile / 100
    lower = floor(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def select_protected_cycle_budget(
    samples_kwh: Iterable[float],
    fallback_kwh: float,
    *,
    minimum_samples: int = 7,
    sample_limit: int = 28,
    percentile: float = 80,
) -> DemandLearningResult:
    """Select the legacy-compatible protected house-energy budget.

    Invalid, negative and non-finite samples are ignored. Until the minimum
    sample count is reached, the explicit fallback is used. Once enough
    samples exist, only the latest ``sample_limit`` valid cycles contribute.
    """
    if not isfinite(fallback_kwh) or fallback_kwh < 0:
        raise ValueError("fallback_kwh must be finite and non-negative")
    if minimum_samples < 1 or sample_limit < minimum_samples:
        raise ValueError("sample limits must be positive and ordered")

    valid = [value for value in samples_kwh if isfinite(value) and value >= 0]
    valid = valid[-sample_limit:]
    if len(valid) < minimum_samples:
        return DemandLearningResult(fallback_kwh, len(valid), "fallback")
    return DemandLearningResult(
        round(_percentile(sorted(valid), percentile), 3),
        len(valid),
        f"p{percentile:g}",
    )


def remaining_protected_cycle_budget_kwh(
    cycle_budget_kwh: float,
    now: datetime,
    free_window_start: time,
    free_window_end: time,
) -> float:
    """Scale a full-cycle budget to the time remaining before free power.

    The protected budget covers the non-free portion of a 24-hour cycle. While
    the free window is active, no battery energy is reserved for the next
    cycle because the controller is already in the protected charging period.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if not isfinite(cycle_budget_kwh) or cycle_budget_kwh < 0:
        raise ValueError("cycle_budget_kwh must be finite and non-negative")
    if free_window_start == free_window_end:
        raise ValueError("free window must not be empty")

    window_start, window_finish = _window_bounds_for_day(
        now.date(), now.tzinfo, free_window_start, free_window_end
    )
    if window_start <= now <= window_finish:
        return 0.0
    next_window_start = window_start if now < window_start else window_start + timedelta(days=1)
    free_hours = (window_finish - window_start).total_seconds() / 3600
    protected_hours = max(24 - free_hours, 0)
    if protected_hours <= 0:
        return 0.0
    remaining_hours = max((next_window_start - now).total_seconds() / 3600, 0)
    return cycle_budget_kwh * min(remaining_hours, protected_hours) / protected_hours


def _window_bounds_for_day(
    day: date,
    tzinfo,
    free_window_start: time,
    free_window_end: time,
) -> tuple[datetime, datetime]:
    """Build one local-time free-window interval, including midnight spans."""
    start = datetime.combine(day, free_window_start, tzinfo=tzinfo)
    finish = datetime.combine(day, free_window_end, tzinfo=tzinfo)
    if finish <= start:
        finish += timedelta(days=1)
    return start, finish
