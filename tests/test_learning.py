"""Tests for the pure protected-demand learner."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.learning import (
    DemandCycleSample,
    DemandCycleSampler,
    DemandHistory,
    remaining_protected_cycle_budget_kwh,
    retain_demand_samples,
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


def test_cycle_sampler_uses_trapezoid_power_between_readings() -> None:
    sampler = DemandCycleSampler(
        time(12), time(15), max_gap=timedelta(days=2)
    )
    sampler.observe(datetime(2026, 9, 1, 12, tzinfo=UTC), 1)
    sampler.observe(datetime(2026, 9, 1, 15, tzinfo=UTC), 1)
    sampler.observe(datetime(2026, 9, 1, 18, tzinfo=UTC), 3)
    sample = sampler.observe(datetime(2026, 9, 2, 12, tzinfo=UTC), 3)
    assert sample is not None
    assert sample.energy_kwh == 60


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
