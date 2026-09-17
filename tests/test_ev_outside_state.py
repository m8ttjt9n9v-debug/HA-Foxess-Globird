from datetime import UTC, datetime, timedelta

from custom_components.home_energy_orchestrator.planner.ev_daily_backfill import (
    DailyBackfillCycleState,
)
from custom_components.home_energy_orchestrator.planner.ev_outside_state import (
    abort_outside_charge_at_battery_floor,
    advance_charge_to_full,
    cleanup_disconnected_ev,
    cleanup_outside_ownership_for_free_window,
)
from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    PreFreeSessionState,
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

    transition = abort_outside_charge_at_battery_floor(
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

    transition = abort_outside_charge_at_battery_floor(
        state,
        charge_switch_on=False,
        charge_limit_percent=80,
    )

    assert transition.daily_state.stop_pending is True
    assert transition.daily_state.stop_attempts == 2
    assert transition.daily_state.last_stop_at == last_stop
    assert transition.outside_control_active is False
    assert transition.continue_reconciliation is False
    assert transition.last_reason == "battery_floor_reached"
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
