"""Pure estimates must not add an actuator, forecast or a second trip policy."""

import json
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.home_energy_orchestrator.planner.trip_impact import estimate_pre_free_impact

SYDNEY = ZoneInfo("Australia/Sydney")


def _at(hour, minute=0, *, day=17):
    return datetime(2026, 10, day, hour, minute, tzinfo=SYDNEY)


def _estimate(**changes):
    inputs = {
        "now": _at(0), "planned_start": _at(3),
        "next_free_start": _at(11), "next_free_end": _at(14),
        "soc": 20, "target_soc": 80, "capacity_kwh": 80,
        "maximum_power_kw": 4, "ev_efficiency_percent": 80,
        "battery_after_floor_kwh": 30, "protected_house_kwh": 10,
        "discharge_efficiency_percent": 90,
        "peak_start": time(16), "peak_end": time(23),
        "peak_rate": 0.6, "shoulder_rate": 0.3,
    }
    inputs.update(changes)
    return estimate_pre_free_impact(**inputs)


def test_pre_free_energy_preserves_house_once_and_converts_dc_to_ac():
    result = _estimate()
    assert result["status"] == "estimated"
    assert result["pack_energy_kwh"] == 48
    assert result["wall_energy_kwh"] == 60
    assert result["before_free_kwh"] == 32
    assert result["during_free_kwh"] == 12
    assert result["after_free_kwh"] == 16
    assert result["battery_available_for_ev_kwh"] == 17
    assert result["battery_contribution_kwh"] == 17
    assert result["extra_paid_energy_kwh"] == 15
    assert result["cost_min"] == result["cost_max"] == 4.5
    assert result["scope"] == "before_next_free_window_only"
    json.dumps(result, allow_nan=False)


def test_planning_margin_changes_start_not_energy_requirement():
    normal = _estimate()
    earlier = _estimate(planned_start=_at(2))
    assert earlier["pack_energy_kwh"] == normal["pack_energy_kwh"]
    assert earlier["wall_energy_kwh"] == normal["wall_energy_kwh"]
    assert earlier["before_free_kwh"] == 36
    assert sum(
        earlier[key] for key in ("before_free_kwh", "during_free_kwh", "after_free_kwh")
    ) == 60


def test_running_charge_uses_remaining_soc_and_now_not_old_start():
    result = _estimate(now=_at(5), planned_start=_at(3), soc=60)
    assert result["wall_energy_kwh"] == 20
    assert result["before_free_kwh"] == 20
    assert result["during_free_kwh"] == result["after_free_kwh"] == 0
    assert datetime.fromisoformat(result["charging_start"]) == _at(5)
    assert datetime.fromisoformat(result["estimated_charging_end"]) == _at(10)


@pytest.mark.parametrize(
    ("battery", "house", "available", "paid"),
    [(100, 10, 80, 0), (0, 10, 0, 32), (10, 20, 0, 32), (20, 0, 18, 14)],
)
def test_battery_and_house_budget_bound_the_contribution(battery, house, available, paid):
    result = _estimate(battery_after_floor_kwh=battery, protected_house_kwh=house)
    assert result["battery_available_for_ev_kwh"] == available
    assert result["extra_paid_energy_kwh"] == paid
    assert result["battery_contribution_kwh"] <= result["before_free_kwh"]


def test_house_imports_can_be_deferred_into_peak_after_ev_charging_ends():
    result = _estimate(
        target_soc=30, battery_after_floor_kwh=0,
        peak_start=time(10), peak_end=time(11),
    )
    assert datetime.fromisoformat(result["estimated_charging_end"]) == _at(5, 30)
    assert result["extra_paid_energy_kwh"] == 10
    assert result["cost_min"] == 3
    assert result["cost_max"] == 6


