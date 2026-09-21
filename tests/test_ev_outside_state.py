from dataclasses import replace
from datetime import UTC, datetime, timedelta

from custom_components.home_energy_orchestrator.planner.ev_daily_backfill import (
    DailyBackfillCycleState,
)
from custom_components.home_energy_orchestrator.planner.ev_outside_state import (
    OutsideBatteryReserveEvidence,
    abort_outside_charge_at_battery_reserve,
    advance_charge_to_full,
    cleanup_disconnected_ev,
    cleanup_outside_ownership_for_free_window,
    outside_battery_reserve_reached,
    reconcile_outside_ownership,
)
from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    PreFreeSessionState,
)

BATTERY_RESERVE = OutsideBatteryReserveEvidence(
    charge_to_full=False,
    battery_soc_percent=20,
    reserve_percent=20,
)


def test_outside_battery_reserve_uses_inclusive_boundary():
    assert outside_battery_reserve_reached(BATTERY_RESERVE) is True
    assert (
        outside_battery_reserve_reached(
            replace(BATTERY_RESERVE, battery_soc_percent=20.001)
        )
        is False
    )


def test_outside_battery_reserve_requires_soc_and_yields_to_paid_override():
    assert (
        outside_battery_reserve_reached(
            replace(BATTERY_RESERVE, battery_soc_percent=None)
        )
        is False
    )
    assert (
        outside_battery_reserve_reached(replace(BATTERY_RESERVE, charge_to_full=True))
        is False
    )


def test_battery_floor_abort_clears_sessions_and_creates_stop_obligation():
    state = DailyBackfillCycleState(
        active=True,
        session_target_kwh=2,
        session_start_delivered_kwh=0.5,
        frozen_start=datetime(2026, 9, 7, 5, tzinfo=UTC),
        stop_attempts=2,
        last_stop_at=datetime(2026, 9, 7, 5, 30, tzinfo=UTC),
    )

    transition = abort_outside_charge_at_battery_reserve(
        state,
        charge_switch_on=True,
        charge_limit_percent=80,
    )

    assert transition.daily_state.active is False
    assert transition.daily_state.session_target_kwh == 0
    assert transition.daily_state.session_start_delivered_kwh == 0
    assert transition.daily_state.frozen_start is None
    assert transition.daily_state.stop_pending is True
    assert transition.daily_state.stop_attempts == 0
    assert transition.daily_state.last_stop_at is None
    assert transition.pre_free_state.active is False
    assert transition.target_current_a == 0
    assert transition.target_limit_percent == 80
    assert transition.outside_stop_requested is True
    assert transition.outside_control_active is True
    assert transition.continue_reconciliation is True
    assert transition.last_reason is None
    assert transition.candidates[0].command_intent == ("stop_charging",)


def test_battery_floor_abort_without_active_charge_retains_existing_stop_state():
    last_stop = datetime(2026, 9, 7, 5, 30, tzinfo=UTC)
    state = DailyBackfillCycleState(
        stop_pending=True,
        stop_attempts=2,
        last_stop_at=last_stop,
    )

    transition = abort_outside_charge_at_battery_reserve(
        state,
        charge_switch_on=False,
        charge_limit_percent=80,
    )

    assert transition.daily_state.stop_pending is True
    assert transition.daily_state.stop_attempts == 2
    assert transition.daily_state.last_stop_at == last_stop
    assert transition.outside_control_active is False
    assert transition.continue_reconciliation is False
    assert transition.last_reason == "ev_battery_reserve_reached"
    assert transition.candidates[0].command_intent == ()


def test_disconnected_cleanup_clears_all_outside_session_ownership():
    last_stop = datetime(2026, 9, 7, 5, 30, tzinfo=UTC)
    state = DailyBackfillCycleState(
        active=True,
        session_target_kwh=2,
        session_start_delivered_kwh=0.5,
        frozen_start=datetime(2026, 9, 7, 5, tzinfo=UTC),
        stop_pending=True,
        stop_attempts=2,
        last_stop_at=last_stop,
    )

    transition = cleanup_disconnected_ev(
        state,
        charge_to_full_started=True,
        solar_spill_enabled=True,
    )

    assert transition.daily_state.active is False
    assert transition.daily_state.session_target_kwh == 0
    assert transition.daily_state.session_start_delivered_kwh == 0
    assert transition.daily_state.frozen_start is None
    assert transition.daily_state.stop_pending is False
    assert transition.daily_state.stop_attempts == 0
    assert transition.daily_state.last_stop_at is None
    assert transition.pre_free_state.active is False
    assert transition.pre_free_phase == "not_eligible"
    assert transition.charge_to_full_started_at is None
    assert transition.clear_charge_to_full_config is True
    assert transition.outside_control_active is False
    assert transition.outside_target_active is False
    assert transition.solar_spill.phase == "vehicle_not_eligible"


def test_disconnected_cleanup_reports_disabled_solar_without_config_write():
    transition = cleanup_disconnected_ev(
        DailyBackfillCycleState(),
        charge_to_full_started=False,
        solar_spill_enabled=False,
    )
    assert transition.clear_charge_to_full_config is False
    assert transition.solar_spill.phase == "disabled"


