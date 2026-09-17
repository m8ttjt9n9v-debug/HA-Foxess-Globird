"""Pure control-window compatibility tests."""

from datetime import UTC, datetime, time

from custom_components.home_energy_orchestrator.planner.control_windows import (
    boosted_window_active,
    control_window_bounds,
    daily_ready_cycle_bounds,
    daily_windows_overlap,
    derive_force_discharge_finish,
    hours_until_next_window,
    pre_free_window_position,
    window_duration_hours,
    window_position,
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


def test_window_duration_and_position_retain_free_window_boundaries() -> None:
    assert window_duration_hours(start=time(23), end=time(2)) == 3
    assert window_duration_hours(start=time(11), end=time(11)) == 24
    assert window_position(
        datetime(2026, 9, 6, 0, 30, tzinfo=UTC),
        start=time(23),
        end=time(2),
    ) == (True, 90.0, 1.5)
    assert window_position(
        datetime(2026, 9, 6, 2, tzinfo=UTC),
        start=time(23),
        end=time(2),
    ) == (False, 0.0, 0.0)


def test_daily_ready_cycle_retains_deadline_and_next_free_rules() -> None:
    before = daily_ready_cycle_bounds(
        datetime(2026, 9, 7, 6, tzinfo=UTC),
        ready=time(7),
        free_start=time(11),
    )
    assert before == (
        datetime(2026, 9, 7, 7, tzinfo=UTC),
        datetime(2026, 9, 7, 0, tzinfo=UTC),
        datetime(2026, 9, 7, 11, tzinfo=UTC),
    )
    at_deadline = daily_ready_cycle_bounds(
        datetime(2026, 9, 7, 7, tzinfo=UTC),
        ready=time(7),
        free_start=time(6),
    )
    assert at_deadline == (
        datetime(2026, 9, 8, 7, tzinfo=UTC),
        datetime(2026, 9, 8, 0, tzinfo=UTC),
        datetime(2026, 9, 9, 6, tzinfo=UTC),
    )


def test_pre_free_and_boosted_membership_retain_equal_and_wrapped_rules() -> None:
    assert pre_free_window_position(
        datetime(2026, 9, 7, 10, tzinfo=UTC),
        free_start=time(11),
        discharge_finish=time(21),
    ) == (datetime(2026, 9, 7, 11, tzinfo=UTC), True, 1.0)
    assert boosted_window_active(
        datetime(2026, 9, 7, 23, 30, tzinfo=UTC),
        start=time(23),
        end=time(2),
    ) is True
    assert boosted_window_active(
        datetime(2026, 9, 7, 12, tzinfo=UTC),
        start=time(11),
        end=time(11),
    ) is False
