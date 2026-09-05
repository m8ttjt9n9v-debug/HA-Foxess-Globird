from __future__ import annotations

import pytest

from custom_components.home_energy_orchestrator.planner.ev import (
    EvAllowanceInputs,
    EvCommand,
    EvCurrentInputs,
    EvObservation,
    ev_charge_should_stop,
    plan_ev_allowance,
    plan_ev_current_target,
    plan_ev_start,
    plan_ev_stop,
)


def allowance_inputs(**changes) -> EvAllowanceInputs:
    values = {
        "free_window_active": True,
        "imported_kwh": 0.0,
        "cutoff_kwh": 49.0,
        "hours_remaining": 178 / 60,
        "grid_import_kw": 16.0,
        "ev_current_a": 0.0,
        "ev_voltage_v": 230.0,
        "ev_phase_count": 3,
        "physical_ceiling_a": 16.0,
        "effective_minimum_a": 6.0,
        "step_a": 1.0,
        "reserved_non_ev_kwh": 33.4,
    }
    values.update(changes)
    return EvAllowanceInputs(**values)


def test_h3_allowance_reserves_battery_and_house_then_limits_ev() -> None:
    decision = plan_ev_allowance(allowance_inputs())

    assert decision.session_allowed is True
    assert decision.ceiling_a == 7.0
    assert decision.ev_budget_remaining_kwh == 15.6
    assert decision.target_site_import_kw == 21.258
    assert decision.non_ev_import_kw == 16.0
    assert decision.reason == "allowance_limited"


def test_h3_allowance_releases_ev_after_battery_charge_finishes() -> None:
    decision = plan_ev_allowance(
        allowance_inputs(
            imported_kwh=31.0,
            hours_remaining=1.0,
            grid_import_kw=1.0,
            reserved_non_ev_kwh=1.0,
        )
    )

    assert decision.session_allowed is True
    assert decision.ceiling_a == 16.0
    assert decision.reason == "physical_ceiling"


def test_mangerton_single_phase_site_stays_at_physical_ceiling() -> None:
    decision = plan_ev_allowance(
        allowance_inputs(
            cutoff_kwh=49.0,
            hours_remaining=3.0,
            grid_import_kw=1.0,
            ev_voltage_v=230.0,
            ev_phase_count=1,
            physical_ceiling_a=32.0,
            reserved_non_ev_kwh=3.0,
        )
    )

    assert decision.session_allowed is True
    assert decision.ceiling_a == 32.0


def test_allowance_cutoff_and_missing_meter_fail_closed() -> None:
    exhausted = plan_ev_allowance(allowance_inputs(imported_kwh=49.0))
    missing = plan_ev_allowance(allowance_inputs(imported_kwh=None))

    assert exhausted.session_allowed is False
    assert exhausted.reason == "free_allowance_cutoff_reached"
    assert missing.session_allowed is False
    assert missing.reason == "allowance_meter_unavailable"


def test_configured_service_limit_caps_ev_below_energy_allowance() -> None:
    decision = plan_ev_allowance(
        allowance_inputs(
            imported_kwh=0.0,
            hours_remaining=1.0,
            grid_import_kw=10.0,
            service_current_a=20.0,
            site_phase_count=3,
            reserved_non_ev_kwh=0.0,
        )
    )

    # 19 A/phase service target is 13.11 kW, leaving 3.11 kW or 4 A/phase.
    assert decision.session_allowed is False
    assert decision.ceiling_a == 4.0
    assert decision.reason == "allowance_below_minimum_current"


def observation(**overrides: object) -> EvObservation:
    values = {
        "soc_percent": 29.0,
        "cable_connected": True,
        "limit_min_percent": 50.0,
        "limit_max_percent": 100.0,
    }
    values.update(overrides)
    return EvObservation(**values)


def test_start_sets_entity_minimum_then_turns_on() -> None:
    plan = plan_ev_start(40, observation())
    assert plan.reason == "ready"
    assert plan.commands == (
        EvCommand("set_charge_limit", 50.0),
        EvCommand("turn_on_charge"),
    )