@pytest.mark.parametrize(
    ("peak_start", "peak_end", "minimum", "maximum"),
    [
        (time(3), time(11), 0.6, 0.6),
        (time(11), time(16), 0.3, 0.3),
        (time(0), time(3), 0.3, 0.3),
        (time(3), time(3), 0.6, 0.6),
        (time(22), time(6), 0.3, 0.6),
        (time(4), time(5), 0.3, 0.6),
    ],
)
def test_half_open_tariff_boundaries_and_crossing_midnight(
    peak_start, peak_end, minimum, maximum,
):
    result = _estimate(
        battery_after_floor_kwh=0, peak_start=peak_start, peak_end=peak_end,
    )
    assert result["cost_min"] == pytest.approx(32 * minimum)
    assert result["cost_max"] == pytest.approx(32 * maximum)


def test_zero_rates_remain_valid_not_missing():
    result = _estimate(battery_after_floor_kwh=0, peak_rate=0, shoulder_rate=0)
    assert result["extra_paid_energy_kwh"] == 32
    assert result["cost_min"] == result["cost_max"] == 0


@pytest.mark.parametrize("soc", [80, 90, 100])
def test_already_at_or_above_target_needs_no_energy_or_cost(soc):
    result = _estimate(soc=soc)
    assert result["status"] == "already_at_target"
    for key in ("pack_energy_kwh", "wall_energy_kwh", "before_free_kwh", "during_free_kwh",
                "after_free_kwh", "battery_contribution_kwh", "extra_paid_energy_kwh",
                "cost_min", "cost_max"):
        assert result[key] == 0


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"now": _at(11)}, "free_window_started"),
        ({"now": _at(12)}, "free_window_started"),
        ({"planned_start": _at(11)}, "charging_starts_at_or_after_free"),
        ({"planned_start": _at(15)}, "charging_starts_at_or_after_free"),
    ],
)
def test_out_of_scope_does_not_report_fake_zero_total_cost(changes, reason):
    result = _estimate(**changes)
    assert result["status"] == "out_of_scope"
    assert result["reason"] == reason
    assert result["cost_min"] is result["cost_max"] is result["extra_paid_energy_kwh"] is None
    assert result["wall_energy_kwh"] == 60
    assert sum(
        result[key] for key in ("before_free_kwh", "during_free_kwh", "after_free_kwh")
    ) == 60


