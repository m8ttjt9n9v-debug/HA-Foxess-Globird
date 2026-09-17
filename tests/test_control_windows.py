"""Pure control-window compatibility tests."""

from datetime import UTC, datetime, time

from custom_components.home_energy_orchestrator.planner.control_windows import (
    control_window_bounds,
    daily_windows_overlap,
    derive_force_discharge_finish,
    hours_until_next_window,
)


def test_force_discharge_finish_retains_offset_and_legacy_semantics() -> None:
    assert derive_force_discharge_finish(
        bonus_end=time(23, 59),
        offset_configured=True,
        offset_minutes=5,
        legacy_finish=time(21, 17),
    ) == time(0, 4)
    assert derive_force_discharge_finish(
        bonus_end=time(21),
        offset_configured=False,
        offset_minutes=5,
        legacy_finish=time(21, 17),
    ) == time(21, 17)


def test_control_window_bounds_retain_overnight_membership() -> None:
    before_midnight = control_window_bounds(
        datetime(2026, 9, 5, 23, tzinfo=UTC),
        start=time(22),
        finish=time(0, 4),
    )
    after_midnight = control_window_bounds(
        datetime(2026, 9, 6, 0, 2, tzinfo=UTC),
        start=time(22),
        finish=time(0, 4),
    )
    expected = (
        datetime(2026, 9, 5, 22, tzinfo=UTC),
        datetime(2026, 9, 6, 0, 4, tzinfo=UTC),
    )
    assert before_midnight == expected
    assert after_midnight == expected


def test_hours_until_next_window_rolls_at_exact_boundary() -> None:
    assert hours_until_next_window(
        datetime(2026, 9, 5, 10, tzinfo=UTC),
        start=time(11),
    ) == 1
    assert hours_until_next_window(
        datetime(2026, 9, 5, 11, tzinfo=UTC),
        start=time(11),
    ) == 24


def test_daily_window_overlap_retains_wrapped_and_touching_boundaries() -> None:
    assert daily_windows_overlap(time(23), time(2), time(1), time(3)) is True
    assert daily_windows_overlap(time(11), time(14), time(14), time(17)) is False
    assert daily_windows_overlap(time(11), time(14), time(13, 59), time(17)) is True
