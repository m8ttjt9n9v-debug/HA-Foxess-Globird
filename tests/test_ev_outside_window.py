from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    PreFreeCurrentInputs,
    PreFreePlanInputs,
    PreFreeSessionState,
    SolarSpillInputs,
    advance_pre_free_session,
    calculate_pre_free_plan,
    plan_pre_free_current,
    plan_solar_spill_current,
    select_outside_window_current,
)

SOLAR = SolarSpillInputs(
    telemetry_valid=True,
    battery_soc_percent=100,
    battery_full_threshold_percent=100,
    connected=True,
    vehicle_soc_percent=60,
    vehicle_soft_limit_percent=90,
    in_boosted_export_window=False,
    ev_power_kw=0.239,
    grid_export_kw=2.0,
    battery_charge_kw=0.5,
    voltage_v=239,
    phase_count=1,
    current_step_a=1,
    charger_minimum_a=1,
    current_ceiling_a=15,
)


@pytest.mark.parametrize(
    ("changes", "expected", "phase"),
    [
        ({}, 11, "solar_spill"),
        ({"telemetry_valid": False}, 0, "telemetry_unavailable"),
        ({"battery_soc_percent": 99}, 0, "battery_not_full"),
        ({"connected": False}, 0, "vehicle_not_eligible"),
        ({"vehicle_soc_percent": 90}, 0, "vehicle_not_eligible"),
        ({"in_boosted_export_window": True}, 0, "boosted_export_window"),
        (
            {"ev_power_kw": 0, "grid_export_kw": 0.1, "battery_charge_kw": 0},
            0,
            "below_charger_minimum",
        ),
        ({"grid_export_kw": 10}, 15, "solar_spill"),
    ],
)
def test_pilot_solar_spill_golden_branches(changes, expected, phase):
    decision = plan_solar_spill_current(replace(SOLAR, **changes))
    assert decision.current_a == expected
    assert decision.phase == phase


def test_solar_spill_removes_battery_discharge_and_preserves_existing_ev_power():
    decision = plan_solar_spill_current(
        replace(SOLAR, ev_power_kw=2.39, grid_export_kw=1, battery_charge_kw=-1)
    )
    assert decision.reconstructed_surplus_kw == 2.39
    assert decision.current_a == 10


def test_three_phase_extension_changes_only_power_to_current_conversion():
    decision = plan_solar_spill_current(
        replace(
            SOLAR,
            ev_power_kw=0,
            grid_export_kw=6.9,
            battery_charge_kw=0,
            voltage_v=230,
            phase_count=3,
            current_ceiling_a=16,
        )
    )
    assert decision.current_a == 10


def test_pre_free_plan_is_back_loaded_from_exact_free_boundary():
    free_start = datetime(2026, 9, 8, 11, 1, tzinfo=UTC)
    plan = calculate_pre_free_plan(
        PreFreePlanInputs(
            discretionary_ac_kwh=8,
            vehicle_wall_room_kwh=5,
            baseline_a=1,
            current_ceiling_a=11,
            voltage_v=230,
            phase_count=1,
            free_window_start=free_start,
        )
    )
    assert plan.planned_energy_kwh == 5
    assert plan.maximum_additional_power_kw == 2.3
    assert plan.planned_duration_minutes == 130.4
    assert plan.planned_start == datetime(2026, 9, 8, 8, 50, 36, tzinfo=UTC)


def test_pre_free_plan_protects_baseline_by_using_only_additional_power():
    plan = calculate_pre_free_plan(
        PreFreePlanInputs(
            discretionary_ac_kwh=2,
            vehicle_wall_room_kwh=2,
            baseline_a=1,
            current_ceiling_a=1,
            voltage_v=230,
            phase_count=1,
            free_window_start=datetime(2026, 9, 8, 11, 1, tzinfo=UTC),
        )
    )
    assert plan.maximum_additional_power_kw == 0
    assert plan.planned_start is None