@pytest.mark.parametrize(
    ("key", "invalid"),
    [(key, invalid) for key in (
        "soc", "target_soc", "capacity_kwh", "maximum_power_kw", "ev_efficiency_percent",
        "battery_after_floor_kwh", "protected_house_kwh", "discharge_efficiency_percent",
        "peak_rate", "shoulder_rate",
    ) for invalid in (None, True, False, "10", float("nan"), float("inf"), -1)]
    + [("soc", 101), ("target_soc", 0), ("target_soc", 101),
       ("capacity_kwh", 0), ("capacity_kwh", 1001),
       ("maximum_power_kw", 0), ("maximum_power_kw", 101),
       ("ev_efficiency_percent", 0), ("ev_efficiency_percent", 101),
       ("discharge_efficiency_percent", 0), ("discharge_efficiency_percent", 101),
       ("peak_start", "16:00"), ("peak_end", None),
       ("peak_start", time(16, tzinfo=UTC))],
)
def test_invalid_numeric_or_tariff_inputs_are_unavailable_not_free(key, invalid):
    result = _estimate(**{key: invalid})
    assert result["status"] == "unavailable"
    assert result["cost_min"] is result["cost_max"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("key", ["now", "planned_start", "next_free_start", "next_free_end"])
@pytest.mark.parametrize("invalid", [None, "tomorrow", datetime(2026, 10, 17)])
def test_datetimes_must_be_aware(key, invalid):
    result = _estimate(**{key: invalid})
    assert result["status"] == "unavailable"
    assert result["cost_min"] is result["cost_max"] is None


def test_free_end_must_follow_free_start_in_elapsed_time():
    assert _estimate(next_free_end=_at(11))["status"] == "unavailable"
    assert _estimate(next_free_end=_at(10))["status"] == "unavailable"


def test_subnormal_efficiency_does_not_crash_an_optional_estimate():
    result = _estimate(ev_efficiency_percent=5e-324)
    assert result["status"] == "unavailable"
    assert result["cost_min"] is None


@pytest.mark.parametrize(
    ("day", "before_hours"),
    [(datetime(2026, 10, 4, tzinfo=SYDNEY), 10),
     (datetime(2026, 4, 5, tzinfo=SYDNEY), 12)],
)
def test_energy_uses_elapsed_utc_hours_across_both_dst_changes(day, before_hours):
    result = _estimate(
        now=day, planned_start=day,
        next_free_start=day.replace(hour=11), next_free_end=day.replace(hour=14),
        soc=0, target_soc=100, capacity_kwh=100, maximum_power_kw=4,
        ev_efficiency_percent=100, battery_after_floor_kwh=0,
    )
    assert result["before_free_kwh"] == before_hours * 4
    assert result["wall_energy_kwh"] == 100
    assert sum(
        result[key] for key in ("before_free_kwh", "during_free_kwh", "after_free_kwh")
    ) == 100


def test_spring_skipped_tariff_band_does_not_invent_peak_imports():
    day = datetime(2026, 10, 4, tzinfo=SYDNEY)
    result = _estimate(
        now=day, planned_start=day, next_free_start=day.replace(hour=4),
        next_free_end=day.replace(hour=7), peak_start=time(2, 10), peak_end=time(2, 50),
        battery_after_floor_kwh=0,
    )
    assert result["cost_min"] == result["cost_max"] == pytest.approx(12 * 0.3)


def test_spring_peak_start_in_gap_still_detects_the_real_tail():
    day = datetime(2026, 10, 4, tzinfo=SYDNEY)
    result = _estimate(
        now=day, planned_start=day, next_free_start=day.replace(hour=4),
        next_free_end=day.replace(hour=7), peak_start=time(2, 30), peak_end=time(3, 5),
        battery_after_floor_kwh=0,
    )
    assert result["cost_min"] == pytest.approx(12 * 0.3)
    assert result["cost_max"] == pytest.approx(12 * 0.6)


def test_autumn_second_fold_retains_local_peak_band():
    day = datetime(2026, 4, 5, tzinfo=SYDNEY)
    start = day.replace(hour=2, minute=20, fold=1)
    result = _estimate(
        now=start, planned_start=start,
        next_free_start=day.replace(hour=2, minute=40, fold=1),
        next_free_end=day.replace(hour=5), peak_start=time(2, 10), peak_end=time(2, 50),
        battery_after_floor_kwh=0,
    )
    assert result["before_free_kwh"] == pytest.approx(4 / 3)
    assert result["cost_min"] == result["cost_max"] == pytest.approx(0.8)


def test_mixed_timezone_inputs_use_site_now_timezone_for_tariffs():
    result = _estimate(
        planned_start=_at(3).astimezone(UTC), next_free_start=_at(11).astimezone(UTC),
        next_free_end=_at(14).astimezone(UTC), peak_start=time(3), peak_end=time(11),
        battery_after_floor_kwh=0,
    )
    assert result["cost_min"] == result["cost_max"] == pytest.approx(32 * 0.6)


def test_extreme_finite_inputs_never_produce_non_json_finite_values():
    result = _estimate(ev_efficiency_percent=1e-300)
    assert result["status"] == "unavailable"
    json.dumps(result, allow_nan=False)
    result = _estimate(battery_after_floor_kwh=1e308)
    assert result["status"] == "estimated"
    json.dumps(result, allow_nan=False)
    result = _estimate(battery_after_floor_kwh=10**1000)
    assert result["status"] == "unavailable"
    json.dumps(result, allow_nan=False)
    result = _estimate(peak_rate=1e308, shoulder_rate=1e308, battery_after_floor_kwh=0)
    assert result["status"] == "unavailable"
    assert result["cost_min"] is result["cost_max"] is None
    json.dumps(result, allow_nan=False)


def test_multi_day_wrong_next_window_does_not_expand_an_unbounded_forecast():
    result = _estimate(next_free_start=_at(11) + timedelta(days=20),
                       next_free_end=_at(14) + timedelta(days=20), battery_after_floor_kwh=0)
    assert result["cost_min"] == pytest.approx(60 * 0.3)
    assert result["cost_max"] == pytest.approx(60 * 0.6)
