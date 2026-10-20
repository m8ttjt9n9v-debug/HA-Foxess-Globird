"""Measured export counted once across configured paid opportunities.

This is a controller-cap meter, not proof of a retailer payment. Tariff windows
and the caller's already-owned price span qualify measured positive net export;
the meter never observes a market price or grants control permission itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import isfinite


@dataclass(slots=True)
class PaidExportAccumulator:
    """Daily paid-cap energy, with volatile bounded price provenance."""

    max_gap_hours: float = 0.25
    local_date: date | None = None
    imported_kwh: float = 0.0
    last_at: datetime | None = None
    last_import_kw: float | None = None
    checkpoint_required: bool = False
    valid: bool = True
    _legacy_seeded_date: date | None = None
    _needs_legacy_seed: bool = False
    _blocked_date: date | None = None
    _price_span: tuple[datetime, datetime] | None = None

    @property
    def legacy_seeded(self) -> bool:
        """Whether today's allowance conservatively includes legacy export."""
        return self._legacy_seeded_date == self.local_date

    @property
    def needs_legacy_seed(self) -> bool:
        """Only a genuinely missing store may receive the migration seed."""
        return self._needs_legacy_seed

    def _new_day(self, day: date) -> None:
        self.local_date = day
        self.imported_kwh = 0.0
        self.last_at = None
        self.last_import_kw = None
        self.valid = True
        self._legacy_seeded_date = None
        self._needs_legacy_seed = False
        self._blocked_date = None
        self._price_span = None

    def restore(self, payload: dict[str, object] | None, now: datetime) -> None:
        """Restore totals, never an old price lease or malformed allowance."""
        self._new_day(now.date())
        self.checkpoint_required = False
        if payload is None:
            self.valid = False
            self._needs_legacy_seed = True
            return
        try:
            if not isinstance(payload, dict):
                raise ValueError
            stored_day = date.fromisoformat(str(payload["date"]))
            if stored_day < now.date():
                return
            if (
                stored_day != now.date()
                or type(payload.get("version")) is not int
                or payload.get("version") != 1
            ):
                raise ValueError
            total = _nonnegative(payload["imported_kwh"])
            valid = payload["valid"]
            blocked = payload["blocked"]
            if not isinstance(valid, bool) or not isinstance(blocked, bool):
                raise ValueError
            if blocked and valid:
                raise ValueError
            legacy = payload.get("legacy_seeded_date")
            legacy_day = None if legacy is None else date.fromisoformat(str(legacy))
            if legacy_day is not None and legacy_day != stored_day:
                raise ValueError
            raw_at, raw_power = payload["last_at"], payload["last_import_kw"]
            if raw_at is None and raw_power is None:
                last_at, last_power = None, None
            else:
                last_at = datetime.fromisoformat(str(raw_at))
                last_power = _nonnegative(raw_power)
                if (
                    not _aware(last_at)
                    or not _aware(now)
                    or last_at.astimezone(UTC) > now.astimezone(UTC)
                    or last_at.astimezone(now.tzinfo).date() != stored_day
                ):
                    raise ValueError
            self.imported_kwh = total
            self.last_at, self.last_import_kw = last_at, last_power
            self.valid = valid
            self._blocked_date = stored_day if blocked else None
            self._legacy_seeded_date = legacy_day
        except (KeyError, OverflowError, TypeError, ValueError):
            self.valid = False
            self._blocked_date = now.date()
            self.last_at = None
            self.last_import_kw = None

    def seed_legacy(self, total_export_kwh: float | None, now: datetime) -> None:
        """Checkpoint a conservative first-day seed, never reset an old meter."""
        if not self._needs_legacy_seed or self.local_date != now.date():
            return
        try:
            self.imported_kwh = _nonnegative(total_export_kwh)
        except (TypeError, ValueError):
            self._blocked_date = now.date()
            self.valid = False
        else:
            self.valid = True
            self._legacy_seeded_date = now.date()
        self._needs_legacy_seed = False
        self.last_at = None
        self.last_import_kw = None
        self.checkpoint_required = True

    def observe(
        self,
        export_kw: float | None,
        now: datetime,
        *,
        standard_window: tuple[time, time],
        standard_rate: float,
        offpeak_rate: float,
        bonus_window: tuple[time, time],
        bonus_rate: float,
        bonus_allowance_remaining_kwh: float,
        price_start: datetime | None,
        price_end: datetime | None,
    ) -> bool:
        """Integrate union-qualified export using the retained trapezoid rule.

        Bonus allowance is the remainder BEFORE this sample interval. All
        measured bonus-window export consumes it, including energy already
        counted through a base tariff or price span. Invalid measurements break
        the anchor rather than bridging the outage at an old power.
        """
        self.checkpoint_required = False
        if self.local_date != now.date():
            self._new_day(now.date())
            self.checkpoint_required = True
        if self._blocked_date == now.date() or self._needs_legacy_seed:
            return False
        try:
            if isinstance(export_kw, bool):
                raise ValueError
            power = float(export_kw)
            if not isfinite(power):
                raise ValueError
            power = max(power, 0.0)
            standard_rate = _nonnegative(standard_rate)
            offpeak_rate = _nonnegative(offpeak_rate)
            bonus_rate = _nonnegative(bonus_rate)
            bonus_left = _nonnegative(bonus_allowance_remaining_kwh)
            gap = _nonnegative(self.max_gap_hours)
            if not _aware(now) or gap <= 0:
                raise ValueError
            for window in (standard_window, bonus_window):
                if len(window) != 2 or any(
                    not isinstance(value, time) or value.tzinfo is not None
                    for value in window
                ):
                    raise ValueError
            span = _span(price_start, price_end)
        except (OverflowError, TypeError, ValueError):
            changed = self.last_at is not None or self.valid
            self.last_at = None
            self.last_import_kw = None
            self._price_span = None
            self.valid = False
            self.checkpoint_required = changed
            return changed

        utc_now = now.astimezone(UTC)
        previous_power = self.last_import_kw
        if self.last_at is not None and previous_power is not None:
            previous_at = self.last_at.astimezone(UTC)
            if utc_now <= previous_at:
                return False
            start = max(previous_at, utc_now - timedelta(hours=gap))
            average = (previous_power + power) / 2
            spans = tuple(value for value in (self._price_span, span) if value is not None)
            boundaries = {start, utc_now}
            for window in (standard_window, bonus_window):
                for boundary in _window_boundaries(start, utc_now, window, now.tzinfo):
                    boundaries.add(boundary)
            transition = _offset_transition(start, utc_now, now.tzinfo)
            if transition is not None:
                boundaries.add(transition)
            for price_from, price_to in spans:
                boundaries.update(
                    boundary for boundary in (price_from, price_to)
                    if start < boundary < utc_now
                )
            ordered = sorted(boundaries)
            for left, right in zip(ordered, ordered[1:], strict=False):
                midpoint = left + (right - left) / 2
                local_clock = midpoint.astimezone(now.tzinfo).time()
                in_bonus = _in_window(local_clock, bonus_window)
                energy = average * (right - left).total_seconds() / 3600
                base_paid = (
                    standard_rate if _in_window(local_clock, standard_window)
                    else offpeak_rate
                ) > 0
                price_paid = any(lower <= midpoint < upper for lower, upper in spans)
                if base_paid or price_paid:
                    self.imported_kwh += energy
                elif in_bonus and bonus_rate > 0:
                    self.imported_kwh += min(energy, bonus_left)
                if in_bonus:
                    bonus_left = max(bonus_left - energy, 0.0)
        self.last_at = now
        self.last_import_kw = power
        self._price_span = span
        self.checkpoint_required = self.checkpoint_required or not self.valid or (
            previous_power is not None and previous_power > 0 and power == 0
        )
        self.valid = True
        return True

    def to_payload(self) -> dict[str, object]:
        """Use a distinct additive store; no old meter or lease is rewritten."""
        return {
            "version": 1,
            "date": self.local_date.isoformat() if self.local_date else None,
            "imported_kwh": self.imported_kwh,
            "last_at": self.last_at.isoformat() if self.last_at else None,
            "last_import_kw": self.last_import_kw,
            "valid": self.valid,
            "blocked": self._blocked_date == self.local_date,
            "legacy_seeded_date": (
                self._legacy_seeded_date.isoformat() if self._legacy_seeded_date else None
            ),
        }


