from datetime import UTC, datetime

import pytest

from custom_components.home_energy_orchestrator.planner.ev_daily_backfill import (
    DailyBackfillInputs,
    calculate_daily_backfill_plan,
)


def _inputs(**changes):
    values = {
        "now": datetime(2026, 9, 10, 6, 0, tzinfo=UTC),
        "ready_at": datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
        "planning_window_start": datetime(2026, 9, 10, 0, 0, tzinfo=UTC),
        "next_free_start": datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
        "available_ac_after_reserve_kwh": 14,
        "protected_house_kwh": 3,
        "protected_ev_allocation_kwh": 5,
        "delivered_this_cycle_kwh": 0,
        "vehicle_wall_room_kwh": 20,
        "inverter_output_limit_kw": 15,
        "outside_inverter_percent": 30,
        "voltage_v": 230,
        "phase_count": 3,
        "current_step_a": 1,
        "charger_minimum_a": 1,
        "charger_maximum_a": 16,
        "planning_buffer_minutes": 0,
    }
    values.update(changes)
    return DailyBackfillInputs(**values)


def test_three_phase_cap_is_floored_to_supported_whole_amp():
    plan = calculate_daily_backfill_plan(_inputs())
    assert plan.current_ceiling_a == 6
    assert plan.power_ceiling_kw == 4.14


def test_allocation_plus_time_proportional_discretionary_energy():
    plan = calculate_daily_backfill_plan(_inputs())
    # 14 available - 3 house - 5 allocation = 6 discretionary; 2/6 remains.
    assert plan.proportional_discretionary_kwh == 2
    assert plan.planned_energy_kwh == 7
    assert plan.duration_minutes == pytest.approx(101.4)
    assert plan.planned_start is not None
    assert plan.planned_start.timestamp() == pytest.approx(
        datetime(2026, 9, 10, 6, 18, 33, tzinfo=UTC).timestamp(), abs=0.1
    )
    assert plan.phase == "waiting_latest_start"


def test_insufficient_live_energy_reports_shortfall_without_assuming_cloud_history():
    plan = calculate_daily_backfill_plan(
        _inputs(available_ac_after_reserve_kwh=6, protected_house_kwh=3)
    )
    assert plan.planned_energy_kwh == 3
    assert plan.allocation_shortfall_kwh == 2
    assert plan.achievable_by_ready is False


def test_delivered_energy_reduces_only_this_ready_cycle_allocation():
    plan = calculate_daily_backfill_plan(_inputs(delivered_this_cycle_kwh=3))
    assert plan.remaining_allocation_kwh == 2
    assert plan.discretionary_energy_kwh == 9
    assert plan.proportional_discretionary_kwh == 3
    assert plan.planned_energy_kwh == 5


def test_long_plan_starts_at_midnight_and_marks_target_unachievable():
    plan = calculate_daily_backfill_plan(
        _inputs(
            now=datetime(2026, 9, 10, 0, 1, tzinfo=UTC),
            protected_ev_allocation_kwh=40,
            available_ac_after_reserve_kwh=50,
            protected_house_kwh=0,
            outside_inverter_percent=10,
        )
    )
    assert plan.planned_start == datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
    assert plan.achievable_by_ready is False
    assert plan.phase == "charge_now"


def test_zero_percent_is_an_explicit_fail_closed_configuration():
    plan = calculate_daily_backfill_plan(_inputs(outside_inverter_percent=0))
    assert plan.current_ceiling_a == 0
    assert plan.phase == "outside_power_ceiling_too_low"


def test_live_service_ceiling_below_physical_minimum_fails_closed():
    plan = calculate_daily_backfill_plan(
        _inputs(charger_minimum_a=1, charger_maximum_a=0)
    )
    assert plan.current_ceiling_a == 0
    assert plan.phase == "outside_power_ceiling_too_low"


def test_ready_must_be_before_next_free_window():
    with pytest.raises(ValueError):
        calculate_daily_backfill_plan(
            _inputs(ready_at=datetime(2026, 9, 10, 13, 0, tzinfo=UTC))
        )
