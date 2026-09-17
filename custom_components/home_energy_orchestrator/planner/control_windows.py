"""Pure control-window calculations shared by active policy facades."""

from __future__ import annotations

from datetime import datetime, time, timedelta


def derive_force_discharge_finish(
    *,
    bonus_end: time,
    offset_configured: bool,
    offset_minutes: float,
    legacy_finish: time,
) -> time:
    """Derive ZEROHERO finish while retaining the pre-offset configuration."""
    if not offset_configured:
        return legacy_finish
    anchor = datetime.combine(datetime.min.date(), bonus_end)
    return (anchor + timedelta(minutes=offset_minutes)).time()


def control_window_bounds(
    now: datetime,
    *,
    start: time,
    finish: time,
) -> tuple[datetime, datetime]:
    """Resolve the current or next chronological bounds for a daily window."""
    start_at = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
    finish_at = datetime.combine(now.date(), finish, tzinfo=now.tzinfo)
    if finish <= start:
        finish_at += timedelta(days=1)
        if now < datetime.combine(now.date(), finish, tzinfo=now.tzinfo):
            start_at -= timedelta(days=1)
            finish_at -= timedelta(days=1)
    return start_at, finish_at


def hours_until_next_window(now: datetime, *, start: time) -> float:
    """Return non-negative hours until the next daily window start."""
    target = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
    if target <= now:
        target += timedelta(days=1)
    return max((target - now).total_seconds() / 3600, 0.0)


def daily_windows_overlap(
    first_start: time,
    first_end: time,
    second_start: time,
    second_end: time,
) -> bool:
    """Return whether two daily windows share any positive-duration interval."""

    def segments(start: time, end: time) -> tuple[tuple[int, int], ...]:
        start_s = start.hour * 3600 + start.minute * 60 + start.second
        end_s = end.hour * 3600 + end.minute * 60 + end.second
        if start_s < end_s:
            return ((start_s, end_s),)
        return ((start_s, 86400), (0, end_s))

    return any(
        max(first_left, second_left) < min(first_right, second_right)
        for first_left, first_right in segments(first_start, first_end)
        for second_left, second_right in segments(second_start, second_end)
    )