def test_free_window_cleanup_clears_only_active_pre_free_ownership():
    frozen = datetime(2026, 9, 7, 10, 30, tzinfo=UTC)
    pre_free = PreFreeSessionState(True, frozen)

    cleared = cleanup_outside_ownership_for_free_window(
        in_free_window=True,
        pre_free_state=pre_free,
        outside_control_active=True,
        outside_target_active=True,
    )
    assert cleared.pre_free_state == PreFreeSessionState()
    assert cleared.outside_control_active is False
    assert cleared.outside_target_active is False
    assert cleared.changed is True

    before_window = cleanup_outside_ownership_for_free_window(
        in_free_window=False,
        pre_free_state=pre_free,
        outside_control_active=True,
        outside_target_active=True,
    )
    assert before_window.pre_free_state is pre_free
    assert before_window.outside_control_active is True
    assert before_window.outside_target_active is True
    assert before_window.changed is False

    inactive = PreFreeSessionState()
    retained = cleanup_outside_ownership_for_free_window(
        in_free_window=True,
        pre_free_state=inactive,
        outside_control_active=True,
        outside_target_active=True,
    )
    assert retained.pre_free_state is inactive
    assert retained.outside_control_active is True
    assert retained.outside_target_active is True
    assert retained.changed is False


def test_outside_ownership_preserves_stage_priority_and_stop_latches():
    active_daily = DailyBackfillCycleState(active=True)
    owned = reconcile_outside_ownership(
        active_daily,
        charge_to_full=False,
        pre_free_active=False,
        solar_current_a=0,
        physical_minimum_a=1,
        baseline_a=0,
        configured_baseline_a=0,
        charge_switch_on=False,
        outside_control_active=False,
    )
    assert owned.outside_target_active is True
    assert owned.outside_control_active is True
    assert owned.outside_stop_requested is False

    pending = DailyBackfillCycleState(
        stop_pending=True,
        stop_attempts=2,
        last_stop_at=datetime(2026, 9, 7, 6, tzinfo=UTC),
    )
    retained_stop = reconcile_outside_ownership(
        pending,
        charge_to_full=False,
        pre_free_active=False,
        solar_current_a=0,
        physical_minimum_a=1,
        baseline_a=0,
        configured_baseline_a=0,
        charge_switch_on=False,
        outside_control_active=False,
    )
    assert retained_stop.daily_state is pending
    assert retained_stop.outside_stop_requested is True
    assert retained_stop.outside_control_active is True

    carried = reconcile_outside_ownership(
        DailyBackfillCycleState(),
        charge_to_full=False,
        pre_free_active=False,
        solar_current_a=0,
        physical_minimum_a=1,
        baseline_a=0,
        configured_baseline_a=0,
        charge_switch_on=True,
        outside_control_active=False,
    )
    assert carried.daily_state.stop_pending is True
    assert carried.daily_state.stop_attempts == 0
    assert carried.daily_state.last_stop_at is None
    assert carried.outside_stop_requested is True
    assert carried.outside_control_active is True


def test_outside_ownership_retains_baseline_and_prior_control_semantics():
    state = DailyBackfillCycleState()
    baseline = reconcile_outside_ownership(
        state,
        charge_to_full=False,
        pre_free_active=False,
        solar_current_a=0,
        physical_minimum_a=1,
        baseline_a=1,
        configured_baseline_a=1,
        charge_switch_on=False,
        outside_control_active=False,
    )
    assert baseline.outside_target_active is False
    assert baseline.outside_control_active is True
    assert baseline.outside_stop_requested is False

    retained = reconcile_outside_ownership(
        state,
        charge_to_full=False,
        pre_free_active=False,
        solar_current_a=0,
        physical_minimum_a=1,
        baseline_a=0,
        configured_baseline_a=0,
        charge_switch_on=False,
        outside_control_active=True,
    )
    assert retained.outside_target_active is False
    assert retained.outside_control_active is True
    assert retained.outside_stop_requested is False


def test_charge_to_full_transition_covers_start_completion_timeout_and_cancel():
    now = datetime(2026, 9, 7, 18, tzinfo=UTC)
    state = DailyBackfillCycleState()
    started = advance_charge_to_full(
        state,
        requested=True,
        started_at=None,
        now=now,
        vehicle_soc_percent=40,
        maximum_limit_percent=100,
        maximum_duration=timedelta(hours=12),
        protected_baseline_a=0,
    )
    assert started.started_at == now
    assert started.clear_config is False
    assert started.daily_state is state

    full = advance_charge_to_full(
        state,
        requested=True,
        started_at=now,
        now=now + timedelta(hours=1),
        vehicle_soc_percent=100,
        maximum_limit_percent=100,
        maximum_duration=timedelta(hours=12),
        protected_baseline_a=0,
    )
    assert full.started_at is None
    assert full.clear_config is True
    assert full.daily_state.stop_pending is True

    timed_out = advance_charge_to_full(
        state,
        requested=True,
        started_at=now,
        now=now + timedelta(hours=12),
        vehicle_soc_percent=None,
        maximum_limit_percent=100,
        maximum_duration=timedelta(hours=12),
        protected_baseline_a=1,
    )
    assert timed_out.started_at is None
    assert timed_out.clear_config is True
    assert timed_out.daily_state.stop_pending is False

    cancelled = advance_charge_to_full(
        state,
        requested=False,
        started_at=now,
        now=now + timedelta(minutes=1),
        vehicle_soc_percent=40,
        maximum_limit_percent=100,
        maximum_duration=timedelta(hours=12),
        protected_baseline_a=0,
    )
    assert cancelled.started_at is None
    assert cancelled.clear_config is False
    assert cancelled.daily_state.stop_pending is True
