from datetime import UTC, datetime

import pytest

from custom_components.home_energy_orchestrator.planner.ev_learning import (
    DrivingSnapshotState,
    estimate_free_window_soc_gain_percent,
    estimate_usable_ev_capacity_kwh,
    plan_learned_general_charge_limit,
    snapshot_daily_driving_energy,
)


def test_daily_driving_snapshot_accepts_only_consecutive_boundary_days():
    first = snapshot_daily_driving_energy(
        DrivingSnapshotState(),
        now=datetime(2026, 9, 7, 11, 1, tzinfo=UTC),
        lifetime_energy_kwh=1000,
    )
    assert first.sample_kwh is None
    second = snapshot_daily_driving_energy(
        first.state,
        now=datetime(2026, 9, 8, 11, 1, tzinfo=UTC),
        lifetime_energy_kwh=1012.3456,
    )
    assert second.sample_kwh == 12.346
    missed = snapshot_daily_driving_energy(
        second.state,
        now=datetime(2026, 9, 10, 11, 1, tzinfo=UTC),
        lifetime_energy_kwh=1020,
    )
    assert missed.sample_kwh is None


def test_capacity_and_single_phase_free_window_gain_match_source_formula():
    capacity = estimate_usable_ev_capacity_kwh(
        stored_energy_kwh=30, soc_percent=40
    )
    assert capacity == 75
    assert estimate_free_window_soc_gain_percent(
        maximum_current_a=10,
        voltage_v=230,
        phase_count=1,
        window_hours=3,
        charge_efficiency_percent=90,
        usable_capacity_kwh=capacity,
    ) == 8.28


def test_learning_fallback_floors_free_limit_minus_full_window_gain():
    decision = plan_learned_general_charge_limit(
        [5, 8],
        minimum_samples=14,
        arrival_reserve_percent=20,
        free_window_limit_percent=90,
        free_window_soc_gain_percent=18.4,
        usable_capacity_kwh=75,
        actuator_minimum_percent=50,
        actuator_maximum_percent=100,
        actuator_step_percent=1,
    )
    assert decision.limit_percent == 71
    assert decision.mode == "learning_full_window_fallback"


def test_learned_p85_branch_ceil_rounds_and_clamps_to_free_limit():
    samples = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
    decision = plan_learned_general_charge_limit(
        samples,
        minimum_samples=14,
        arrival_reserve_percent=20,
        free_window_limit_percent=90,
        free_window_soc_gain_percent=8,
        usable_capacity_kwh=75,
        actuator_minimum_percent=0,
        actuator_maximum_percent=100,
        actuator_step_percent=1,
    )
    assert decision.p85_daily_energy_kwh == pytest.approx(19.05)
    assert decision.limit_percent == 38
    assert decision.mode == "learned_p85"


def test_three_phase_gain_is_only_a_configured_conversion_extension():
    single = estimate_free_window_soc_gain_percent(
        maximum_current_a=10,
        voltage_v=230,
        phase_count=1,
        window_hours=3,
        charge_efficiency_percent=90,
        usable_capacity_kwh=75,
    )
    three = estimate_free_window_soc_gain_percent(
        maximum_current_a=10,
        voltage_v=230,
        phase_count=3,
        window_hours=3,
        charge_efficiency_percent=90,
        usable_capacity_kwh=75,
    )
    assert three == pytest.approx(single * 3)
