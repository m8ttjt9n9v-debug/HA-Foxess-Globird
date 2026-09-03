"""A small, persisted daily import accumulator for greenfield installations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import isfinite


@dataclass(slots=True)
class DailyImportAccumulator:
    """Integrate positive grid power into a local-calendar-day meter.

    The accumulator deliberately accepts instantaneous power rather than
    pretending that an external cumulative sensor exists.  A bounded gap
    prevents a restart or communications outage from charging the entire
    outage interval at the last observed power.
    """

    max_gap_hours: float = 0.25
    local_date: date | None = None
    imported_kwh: float = 0.0
    last_at: datetime | None = None
    last_import_kw: float | None = None

    def restore(self, payload: dict[str, object] | None, now: datetime) -> None:
        """Restore same-day state; discard stale or malformed data safely."""
        self.local_date = now.date()
        self.imported_kwh = 0.0
        self.last_at = None
        self.last_import_kw = None
        if not isinstance(payload, dict) or payload.get("date") != now.date().isoformat():
            return
        try:
            imported = float(payload["imported_kwh"])
            last_at = datetime.fromisoformat(str(payload["last_at"]))
            last_import = float(payload["last_import_kw"])
        except (KeyError, TypeError, ValueError):
            return
        if (
            not isfinite(imported)
            or imported < 0
            or not isfinite(last_import)
            or last_import < 0
        ):
            return
        self.imported_kwh = imported
        self.last_at = last_at
        self.last_import_kw = last_import

    def observe(self, import_kw: float | None, now: datetime) -> bool:
        """Add one reading and return whether the state changed."""
        if import_kw is None or not isfinite(import_kw):
            return False
        import_kw = max(0.0, import_kw)
        if self.local_date != now.date():
            self.local_date = now.date()
            self.imported_kwh = 0.0
            self.last_at = None
            self.last_import_kw = None
        if self.last_at is not None and self.last_import_kw is not None:
            elapsed_hours = (now - self.last_at).total_seconds() / 3600
            if elapsed_hours > 0:
                elapsed_hours = min(elapsed_hours, self.max_gap_hours)
                self.imported_kwh += (self.last_import_kw + import_kw) / 2 * elapsed_hours
        self.last_at = now
        self.last_import_kw = import_kw
        return True

    def to_payload(self) -> dict[str, object]:
        """Return a Home Assistant Store-compatible payload."""
        return {
            "date": self.local_date.isoformat() if self.local_date else None,
            "imported_kwh": self.imported_kwh,
            "last_at": self.last_at.isoformat() if self.last_at else None,
            "last_import_kw": self.last_import_kw,
        }


@dataclass(slots=True)
class WindowImportAccumulator(DailyImportAccumulator):
    """Persist import energy observed inside one local-time window."""

    window_start: time = time(0)
    window_end: time = time(0)

    def observe(self, import_kw: float | None, now: datetime) -> bool:
        """Integrate only the overlap between the sample interval and the window."""
        if import_kw is None or not isfinite(import_kw):
            return False
        import_kw = max(0.0, import_kw)
        if self.local_date != now.date():
            self.local_date = now.date()
            self.imported_kwh = 0.0
            self.last_at = None
            self.last_import_kw = None
        if self.last_at is not None and self.last_import_kw is not None:
            elapsed_seconds = (now - self.last_at).total_seconds()
            if elapsed_seconds > 0:
                elapsed_seconds = min(elapsed_seconds, self.max_gap_hours * 3600)
                end = now
                start = now - timedelta(seconds=elapsed_seconds)
                overlap_hours = _window_overlap_hours(
                    start,
                    end,
                    self.window_start,
                    self.window_end,
                )
                if overlap_hours > 0:
                    self.imported_kwh += (self.last_import_kw + import_kw) / 2 * overlap_hours
        self.last_at = now
        self.last_import_kw = import_kw
        return True


@dataclass(slots=True)
class HourlyWindowImportAccumulator:
    """Persist import energy in independent local hourly buckets."""

    window_start: time
    window_end: time
    max_gap_hours: float = 0.25
    local_date: date | None = None
    hourly_import_kwh: dict[str, float] | None = None
    last_at: datetime | None = None
    last_import_kw: float | None = None

    def __post_init__(self) -> None:
        if self.hourly_import_kwh is None:
            self.hourly_import_kwh = {}

    def restore(self, payload: dict[str, object] | None, now: datetime) -> None:
        """Restore same-day buckets and discard malformed state."""
        self.local_date = now.date()
        self.hourly_import_kwh = {}
        self.last_at = None
        self.last_import_kw = None
        if not isinstance(payload, dict) or payload.get("date") != now.date().isoformat():
            return
        try:
            buckets = payload["hourly_import_kwh"]
            last_at = datetime.fromisoformat(str(payload["last_at"]))
            last_import = float(payload["last_import_kw"])
            if not isinstance(buckets, dict):
                return
            parsed = {str(key): float(value) for key, value in buckets.items()}
        except (KeyError, TypeError, ValueError):
            return
        if (
            not all(isfinite(value) and value >= 0 for value in parsed.values())
            or not isfinite(last_import)
            or last_import < 0
        ):
            return
        self.hourly_import_kwh = parsed
        self.last_at = last_at
        self.last_import_kw = last_import

    def observe(self, import_kw: float | None, now: datetime) -> bool:
        """Integrate one reading into the affected local hourly buckets."""
        if import_kw is None or not isfinite(import_kw):
            return False
        import_kw = max(0.0, import_kw)
        if self.local_date != now.date():
            self.local_date = now.date()
            self.hourly_import_kwh = {}
            self.last_at = None
            self.last_import_kw = None
        if self.last_at is not None and self.last_import_kw is not None:
            elapsed_seconds = (now - self.last_at).total_seconds()
            if elapsed_seconds > 0:
                elapsed_seconds = min(elapsed_seconds, self.max_gap_hours * 3600)
                start = now - timedelta(seconds=elapsed_seconds)
                average_kw = (self.last_import_kw + import_kw) / 2
                for bucket, overlap_hours in _hour_window_segments(
                    start, now, self.window_start, self.window_end
                ):
                    self.hourly_import_kwh[bucket] = (
                        self.hourly_import_kwh.get(bucket, 0.0) + average_kw * overlap_hours
                    )
        self.last_at = now
        self.last_import_kw = import_kw
        return True

    def to_payload(self) -> dict[str, object]:
        """Return a Home Assistant Store-compatible payload."""
        return {
            "date": self.local_date.isoformat() if self.local_date else None,
            "hourly_import_kwh": self.hourly_import_kwh,
            "last_at": self.last_at.isoformat() if self.last_at else None,
            "last_import_kw": self.last_import_kw,
        }


def _window_overlap_hours(
    start: datetime, end: datetime, window_start: time, window_end: time
) -> float:
    """Return overlap with a local-time daily window, including overnight windows."""
    if end <= start or window_start == window_end:
        return 0.0
    total_seconds = 0.0
    day = start.date()
    while day <= end.date():
        base = datetime.combine(day, window_start, tzinfo=start.tzinfo)
        window_end_at = datetime.combine(day, window_end, tzinfo=start.tzinfo)
        if window_end <= window_start:
            window_end_at += timedelta(days=1)
        overlap_start = max(start, base)
        overlap_end = min(end, window_end_at)
        if overlap_end > overlap_start:
            total_seconds += (overlap_end - overlap_start).total_seconds()
        day += timedelta(days=1)
    return total_seconds / 3600


def _hour_window_segments(
    start: datetime, end: datetime, window_start: time, window_end: time
) -> list[tuple[str, float]]:
    """Return (hour-bucket, overlap-hours) pairs for a local window."""
    if end <= start or window_start == window_end:
        return []
    segments: list[tuple[str, float]] = []
    cursor = start.replace(minute=0, second=0, microsecond=0)
    while cursor < end:
        next_hour = cursor + timedelta(hours=1)
        overlap_start = max(start, cursor)
        overlap_end = min(end, next_hour)
        if overlap_end > overlap_start:
            midpoint = overlap_start + (overlap_end - overlap_start) / 2
            current = midpoint.timetz().replace(tzinfo=None)
            active = (
                window_start <= current < window_end
                if window_start < window_end
                else current >= window_start or current < window_end
            )
            if active:
                segments.append(
                    (
                        cursor.isoformat(),
                        (overlap_end - overlap_start).total_seconds() / 3600,
                    )
                )
        cursor = next_hour
    return segments
