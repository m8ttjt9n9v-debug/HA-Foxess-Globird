from datetime import UTC, datetime

from custom_components.home_energy_orchestrator.planner.ev_daily_backfill import (
    DailyBackfillCycleState,
)
from custom_components.home_energy_orchestrator.planner.ev_outside_state import (
    abort_outside_charge_at_battery_floor,
    cleanup_disconnected_ev,
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
