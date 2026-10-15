"""A dedicated capacity feeds existing calculations, not a second controller."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.ev import (
    estimate_vehicle_energy_to_target_kwh,
    evaluate_allowance_projection,
)
from custom_components.home_energy_orchestrator.planner.ev_daily_backfill import (
    DailyBackfillPlanningEvidence,
    evaluate_daily_backfill_plan,
)
from custom_components.home_energy_orchestrator.planner.ev_learning import (
    estimate_usable_ev_capacity_kwh,
    evaluate_learned_charge_limit,
)
from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    evaluate_pre_free_plan,
)
from custom_components.home_energy_orchestrator.planner.trip_charge import (
    calculate_trip_charge_plan,
)

from .test_ev import ALLOWANCE_PROJECTION
from .test_ev_learning import LEARNED_EVIDENCE
from .test_ev_outside_window import PRE_FREE_PLANNING


def test_synthetic_low_soc_ratio_replay_and_corrected_latest_start():
    """An energy/SoC zero-point mismatch cannot inflate selected capacity."""
    inferred = estimate_usable_ev_capacity_kwh(stored_energy_kwh=24, soc_percent=20)
    assert inferred == 120
    departure = datetime(2030, 4, 10, 12, tzinfo=UTC)
    inputs = dict(
        departure=departure,
        target_soc=50,
        soc=20,
        maximum_power_kw=3.6,
        efficiency_percent=90,
        extra_minutes=0,
        maximum_hours=24,
    )
    legacy = calculate_trip_charge_plan(**inputs, capacity_kwh=inferred)
    corrected = calculate_trip_charge_plan(**inputs, capacity_kwh=80)
    assert legacy.planned_hours == pytest.approx(36 / 3.24, abs=1e-6)
    assert corrected.planned_hours == pytest.approx(24 / 3.24, abs=1e-6)
    assert corrected.planned_start > legacy.planned_start + timedelta(hours=3)


@pytest.mark.parametrize("stored,soc", [(24, 20), (40, 40), (None, 0)])
def test_selected_capacity_not_remaining_energy_controls_learning(stored, soc):
    learned = evaluate_learned_charge_limit(
        replace(
            LEARNED_EVIDENCE,
            stored_energy_kwh=stored,
            vehicle_soc_percent=soc,
            planning_capacity_kwh=80,
        )
    )
    assert learned.usable_capacity_kwh == 80


@pytest.mark.parametrize("stored", [None, 24, 500])
def test_energy_room_uses_selected_capacity_without_requiring_stored_energy(stored):
    assert (
        estimate_vehicle_energy_to_target_kwh(
            stored_energy_kwh=stored,
            current_soc_percent=20,
            target_soc_percent=50,
            charge_efficiency_percent=90,
            planning_capacity_kwh=80,
        )
        == 26.667
    )
    assert (
        estimate_vehicle_energy_to_target_kwh(
            stored_energy_kwh=stored,
            current_soc_percent=0,
            target_soc_percent=50,
            charge_efficiency_percent=100,
            planning_capacity_kwh=80,
        )
        == 40
    )


@pytest.mark.parametrize("capacity", [0, -1, True, float("nan"), float("inf"), 1001])
def test_invalid_selected_capacity_cannot_revert_to_a_valid_legacy_ratio(capacity):
    with pytest.raises(ValueError):
        estimate_vehicle_energy_to_target_kwh(
            stored_energy_kwh=24,
            current_soc_percent=20,
            target_soc_percent=50,
            charge_efficiency_percent=90,
            planning_capacity_kwh=capacity,
        )
    with pytest.raises(ValueError):
        evaluate_learned_charge_limit(replace(LEARNED_EVIDENCE, planning_capacity_kwh=capacity))


@pytest.mark.parametrize("soc", [-1, 101, True, float("nan"), float("inf")])
def test_explicit_capacity_does_not_make_invalid_vehicle_soc_usable(soc):
    with pytest.raises(ValueError):
        evaluate_learned_charge_limit(replace(
            LEARNED_EVIDENCE, vehicle_soc_percent=soc, planning_capacity_kwh=80,
        ))


def test_allowance_projection_accepts_explicit_capacity_without_stored_energy():
    result = evaluate_allowance_projection(
        replace(
            ALLOWANCE_PROJECTION,
            stored_energy_kwh=None,
            planning_capacity_kwh=80,
        )
    )
    assert result.decision is not None


def test_pre_free_retains_export_budget_but_limits_vehicle_room_using_capacity():
    result = evaluate_pre_free_plan(
        replace(
            PRE_FREE_PLANNING,
            stored_vehicle_energy_kwh=None,
            planning_capacity_kwh=80,
            vehicle_soc_percent=50,
            vehicle_target_soc_percent=55,
            charge_efficiency_percent=100,
            planned_export_energy_kwh=10,
        )
    )
    assert result.plan is not None
    assert result.planned_energy_kwh == 4


def test_daily_ready_by_retains_house_budget_and_uses_same_vehicle_room():
    evidence = DailyBackfillPlanningEvidence(
        now=datetime(2030, 4, 10, 2, tzinfo=UTC),
        ready_at=datetime(2030, 4, 10, 8, tzinfo=UTC),
        planning_window_start=datetime(2030, 4, 10, 0, tzinfo=UTC),
        next_free_start=datetime(2030, 4, 10, 12, tzinfo=UTC),
        available_after_reserve_kwh=20,
        discharge_efficiency_percent=100,
        protected_house_kwh=5,
        sellable_energy_kwh=15,
        protected_ev_allocation_kwh=10,
        delivered_this_cycle_kwh=0,
        stored_vehicle_energy_kwh=None,
        vehicle_soc_percent=50,
        vehicle_target_soc_percent=55,
        vehicle_charge_efficiency_percent=100,
        inverter_output_limit_kw=10,
        outside_inverter_percent=50,
        voltage_v=230,
        phase_count=1,
        current_step_a=1,
        charger_minimum_a=1,
        charger_maximum_a=15,
        planning_buffer_minutes=0,
        planning_capacity_kwh=80,
    )
    plan = evaluate_daily_backfill_plan(evidence)
    assert plan.protected_house_kwh == 5
    assert plan.planned_energy_kwh == 4
