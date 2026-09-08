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


@dataclass(frozen=True, slots=True)
class OccupancyPerson:
    """One Home Assistant person's state used by the energy policy."""

    state: str
    last_changed: datetime


@dataclass(frozen=True, slots=True)
class OccupancyResult:
    """Conservative occupancy classification and its evidence."""

    state: str
    selected_mode: str
    person_count: int
    people_home: int
    all_people_away_for_hours: float
    reason: str


@dataclass(frozen=True, slots=True)
class HouseBudgetResult:
    """The one protected-house cycle budget selected by canonical policy."""

    cycle_budget_kwh: float
    base_sample_count: int
    heater_sample_count: int
    model: str
    occupancy: str

    @property
    def sample_count(self) -> int:
        """Retain the original base-learning diagnostic name."""
        return self.base_sample_count


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

    def restore(self, payload: Any, now: datetime) -> None:
        """Restore one in-progress cycle after a short Home Assistant restart."""
        if not isinstance(payload, dict) or now.tzinfo is None:
            return
        try:
            last_at = datetime.fromisoformat(str(payload["last_at"]))
            last_power_kw = float(payload["last_power_kw"])
            cycle_energy_kwh = float(payload["cycle_energy_kwh"])
            cycle_started = bool(payload["cycle_started"])
        except (KeyError, TypeError, ValueError):
            return
        if (
            last_at.tzinfo is None
            or last_at > now
            or now - last_at > self.max_gap
            or not isfinite(last_power_kw)
            or last_power_kw < 0
            or not isfinite(cycle_energy_kwh)
            or cycle_energy_kwh < 0
        ):
            return
        self._last_at = last_at
        self._last_power_kw = last_power_kw
        self._cycle_started = cycle_started
        self._cycle_energy_kwh = cycle_energy_kwh

    def to_payload(self) -> dict[str, str | float | bool] | None:
        """Encode the in-progress cycle for restart-safe persistence."""
        if self._last_at is None or self._last_power_kw is None:
            return None
        return {
            "last_at": self._last_at.isoformat(),
            "last_power_kw": self._last_power_kw,
            "cycle_started": self._cycle_started,
            "cycle_energy_kwh": self._cycle_energy_kwh,
        }

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


@dataclass(slots=True)
class DailyDemandCycleSampler:
    """Integrate a power source between successive local-time boundaries."""

    boundary: time
    max_gap: timedelta = timedelta(minutes=10)
    _last_at: datetime | None = None
    _last_power_kw: float | None = None
    _cycle_started: bool = False
    _cycle_energy_kwh: float = 0.0

    def __post_init__(self) -> None:
        if self.max_gap <= timedelta(0):
            raise ValueError("max_gap must be positive")

    def observe(self, observed_at: datetime, power_kw: float) -> DemandCycleSample | None:
        """Accept one reading and return the completed daily cycle, if any."""
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if not isfinite(power_kw) or power_kw < 0:
            self._reset(observed_at, None)
            return None
        if self._last_at is None or self._last_power_kw is None:
            self._last_at = observed_at
            self._last_power_kw = power_kw
            if observed_at.timetz().replace(tzinfo=None) == self.boundary:
                self._cycle_started = True
            return None
        if observed_at <= self._last_at or observed_at - self._last_at > self.max_gap:
            self._reset(observed_at, power_kw)
            return None

        boundaries = self._boundaries_between(self._last_at, observed_at)
        result: DemandCycleSample | None = None
        cuts = sorted({self._last_at, observed_at, *boundaries})
        for begin, finish in zip(cuts, cuts[1:]):
            if self._cycle_started:
                self._cycle_energy_kwh += self._trapezoid_energy(
                    begin, finish, observed_at, power_kw
                )
            if finish in boundaries:
                if self._cycle_started:
                    result = DemandCycleSample(finish, self._cycle_energy_kwh)
                self._cycle_started = True
                self._cycle_energy_kwh = 0.0

        self._last_at = observed_at
        self._last_power_kw = power_kw
        return result

    def restore(self, payload: Any, now: datetime) -> None:
        """Restore one in-progress daily cycle after a short restart."""
        if not isinstance(payload, dict) or now.tzinfo is None:
            return
        try:
            last_at = datetime.fromisoformat(str(payload["last_at"]))
            last_power_kw = float(payload["last_power_kw"])
            cycle_energy_kwh = float(payload["cycle_energy_kwh"])
            cycle_started = bool(payload["cycle_started"])
        except (KeyError, TypeError, ValueError):
            return
        if (
            last_at.tzinfo is None
            or last_at > now
            or now - last_at > self.max_gap
            or not isfinite(last_power_kw)
            or last_power_kw < 0
            or not isfinite(cycle_energy_kwh)
            or cycle_energy_kwh < 0
        ):
            return
        self._last_at = last_at
        self._last_power_kw = last_power_kw
        self._cycle_started = cycle_started
        self._cycle_energy_kwh = cycle_energy_kwh

    def to_payload(self) -> dict[str, str | float | bool] | None:
        """Encode the in-progress daily cycle for restart-safe persistence."""
        if self._last_at is None or self._last_power_kw is None:
            return None
        return {
            "last_at": self._last_at.isoformat(),
            "last_power_kw": self._last_power_kw,
            "cycle_started": self._cycle_started,
            "cycle_energy_kwh": self._cycle_energy_kwh,
        }

    def _reset(self, observed_at: datetime, power_kw: float | None) -> None:
        self._last_at = observed_at
        self._last_power_kw = power_kw
        self._cycle_started = False
        self._cycle_energy_kwh = 0.0

    def _boundaries_between(self, begin: datetime, finish: datetime) -> set[datetime]:
        boundaries: set[datetime] = set()
        day = begin.date()
        while day <= finish.date():
            candidate = datetime.combine(day, self.boundary, tzinfo=begin.tzinfo)
            if begin < candidate <= finish:
                boundaries.add(candidate)
            day += timedelta(days=1)
        return boundaries

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


