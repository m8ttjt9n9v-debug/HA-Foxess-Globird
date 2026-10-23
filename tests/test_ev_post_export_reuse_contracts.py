"""Characterize existing reuse points, not an implemented post-export policy.

These golden contracts support the design in ev-post-export-design.md. They
deliberately exercise unchanged production functions and grant no new control
authority. All times, capacities and electrical ratings are synthetic fixtures.
"""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.control_windows import (
    daily_ready_cycle_bounds,
    pre_free_window_position,
)
from custom_components.home_energy_orchestrator.planner.ev_before_export import (
    plan_ev_before_export_current,
)
from custom_components.home_energy_orchestrator.planner.ev_daily_backfill import (
    DailyBackfillCycleState,
    DailyBackfillEnergyState,
    DailyBackfillInputs,
    calculate_daily_backfill_plan,
    daily_backfill_protection_remainder_kwh,
    roll_daily_backfill_cycle,
)
from custom_components.home_energy_orchestrator.planner.export import calculate_export_plan


def _at(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2027, 1, day, hour, minute, second, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "eligible"),
    [
        (_at(22, 19, 59, 59), False),
        (_at(22, 20), True),
        (_at(22, 22), True),
        (_at(22, 23, 59, 59), True),
        (_at(23, 0), True),
        (_at(23, 5, 59, 59), True),
        (_at(23, 6), True),
        (_at(23, 10, 59, 59), True),
        (_at(23, 11), False),
        (_at(23, 12), False),
    ],
)
def test_existing_interval_already_covers_evening_midnight_and_morning(now, eligible):
    _, active, _ = pre_free_window_position(
        now, free_start=time(11), discharge_finish=time(20),
    )
    assert active is eligible


def test_midnight_is_not_a_new_ready_accounting_cycle():
    before = daily_ready_cycle_bounds(_at(22, 23, 59), ready=time(6), free_start=time(11))
    after = daily_ready_cycle_bounds(_at(23, 0), ready=time(6), free_start=time(11))
    assert before == after
    assert before[0] == _at(23, 6)
    assert before[1] == _at(23, 0)  # Current planning opens later than export finish.


def test_adding_another_deadline_resets_delivery_and_recreates_allocation():
    state = DailyBackfillCycleState(
        ready_at=_at(23, 6),
        energy=DailyBackfillEnergyState(delivered_kwh=2),
        active=True,
        session_target_kwh=4,
        session_start_delivered_kwh=1,
        frozen_start=_at(22, 22),
    )
    retained = roll_daily_backfill_cycle(state, _at(23, 6))
    changed = roll_daily_backfill_cycle(state, _at(23, 5))
    assert retained == state
    assert changed.energy.delivered_kwh == 0
    assert not changed.active
    assert changed.stop_pending
    assert daily_backfill_protection_remainder_kwh(
        configured_allocation_kwh=3, delivered_kwh=retained.energy.delivered_kwh,
        same_ready_cycle=True,
    ) == 1
    assert daily_backfill_protection_remainder_kwh(
        configured_allocation_kwh=3, delivered_kwh=changed.energy.delivered_kwh,
        same_ready_cycle=True,
    ) == 3


def _plan_inputs() -> DailyBackfillInputs:
    return DailyBackfillInputs(
        now=_at(22, 22), ready_at=_at(23, 6),
        planning_window_start=_at(23, 0), next_free_start=_at(23, 11),
        available_ac_after_reserve_kwh=14, protected_house_kwh=4,
        sellable_energy_kwh=10, protected_ev_allocation_kwh=0,
        delivered_this_cycle_kwh=0, vehicle_wall_room_kwh=20,
        inverter_output_limit_kw=10, outside_inverter_percent=50,
        voltage_v=230, phase_count=3, current_step_a=1,
        charger_minimum_a=1, charger_maximum_a=16,
        use_all_discretionary_energy=True,
    )


def test_widening_planning_window_alone_still_waits_for_latest_start():
    normal = calculate_daily_backfill_plan(_plan_inputs())
    widened = calculate_daily_backfill_plan(replace(
        _plan_inputs(), planning_window_start=_at(22, 20),
    ))
    assert normal.phase == "before_planning_window"
    assert widened.phase == "waiting_latest_start"
    assert normal.planned_start == widened.planned_start
    assert widened.planned_energy_kwh == 10
    assert widened.planned_start > _plan_inputs().now


@pytest.mark.parametrize(("allowance", "hours"), [(0, 3), (20, 0), (2, 3)])
def test_paid_export_clipping_does_not_remove_discretionary_energy(allowance, hours):
    plan = calculate_export_plan(
        available_ac_kwh=14, protected_house_kwh=4, protected_ev_kwh=2,
        allowance_remaining_kwh=allowance, discharge_power_kw=10, window_hours=hours,
    )
    assert plan.sellable_energy_kwh == 8
    assert plan.planned_export_energy_kwh == min(8, allowance, 10 * hours)


@pytest.mark.parametrize("phase_count", [1, 3])
@pytest.mark.parametrize("baseline", [0, 1])
@pytest.mark.parametrize(("budget", "room"), [(0, 20), (0.001, 20), (8, 0.01), (8, 20)])
def test_existing_immediate_conversion_is_funded_and_never_exceeds_total_cap(
    phase_count, baseline, budget, room,
):
    decision = plan_ev_before_export_current(
        sellable_kwh=budget, vehicle_room_kwh=room, baseline_a=baseline,
        current_ceiling_a=7, charger_minimum_a=1, voltage_v=230,
        phase_count=phase_count, current_step_a=1, vehicle_soc=45, target_soc=80,
    )
    assert baseline <= decision.current_a <= 7
    assert decision.current_a % 1 == 0
    additional_wall_kwh = (decision.current_a - baseline) * 230 * phase_count / 1000 * 3 / 60
    assert additional_wall_kwh <= min(budget, room) + 1e-12
    if budget == 0:
        assert decision.current_a == baseline


def test_current_live_energy_and_vehicle_room_are_independent_ceiling_bounds():
    original = replace(_plan_inputs(), now=_at(23, 1))
    reduced = calculate_daily_backfill_plan(replace(
        original, available_ac_after_reserve_kwh=6, vehicle_wall_room_kwh=1.5,
    ))
    assert reduced.planned_energy_kwh == 1.5
    exhausted = calculate_daily_backfill_plan(replace(
        original, available_ac_after_reserve_kwh=4,
    ))
    assert exhausted.planned_energy_kwh == 0
    assert exhausted.phase == "protected_energy_unavailable"


def test_ready_boundary_is_deliberately_a_new_cycle_not_an_extra_deadline():
    before = daily_ready_cycle_bounds(_at(23, 5, 59, 59), ready=time(6), free_start=time(11))
    after = daily_ready_cycle_bounds(_at(23, 6), ready=time(6), free_start=time(11))
    assert after[0] == before[0] + timedelta(days=1)
    # New post-export admission must use the existing pre-free successor here,
    # not count late delivery against the freshly opened tomorrow allocation.
    assert pre_free_window_position(
        _at(23, 6), free_start=time(11), discharge_finish=time(20),
    )[1]
