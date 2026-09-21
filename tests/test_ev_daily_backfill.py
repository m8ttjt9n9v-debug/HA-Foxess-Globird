from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.ev_daily_backfill import (
    DailyBackfillCycleState,
    DailyBackfillEnergyState,
    DailyBackfillInputs,
    DailyBackfillPlanningEvidence,
    DailyBackfillStopState,
    advance_daily_backfill_session,
    calculate_daily_backfill_plan,
    evaluate_daily_backfill_plan,
    integrate_daily_backfill_energy,
    reconcile_daily_backfill_stop,
    record_daily_backfill_stop_attempt,
    roll_daily_backfill_cycle,
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
        maximum_attempts=3,
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
        maximum_attempts=3,
        retry_interval=timedelta(seconds=30),
    )
    assert waiting.state is state
    assert waiting.plan.commands == ()
    assert waiting.plan.reason == "daily_backfill_stop_awaiting_feedback"

    for attempt in (2, 3):
        at = start + timedelta(seconds=30 * (attempt - 1))
        retry = reconcile_daily_backfill_stop(
            state,
            charge_switch_on=True,
            now=at,
            maximum_attempts=3,
            retry_interval=timedelta(seconds=30),
        )
        assert tuple(item.action for item in retry.plan.commands) == ("stop_charging",)
        state = record_daily_backfill_stop_attempt(retry.state, at)

    fault = reconcile_daily_backfill_stop(
        state,
        charge_switch_on=True,
        now=start + timedelta(seconds=90),
        maximum_attempts=3,
        retry_interval=timedelta(seconds=30),
    )
    assert fault.state is state
    assert fault.plan.commands == ()
    assert fault.plan.reason == "daily_backfill_stop_fault_maximum_attempts"

    stopped = reconcile_daily_backfill_stop(
        state,
        charge_switch_on=False,
        now=start + timedelta(seconds=120),
        maximum_attempts=3,
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
