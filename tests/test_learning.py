"""Tests for the pure protected-demand learner."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.learning import (
    DailyDemandCycleSampler,
    DemandCycleSample,
    DemandCycleSampler,
    DemandHistory,
    OccupancyPerson,
    classify_energy_occupancy,
    protected_base_house_power_kw,
    remaining_protected_cycle_budget_kwh,
    retain_demand_samples,
    select_house_cycle_budget,
    select_protected_cycle_budget,
)


def test_learning_uses_explicit_fallback_during_warmup() -> None:
    result = select_protected_cycle_budget([5, 6, 7], 17.5)
    assert result.cycle_budget_kwh == 17.5
    assert result.sample_count == 3
    assert result.model == "fallback"


def test_learning_uses_p80_after_seven_valid_cycles() -> None:
    result = select_protected_cycle_budget([1, 2, 3, 4, 5, 6, 7], 17.5)
    assert result.cycle_budget_kwh == 5.8
    assert result.sample_count == 7
    assert result.model == "p80"


def test_learning_ignores_bad_values_and_limits_history() -> None:
    samples = [float("nan"), -1, *range(1, 35)]
    result = select_protected_cycle_budget(samples, 17.5)
    assert result.sample_count == 28
    assert result.cycle_budget_kwh == 28.6


def test_learning_rejects_invalid_fallback() -> None:
    with pytest.raises(ValueError):
        select_protected_cycle_budget([1] * 7, -1)


def test_sample_retention_prunes_old_and_invalid_cycles() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    samples = [
        DemandCycleSample(now - timedelta(days=36), 99),
        DemandCycleSample(now - timedelta(days=1), 3),
        DemandCycleSample(now - timedelta(hours=1), 4),
        DemandCycleSample(now - timedelta(minutes=1), 5),
        DemandCycleSample(now.replace(tzinfo=None), 6),
    ]
    retained = retain_demand_samples(samples, now)
    assert [sample.energy_kwh for sample in retained] == [3, 4, 5]


def test_history_round_trips_and_selects_the_legacy_budget() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    payload = {
        "samples": [
            {"observed_at": (now - timedelta(days=i)).isoformat(), "energy_kwh": i}
            for i in range(1, 8)
        ]
    }
    history = DemandHistory.from_payload(
        payload,
        now,
    )
    assert history.select(17.5).cycle_budget_kwh == 5.8
    restored = DemandHistory.from_payload(history.to_payload(), now)
    assert [sample.energy_kwh for sample in restored.samples] == [7, 6, 5, 4, 3, 2, 1]


def test_history_add_keeps_existing_samples_when_a_late_row_arrives() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    history = DemandHistory(
        [DemandCycleSample(now - timedelta(days=1), 4)]
    )
    history.add(now - timedelta(days=2), 3)
    assert [sample.energy_kwh for sample in history.samples] == [3, 4]


def test_pilot_learning_source_subtracts_ev_and_heater_once_then_clamps() -> None:
    assert protected_base_house_power_kw(
        12.0,
        ev_power_kw=6.9,
        heater_power_kw=2.1,
        house_includes_ev=True,
        heater_is_mapped=True,
    ) == pytest.approx(3.0)
    assert protected_base_house_power_kw(
        -4.0,
        house_includes_ev=False,
        heater_is_mapped=False,
    ) == 0.0


def test_learning_source_fails_closed_when_required_subtraction_is_unavailable() -> None:
    assert protected_base_house_power_kw(5.0, house_includes_ev=True) is None
    assert protected_base_house_power_kw(5.0, heater_is_mapped=True) is None


def test_pilot_zero_clamp_prevents_negative_load_from_erasing_a_cycle() -> None:
    sampler = DemandCycleSampler(time(12), time(15), max_gap=timedelta(days=2))
    sampler.observe(datetime(2026, 9, 1, 12, tzinfo=UTC), 1.0)
    sampler.observe(datetime(2026, 9, 1, 15, tzinfo=UTC), 1.0)
    clamped = protected_base_house_power_kw(-4.0)
    assert clamped == 0.0
    sampler.observe(datetime(2026, 9, 1, 18, tzinfo=UTC), clamped)

    sample = sampler.observe(datetime(2026, 9, 2, 12, tzinfo=UTC), 1.0)

    assert sample is not None
    assert sample.energy_kwh == pytest.approx(3.0)


def test_cycle_sampler_excludes_the_free_window() -> None:
    sampler = DemandCycleSampler(
        time(12), time(15), max_gap=timedelta(days=2)
    )
    assert sampler.observe(datetime(2026, 9, 1, 12, tzinfo=UTC), 1) is None
    assert sampler.observe(datetime(2026, 9, 1, 15, tzinfo=UTC), 1) is None
    sample = sampler.observe(datetime(2026, 9, 2, 12, tzinfo=UTC), 1)
    assert sample is not None
    assert sample.observed_at == datetime(2026, 9, 2, 12, tzinfo=UTC)
    assert sample.energy_kwh == 21


def test_cycle_sampler_uses_the_pilot_left_integration_method() -> None:
    sampler = DemandCycleSampler(
        time(12), time(15), max_gap=timedelta(days=2)
    )
    sampler.observe(datetime(2026, 9, 1, 12, tzinfo=UTC), 1)
    sampler.observe(datetime(2026, 9, 1, 15, tzinfo=UTC), 1)
    sampler.observe(datetime(2026, 9, 1, 18, tzinfo=UTC), 3)
    sample = sampler.observe(datetime(2026, 9, 2, 12, tzinfo=UTC), 3)
    assert sample is not None
    assert sample.energy_kwh == 57


def test_cycle_sampler_restores_an_in_progress_cycle_after_short_restart() -> None:
    start = datetime(2026, 9, 1, 12, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.observe(start, 1.0)
    sampler.observe(start + timedelta(minutes=5), 1.0)
    payload = sampler.to_payload()

    restored = DemandCycleSampler(time(12), time(15))
    restored.restore(payload, start + timedelta(minutes=9))

    assert restored.to_payload() == payload


def test_cycle_sampler_rejects_stale_in_progress_state() -> None:
    start = datetime(2026, 9, 1, 12, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.observe(start, 1.0)

    restored = DemandCycleSampler(time(12), time(15))
    restored.restore(sampler.to_payload(), start + timedelta(minutes=11))

    assert restored.to_payload() is None


def test_daily_sampler_records_a_full_boundary_to_boundary_heater_cycle() -> None:
    sampler = DailyDemandCycleSampler(time(12, 1), max_gap=timedelta(days=2))
    assert sampler.observe(datetime(2026, 9, 1, 12, 1, tzinfo=UTC), 2) is None
    sample = sampler.observe(datetime(2026, 9, 2, 12, 1, tzinfo=UTC), 2)
    assert sample is not None
    assert sample.observed_at == datetime(2026, 9, 2, 12, 1, tzinfo=UTC)
    assert sample.energy_kwh == 48


def test_daily_sampler_splits_a_reading_across_the_boundary() -> None:
    sampler = DailyDemandCycleSampler(time(12), max_gap=timedelta(days=2))
    sampler.observe(datetime(2026, 9, 1, 12, tzinfo=UTC), 1)
    sample = sampler.observe(datetime(2026, 9, 2, 13, tzinfo=UTC), 3)
    assert sample is not None
    assert sample.energy_kwh == pytest.approx(24.0)
    assert sampler.to_payload()["cycle_energy_kwh"] == pytest.approx(1.0)


def test_auto_occupancy_assumes_home_without_person_entities() -> None:
    now = datetime(2026, 9, 2, 18, tzinfo=UTC)
    result = classify_energy_occupancy("auto", [], now, 6)
    assert result.state == "home"
    assert result.reason == "no_person_entities_assume_home"


def test_auto_occupancy_requires_everyone_away_for_confirmation_period() -> None:
    now = datetime(2026, 9, 2, 18, tzinfo=UTC)
    pending = classify_energy_occupancy(
        "auto", [OccupancyPerson("not_home", now - timedelta(hours=5))], now, 6
    )
    confirmed = classify_energy_occupancy(
        "auto", [OccupancyPerson("not_home", now - timedelta(hours=6))], now, 6
    )
    assert (pending.state, pending.reason) == ("home", "away_confirmation_pending")
    assert (confirmed.state, confirmed.reason) == ("away", "all_people_away_confirmed")


def test_auto_occupancy_treats_unknown_presence_as_home() -> None:
    now = datetime(2026, 9, 2, 18, tzinfo=UTC)
    result = classify_energy_occupancy(
        "auto", [OccupancyPerson("unavailable", now - timedelta(hours=12))], now, 6
    )
    assert result.state == "home"
    assert result.reason == "presence_uncertain_assume_home"


def test_auto_occupancy_treats_invalid_person_timestamp_as_home() -> None:
    now = datetime(2026, 9, 2, 18, tzinfo=UTC)
    result = classify_energy_occupancy(
        "auto", [OccupancyPerson("not_home", now.replace(tzinfo=None))], now, 6
    )
    assert result.state == "home"
    assert result.reason == "presence_uncertain_assume_home"


def test_manual_away_bypasses_confirmation_like_the_pilot() -> None:
    now = datetime(2026, 9, 2, 18, tzinfo=UTC)
    result = classify_energy_occupancy(
        "away", [OccupancyPerson("home", now)], now, 6
    )
    assert result.state == "away"
    assert result.reason == "manual_away"


def test_occupied_budget_requires_both_base_and_heater_p80_when_mapped() -> None:
    warming = select_house_cycle_budget(
        [1, 2, 3, 4, 5, 6, 7],
        [1, 2, 3, 4, 5, 6],
        17.5,
        6.5,
        "home",
    )
    learned = select_house_cycle_budget(
        [1, 2, 3, 4, 5, 6, 7],
        [0, 1, 2, 3, 4, 5, 6],
        17.5,
        6.5,
        "home",
    )
    assert (warming.cycle_budget_kwh, warming.model) == (17.5, "occupied_fallback")
    assert (learned.cycle_budget_kwh, learned.model) == (10.6, "measured_occupied_p80")


def test_away_budget_never_uses_occupied_learning() -> None:
    result = select_house_cycle_budget(
        [20] * 7,
        [5] * 7,
        17.5,
        6.5,
        "away",
    )
    assert result.cycle_budget_kwh == 6.5
    assert result.model == "away_fallback"


def test_complete_house_source_can_learn_without_optional_heater_mapping() -> None:
    result = select_house_cycle_budget([1, 2, 3, 4, 5, 6, 7], None, 17.5, 6.5, "home")
    assert result.cycle_budget_kwh == 5.8
    assert result.model == "measured_occupied_p80"


def test_remaining_budget_scales_to_next_free_window() -> None:
    start = datetime(2026, 9, 1, 18, 1, tzinfo=UTC)
    remaining = remaining_protected_cycle_budget_kwh(
        17.5, start, time(12, 1), time(14, 59)
    )
    protected_hours = 24 - (2 + 58 / 60)
    expected = 17.5 * 18.0 / protected_hours
    assert remaining == pytest.approx(expected)


def test_remaining_budget_is_zero_inside_free_window() -> None:
    assert (
        remaining_protected_cycle_budget_kwh(
            17.5, datetime(2026, 9, 1, 13, tzinfo=UTC), time(12, 1), time(14, 59)
        )
        == 0
    )


def test_remaining_budget_treats_configured_window_end_as_free() -> None:
    assert (
        remaining_protected_cycle_budget_kwh(
            17.5, datetime(2026, 9, 1, 14, 59, tzinfo=UTC), time(12, 1), time(14, 59)
        )
        == 0
    )
