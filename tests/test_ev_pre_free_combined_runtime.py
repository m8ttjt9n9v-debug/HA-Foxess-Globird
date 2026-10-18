"""Adversarial sequential runtime traces for additive morning pre-free charging.

No real Home Assistant host or external service is contacted. Every trace uses
the existing runtime harness, coherent synthetic electrical reports and captured
service calls. The tests assert policy outcomes, not a copied implementation.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.planner.export import ExportPlan
from custom_components.home_energy_orchestrator.planner.export_session import ExportSessionState
from tests.test_ev_backfill_timing import _at, _charging, _fresh, _services, _site


def _scenario(hass, *, budget=2, **changes):
    config = {
        "solar_configured": True,
        "ev_morning_solar_enabled": True,
        "ev_morning_solar_reserve_soc_percent": 17,
        "ev_outside_battery_reserve_percent": 17,
        "ev_outside_inverter_percent": 50,
        "ev_daily_ready_time": "07:00:00",
        "free_charge_window_start": "12:01:00",
    }
    config.update(changes)
    coordinator, controller = _site(hass, **config)
    coordinator.data.available_after_reserve_kwh = budget + 1
    coordinator.learning_remaining_kwh = 1
    coordinator.active_controller.export_plan = ExportPlan(budget, budget, 1, "ready")
    coordinator.snapshot = replace(
        coordinator.snapshot, battery_soc=25, grid_power_kw=0, house_load_kw=0.5
    )
    hass.states.async_set("sensor.site_battery_soc", "25", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.car_soc", "44", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.car_energy", "26.4", {"unit_of_measurement": "kWh"})
    _power(hass, coordinator, _at(11))
    return coordinator, controller


def _power(hass, coordinator, now, *, surplus=2.5, current=0, house=0.5, grid=0):
    """PV minus house is reconstructed once from physical EV/grid/battery flows."""
    _fresh(coordinator, now, grid_kw=grid, current_a=current)
    phases = int(coordinator.config["ev_phase_count"])
    ev_kw = current * 230 * phases / 1000
    coordinator.telemetry = replace(
        coordinator.telemetry,
        battery_power=replace(coordinator.telemetry.battery_power, value=surplus - ev_kw + grid),
        house_load=replace(coordinator.telemetry.house_load, value=house),
    )
    coordinator.snapshot = replace(coordinator.snapshot, grid_power_kw=grid, house_load_kw=house)
    hass.states.async_set("sensor.car_actual_current", str(current), {"unit_of_measurement": "A"})


def _assert_single_ev_writer(calls):
    assert all(domain in {"number", "switch"} for domain, _, _ in calls)
    assert all(
        data["entity_id"] in {"number.car_limit", "number.car_current", "switch.car_charge"}
        for _, _, data in calls
    )


async def test_user_arrival_scenario_starts_combined_before_legacy_latest_start(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))

    assert controller.pre_free_session.active
    assert controller.pre_free_plan.planned_energy_kwh == 2
    assert controller.target_current_a == 6
    assert controller.decision_phase == "pre_free_combined"
    assert not controller.daily_backfill_active
    assert controller.outside_stage_selection.stage == "pre_free"
    assert calls[-1][:2] == ("switch", "turn_on")
    _assert_single_ev_writer(calls)


@pytest.mark.parametrize("phases,expected", [(1, 16), (3, 6)])
async def test_same_power_policy_uses_configured_single_or_three_phase_conversion(
    hass, phases, expected
):
    calls = _services(hass)
    _, controller = _scenario(hass, ev_phase_count=phases, site_phase_count=phases)
    await controller.async_reconcile(_at(11))

    assert controller.target_current_a == expected
    assert controller.decision_phase == "pre_free_combined"
    _assert_single_ev_writer(calls)


async def test_house_load_reduces_available_solar_not_the_battery_budget_twice(hass):
    _services(hass)
    coordinator, controller = _scenario(hass)
    _power(hass, coordinator, _at(11), surplus=2, house=1)
    await controller.async_reconcile(_at(11))

    assert controller.pre_free_plan.planned_energy_kwh == 2
    assert controller.target_current_a == 5


async def test_solar_below_charger_minimum_can_start_with_protected_battery_contribution(hass):
    _services(hass)
    coordinator, controller = _scenario(hass, budget=4.2)
    hass.states.async_set("number.car_current", "6", {"min": 6, "max": 16, "step": 1})
    _power(hass, coordinator, _at(11), surplus=0.1)
    await controller.async_reconcile(_at(11))

    assert controller.morning_solar.phase == "below_charger_minimum"
    assert controller.pre_free_session.active
    assert controller.target_current_a == 6
    assert controller.decision_phase == "pre_free_combined"


async def test_combined_rate_below_physical_minimum_does_not_invent_a_start(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    hass.states.async_set("number.car_current", "6", {"min": 6, "max": 16, "step": 1})
    _power(hass, coordinator, _at(11), surplus=0.1)
    await controller.async_reconcile(_at(11))

    assert not controller.pre_free_session.active
    assert controller.target_current_a in (None, 0)
    assert not any(service == "turn_on" for _, service, _ in calls)


async def test_no_solar_at_first_arrival_preserves_legacy_latest_start(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    _power(hass, coordinator, _at(11), surplus=0)
    await controller.async_reconcile(_at(11))

    assert not controller.pre_free_session.active
    assert controller.pre_free_phase == "waiting_latest_start"
    assert controller.target_current_a in (None, 0)
    assert not any(service == "turn_on" for _, service, _ in calls)


async def test_cloud_after_start_retains_one_owner_and_ten_minute_update_cadence(hass):
    _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    _power(hass, coordinator, _at(11, 1), surplus=0, current=6)
    await controller.async_reconcile(_at(11, 1))
    assert controller.pre_free_session.active
    assert controller.target_current_a == 6
    assert controller.decision_phase == "pre_free_combined"

    # The moving deadline crosses a current step at 11:04. That must not reset
    # the combined policy's ten-minute opportunity to adopt its latest target.
    # Existing standalone measured-solar policies retain their stability filter.
    for minute in range(2, 10):
        _power(hass, coordinator, _at(11, minute), surplus=0, current=6)
        await controller.async_reconcile(_at(11, minute))
        assert controller.target_current_a == 6
    _power(hass, coordinator, _at(11, 10), surplus=0, current=6)
    await controller.async_reconcile(_at(11, 10))
    assert controller.pre_free_session.active
    assert controller.target_current_a == 3
    assert not controller.daily_backfill_active


async def test_cloud_edge_reversals_do_not_chatter_current_commands(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    count = len(calls)
    for minute, solar in [(1, 1), (3, 2.5), (5, 1), (7, 2.5), (9, 1)]:
        _power(hass, coordinator, _at(11, minute), surplus=solar, current=6)
        await controller.async_reconcile(_at(11, minute))
        assert controller.target_current_a == 6
    assert not any(
        data.get("entity_id") == "number.car_current" for _, _, data in calls[count:]
    )


@pytest.mark.parametrize("field", ["house_load", "grid_power", "battery_power"])
@pytest.mark.parametrize("loss", ["stale", "missing"])
async def test_lost_evidence_cannot_fall_through_to_legacy_on_second_cycle(hass, field, loss):
    calls = _services(hass)
    coordinator, controller = _scenario(hass, ev_pre_free_backfill_timing="conservative")
    await controller.async_reconcile(_at(11))
    assert controller.target_current_a == 6
    _charging(hass, 6)

    # Well after the old latest start, neither the active combined latch nor a
    # fresh legacy fallback may bypass the same lost electrical/house evidence.
    for minute in (55, 56):
        _power(hass, coordinator, _at(11, minute), current=6)
        sample = getattr(coordinator.telemetry, field)
        invalid = replace(
            sample,
            fresh=False,
            valid=loss != "missing",
            value=sample.value if loss == "stale" else None,
            sources=tuple(
                replace(source, updated_at=_at(10)) for source in sample.sources
            ),
            reason=f"source_{loss}",
        )
        coordinator.telemetry = replace(coordinator.telemetry, **{field: invalid})
        before = len(calls)
        await controller.async_reconcile(_at(11, minute))
        # House-budget authority is needed for battery spend. Independent
        # measured solar capture may still use its coherent grid+battery
        # balance; losing either of those electrical inputs cannot do so.
        maximum_a = 3 if field == "house_load" else 0
        assert controller.target_current_a == maximum_a
        assert not controller.pre_free_session.active
        assert controller.measured_solar_adjustment.battery_current_a is None
        assert not any(service == "turn_on" for _, service, _ in calls[before:])
        assert not any(
            data.get("entity_id") == "number.car_current" and data["value"] > maximum_a
            for _, _, data in calls[before:]
        )


@pytest.mark.parametrize("baseline", [0, 1])
async def test_reserve_cutoff_immediately_discards_combined_hold(hass, baseline):
    calls = _services(hass)
    coordinator, controller = _scenario(hass, ev_protected_baseline_a=baseline)
    await controller.async_reconcile(_at(11))
    _charging(hass, controller.target_current_a)
    _power(hass, coordinator, _at(11, 1), current=6)
    coordinator.snapshot = replace(coordinator.snapshot, battery_soc=17)
    hass.states.async_set("sensor.site_battery_soc", "17", {"unit_of_measurement": "%"})
    before = len(calls)
    await controller.async_reconcile(_at(11, 1))

    assert controller.target_current_a == baseline
    assert not controller.pre_free_session.active
    assert controller.measured_solar_adjustment.battery_current_a is None
    if baseline == 0:
        assert calls[-1][:2] == ("switch", "turn_off")
    else:
        assert not any(service == "turn_off" for _, service, _ in calls[before:])


async def test_ev_hard90_target_ends_combined_without_waiting_for_solar_cadence(hass):
    _services(hass)
    coordinator, controller = _scenario(hass, ev_free_window_charge_limit_percent=100)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
    _power(hass, coordinator, _at(11, 1), current=6)
    await controller.async_reconcile(_at(11, 1))

    assert controller.target_current_a == 0
    assert controller.target_limit_percent <= 90
    assert not controller.pre_free_session.active


async def test_large_solar_still_honours_total_outside_cap(hass):
    _services(hass)
    coordinator, controller = _scenario(hass)
    _power(hass, coordinator, _at(11), surplus=45)
    await controller.async_reconcile(_at(11))

    assert controller.target_current_a == 10
    assert controller.target_current_a * 0.69 <= 7.5
    assert controller.decision_phase == "pre_free_combined"


async def test_current_steps_apply_once_to_combined_rate(hass):
    _services(hass)
    coordinator, controller = _scenario(hass)
    hass.states.async_set("number.car_current", "2", {"min": 2, "max": 16, "step": 2})
    _power(hass, coordinator, _at(11), surplus=1.5)
    await controller.async_reconcile(_at(11))

    assert controller.target_current_a == 4
    assert controller.target_current_a % 2 == 0
    assert controller.decision_phase == "pre_free_combined"


async def test_fractional_current_step_does_not_lose_a_step_to_float_flooring(hass):
    _services(hass)
    _, controller = _scenario(hass)
    hass.states.async_set("number.car_current", "1", {"min": 1, "max": 16, "step": 0.1})
    await controller.async_reconcile(_at(11))

    assert controller.target_current_a == 6.4
    assert controller.decision_phase == "pre_free_combined"


async def test_arrival_cannot_validate_retained16_as_solar(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    _charging(hass, 16)
    _power(hass, coordinator, _at(11), current=16)
    await controller.async_reconcile(_at(11))

    assert controller.morning_solar.reconstructed_surplus_kw == pytest.approx(2.5)
    assert controller.target_current_a == 6
    assert not any(
        data.get("entity_id") == "number.car_current" and data.get("value") == 16
        for _, _, data in calls
    )
    assert any(
        data.get("entity_id") == "number.car_current" and data.get("value") == 6
        for _, _, data in calls
    )


@pytest.mark.parametrize(
    "entity,value",
    [
        ("device_tracker.car", "not_home"),
        ("device_tracker.car", "unknown"),
        ("binary_sensor.car_cable", "off"),
        ("binary_sensor.car_cable", "unknown"),
    ],
)
async def test_home_and_cable_must_both_be_qualified_before_positive_write(hass, entity, value):
    calls = _services(hass)
    _, controller = _scenario(hass)
    hass.states.async_set(entity, value)
    await controller.async_reconcile(_at(11))
    assert calls == []


async def test_home_then_cable_event_starts_only_after_both_arrive(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    hass.states.async_set("device_tracker.car", "not_home")
    hass.states.async_set("binary_sensor.car_cable", "off")
    await controller.async_reconcile(_at(10, 59))
    assert calls == []
    hass.states.async_set("device_tracker.car", "home")
    _power(hass, coordinator, _at(11))
    await controller.async_reconcile(_at(11))
    assert calls == []
    hass.states.async_set("binary_sensor.car_cable", "on")
    _power(hass, coordinator, _at(11, 1))
    await controller.async_reconcile(_at(11, 1))
    assert controller.target_current_a == 6
    assert calls[-1][:2] == ("switch", "turn_on")


async def test_ready_by_active_session_retains_exclusive_priority(hass):
    _services(hass)
    coordinator, controller = _scenario(hass)
    _power(hass, coordinator, _at(6, 50))
    await controller.async_reconcile(_at(6, 50))

    assert controller.daily_backfill_active
    assert not controller.pre_free_session.active
    assert controller.decision_phase == "daily_ready_backfill"
    assert controller.measured_solar_adjustment.battery_current_a is None


async def test_paid_full_remains_explicit_higher_priority(hass):
    calls = _services(hass)
    _, controller = _scenario(hass, ev_charge_to_full_enabled=True)
    await controller.async_reconcile(_at(11))

    assert controller.target_current_a == 16
    assert controller.target_limit_percent == 100
    assert controller.decision_phase == "charge_to_full_paid_grid_override"
    assert controller.outside_stage_selection.stage == "charge_to_full"
    _assert_single_ev_writer(calls)


async def test_conservative_overnight_darkness_does_not_gain_early_battery_permission(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass, ev_pre_free_backfill_timing="conservative")
    _power(hass, coordinator, _at(2), surplus=0)
    await controller.async_reconcile(_at(2))

    assert not controller.pre_free_session.active
    assert not controller.daily_backfill_active
    assert controller.target_current_a in (None, 0)
    assert not any(service == "turn_on" for _, service, _ in calls)


async def test_pending_stop_cannot_overrule_free_window_successor(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    controller.daily_backfill_stop_pending = True
    controller.daily_backfill_stop_attempts = 4
    _power(hass, coordinator, _at(12, 1), current=6)
    before = len(calls)
    await controller.async_reconcile(_at(12, 1))

    assert controller.target_current_a == 16
    assert not controller.pre_free_session.active
    assert not controller.daily_backfill_stop_pending
    assert not any(service == "turn_off" for _, service, _ in calls[before:])


async def test_restart_retains_combined_context_and_cloud_hold(hass):
    _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    await controller._async_save(_at(11))
    restarted = ActiveEvController(hass, coordinator)
    await restarted._async_restore()
    assert restarted.measured_solar_adjustment.battery_current_a is not None
    assert restarted.pre_free_session.active
    _power(hass, coordinator, _at(11, 1), surplus=0, current=6)
    await restarted.async_reconcile(_at(11, 1))

    assert restarted.target_current_a == 6
    assert restarted.decision_phase == "pre_free_combined"
    assert restarted.pre_free_session.active


async def test_unplug_replug_replans_only_current_protected_budget(hass):
    _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("sensor.car_charging", "disconnected")
    hass.states.async_set("switch.car_charge", "off")
    _power(hass, coordinator, _at(11, 1))
    await controller.async_reconcile(_at(11, 1))
    assert not controller.pre_free_session.active

    # The old 2 kWh export plan is intentionally retained. Fresh protection
    # leaves only 0.5 kWh; reconnect must not replay the previous 6 A budget.
    coordinator.data.available_after_reserve_kwh = 1.5
    hass.states.async_set("binary_sensor.car_cable", "on")
    hass.states.async_set("sensor.car_charging", "stopped")
    _power(hass, coordinator, _at(11, 2))
    await controller.async_reconcile(_at(11, 2))

    assert controller.pre_free_plan.planned_energy_kwh == 0.5
    assert controller.target_current_a == 4
    assert controller.decision_phase == "pre_free_combined"


async def test_live_protected_budget_loss_curtails_before_ten_minutes(hass):
    _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    coordinator.data.available_after_reserve_kwh = 1.5
    _power(hass, coordinator, _at(11, 1), current=6)
    await controller.async_reconcile(_at(11, 1))

    assert controller.pre_free_plan.planned_energy_kwh == 0.5
    assert controller.target_current_a == 4
    assert controller.decision_phase == "pre_free_combined"


async def test_service_headroom_loss_curtails_a_held_current_immediately(hass):
    _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    _power(hass, coordinator, _at(11, 1), current=6)
    coordinator.telemetry = replace(
        coordinator.telemetry,
        site_grid_current=replace(coordinator.telemetry.site_grid_current, value=81),
    )
    await controller.async_reconcile(_at(11, 1))

    assert controller.target_current_a == 4
    assert controller.target_current_a < 6


async def test_zero_service_headroom_cannot_fall_back_to_positive_solar_candidate(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    assert controller.target_current_a == 6
    _charging(hass, 6)
    _power(hass, coordinator, _at(11, 1), current=6)
    coordinator.telemetry = replace(
        coordinator.telemetry,
        site_grid_current=replace(coordinator.telemetry.site_grid_current, value=86),
    )
    before = len(calls)
    await controller.async_reconcile(_at(11, 1))

    assert controller.target_current_a == 0
    assert controller.morning_solar.current_a == 0
    assert not controller.pre_free_session.active
    assert controller.measured_solar_adjustment.battery_current_a is None
    assert calls[-1][:2] == ("switch", "turn_off")
    assert not any(service == "turn_on" for _, service, _ in calls[before:])


async def test_solar_above_minimum_cannot_bypass_service_headroom_below_minimum(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    hass.states.async_set("number.car_current", "6", {"min": 6, "max": 16, "step": 1})
    _power(hass, coordinator, _at(11), surplus=5)
    await controller.async_reconcile(_at(11))
    assert controller.target_current_a == 10
    _charging(hass, 10)
    hass.states.async_set("number.car_current", "10", {"min": 6, "max": 16, "step": 1})
    _power(hass, coordinator, _at(11, 1), surplus=5, current=10)
    coordinator.telemetry = replace(
        coordinator.telemetry,
        site_grid_current=replace(coordinator.telemetry.site_grid_current, value=86),
    )
    before = len(calls)
    await controller.async_reconcile(_at(11, 1))

    # Raw solar alone supports more than 6 A, but available service headroom
    # is only 3 A. It cannot be rounded up to the charger's physical minimum.
    assert controller.target_current_a == 0
    assert controller.morning_solar.current_a == 0
    assert not controller.pre_free_session.active
    assert calls[-1][:2] == ("switch", "turn_off")
    assert not any(
        data.get("entity_id") == "number.car_current" and data["value"] > 3
        for _, _, data in calls[before:]
    )


@pytest.mark.parametrize("headroom", [1, 2])
async def test_zero_budget_solar_successor_obeys_fresh_tiny_service_cap_on_every_cycle(
    hass, headroom
):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    coordinator.data.available_after_reserve_kwh = 1
    for minute, actual in [(1, 6), (2, headroom)]:
        _power(hass, coordinator, _at(11, minute), current=actual)
        coordinator.telemetry = replace(
            coordinator.telemetry,
            site_grid_current=replace(
                coordinator.telemetry.site_grid_current,
                value=79 - headroom + actual,
            ),
        )
        before = len(calls)
        await controller.async_reconcile(_at(11, minute))

        assert controller.target_current_a == headroom
        assert not controller.pre_free_session.active
        assert controller.outside_stage_selection.stage == "morning_solar"
        assert controller.measured_solar_adjustment.battery_current_a is None
        assert not any(
            data.get("entity_id") == "number.car_current" and data["value"] > headroom
            for _, _, data in calls[before:]
        )


async def test_reduced_percentage_cap_curtails_a_held_current_immediately(hass):
    _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    coordinator.update_config_value("ev_outside_inverter_percent", 20)
    _power(hass, coordinator, _at(11, 1), current=6)
    await controller.async_reconcile(_at(11, 1))

    assert controller.target_current_a == 4
    assert controller.target_current_a * 0.69 <= 3


async def test_cap_below_physical_minimum_cannot_round_back_up_to_unsafe_current(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass, budget=4.2)
    hass.states.async_set("number.car_current", "6", {"min": 6, "max": 16, "step": 1})
    _power(hass, coordinator, _at(11), surplus=0.1)
    await controller.async_reconcile(_at(11))
    assert controller.target_current_a == 6
    _charging(hass, 6)
    hass.states.async_set("number.car_current", "6", {"min": 6, "max": 16, "step": 1})
    coordinator.update_config_value("ev_outside_inverter_percent", 20)
    _power(hass, coordinator, _at(11, 1), surplus=0.1, current=6)
    before = len(calls)
    await controller.async_reconcile(_at(11, 1))

    assert controller.target_current_a == 0
    assert not any(
        data.get("entity_id") == "number.car_current" and data["value"] > 4
        for _, _, data in calls[before:]
    )


async def test_safety_lock_during_combined_session_prevents_any_later_service(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    coordinator.update_config_value("rehearsal_mode", True)
    before = len(calls)
    _power(hass, coordinator, _at(11, 1), surplus=40, current=6)
    await controller.async_reconcile(_at(11, 1))
    assert calls[before:] == []
    assert controller.gate_status == "safety_locked"


async def test_export_session_never_gains_combined_battery_owner(hass):
    _services(hass)
    coordinator, controller = _scenario(hass)
    coordinator.active_controller.export_session = ExportSessionState(phase="active")
    await controller.async_reconcile(_at(11))
    assert not controller.pre_free_session.active
    assert controller.decision_phase != "pre_free_combined"


async def test_disabled_morning_policy_retains_existing_late_pre_free_behaviour(hass):
    _services(hass)
    coordinator, controller = _scenario(hass, ev_morning_solar_enabled=False)
    await controller.async_reconcile(_at(11))
    assert not controller.pre_free_session.active
    _power(hass, coordinator, _at(11, 55))
    await controller.async_reconcile(_at(11, 55))
    assert controller.pre_free_session.active
    assert controller.target_current_a == 10
    assert controller.decision_phase == "pre_free_backfill"


async def test_no_budget_cannot_turn_solar_capture_into_battery_permission(hass):
    _services(hass)
    coordinator, controller = _scenario(hass, budget=0)
    await controller.async_reconcile(_at(11))

    assert not controller.pre_free_session.active
    assert controller.target_current_a == 3
    assert controller.outside_stage_selection.stage == "morning_solar"
    assert controller.measured_solar_adjustment.battery_current_a is None


async def test_grid_import_immediately_revokes_combined_battery_permission(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    _power(hass, coordinator, _at(11, 1), current=6, grid=2)
    before = len(calls)
    await controller.async_reconcile(_at(11, 1))

    assert not controller.pre_free_session.active
    assert controller.target_current_a == 3
    assert controller.measured_solar_adjustment.battery_current_a is None
    assert controller.outside_stage_selection.stage == "morning_solar"
    assert not any(service == "turn_on" for _, service, _ in calls[before:])
    assert not any(
        data.get("entity_id") == "number.car_current" and data["value"] > 3
        for _, _, data in calls[before:]
    )


async def test_budget_zero_with_solar_cannot_inherit_held_battery_permission(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    coordinator.data.available_after_reserve_kwh = 1
    for minute, actual in [(1, 6), (2, 3)]:
        _power(hass, coordinator, _at(11, minute), current=actual)
        before = len(calls)
        await controller.async_reconcile(_at(11, minute))
        assert not controller.pre_free_session.active
        assert controller.target_current_a == 3
        assert controller.measured_solar_adjustment.battery_current_a is None
        assert controller.outside_stage_selection.stage == "morning_solar"
        assert not any(
            data.get("entity_id") == "number.car_current" and data["value"] > 3
            for _, _, data in calls[before:]
        )


async def test_tiny_reconnect_gap_does_not_replay_old_solar_hold(hass):
    _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _charging(hass, 6)
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("sensor.car_charging", "disconnected")
    hass.states.async_set("switch.car_charge", "off")
    unplug_at = _at(11) + timedelta(seconds=3)
    _power(hass, coordinator, unplug_at)
    await controller.async_reconcile(unplug_at)
    assert not controller.pre_free_session.active
    coordinator.data.available_after_reserve_kwh = 1.5
    hass.states.async_set("binary_sensor.car_cable", "on")
    hass.states.async_set("sensor.car_charging", "stopped")
    reconnect_at = _at(11) + timedelta(seconds=11)
    _power(hass, coordinator, reconnect_at)
    await controller.async_reconcile(reconnect_at)

    assert controller.target_current_a == 4
    assert controller.pre_free_plan.planned_energy_kwh == 0.5
    assert controller.decision_phase == "pre_free_combined"
