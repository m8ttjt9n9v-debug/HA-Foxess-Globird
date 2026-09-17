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


def window_duration_hours(*, start: time, end: time) -> float:
    """Return retained daily window duration, treating equal bounds as 24 h."""
    anchor = datetime.min.date()
    start_at = datetime.combine(anchor, start)
    end_at = datetime.combine(anchor, end)
    if end_at <= start_at:
        end_at += timedelta(days=1)
    return (end_at - start_at).total_seconds() / 3600


def window_position(
    now: datetime,
    *,
    start: time,
    end: time,
) -> tuple[bool, float, float]:
    """Return active, elapsed minutes and remaining hours for a daily window."""
    start_at, end_at = control_window_bounds(now, start=start, finish=end)
    active = start_at <= now < end_at
    return (
        active,
        max((now - start_at).total_seconds() / 60, 0.0) if active else 0.0,
        max((end_at - now).total_seconds() / 3600, 0.0) if active else 0.0,
    )


def daily_ready_cycle_bounds(
    now: datetime,
    *,
    ready: time,
    free_start: time,
) -> tuple[datetime, datetime, datetime]:
    """Return next ready deadline, its planning-day start and next free start."""
    ready_at = datetime.combine(now.date(), ready, tzinfo=now.tzinfo)
    if now >= ready_at:
        ready_at += timedelta(days=1)
    planning_start = datetime.combine(
        ready_at.date(),
        datetime.min.time(),
        tzinfo=now.tzinfo,
    )
    next_free = datetime.combine(ready_at.date(), free_start, tzinfo=now.tzinfo)
    if next_free <= ready_at:
        next_free += timedelta(days=1)
    return ready_at, planning_start, next_free


def pre_free_window_position(
    now: datetime,
    *,
    free_start: time,
    discharge_finish: time,
) -> tuple[datetime, bool, float]:
    """Return next free start and retained pre-free interval membership."""
    free_at = datetime.combine(now.date(), free_start, tzinfo=now.tzinfo)
    if free_at <= now:
        free_at += timedelta(days=1)
    finish_at = datetime.combine(
        free_at.date(),
        discharge_finish,
        tzinfo=now.tzinfo,
    )
    if discharge_finish >= free_start:
        finish_at -= timedelta(days=1)
    return (
        free_at,
        finish_at <= now < free_at,
        max((free_at - now).total_seconds() / 3600, 0.0),
    )


def boosted_window_active(
    now: datetime,
    *,
    start: time,
    end: time,
) -> bool:
    """Return boosted-window membership, retaining equal-bounds disabled state."""
    start_at = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
    end_at = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
    if end > start:
        return start_at <= now < end_at
    if end < start:
        return now >= start_at or now < end_at
    return False


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
