from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.home_energy_orchestrator.planner.ev_daily_backfill import (
    DailyBackfillCycleState,
    DailyBackfillEnergyState,
    DailyBackfillInputs,
    DailyBackfillPlanningEvidence,
    DailyBackfillStopState,
    advance_daily_backfill_session,
    calculate_daily_backfill_plan,
    daily_backfill_protection_remainder_kwh,
    end_daily_backfill_session,
    evaluate_daily_backfill_plan,
    integrate_daily_backfill_energy,
    reconcile_daily_backfill_stop,
    record_daily_backfill_stop_attempt,
    roll_daily_backfill_cycle,
)


@pytest.mark.parametrize(
    ("configured", "delivered", "same_cycle", "expected"),
    [
        (5, 1.23456, True, 3.765),
        (5, 1.23456, False, 5.0),
        (5, 6, True, 0.0),
        (0, 1, True, 0.0),
    ],
)
def test_daily_backfill_protection_remainder_is_cycle_scoped(
    configured,
    delivered,
    same_cycle,
    expected,
):
    assert (
        daily_backfill_protection_remainder_kwh(
            configured_allocation_kwh=configured,
            delivered_kwh=delivered,
            same_ready_cycle=same_cycle,
        )
        == expected
    )


def _inputs(**changes):
    values = {
        "now": datetime(2026, 9, 10, 6, 0, tzinfo=UTC),
        "ready_at": datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
        "planning_window_start": datetime(2026, 9, 10, 0, 0, tzinfo=UTC),
        "next_free_start": datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
        "available_ac_after_reserve_kwh": 14,
        "protected_house_kwh": 3,
        "sellable_energy_kwh": 11,
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


def test_daily_backfill_evaluation_composes_efficiency_and_live_vehicle_room():
    plan = evaluate_daily_backfill_plan(
        DailyBackfillPlanningEvidence(
            now=datetime(2026, 9, 7, 6, 30, tzinfo=UTC),
            ready_at=datetime(2026, 9, 7, 8, 0, tzinfo=UTC),
            planning_window_start=datetime(2026, 9, 7, 0, 0, tzinfo=UTC),
            next_free_start=datetime(2026, 9, 7, 12, 1, tzinfo=UTC),
            available_after_reserve_kwh=14,
            discharge_efficiency_percent=50,
            protected_house_kwh=3,
            sellable_energy_kwh=100,
            protected_ev_allocation_kwh=5,
            delivered_this_cycle_kwh=0,
            stored_vehicle_energy_kwh=5,
            vehicle_soc_percent=50,
            vehicle_target_soc_percent=60,
            vehicle_charge_efficiency_percent=90,
            inverter_output_limit_kw=15,
            outside_inverter_percent=30,
            voltage_v=230,
            phase_count=3,
            current_step_a=1,
            charger_minimum_a=1,
            charger_maximum_a=16,
            planning_buffer_minutes=0,
        )
    )

    assert plan.remaining_allocation_kwh == 5
    assert plan.protected_house_kwh == 3
    assert plan.discretionary_energy_kwh == 0
    assert plan.planned_energy_kwh == 1.111
    assert plan.allocation_shortfall_kwh == 3.889
    assert plan.current_ceiling_a == 6
    assert plan.power_ceiling_kw == 4.14
    assert plan.phase == "waiting_latest_start"


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


@pytest.mark.parametrize(("allocation", "delivered"), [(0, 0), (5, 5)])
def test_conservative_mode_retains_completed_allocation_gate(allocation, delivered):
    inputs = _inputs(
        protected_ev_allocation_kwh=allocation,
        delivered_this_cycle_kwh=delivered,
    )
    plan = calculate_daily_backfill_plan(inputs)

    assert inputs.use_all_discretionary_energy is False
    assert plan == calculate_daily_backfill_plan(
        replace(inputs, use_all_discretionary_energy=False)
    )
    assert plan.remaining_allocation_kwh == 0
    assert plan.proportional_discretionary_kwh == 3.667
    assert plan.planned_energy_kwh == 3.667
    assert plan.phase == "allocation_complete"
    assert advance_daily_backfill_session(
        DailyBackfillCycleState(ready_at=inputs.ready_at),
        plan,
        now=inputs.now,
        actual_current_a=0,
    ).state.active is False


@pytest.mark.parametrize(("allocation", "delivered"), [(0, 0), (5, 5)])
def test_full_surplus_operates_without_remaining_fixed_allocation(allocation, delivered):
    inputs = _inputs(
        protected_ev_allocation_kwh=allocation,
        delivered_this_cycle_kwh=delivered,
        use_all_discretionary_energy=True,
    )
    plan = calculate_daily_backfill_plan(inputs)

    assert plan.remaining_allocation_kwh == 0
    assert plan.discretionary_energy_kwh == 11
    # Keep this diagnostic as the original time-proportional reference.
    assert plan.proportional_discretionary_kwh == 3.667
    assert plan.planned_energy_kwh == 11
    assert plan.phase == "charge_now"
    started = advance_daily_backfill_session(
        DailyBackfillCycleState(
            ready_at=inputs.ready_at,
            energy=DailyBackfillEnergyState(delivered_kwh=delivered),
        ),
        plan,
        now=inputs.now,
        actual_current_a=0,
    )
    assert started.state.active is True
    assert started.state.session_target_kwh == 11
    assert started.state.session_start_delivered_kwh == delivered
    assert started.current_a == 6


def test_full_surplus_evidence_composes_live_efficiency_and_bounds():
    evidence = DailyBackfillPlanningEvidence(
        now=datetime(2026, 9, 10, 6, tzinfo=UTC),
        ready_at=datetime(2026, 9, 10, 8, tzinfo=UTC),
        planning_window_start=datetime(2026, 9, 10, 0, tzinfo=UTC),
        next_free_start=datetime(2026, 9, 10, 12, tzinfo=UTC),
        available_after_reserve_kwh=20,
        discharge_efficiency_percent=50,
        protected_house_kwh=2,
        sellable_energy_kwh=6,
        protected_ev_allocation_kwh=0,
        delivered_this_cycle_kwh=0,
        stored_vehicle_energy_kwh=40,
        vehicle_soc_percent=50,
        vehicle_target_soc_percent=60,
        vehicle_charge_efficiency_percent=80,
        inverter_output_limit_kw=15,
        outside_inverter_percent=30,
        voltage_v=230,
        phase_count=3,
        current_step_a=1,
        charger_minimum_a=1,
        charger_maximum_a=16,
        planning_buffer_minutes=0,
        use_all_discretionary_energy=True,
    )

    plan = evaluate_daily_backfill_plan(evidence)

    assert plan.discretionary_energy_kwh == 8
    assert plan.proportional_discretionary_kwh == 2.667
    assert plan.planned_energy_kwh == 6
    assert plan.current_ceiling_a == 6
    assert plan.phase == "waiting_latest_start"
    conservative = evaluate_daily_backfill_plan(
        replace(evidence, use_all_discretionary_energy=False)
    )
    assert conservative.planned_energy_kwh == 2.667
    assert conservative.phase == "allocation_complete"
    vehicle_bound = evaluate_daily_backfill_plan(
        replace(evidence, stored_vehicle_energy_kwh=4)
    )
    assert vehicle_bound.planned_energy_kwh == 1


def test_full_surplus_overnight_latest_start_keeps_three_phase_cap():
    inputs = _inputs(
        now=datetime(2026, 9, 9, 23, tzinfo=UTC),
        protected_ev_allocation_kwh=0,
        planning_buffer_minutes=10,
        use_all_discretionary_energy=True,
    )
    plan = calculate_daily_backfill_plan(inputs)

    assert plan.current_ceiling_a == 6
    assert plan.power_ceiling_kw == 4.14
    assert plan.duration_minutes == 159.4
    assert plan.planned_start is not None
    assert plan.planned_start.timestamp() == pytest.approx(
        datetime(2026, 9, 10, 5, 10, 34, 782609, tzinfo=UTC).timestamp(), abs=0.1
    )
    assert plan.achievable_by_ready is True
    assert plan.phase == "before_planning_window"
    waiting = calculate_daily_backfill_plan(
        replace(inputs, now=inputs.planning_window_start)
    )
    assert waiting.planned_start == plan.planned_start
    assert waiting.phase == "waiting_latest_start"
    started = calculate_daily_backfill_plan(replace(inputs, now=plan.planned_start))
    assert started.planned_start == plan.planned_start
    assert started.phase == "charge_now"


@pytest.mark.parametrize(
    ("delivered", "remaining", "discretionary"),
    [(0, 5, 6), (3, 2, 9), (6, 0, 11)],
)
def test_full_surplus_and_fixed_quota_share_one_live_energy_budget(
    delivered, remaining, discretionary
):
    plan = calculate_daily_backfill_plan(
        _inputs(delivered_this_cycle_kwh=delivered, use_all_discretionary_energy=True)
    )

    assert plan.remaining_allocation_kwh == remaining
    assert plan.discretionary_energy_kwh == discretionary
    assert plan.planned_energy_kwh == 11
    assert daily_backfill_protection_remainder_kwh(
        configured_allocation_kwh=5,
        delivered_kwh=delivered,
        same_ready_cycle=True,
    ) == remaining
    assert daily_backfill_protection_remainder_kwh(
        configured_allocation_kwh=0,
        delivered_kwh=delivered,
        same_ready_cycle=False,
    ) == 0


def test_full_surplus_is_capped_by_current_vehicle_wall_room():
    plan = calculate_daily_backfill_plan(
        _inputs(
            protected_ev_allocation_kwh=0,
            vehicle_wall_room_kwh=1.25,
            use_all_discretionary_energy=True,
        )
    )

    assert plan.discretionary_energy_kwh == 11
    assert plan.planned_energy_kwh == 1.25
    assert plan.duration_minutes == 18.1


def test_full_surplus_late_arrival_charges_partial_and_reports_unachievable():
    inputs = _inputs(
        now=datetime(2026, 9, 10, 7, 55, tzinfo=UTC),
        available_ac_after_reserve_kwh=22,
        sellable_energy_kwh=19,
        protected_ev_allocation_kwh=0,
        outside_inverter_percent=40,
        use_all_discretionary_energy=True,
    )
    plan = calculate_daily_backfill_plan(inputs)

    assert plan.planned_energy_kwh == 19
    assert plan.current_ceiling_a == 8
    assert plan.power_ceiling_kw == 5.52
    assert plan.duration_minutes == 206.5
    assert plan.planned_start is not None
    assert inputs.planning_window_start < plan.planned_start < inputs.now
    assert plan.achievable_by_ready is False
    assert plan.phase == "charge_now"
    started = advance_daily_backfill_session(
        DailyBackfillCycleState(ready_at=inputs.ready_at),
        plan,
        now=inputs.now,
        actual_current_a=0,
    )
    assert started.state.active is True
    assert started.current_a == 8

    conservative = calculate_daily_backfill_plan(
        replace(inputs, protected_ev_allocation_kwh=19, use_all_discretionary_energy=False)
    )
    assert conservative.planned_energy_kwh == plan.planned_energy_kwh
    assert conservative.planned_start == plan.planned_start
    assert conservative.achievable_by_ready is True
    assert conservative.phase == "charge_now"


def test_insufficient_live_energy_reports_shortfall_without_assuming_cloud_history():
    plan = calculate_daily_backfill_plan(
        _inputs(available_ac_after_reserve_kwh=6, protected_house_kwh=3)
    )
    assert plan.planned_energy_kwh == 3
    assert plan.allocation_shortfall_kwh == 2
    assert plan.achievable_by_ready is False


def test_no_sellable_energy_means_no_pre_free_charge_even_with_allocation():
    plan = calculate_daily_backfill_plan(_inputs(sellable_energy_kwh=0))

    assert plan.planned_energy_kwh == 0
    assert plan.phase == "sellable_energy_unavailable"


def test_ready_by_plan_is_capped_by_live_sellable_energy():
    plan = calculate_daily_backfill_plan(_inputs(sellable_energy_kwh=0.4))

    assert plan.planned_energy_kwh == 0.4


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
            sellable_energy_kwh=50,
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


def test_daily_backfill_energy_integrates_confirmed_current_trapezoid():
    start = datetime(2026, 9, 10, 6, 0, tzinfo=UTC)
    state = DailyBackfillEnergyState(1.0, start, 10.0)

    transition = integrate_daily_backfill_energy(
        state,
        active=True,
        now=start + timedelta(seconds=60),
        actual_current_a=14.0,
        voltage_v=230.0,
        phase_count=3,
        maximum_sample_age_seconds=90.0,
    )

    assert transition.delivered_kwh == pytest.approx(1.138)
    assert transition.last_sample_at == start + timedelta(seconds=60)
    assert transition.last_actual_current_a == 14.0


def test_daily_backfill_energy_restarts_sampling_after_stale_or_missing_feedback():
    start = datetime(2026, 9, 10, 6, 0, tzinfo=UTC)
    state = DailyBackfillEnergyState(1.0, start, 10.0)

    stale = integrate_daily_backfill_energy(
        state,
        active=True,
        now=start + timedelta(seconds=91),
        actual_current_a=14.0,
        voltage_v=230.0,
        phase_count=3,
        maximum_sample_age_seconds=90.0,
    )
    assert stale == DailyBackfillEnergyState(
        1.0, start + timedelta(seconds=91), 14.0
    )

    missing = integrate_daily_backfill_energy(
        stale,
        active=True,
        now=start + timedelta(seconds=121),
        actual_current_a=None,
        voltage_v=230.0,
        phase_count=3,
        maximum_sample_age_seconds=90.0,
    )
    assert missing == DailyBackfillEnergyState(
        1.0, start + timedelta(seconds=121), None
    )

    out_of_order = integrate_daily_backfill_energy(
        state,
        active=True,
        now=start - timedelta(seconds=1),
        actual_current_a=8.0,
        voltage_v=230.0,
        phase_count=3,
        maximum_sample_age_seconds=90.0,
    )
    assert out_of_order == DailyBackfillEnergyState(
        1.0, start - timedelta(seconds=1), 8.0
    )


def test_daily_backfill_energy_clears_samples_when_policy_is_inactive():
    start = datetime(2026, 9, 10, 6, 0, tzinfo=UTC)
    transition = integrate_daily_backfill_energy(
        DailyBackfillEnergyState(1.0, start, 10.0),
        active=False,
        now=start + timedelta(seconds=30),
        actual_current_a=10.0,
        voltage_v=230.0,
        phase_count=3,
        maximum_sample_age_seconds=90.0,
    )
    assert transition == DailyBackfillEnergyState(1.0, None, None)


@pytest.mark.parametrize(
    ("previous_at", "now", "delivered"),
    [
        (
            datetime(2026, 10, 4, 1, 59, 30, tzinfo=ZoneInfo("Australia/Sydney")),
            datetime(2026, 10, 4, 3, 0, 30, tzinfo=ZoneInfo("Australia/Sydney")),
            1.069,
        ),
        (
            datetime(2026, 4, 5, 2, 59, 30, tzinfo=ZoneInfo("Australia/Sydney")),
            datetime(2026, 4, 5, 2, 0, 30, tzinfo=ZoneInfo("Australia/Sydney"), fold=1),
            1.069,
        ),
        (
            datetime(2026, 4, 5, 2, 0, tzinfo=ZoneInfo("Australia/Sydney")),
            datetime(2026, 4, 5, 2, 1, tzinfo=ZoneInfo("Australia/Sydney"), fold=1),
            1.0,
        ),
        (
            datetime(2026, 4, 5, 2, 0, tzinfo=ZoneInfo("Australia/Sydney"), fold=1),
            datetime(2026, 4, 5, 2, 1, tzinfo=ZoneInfo("Australia/Sydney")),
            1.0,
        ),
    ],
)
def test_confirmed_wall_energy_uses_physical_elapsed_time_across_dst(
    previous_at, now, delivered
):
    state = integrate_daily_backfill_energy(
        DailyBackfillEnergyState(1.0, previous_at, 6.0),
        active=True,
        now=now,
        actual_current_a=6.0,
        voltage_v=230.0,
        phase_count=3,
        maximum_sample_age_seconds=90.0,
    )

    assert state.delivered_kwh == pytest.approx(delivered)
    assert state.last_sample_at == now


def test_full_surplus_latest_start_uses_physical_duration_at_spring_dst():
    zone = ZoneInfo("Australia/Sydney")
    inputs = _inputs(
        now=datetime(2026, 10, 4, 1, tzinfo=zone),
        ready_at=datetime(2026, 10, 4, 8, tzinfo=zone),
        planning_window_start=datetime(2026, 10, 4, 0, tzinfo=zone),
        next_free_start=datetime(2026, 10, 4, 12, tzinfo=zone),
        available_ac_after_reserve_kwh=27.84,
        protected_ev_allocation_kwh=0,
        sellable_energy_kwh=24.84,
        vehicle_wall_room_kwh=40,
        use_all_discretionary_energy=True,
    )
    plan = calculate_daily_backfill_plan(inputs)

    assert plan.duration_minutes == 360
    assert plan.planned_start == datetime(2026, 10, 4, 1, tzinfo=zone)
    assert plan.proportional_discretionary_kwh == 14.904
    assert plan.phase == "charge_now"
    assert plan.achievable_by_ready is True


def test_full_surplus_repeated_hour_start_requires_the_correct_fold():
    zone = ZoneInfo("Australia/Sydney")
    inputs = _inputs(
        now=datetime(2026, 4, 5, 2, 30, tzinfo=zone),
        ready_at=datetime(2026, 4, 5, 8, tzinfo=zone),
        planning_window_start=datetime(2026, 4, 5, 0, tzinfo=zone),
        next_free_start=datetime(2026, 4, 5, 12, tzinfo=zone),
        available_ac_after_reserve_kwh=27.84,
        protected_ev_allocation_kwh=0,
        sellable_energy_kwh=24.84,
        vehicle_wall_room_kwh=40,
        use_all_discretionary_energy=True,
    )
    plan = calculate_daily_backfill_plan(inputs)

    assert plan.duration_minutes == 360
    assert plan.planned_start is not None
    assert plan.planned_start.timestamp() == datetime(
        2026, 4, 5, 2, tzinfo=zone, fold=1
    ).timestamp()
    assert plan.planned_start.fold == 1
    assert plan.proportional_discretionary_kwh == 15.377
    assert plan.phase == "waiting_latest_start"
    started = calculate_daily_backfill_plan(
        replace(inputs, now=datetime(2026, 4, 5, 2, 15, tzinfo=zone, fold=1))
    )
    assert started.phase == "charge_now"


def test_daily_backfill_cycle_rollover_resets_active_cycle_and_latches_stop():
    old_ready = datetime(2026, 9, 10, 8, tzinfo=UTC)
    new_ready = datetime(2026, 9, 11, 8, tzinfo=UTC)
    state = DailyBackfillCycleState(
        ready_at=old_ready,
        energy=DailyBackfillEnergyState(2.0, old_ready, 10.0),
        active=True,
        session_target_kwh=4.0,
        session_start_delivered_kwh=1.0,
        frozen_start=old_ready - timedelta(hours=1),
        stop_pending=False,
        stop_attempts=2,
        last_stop_at=old_ready - timedelta(seconds=30),
    )

    transition = roll_daily_backfill_cycle(state, new_ready)

    assert transition == DailyBackfillCycleState(
        ready_at=new_ready,
        stop_pending=True,
    )


def test_daily_backfill_cycle_rollover_preserves_existing_inactive_stop_obligation():
    old_ready = datetime(2026, 9, 10, 8, tzinfo=UTC)
    new_ready = datetime(2026, 9, 11, 8, tzinfo=UTC)
    last_stop = old_ready - timedelta(seconds=30)
    state = DailyBackfillCycleState(
        ready_at=old_ready,
        active=False,
        stop_pending=True,
        stop_attempts=2,
        last_stop_at=last_stop,
    )

    transition = roll_daily_backfill_cycle(state, new_ready)

    assert transition == DailyBackfillCycleState(
        ready_at=new_ready,
        stop_pending=True,
        stop_attempts=2,
        last_stop_at=last_stop,
    )
    assert roll_daily_backfill_cycle(transition, new_ready) is transition


def test_daily_backfill_stop_transition_matches_bounded_feedback_trace():
    start = datetime(2026, 9, 10, 6, tzinfo=UTC)
    state = DailyBackfillStopState(
        pending=True,
        outside_control_active=True,
    )

    command = reconcile_daily_backfill_stop(
        state,
        charge_switch_on=True,
        now=start,
        retry_interval=timedelta(seconds=30),
    )
    assert tuple(item.action for item in command.plan.commands) == ("stop_charging",)
    assert command.plan.reason == "daily_backfill_complete"
    assert command.save_required is False

    state = record_daily_backfill_stop_attempt(command.state, start)
    assert state == DailyBackfillStopState(True, 1, start, True)

    waiting = reconcile_daily_backfill_stop(
        state,
        charge_switch_on=True,
        now=start + timedelta(seconds=29),
        retry_interval=timedelta(seconds=30),
    )
    assert waiting.state is state
    assert waiting.plan.commands == ()
    assert waiting.plan.reason == "daily_backfill_stop_awaiting_feedback"

    for seconds in (30, 90, 210, 450, 930, 1890, 3690):
        at = start + timedelta(seconds=seconds)
        retry = reconcile_daily_backfill_stop(
            state,
            charge_switch_on=True,
            now=at,
            retry_interval=timedelta(seconds=30),
        )
        assert tuple(item.action for item in retry.plan.commands) == ("stop_charging",)
        state = record_daily_backfill_stop_attempt(retry.state, at)

    assert state.attempts == 8
    slow_wait = reconcile_daily_backfill_stop(
        state,
        charge_switch_on=True,
        now=start + timedelta(seconds=5400),
        retry_interval=timedelta(seconds=30),
    )
    assert slow_wait.state is state
    assert slow_wait.plan.commands == ()
    assert slow_wait.plan.reason == "daily_backfill_stop_awaiting_feedback"

    slow_retry = reconcile_daily_backfill_stop(
        state,
        charge_switch_on=True,
        now=start + timedelta(seconds=5490),
        retry_interval=timedelta(seconds=30),
    )
    assert tuple(item.action for item in slow_retry.plan.commands) == ("stop_charging",)

    stopped = reconcile_daily_backfill_stop(
        state,
        charge_switch_on=False,
        now=start + timedelta(seconds=5500),
        retry_interval=timedelta(seconds=30),
    )
    assert stopped.state == DailyBackfillStopState()
    assert stopped.plan.reason == "daily_backfill_stopped"
    assert stopped.save_required is True


def test_daily_backfill_session_transition_starts_shrinks_and_completes():
    now = datetime(2026, 9, 10, 6, tzinfo=UTC)
    planned_start = now - timedelta(minutes=1)
    plan = replace(
        calculate_daily_backfill_plan(_inputs()),
        phase="charge_now",
        planned_energy_kwh=4.0,
        current_ceiling_a=6.0,
        planned_start=planned_start,
    )
    state = DailyBackfillCycleState(
        ready_at=datetime(2026, 9, 10, 8, tzinfo=UTC),
        energy=DailyBackfillEnergyState(delivered_kwh=1.0),
        stop_pending=True,
        stop_attempts=2,
    )

    started = advance_daily_backfill_session(
        state,
        plan,
        now=now,
        actual_current_a=2.0,
    )
    assert started.current_a == 6.0
    assert started.state.active is True
    assert started.state.session_target_kwh == 4.0
    assert started.state.session_start_delivered_kwh == 1.0
    assert started.state.frozen_start == planned_start
    assert started.state.energy == DailyBackfillEnergyState(1.0, now, 2.0)
    assert started.state.stop_pending is False
    assert started.state.stop_attempts == 0

    progressed = replace(
        started.state,
        energy=replace(started.state.energy, delivered_kwh=1.2),
    )
    shrunk = advance_daily_backfill_session(
        progressed,
        replace(plan, phase="waiting_latest_start", planned_energy_kwh=0.4),
        now=now + timedelta(minutes=1),
        actual_current_a=6.0,
    )
    assert shrunk.current_a == 6.0
    assert shrunk.state.active is True
    assert shrunk.state.session_target_kwh == pytest.approx(0.6)
    assert shrunk.state.frozen_start == planned_start

    completed = advance_daily_backfill_session(
        shrunk.state,
        replace(plan, phase="sellable_energy_unavailable", planned_energy_kwh=0.0),
        now=now + timedelta(minutes=2),
        actual_current_a=6.0,
    )
    assert completed.current_a == 0.0
    assert completed.state.active is False
    assert completed.state.session_target_kwh == 0.0
    assert completed.state.session_start_delivered_kwh == 0.0
    assert completed.state.frozen_start is None
    assert completed.state.stop_pending is True
    assert completed.state.stop_attempts == 0


@pytest.mark.parametrize(
    ("reduction", "exhaustion", "phase"),
    [
        (
            {"sellable_energy_kwh": 0.4},
            {"sellable_energy_kwh": 0},
            "sellable_energy_unavailable",
        ),
        (
            {"available_ac_after_reserve_kwh": 3.4},
            {"available_ac_after_reserve_kwh": 3},
            "protected_energy_unavailable",
        ),
        (
            {"protected_house_kwh": 13.6},
            {"protected_house_kwh": 14},
            "protected_energy_unavailable",
        ),
    ],
)
def test_full_surplus_live_budget_shrinks_without_regrowing_then_stops(
    reduction, exhaustion, phase
):
    inputs = _inputs(protected_ev_allocation_kwh=0, use_all_discretionary_energy=True)
    plan = calculate_daily_backfill_plan(inputs)
    started = advance_daily_backfill_session(
        DailyBackfillCycleState(ready_at=inputs.ready_at),
        plan,
        now=inputs.now,
        actual_current_a=6,
    )
    now = inputs.now + timedelta(minutes=1)
    energy = integrate_daily_backfill_energy(
        started.state.energy,
        active=True,
        now=now,
        actual_current_a=6,
        voltage_v=inputs.voltage_v,
        phase_count=inputs.phase_count,
        maximum_sample_age_seconds=90,
    )
    reduced_plan = calculate_daily_backfill_plan(replace(inputs, now=now, **reduction))
    shrunk = advance_daily_backfill_session(
        replace(started.state, energy=energy),
        reduced_plan,
        now=now,
        actual_current_a=6,
    )

    assert energy.delivered_kwh == pytest.approx(0.069)
    assert reduced_plan.planned_energy_kwh == 0.4
    assert shrunk.state.active is True
    assert shrunk.state.session_target_kwh == pytest.approx(0.469)
    assert shrunk.state.frozen_start == started.state.frozen_start
    recovered = advance_daily_backfill_session(
        shrunk.state,
        calculate_daily_backfill_plan(replace(inputs, now=now)),
        now=now,
        actual_current_a=6,
    )
    assert recovered.state.session_target_kwh == shrunk.state.session_target_kwh
    unavailable = calculate_daily_backfill_plan(replace(inputs, now=now, **exhaustion))
    assert unavailable.phase == phase
    stopped = advance_daily_backfill_session(
        recovered.state,
        unavailable,
        now=now,
        actual_current_a=6,
    )
    assert stopped.current_a == 0
    assert stopped.state.active is False
    assert stopped.state.stop_pending is True
    assert stopped.state.energy is energy


def test_full_surplus_completes_from_confirmed_delivered_energy_before_ready():
    inputs = _inputs(
        now=datetime(2026, 9, 10, 6, 4, tzinfo=UTC),
        ready_at=datetime(2026, 9, 10, 6, 10, tzinfo=UTC),
        available_ac_after_reserve_kwh=3.1,
        sellable_energy_kwh=0.1,
        protected_ev_allocation_kwh=0,
        delivered_this_cycle_kwh=1,
        planning_buffer_minutes=5,
        use_all_discretionary_energy=True,
    )
    started = advance_daily_backfill_session(
        DailyBackfillCycleState(
            ready_at=inputs.ready_at,
            energy=DailyBackfillEnergyState(delivered_kwh=1),
        ),
        calculate_daily_backfill_plan(inputs),
        now=inputs.now,
        actual_current_a=6,
    )
    assert started.state.active is True
    assert started.state.session_start_delivered_kwh == 1
    assert started.state.session_target_kwh == 0.1
    now = inputs.now + timedelta(seconds=90)
    energy = integrate_daily_backfill_energy(
        started.state.energy,
        active=True,
        now=now,
        actual_current_a=6,
        voltage_v=inputs.voltage_v,
        phase_count=inputs.phase_count,
        maximum_sample_age_seconds=90,
    )
    live_plan = calculate_daily_backfill_plan(
        replace(inputs, now=now, available_ac_after_reserve_kwh=3.01, sellable_energy_kwh=0.01)
    )
    assert live_plan.planned_energy_kwh > 0
    assert live_plan.phase == "charge_now"
    completed = advance_daily_backfill_session(
        replace(started.state, energy=energy),
        live_plan,
        now=now,
        actual_current_a=6,
    )

    assert now < inputs.ready_at
    assert completed.state.energy.delivered_kwh == pytest.approx(1.1035)
    assert completed.state.active is False
    assert completed.state.stop_pending is True
    assert completed.current_a == 0


def test_full_surplus_retains_existing_session_state_after_restart():
    inputs = _inputs(
        protected_ev_allocation_kwh=0,
        delivered_this_cycle_kwh=2.25,
        use_all_discretionary_energy=True,
    )
    frozen_start = datetime(2026, 9, 10, 5, tzinfo=UTC)
    # Existing persisted fields are sufficient; this mode adds no new latch.
    restored = DailyBackfillCycleState(
        ready_at=inputs.ready_at,
        energy=DailyBackfillEnergyState(delivered_kwh=2.25),
        active=True,
        session_target_kwh=4,
        session_start_delivered_kwh=1,
        frozen_start=frozen_start,
    )
    same_cycle = roll_daily_backfill_cycle(restored, inputs.ready_at)
    assert same_cycle is restored
    plan = calculate_daily_backfill_plan(replace(inputs, sellable_energy_kwh=0.4))
    assert plan.phase == "waiting_latest_start"
    resumed = advance_daily_backfill_session(
        same_cycle,
        plan,
        now=inputs.now,
        actual_current_a=6,
    )

    assert resumed.state.active is True
    assert resumed.state.session_target_kwh == pytest.approx(1.65)
    assert resumed.state.session_start_delivered_kwh == 1
    assert resumed.state.frozen_start == frozen_start
    assert resumed.state.energy.delivered_kwh == 2.25
    assert resumed.current_a == 6


def test_full_surplus_exact_ready_deadline_stops_and_rolls_existing_cycle():
    inputs = _inputs(protected_ev_allocation_kwh=0, use_all_discretionary_energy=True)
    active = advance_daily_backfill_session(
        DailyBackfillCycleState(ready_at=inputs.ready_at),
        calculate_daily_backfill_plan(inputs),
        now=inputs.now,
        actual_current_a=6,
    ).state
    deadline_plan = calculate_daily_backfill_plan(replace(inputs, now=inputs.ready_at))
    assert deadline_plan.planned_energy_kwh == 11
    assert deadline_plan.phase == "ready_time_passed"
    stopped = advance_daily_backfill_session(
        active, deadline_plan, now=inputs.ready_at, actual_current_a=6
    )

    assert stopped.state.active is False
    assert stopped.state.stop_pending is True
    assert stopped.current_a == 0
    next_ready = inputs.ready_at + timedelta(days=1)
    assert roll_daily_backfill_cycle(stopped.state, next_ready) == DailyBackfillCycleState(
        ready_at=next_ready,
        stop_pending=True,
    )


def test_end_daily_backfill_session_matches_existing_active_reset():
    now = datetime(2026, 9, 10, 6, tzinfo=UTC)
    state = DailyBackfillCycleState(
        ready_at=now + timedelta(hours=2),
        energy=DailyBackfillEnergyState(2, now, 6),
        active=True,
        session_target_kwh=4,
        session_start_delivered_kwh=1,
        frozen_start=now - timedelta(minutes=10),
        stop_pending=True,
        stop_attempts=2,
        last_stop_at=now - timedelta(seconds=30),
    )

    ended = end_daily_backfill_session(state)

    assert ended == DailyBackfillCycleState(
        ready_at=state.ready_at,
        energy=state.energy,
        stop_pending=True,
    )
    assert ended.energy is state.energy
    assert state.active is True


def test_end_daily_backfill_session_preserves_inactive_stop_obligation():
    now = datetime(2026, 9, 10, 6, tzinfo=UTC)
    state = DailyBackfillCycleState(
        ready_at=now + timedelta(hours=2),
        energy=DailyBackfillEnergyState(delivered_kwh=2),
        stop_pending=True,
        stop_attempts=3,
        last_stop_at=now,
    )

    assert end_daily_backfill_session(state) is state