def test_start_rejects_disconnected_or_unknown_vehicle() -> None:
    assert plan_ev_start(40, observation(cable_connected=False)).commands == ()
    assert plan_ev_start(40, observation(soc_percent=None)).reason == "soc_unknown"


def test_start_rejects_target_above_mapped_maximum() -> None:
    plan = plan_ev_start(90, observation(limit_max_percent=80))
    assert plan.commands == ()
    assert plan.reason == "target_exceeds_charge_limit"


def test_start_is_noop_at_or_above_target() -> None:
    assert plan_ev_start(40, observation(soc_percent=40)).reason == "target_reached"


def test_stop_always_turns_off_charge() -> None:
    assert plan_ev_stop(observation()).commands == (EvCommand("turn_off_charge"),)
    assert plan_ev_stop(observation(cable_connected=False)).commands == (
        EvCommand("turn_off_charge"),
    )


def test_stop_guard_handles_disconnect_and_target() -> None:
    assert ev_charge_should_stop(40, soc_percent=35, cable_connected=False, armed=True)
    assert ev_charge_should_stop(40, soc_percent=40, cable_connected=True, armed=True)
    assert not ev_charge_should_stop(40, soc_percent=None, cable_connected=True, armed=True)
    assert not ev_charge_should_stop(40, soc_percent=99, cable_connected=True, armed=False)


def current_inputs(**overrides: object) -> EvCurrentInputs:
    values = {
        "free_window_active": False,
        "cable_connected": True,
        "ceiling_a": 32.0,
        "protected_baseline_a": 0.0,
        "effective_minimum_a": 0.0,
        "requested_current_a": 10.0,
        "service_current_a": 32.0,
        "headroom_a": 1.0,
        "grid_average_a": 0.0,
        "grid_coverage_ratio": 1.0,
        "ev_average_a": 10.0,
        "ev_current_now_a": 10.0,
        "ev_feedback_source_valid": True,
        "elapsed_free_window_minutes": 20.0,
        "settle_minutes": 5.0,
    }
    values.update(overrides)
    return EvCurrentInputs(**values)


def test_current_planner_never_applies_limits_to_an_away_vehicle() -> None:
    decision = plan_ev_current_target(current_inputs(at_home=False))
    assert decision.reason == "away"
    assert decision.target_current_a == 0.0


def test_current_planner_uses_solar_spill_after_battery_is_full() -> None:
    decision = plan_ev_current_target(
        current_inputs(
            solar_spill_active=True,
            solar_surplus_kw=2.3,
            battery_soc_percent=100.0,
            solar_spill_soc_threshold=99.0,
            ev_voltage_v=230.0,
            ev_phase_count=1,
            ceiling_a=32.0,
        )
    )
    assert decision.reason == "solar_spill"
    assert decision.target_current_a == 10.0


def test_current_planner_backfills_before_free_window_with_requested_target() -> None:
    decision = plan_ev_current_target(
        current_inputs(
            pre_free_backfill_active=True,
            pre_free_backfill_current_a=4.0,
        )
    )
    assert decision.reason == "pre_free_backfill"
    assert decision.target_current_a == 4.0


def test_current_planner_fails_closed_when_home_presence_is_unknown() -> None:
    decision = plan_ev_current_target(current_inputs(home_presence_known=False))
    assert decision.reason == "home_presence_unknown"
    assert decision.target_current_a == 0.0


def test_zero_service_limit_disables_only_service_feedback_guard() -> None:
    decision = plan_ev_current_target(
        current_inputs(
            free_window_active=True,
            priority_ev=True,
            service_current_a=0.0,
            grid_average_a=20.0,
        )
    )

    assert decision.reason == "ev_priority"
    assert decision.target_current_a == 32.0


@pytest.mark.parametrize(
    "target, expected",
    [(-1, "target_soc_percent"), (101, "target_soc_percent"), (float("nan"), "target_soc_percent")],
)
def test_start_rejects_invalid_target(target: float, expected: str) -> None:
    with pytest.raises(ValueError, match=expected):
        plan_ev_start(target, observation())