def test_pre_free_latch_freezes_start_and_clears_when_budget_disappears():
    start = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
    waiting = advance_pre_free_session(
        PreFreeSessionState(),
        now=datetime(2026, 9, 8, 8, 59, tzinfo=UTC),
        in_pre_free_window=True,
        connected=True,
        export_session_active=False,
        planned_energy_kwh=5,
        vehicle_soc_percent=40,
        vehicle_soft_limit_percent=90,
        planned_start=start,
    )
    assert waiting.phase == "waiting_latest_start"
    started = advance_pre_free_session(
        waiting.state,
        now=start,
        in_pre_free_window=True,
        connected=True,
        export_session_active=False,
        planned_energy_kwh=5,
        vehicle_soc_percent=40,
        vehicle_soft_limit_percent=90,
        planned_start=start,
    )
    assert started.state == PreFreeSessionState(True, start)
    active = advance_pre_free_session(
        started.state,
        now=datetime(2026, 9, 8, 9, 5, tzinfo=UTC),
        in_pre_free_window=True,
        connected=True,
        export_session_active=False,
        planned_energy_kwh=4,
        vehicle_soc_percent=41,
        vehicle_soft_limit_percent=90,
        planned_start=datetime(2026, 9, 8, 9, 30, tzinfo=UTC),
    )
    assert active.state.frozen_start == start
    cleared = advance_pre_free_session(
        active.state,
        now=datetime(2026, 9, 8, 9, 6, tzinfo=UTC),
        in_pre_free_window=True,
        connected=True,
        export_session_active=False,
        planned_energy_kwh=0,
        vehicle_soc_percent=41,
        vehicle_soft_limit_percent=90,
        planned_start=None,
    )
    assert cleared.state == PreFreeSessionState()


def test_export_session_blocks_pre_free_latch():
    transition = advance_pre_free_session(
        PreFreeSessionState(),
        now=datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
        in_pre_free_window=True,
        connected=True,
        export_session_active=True,
        planned_energy_kwh=5,
        vehicle_soc_percent=40,
        vehicle_soft_limit_percent=90,
        planned_start=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
    )
    assert transition.phase == "not_eligible"
    assert transition.state.active is False


def test_contradictory_persisted_pre_free_phase_is_rejected():
    with pytest.raises(ValueError, match="frozen start"):
        advance_pre_free_session(
            PreFreeSessionState(active=True),
            now=datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
            in_pre_free_window=True,
            connected=True,
            export_session_active=False,
            planned_energy_kwh=5,
            vehicle_soc_percent=40,
            vehicle_soft_limit_percent=90,
            planned_start=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        )


def test_active_pre_free_current_jumps_directly_to_live_safe_whole_amp():
    base = PreFreeCurrentInputs(
        session_active=True,
        planned_energy_kwh=4,
        hours_until_free=2,
        voltage_v=230,
        phase_count=1,
        current_step_a=1,
        baseline_a=1,
        current_ceiling_a=15,
        vehicle_soc_percent=40,
        vehicle_soft_limit_percent=90,
    )
    assert plan_pre_free_current(base).current_a == 9
    assert plan_pre_free_current(replace(base, planned_energy_kwh=2)).current_a == 5


def test_three_phase_pre_free_extension_uses_configured_phase_count():
    decision = plan_pre_free_current(
        PreFreeCurrentInputs(
            session_active=True,
            planned_energy_kwh=6.9,
            hours_until_free=1,
            voltage_v=230,
            phase_count=3,
            current_step_a=1,
            baseline_a=1,
            current_ceiling_a=16,
            vehicle_soc_percent=40,
            vehicle_soft_limit_percent=90,
        )
    )
    assert decision.current_a == 11


def test_outside_branch_order_takes_maximum_of_active_backfill_and_spill():
    decision = select_outside_window_current(
        baseline_a=1,
        current_ceiling_a=15,
        charger_minimum_a=1,
        pre_free_active=True,
        pre_free_current_a=5,
        solar_spill_current_a=8,
    )
    assert decision.current_a == 8
    assert decision.phase == "pre_free_or_solar_spill"


def test_outside_branch_falls_back_to_protected_baseline():
    decision = select_outside_window_current(
        baseline_a=1,
        current_ceiling_a=15,
        charger_minimum_a=1,
        pre_free_active=False,
        pre_free_current_a=1,
        solar_spill_current_a=0,
    )
    assert decision.current_a == 1
    assert decision.phase == "protected_baseline"