def _nonnegative(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError
    result = float(value)
    if not isfinite(result) or result < 0:
        raise ValueError
    return result


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _span(
    start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime] | None:
    if start is None and end is None:
        return None
    if (
        not isinstance(start, datetime)
        or not isinstance(end, datetime)
        or not _aware(start)
        or not _aware(end)
        or end.astimezone(UTC) <= start.astimezone(UTC)
    ):
        raise ValueError
    return start.astimezone(UTC), end.astimezone(UTC)


def _in_window(clock: time, window: tuple[time, time]) -> bool:
    start, end = window
    if start == end:
        return False
    return start <= clock < end if start < end else clock >= start or clock < end


def _window_boundaries(start, end, window, timezone):
    """Split in UTC while local clocks retain configured tariff semantics."""
    day = start.astimezone(timezone).date() - timedelta(days=1)
    last_day = end.astimezone(timezone).date() + timedelta(days=1)
    while day <= last_day:
        for clock in window:
            # Both folds represent ambiguous local boundaries. The actual
            # offset transition is added separately for skipped-hour endpoints.
            for fold in (0, 1):
                boundary = datetime.combine(day, clock, tzinfo=timezone).replace(
                    fold=fold
                ).astimezone(UTC)
                if start < boundary < end:
                    yield boundary
        day += timedelta(days=1)


def _offset_transition(start, end, timezone):
    """Find a clock jump within the bounded sample, including skipped hours.

    Window endpoints inside a skipped local hour do not identify the actual
    offset transition. Split there as well so midpoint classification cannot
    assign both sides of the jump to one tariff. The normal fifteen-minute
    sample bound contains at most one timezone transition; binary search is
    bounded independently of elapsed time and finishes at datetime precision.
    """
    before = start.astimezone(timezone).utcoffset()
    if before == (end - timedelta(microseconds=1)).astimezone(timezone).utcoffset():
        return None
    left, right = start, end
    for _ in range(64):
        if right - left <= timedelta(microseconds=1):
            break
        middle = left + (right - left) / 2
        if middle.astimezone(timezone).utcoffset() == before:
            left = middle
        else:
            right = middle
    return right if start < right < end else None
