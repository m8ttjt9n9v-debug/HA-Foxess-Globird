"""Paid cap counts measured union energy, never a second sale or price rule."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.home_energy_orchestrator.planner.paid_export import (
    PaidExportAccumulator,
)

SYDNEY = ZoneInfo("Australia/Sydney")


def _at(hour=18, minute=0, *, day=20):
    return datetime(2026, 10, day, hour, minute, tzinfo=SYDNEY)


def _observe(meter, power, now, **overrides):
    inputs = {
        "standard_window": (time(16), time(23)),
        "standard_rate": 0.15,
        "offpeak_rate": 0.0,
        "bonus_window": (time(18), time(21)),
        "bonus_rate": 0.10,
        "bonus_allowance_remaining_kwh": 15.0,
        "price_start": None,
        "price_end": None,
    }
    inputs.update(overrides)
    return meter.observe(power, now, **inputs)


@pytest.mark.parametrize(
    ("hour", "overrides", "expected"),
    [
        (12, {}, 0.0),
        (17, {}, 1.0),
        (19, {}, 1.0),
        (22, {}, 1.0),
        (23, {}, 0.0),
        (12, {"offpeak_rate": 0.01}, 1.0),
        (19, {"standard_rate": 0.0, "bonus_rate": 0.0}, 0.0),
        (19, {"standard_rate": 0.0}, 1.0),
        (19, {"standard_rate": 0.0, "bonus_allowance_remaining_kwh": 0}, 0.0),
        (19, {"standard_rate": 0.0, "bonus_allowance_remaining_kwh": 0.4}, 0.4),
        (19, {"bonus_allowance_remaining_kwh": 0}, 1.0),
        (12, {"standard_window": (time(0), time(0))}, 0.0),
    ],
)
def test_only_positive_applicable_tariff_counts_once(hour, overrides, expected):
    meter = PaidExportAccumulator()
    start = _at(hour)
    _observe(meter, 4.0, start, **overrides)
    _observe(meter, 4.0, start + timedelta(minutes=15), **overrides)
    assert meter.valid
    assert meter.imported_kwh == pytest.approx(expected)


def test_standard_bonus_and_price_overlap_count_same_export_once():
    meter = PaidExportAccumulator()
    start = _at(19)
    price = {"price_start": start, "price_end": start + timedelta(minutes=5)}
    _observe(meter, 12.0, start, **price)
    _observe(meter, 12.0, start + timedelta(minutes=5), **price)
    assert meter.imported_kwh == pytest.approx(1.0)


def test_arbitrary_window_union_and_bonus_exhaustion_are_not_summed():
    meter = PaidExportAccumulator(max_gap_hours=4)
    options = {
        "standard_window": (time(18), time(19)),
        "bonus_window": (time(17), time(20)),
        "bonus_allowance_remaining_kwh": 1.0,
    }
    _observe(meter, 3.0, _at(17, 30), **options)
    _observe(meter, 3.0, _at(19, 30), **options)
    assert meter.imported_kwh == pytest.approx(4.0)


def test_base_paid_energy_still_consumes_bonus_allowance_before_later_segment():
    meter = PaidExportAccumulator(max_gap_hours=4)
    options = {
        "standard_window": (time(18), time(19)),
        "bonus_window": (time(18), time(21)),
        "bonus_allowance_remaining_kwh": 3.0,
    }
    _observe(meter, 2.0, _at(18), **options)
    _observe(meter, 2.0, _at(20), **options)
    assert meter.imported_kwh == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("window", "start", "finish", "expected"),
    [
        ((time(18), time(21)), _at(17, 59), _at(18, 1), 0.1),
        ((time(18), time(21)), _at(20, 59), _at(21, 1), 0.1),
        ((time(18), time(21)), _at(21), _at(21, 2), 0.0),
        ((time(22), time(2)), _at(23), _at(23, 10), 1.0),
        ((time(22), time(2)), _at(1), _at(1, 10), 1.0),
    ],
)
def test_window_boundaries_and_overnight_windows(window, start, finish, expected):
    meter = PaidExportAccumulator()
    inputs = {"standard_window": window, "bonus_rate": 0}
    _observe(meter, 6.0, start, **inputs)
    _observe(meter, 6.0, finish, **inputs)
    assert meter.imported_kwh == pytest.approx(expected)


def test_price_only_counts_measured_energy_inside_its_absolute_span():
    meter = PaidExportAccumulator(max_gap_hours=1)
    start = _at(12)
    inputs = {
        "price_start": start + timedelta(minutes=10),
        "price_end": start + timedelta(minutes=20),
    }
    _observe(meter, 4.0, start, **inputs)
    _observe(meter, 4.0, start + timedelta(minutes=30), **inputs)
    assert meter.imported_kwh == pytest.approx(2 / 3)


def test_last_owned_price_span_finishes_once_when_current_authority_withdrawn():
    meter = PaidExportAccumulator()
    start = _at(12)
    _observe(
        meter, 6.0, start + timedelta(minutes=4),
        price_start=start, price_end=start + timedelta(minutes=5),
    )
    _observe(meter, 6.0, start + timedelta(minutes=6))
    assert meter.imported_kwh == pytest.approx(0.1)
    _observe(meter, 6.0, start + timedelta(minutes=10))
    assert meter.imported_kwh == pytest.approx(0.1)


def test_adjacent_owned_price_blocks_do_not_duplicate_or_gap_energy():
    meter = PaidExportAccumulator()
    start = _at(12)
    _observe(meter, 6, start, price_start=start, price_end=start + timedelta(minutes=5))
    _observe(
        meter, 6, start + timedelta(minutes=7),
        price_start=start + timedelta(minutes=5), price_end=start + timedelta(minutes=10),
    )
    assert meter.imported_kwh == pytest.approx(0.7)


def test_expired_price_does_not_authorise_bounded_outage_tail():
    meter = PaidExportAccumulator()
    start = _at(12)
    _observe(meter, 8, start, price_start=start, price_end=start + timedelta(minutes=5))
    _observe(meter, 8, start + timedelta(hours=1))
    assert meter.imported_kwh == 0


def test_trapezoid_and_existing_maximum_gap_are_preserved():
    meter = PaidExportAccumulator()
    _observe(meter, 4, _at(18))
    _observe(meter, 8, _at(19))
    assert meter.imported_kwh == pytest.approx(1.5)


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), True, "bad"])
def test_invalid_power_breaks_anchor_without_erasing_total_or_bridging(bad):
    meter = PaidExportAccumulator()
    _observe(meter, 6, _at(18))
    _observe(meter, 6, _at(18, 1))
    assert meter.imported_kwh == pytest.approx(0.1)
    _observe(meter, bad, _at(18, 2))
    assert not meter.valid
    assert meter.checkpoint_required
    assert meter.last_at is None
    _observe(meter, 6, _at(18, 10))
    assert meter.valid
    assert meter.imported_kwh == pytest.approx(0.1)
    _observe(meter, 6, _at(18, 11))
    assert meter.imported_kwh == pytest.approx(0.2)


def test_negative_flow_has_zero_export_and_positive_to_zero_checkpoints():
    meter = PaidExportAccumulator()
    _observe(meter, 6, _at(18))
    _observe(meter, -2, _at(18, 1))
    assert meter.valid
    assert meter.imported_kwh == pytest.approx(0.05)
    assert meter.checkpoint_required
    assert meter.last_import_kw == 0


@pytest.mark.parametrize(
    "invalid",
    [
        {"standard_rate": -0.01}, {"offpeak_rate": float("nan")},
        {"bonus_rate": True}, {"bonus_allowance_remaining_kwh": -1},
        {"standard_window": ("16", time(23))},
        {"price_start": _at(18)},
        {"price_start": _at(18), "price_end": _at(17)},
        {"price_start": datetime(2026, 10, 20, 18), "price_end": _at(19)},
    ],
)
def test_invalid_eligibility_does_not_silently_create_allowance(invalid):
    meter = PaidExportAccumulator()
    _observe(meter, 6, _at(18))
    _observe(meter, 6, _at(18, 1), **invalid)
    assert not meter.valid
    assert meter.imported_kwh == 0
    assert meter.last_at is None


def test_same_or_backward_observation_does_not_replace_anchor():
    meter = PaidExportAccumulator()
    _observe(meter, 6, _at(18))
    assert not _observe(meter, 20, _at(18))
    assert not _observe(meter, 20, _at(17, 59))
    assert meter.last_import_kw == 6
    _observe(meter, 6, _at(18, 1))
    assert meter.imported_kwh == pytest.approx(0.1)


def test_midnight_resets_paid_day_and_conservative_seed_marker():
    meter = PaidExportAccumulator()
    meter.restore(None, _at(23))
    meter.seed_legacy(17, _at(23))
    assert meter.valid and meter.legacy_seeded
    _observe(meter, 6, _at(23, 59), offpeak_rate=0.01)
    _observe(meter, 6, _at(0, day=21), offpeak_rate=0.01)
    assert meter.imported_kwh == 0
    assert not meter.legacy_seeded
    _observe(meter, 6, _at(0, 1, day=21), offpeak_rate=0.01)
    assert meter.imported_kwh == pytest.approx(0.1)


@pytest.mark.parametrize(
    ("utc_start", "utc_end", "window", "expected"),
    [
        # Spring forward: 01:55 -> 03:05 is ten physical minutes, not seventy.
        (datetime(2026, 10, 3, 15, 55, tzinfo=UTC),
         datetime(2026, 10, 3, 16, 5, tzinfo=UTC), (time(1), time(4)), 1.0),
        # Both copies of the fall-back hour are physical paid time.
        (datetime(2026, 4, 4, 15, 55, tzinfo=UTC),
         datetime(2026, 4, 4, 16, 5, tzinfo=UTC), (time(2), time(3)), 1.0),
    ],
)
def test_dst_uses_elapsed_utc_time_with_local_tariff_windows(
    utc_start, utc_end, window, expected
):
    meter = PaidExportAccumulator()
    inputs = {"standard_window": window, "bonus_rate": 0}
    _observe(meter, 6, utc_start.astimezone(SYDNEY), **inputs)
    _observe(meter, 6, utc_end.astimezone(SYDNEY), **inputs)
    assert meter.imported_kwh == pytest.approx(expected)


@pytest.mark.parametrize(
    ("start", "finish", "window", "expected"),
    [
        # The nonexistent 02:30 boundary is not the actual 02:00 -> 03:00 jump.
        (datetime(2026, 10, 3, 15, 55, tzinfo=UTC),
         datetime(2026, 10, 3, 16, 5, tzinfo=UTC), (time(1, 30), time(2, 30)), 0.5),
        (datetime(2026, 10, 3, 15, 55, tzinfo=UTC),
         datetime(2026, 10, 3, 16, 5, tzinfo=UTC), (time(2, 30), time(3, 30)), 0.5),
        # Exact transition endpoint belongs wholly to the preceding interval.
        (datetime(2026, 10, 3, 15, 55, tzinfo=UTC),
         datetime(2026, 10, 3, 16, tzinfo=UTC), (time(1, 30), time(2, 30)), 0.5),
        (datetime(2026, 10, 3, 16, tzinfo=UTC),
         datetime(2026, 10, 3, 16, 5, tzinfo=UTC), (time(2, 30), time(3, 30)), 0.5),
        # Fall back crosses 02:55(first fold) -> 02:05(second fold).
        (datetime(2026, 4, 4, 15, 55, tzinfo=UTC),
         datetime(2026, 4, 4, 16, 5, tzinfo=UTC), (time(2, 30), time(3, 30)), 0.5),
        (datetime(2026, 4, 4, 15, 55, tzinfo=UTC),
         datetime(2026, 4, 4, 16, 5, tzinfo=UTC), (time(1, 30), time(2, 30)), 0.5),
        (datetime(2026, 4, 4, 15, 55, tzinfo=UTC),
         datetime(2026, 4, 4, 16, tzinfo=UTC), (time(2, 30), time(3, 30)), 0.5),
        (datetime(2026, 4, 4, 16, tzinfo=UTC),
         datetime(2026, 4, 4, 16, 5, tzinfo=UTC), (time(1, 30), time(2, 30)), 0.5),
    ],
)
def test_dst_jump_itself_splits_skipped_or_repeated_window_boundaries(
    start, finish, window, expected
):
    meter = PaidExportAccumulator()
    inputs = {"standard_window": window, "bonus_rate": 0}
    _observe(meter, 6, start.astimezone(SYDNEY), **inputs)
    _observe(meter, 6, finish.astimezone(SYDNEY), **inputs)
    assert meter.imported_kwh == pytest.approx(expected)


def test_missing_store_requires_one_explicit_conservative_seed():
    meter = PaidExportAccumulator()
    meter.restore(None, _at(18))
    assert meter.needs_legacy_seed
    assert not meter.valid
    assert not _observe(meter, 6, _at(18))
    meter.seed_legacy(13.03, _at(18))
    assert meter.valid and meter.legacy_seeded and meter.checkpoint_required
    assert not meter.needs_legacy_seed
    meter.seed_legacy(0, _at(18, 1))
    assert meter.imported_kwh == 13.03
    _observe(meter, 6, _at(18))
    assert meter.imported_kwh == 13.03
    _observe(meter, 6, _at(18, 1))
    assert meter.imported_kwh == pytest.approx(13.13)


def test_same_day_restore_retains_total_but_never_old_price_permission():
    meter = PaidExportAccumulator()
    start = _at(12)
    _observe(meter, 6, start, price_start=start, price_end=start + timedelta(minutes=5))
    restored = PaidExportAccumulator()
    payload = meter.to_payload()
    assert "price_start" not in payload and "price_end" not in payload
    restored.restore(payload, start + timedelta(minutes=1))
    assert restored.valid
    _observe(restored, 6, start + timedelta(minutes=2))
    assert restored.imported_kwh == 0


def test_paid_tariff_and_migration_marker_survive_ordinary_restore():
    meter = PaidExportAccumulator()
    meter.restore(None, _at(18))
    meter.seed_legacy(3, _at(18))
    _observe(meter, 6, _at(18))
    _observe(meter, 6, _at(18, 1))
    restored = PaidExportAccumulator()
    restored.restore(meter.to_payload(), _at(18, 2))
    assert restored.valid and restored.legacy_seeded
    _observe(restored, 6, _at(18, 2))
    assert restored.imported_kwh == pytest.approx(3.2)


@pytest.mark.parametrize(
    "change",
    [
        {"version": 2}, {"version": True}, {"imported_kwh": -1},
        {"imported_kwh": float("nan")}, {"valid": "yes"},
        {"last_at": "not-a-time"}, {"last_import_kw": None},
        {"last_at": _at(19).isoformat()},
        {"legacy_seeded_date": "2026-10-19"}, {"blocked": True},
    ],
)
def test_malformed_same_day_store_locks_cap_until_midnight_not_a_fresh_allowance(change):
    original = PaidExportAccumulator()
    _observe(original, 6, _at(18))
    payload = original.to_payload() | change
    meter = PaidExportAccumulator()
    meter.restore(payload, _at(18, 1))
    assert not meter.valid and not meter.needs_legacy_seed
    meter.seed_legacy(0, _at(18, 1))
    assert not meter.valid
    assert not _observe(meter, 6, _at(18, 2))
    restored_again = PaidExportAccumulator()
    restored_again.restore(meter.to_payload(), _at(18, 3))
    assert not restored_again.valid
    assert not _observe(restored_again, 6, _at(18, 4))
    _observe(restored_again, 6, _at(0, day=21), offpeak_rate=0.01)
    assert restored_again.valid and restored_again.imported_kwh == 0


@pytest.mark.parametrize("bad", [None, -1, float("nan"), True])
def test_invalid_legacy_seed_locks_day_and_is_not_repeatable(bad):
    meter = PaidExportAccumulator()
    meter.restore(None, _at(18))
    meter.seed_legacy(bad, _at(18))
    assert not meter.valid and not meter.needs_legacy_seed
    meter.seed_legacy(0, _at(18, 1))
    assert not meter.valid


def test_old_day_store_starts_clean_and_transient_invalid_round_trip_recovers():
    old = PaidExportAccumulator()
    _observe(old, 6, _at(18))
    _observe(old, None, _at(18, 1))
    transient = PaidExportAccumulator()
    transient.restore(old.to_payload(), _at(18, 2))
    assert not transient.valid
    _observe(transient, 6, _at(18, 2))
    assert transient.valid
    fresh = PaidExportAccumulator()
    fresh.restore(old.to_payload(), _at(0, day=21))
    assert fresh.valid and fresh.imported_kwh == 0 and not fresh.needs_legacy_seed