def classify_energy_occupancy(
    mode: str,
    people: Iterable[OccupancyPerson],
    now: datetime,
    away_confirmation_hours: float,
) -> OccupancyResult:
    """Mirror the pilot's conservative Auto/Home/Away occupancy policy."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    selected_mode = str(mode).lower()
    if selected_mode not in {"auto", "home", "away"}:
        raise ValueError("mode must be auto, home, or away")
    if not isfinite(away_confirmation_hours) or away_confirmation_hours < 0:
        raise ValueError("away confirmation must be finite and non-negative")

    occupants = list(people)
    home_count = sum(person.state == "home" for person in occupants)
    uncertain = any(person.state in {"unknown", "unavailable"} for person in occupants)
    timestamps_valid = all(
        person.last_changed.tzinfo is not None and person.last_changed <= now
        for person in occupants
    )
    latest_change = (
        max((person.last_changed for person in occupants), default=now)
        if timestamps_valid
        else now
    )
    away_hours = (
        max((now - latest_change).total_seconds() / 3600, 0.0)
        if occupants and not home_count and not uncertain and timestamps_valid
        else 0.0
    )

    if selected_mode == "home":
        state, reason = "home", "manual_home"
    elif selected_mode == "away":
        state, reason = "away", "manual_away"
    elif not occupants:
        state, reason = "home", "no_person_entities_assume_home"
    elif home_count:
        state, reason = "home", "person_home"
    elif uncertain or not timestamps_valid:
        state, reason = "home", "presence_uncertain_assume_home"
    elif away_hours >= away_confirmation_hours:
        state, reason = "away", "all_people_away_confirmed"
    else:
        state, reason = "home", "away_confirmation_pending"

    return OccupancyResult(
        state=state,
        selected_mode=selected_mode,
        person_count=len(occupants),
        people_home=home_count,
        all_people_away_for_hours=round(away_hours, 3),
        reason=reason,
    )


def select_house_cycle_budget(
    base_samples_kwh: Iterable[float],
    heater_samples_kwh: Iterable[float] | None,
    occupied_fallback_kwh: float,
    away_fallback_kwh: float,
    occupancy: str,
    *,
    minimum_samples: int = 7,
    sample_limit: int = 28,
) -> HouseBudgetResult:
    """Select exactly one canonical occupied/away protected-house budget.

    When a separately metered heater is configured, both measured P80 streams
    must be mature before replacing the occupied fallback. Without that
    optional mapping, the mapped house source is treated as the complete
    protected load and its mature P80 can replace the fallback alone.
    """
    if occupancy not in {"home", "away"}:
        raise ValueError("occupancy must be home or away")
    if not isfinite(away_fallback_kwh) or away_fallback_kwh < 0:
        raise ValueError("away fallback must be finite and non-negative")
    base = select_protected_cycle_budget(
        base_samples_kwh,
        occupied_fallback_kwh,
        minimum_samples=minimum_samples,
        sample_limit=sample_limit,
        percentile=80,
    )
    heater = (
        None
        if heater_samples_kwh is None
        else select_protected_cycle_budget(
            heater_samples_kwh,
            0.0,
            minimum_samples=minimum_samples,
            sample_limit=sample_limit,
            percentile=80,
        )
    )
    heater_count = 0 if heater is None else heater.sample_count
    if occupancy == "away":
        return HouseBudgetResult(
            away_fallback_kwh,
            base.sample_count,
            heater_count,
            "away_fallback",
            occupancy,
        )
    if base.model == "p80" and (heater is None or heater.model == "p80"):
        return HouseBudgetResult(
            round(base.cycle_budget_kwh + (heater.cycle_budget_kwh if heater else 0.0), 3),
            base.sample_count,
            heater_count,
            "measured_occupied_p80",
            occupancy,
        )
    return HouseBudgetResult(
        occupied_fallback_kwh,
        base.sample_count,
        heater_count,
        "occupied_fallback",
        occupancy,
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
