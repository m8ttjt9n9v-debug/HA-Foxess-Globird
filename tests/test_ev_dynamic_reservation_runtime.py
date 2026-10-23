"""Current-SoC reservation through the existing EV and export controllers.

All vehicles, native frames and electrical readings are synthetic local
fixtures. No provider is loaded and no installation or physical device is
contacted. Reservation arithmetic is exercised through the runtime facade;
only service transport is simulated.
"""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.foxess_adapter import FoxessEntityMap
from custom_components.home_energy_orchestrator.foxess_observation_adapter import (
    capture_foxess_feedback,
)
from custom_components.home_energy_orchestrator.planner.ev_before_export import (
    EvBeforeExportRecovery,
)
from custom_components.home_energy_orchestrator.planner.export import ExportPlan
from custom_components.home_energy_orchestrator.planner.export_session import ExportSessionState
from custom_components.home_energy_orchestrator.planner.foxess_export_policy import (
    evaluate_foxess_export_policy,
)
from tests.test_ev_backfill_timing import _at, _fresh, _site
from tests.test_ev_backfill_timing import _services as _generic_services
from tests.test_ev_before_export_charging import _foxess
from tests.test_ev_before_export_source_clocks import _native
from tests.test_ev_before_export_source_clocks import (
    native_provider_cleanup as native_provider_cleanup,
)
from tests.test_ev_before_export_source_clocks import utc_clock as utc_clock
from tests.test_zerohero_active import _loaded_controller


def _publish_vehicle(hass, rig, *, soc=35, home=True, connected=True, actual=0, charging=False):
    rig.provider.data.update({
        "state": "online",
        "charge_state_timestamp": rig.now.timestamp() * 1000,
        "charge_state_usable_battery_level": soc,
        "charge_state_charger_actual_current": actual,
        "charge_state_charging_state": (
            "Charging" if charging else "Stopped" if connected else "Disconnected"
        ),
        "charge_state_conn_charge_cable": "IEC" if connected else "<invalid>",
    })
    hass.states.async_set("sensor.car_soc", str(soc), {"unit_of_measurement": "%"})
    hass.states.async_set("device_tracker.car", "home" if home else "not_home", force_update=True)
    hass.states.async_set("binary_sensor.car_cable", "on" if connected else "off",
                          force_update=True)
    hass.states.async_set("sensor.car_charging", (
        "charging" if charging else "stopped" if connected else "disconnected"
    ), force_update=True)
    hass.states.async_set("sensor.car_actual_current", str(actual), {"unit_of_measurement": "A"})
    hass.states.async_set("switch.car_charge", "on" if charging else "off", force_update=True)
    rig.coordinator.snapshot = replace(rig.coordinator.snapshot, ev_soc=soc)


async def _rig(hass, freezer, **changes):
    rig = _native(hass, freezer, old_seconds=0)
    config = {
        "ev_reservation_mode": "dynamic",
        "ev_before_export_enabled": True,
        "ev_before_export_soc_target_percent": 40,
        "ev_before_export_soc_buffer_percent": 1,
        "ev_charge_efficiency_percent": 100,
        "ev_daily_backfill_energy_kwh": 7,
        "ev_free_window_charge_limit_percent": 90,
        "bonus_window_start": "15:00:00",
        "bonus_window_end": "17:00:00",
        "force_discharge_finish": "17:01:00",
    }
    config.update(changes)
    for key, value in config.items():
        rig.coordinator.update_config_value(key, value)
    rig.fox = _loaded_controller(hass, rig.coordinator)
    rig.coordinator.active_controller = rig.fox
    await rig.fox.manual.async_restore_handoff()
    await rig.controller._async_restore()
    _publish_vehicle(hass, rig)
    _fresh(rig.coordinator, rig.now)
    return rig


def _context(hass, rig, *, price=False):
    feedback = capture_foxess_feedback(hass, FoxessEntityMap(
        "select.foxess_mode", "number.foxess_charge", "number.foxess_discharge",
    ))
    context = rig.fox._export_context(feedback, rig.now)
    if price:
        context = replace(
            context, requested_enabled=False, price_export_enabled=True,
            price_interval_start=rig.now, price_interval_end=rig.now + timedelta(minutes=5),
        )
    return context


def _budget(rig, *, available=24, house=5, keepalive=0):
    return rig.controller.reservation_budget(
        rig.now, available_ac_kwh=available, protected_house_kwh=house, keepalive_kwh=keepalive,
    )


def _services(hass, monkeypatch, rig):
    calls = []

    async def apply(call):
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            entity = entity[0]
        value = (
            call.data.get("value", call.data.get("option"))
            if call.domain in {"number", "select"}
            else "on" if call.service == "turn_on" else "off"
        )
        calls.append((entity, value))
        old = hass.states.get(entity)
        hass.states.async_set(entity, str(value), dict(old.attributes), force_update=True)
        # Match the existing native transport: acknowledgements update only
        # the requested cache field, never actual current or measurement time.
        field = {
            "number.car_current": "charge_state_charge_current_request",
            "number.car_limit": "charge_state_charge_limit_soc",
        }.get(entity)
        if field is not None:
            rig.provider.data[field] = value

    async def no_wait(_seconds):
        return None

    for domain, service in (
        ("number", "set_value"), ("select", "select_option"),
        ("switch", "turn_on"), ("switch", "turn_off"),
    ):
        hass.services.async_register(domain, service, apply)
    monkeypatch.setattr("custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep",
                        no_wait)
    return calls


@pytest.mark.parametrize("home,connected", [(False, False), (True, False)])
@pytest.mark.parametrize("price", [False, True])
async def test_unplugged_below_minimum_reserves_only_its_shortfall_and_permits_balance(
    hass, freezer, home, connected, price,
):
    rig = await _rig(hass, freezer)
    _publish_vehicle(hass, rig, home=home, connected=connected)
    budget = _budget(rig)
    assert rig.controller.dynamic_reservation_selected()
    assert budget.valid and budget.requested_reservation_kwh == pytest.approx(3.6)
    assert budget.exportable_kwh == pytest.approx(15.4)
    assert not rig.controller.dynamic_topup_requested(rig.now)
    context = _context(hass, rig, price=price)
    policy = evaluate_foxess_export_policy(context)
    assert not context.before_export_enabled
    assert context.protected_ev_kwh == pytest.approx(3.6)
    assert policy.export_plan.sellable_energy_kwh == pytest.approx(15.4)
    assert policy.before_export_decision.export_allowed
    assert policy.eligible
    assert rig.fox._ev_before_export_handoff_ready(rig.now)


@pytest.mark.parametrize("soc,expected", [
    (39.9, 0.66), (40, 0.6), (40.1, 0.54), (40.9, 0.06), (41, 0), (41.1, 0),
])
async def test_runtime_budget_at_minimum_and_release_uses_live_soc_not_fixed_quota(
    hass, freezer, soc, expected,
):
    rig = await _rig(hass, freezer)
    _publish_vehicle(hass, rig, soc=soc)
    assert _budget(rig).requested_reservation_kwh == pytest.approx(expected)
    assert rig.controller.daily_backfill_protection_kwh(rig.now) == pytest.approx(expected)


@pytest.mark.parametrize("old_quota,delivered", [(0, 0), (7, 0), (7, 7), (50, 100)])
async def test_dynamic_does_not_add_or_subtract_fixed_ready_cycle_delivery(
    hass, freezer, old_quota, delivered,
):
    rig = await _rig(hass, freezer, ev_daily_backfill_energy_kwh=old_quota)
    rig.controller.daily_backfill_delivered_kwh = delivered
    rig.controller.daily_backfill_cycle_ready_at = rig.controller._daily_ready_cycle(rig.now)[0]
    assert _budget(rig).requested_reservation_kwh == pytest.approx(3.6)
    assert rig.controller.daily_backfill_protection_kwh(rig.now) == pytest.approx(3.6)


@pytest.mark.parametrize("house_mode", ["auto", "home", "away"])
@pytest.mark.parametrize("vehicle_home", [False, True])
async def test_automatic_or_manual_house_presence_is_not_extended_away(
    hass, freezer, house_mode, vehicle_home,
):
    rig = await _rig(hass, freezer, house_occupancy_mode=house_mode)
    _publish_vehicle(hass, rig, home=vehicle_home, connected=False)
    assert _budget(rig).requested_reservation_kwh == pytest.approx(3.6)


async def test_switching_priority_off_does_not_resurrect_the_old_fixed_reservation(hass, freezer):
    rig = await _rig(hass, freezer, ev_daily_backfill_energy_kwh=12)
    assert _budget(rig).requested_reservation_kwh == pytest.approx(3.6)
    rig.coordinator.update_config_value("ev_before_export_enabled", False)
    assert not rig.controller.dynamic_reservation_selected()
    assert _budget(rig).requested_reservation_kwh == 0
    assert _budget(rig).exportable_kwh == 19
    assert rig.controller.daily_backfill_protection_kwh(rig.now) == 0
    # With its explicit priority off, unavailable SoC cannot restore that
    # disabled reservation through either the fixed or learned alternative.
    hass.states.async_set("sensor.car_soc", "unavailable")
    assert _budget(rig).valid and _budget(rig).requested_reservation_kwh == 0


@pytest.mark.parametrize("fault", [
    "soc_unavailable", "soc_negative", "soc_over_100", "soc_restored", "soc_mismatch",
    "expired_frame", "future_frame", "missing_frame", "provider_failed", "provider_unloaded",
    "capacity_missing", "capacity_invalid",
])
@pytest.mark.parametrize("price", [False, True])
async def test_invalid_dynamic_evidence_cannot_release_normal_or_price_export(
    hass, freezer, fault, price,
):
    rig = await _rig(hass, freezer)
    _publish_vehicle(hass, rig, home=False, connected=False)
    if fault.startswith("soc_"):
        if fault == "soc_mismatch":
            rig.provider.data["charge_state_usable_battery_level"] = 36
        else:
            value = {"soc_unavailable": "unavailable", "soc_negative": "-1",
                     "soc_over_100": "101", "soc_restored": "35"}[fault]
            attrs = {"unit_of_measurement": "%"}
            if fault == "soc_restored":
                attrs["restored"] = True
            hass.states.async_set("sensor.car_soc", value, attrs)
    elif fault in {"expired_frame", "future_frame"}:
        rig.provider.data["charge_state_timestamp"] = (
            rig.now + timedelta(seconds=-91 if fault == "expired_frame" else 1)
        ).timestamp() * 1000
    elif fault == "missing_frame":
        rig.provider.data.pop("charge_state_timestamp")
    elif fault == "provider_failed":
        rig.provider.last_update_success = False
    elif fault == "provider_unloaded":
        rig.entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    else:
        rig.coordinator.update_config_value("ev_capacity_fallback_kwh", (
            0 if fault == "capacity_missing" else float("nan")
        ))
    budget = _budget(rig)
    assert not budget.valid
    assert budget.exportable_kwh == budget.ev_available_kwh == 0
    assert rig.controller.daily_backfill_protection_kwh(rig.now) is None
    policy = evaluate_foxess_export_policy(_context(hass, rig, price=price))
    assert not policy.eligible and not policy.should_advance
    if price:
        assert policy.finish_requested and not policy.session_window_active
    else:
        assert not policy.effective_enabled
    assert policy.export_plan is None or policy.export_plan.planned_export_energy_kwh == 0


async def test_home_connected_recovery_blocks_export_even_when_some_energy_is_unreserved(
    hass, freezer,
):
    rig = await _rig(hass, freezer)
    assert _budget(rig).exportable_kwh > 0
    assert rig.controller.dynamic_topup_requested(rig.now)
    assert not rig.fox._ev_before_export_handoff_ready(rig.now)
    assert rig.fox.ev_export_handoff_reason == "dynamic_ev_recovery_requested"


@pytest.mark.parametrize("location_mode,tracker_home,requested", [
    ("home", False, True), ("away", True, False),
])
async def test_return_recovery_obeys_existing_explicit_home_control_selection(
    hass, freezer, location_mode, tracker_home, requested,
):
    rig = await _rig(hass, freezer, ev_location_mode=location_mode)
    _publish_vehicle(hass, rig, home=tracker_home)
    assert rig.controller.dynamic_topup_requested(rig.now) is requested


async def test_reservation_does_not_remove_physical_handoff_after_ev_target_is_met(
    hass, freezer,
):
    rig = await _rig(hass, freezer)
    _publish_vehicle(hass, rig, soc=41, actual=8, charging=True)
    assert not rig.controller.dynamic_topup_requested(rig.now)
    assert _budget(rig).requested_reservation_kwh == 0
    assert evaluate_foxess_export_policy(_context(hass, rig)).eligible
    assert not rig.fox._ev_before_export_handoff_ready(rig.now)
    _publish_vehicle(hass, rig, soc=41, actual=0, charging=False)
    assert rig.fox._ev_before_export_handoff_ready(rig.now)


@pytest.mark.parametrize("soc,pending,requested", [
    (39.9, False, True), (40, False, False), (40.9, False, False),
    (40, True, True), (40.9, True, True), (41, True, False), (41.1, False, False),
])
async def test_return_topup_reuses_existing_recovery_start_and_release_thresholds(
    hass, freezer, soc, pending, requested,
):
    rig = await _rig(hass, freezer)
    _publish_vehicle(hass, rig, soc=soc)
    rig.controller.before_export_recovery = EvBeforeExportRecovery(
        pending, rig.controller._before_export_recovery_binding(),
    )
    assert rig.controller.dynamic_topup_requested(rig.now) is requested


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("soc,requested", [(89.9, True), (90, False), (90.1, False)])
async def test_minimum_above_normal_limit_cannot_deadlock_export_handoff(
    hass, freezer, pending, soc, requested,
):
    rig = await _rig(hass, freezer, ev_before_export_soc_target_percent=95)
    _publish_vehicle(hass, rig, soc=soc)
    rig.controller.before_export_recovery = EvBeforeExportRecovery(
        pending, rig.controller._before_export_recovery_binding(),
    )
    budget = _budget(rig)
    assert budget.target_soc_percent == 90
    assert budget.requested_reservation_kwh == pytest.approx(0.06 if requested else 0)
    assert rig.controller.dynamic_topup_requested(rig.now) is requested
    # A persisted minimum+buffer intent cannot demand a normal-policy target
    # above the legal normal charging ceiling. Physical stopped proof remains.
    assert rig.fox._ev_before_export_handoff_ready(rig.now) is not requested


async def test_pending_recovery_survives_restart_without_restoring_a_daily_quota(hass, freezer):
    rig = await _rig(hass, freezer)
    _publish_vehicle(hass, rig, soc=40.5)
    rig.controller.before_export_recovery = EvBeforeExportRecovery(
        True, rig.controller._before_export_recovery_binding(),
    )
    rig.controller.daily_backfill_delivered_kwh = 7
    await rig.controller._async_save(rig.now)
    replacement = ActiveEvController(hass, rig.coordinator)
    rig.coordinator.ev_controller = replacement
    await replacement._async_restore()
    assert replacement.before_export_recovery.pending
    assert replacement.dynamic_topup_requested(rig.now)
    assert replacement.daily_backfill_protection_kwh(rig.now) == pytest.approx(0.3)
    _publish_vehicle(hass, rig, soc=41)
    assert not replacement.dynamic_topup_requested(rig.now)


async def test_ev_can_charge_its_reserved_energy_when_unreserved_sellable_is_zero(
    hass, freezer, monkeypatch,
):
    rig = await _rig(hass, freezer)
    calls = _services(hass, monkeypatch, rig)
    rig.coordinator.data.available_after_reserve_kwh = 8.6
    rig.fox.export_plan = ExportPlan(0, 0, 0, "no_protected_energy")
    rig.fox.export_protected_ev_kwh = 3.6
    budget = _budget(rig, available=8.6)
    assert budget.exportable_kwh == 0
    assert budget.ev_available_kwh == pytest.approx(3.6)
    assert rig.controller._before_export_energy_budget(rig.now) == pytest.approx(3.6)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.decision_phase == "ev_before_export_charging"
    assert 0 < rig.controller.target_current_a <= 8
    assert any(entity == "number.car_current" and value > 0 for entity, value in calls)
    assert ("switch.car_charge", "on") in calls
    assert not any(value == "Force Discharge" for _, value in calls)


async def test_connected_recovery_retires_owned_export_before_ev_spends_its_reservation(
    hass, freezer, monkeypatch,
):
    rig = await _rig(hass, freezer)
    calls = _services(hass, monkeypatch, rig)
    _foxess(hass, mode="Force Discharge", discharge=15)
    rig.fox.export_session = ExportSessionState("active", 15, 0)
    await rig.fox.async_reconcile()
    assert ("select.foxess_mode", "Self Use") in calls
    assert ("number.foxess_discharge", 0) in calls
    assert not any(entity == "number.car_current" and value > 0 for entity, value in calls)
    # Fresh physical acknowledgement of cleanup permits the existing owner to
    # finish. Merely asking for Self Use is not the handoff proof.
    rig.now += timedelta(seconds=1)
    freezer.move_to(rig.now)
    _publish_vehicle(hass, rig)
    _fresh(rig.coordinator, rig.now)
    await rig.fox.async_reconcile()
    assert rig.fox.export_session.phase == "idle"
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.decision_phase == "ev_before_export_charging"
    assert rig.controller.target_current_a > 0
    assert ("switch.car_charge", "on") in calls


@pytest.mark.parametrize("timing", ["conservative", "ready_by"])
async def test_fixed_daily_planner_can_spend_its_own_reserved_energy(
    hass, freezer, timing,
):
    now = _at(7, 55)
    freezer.move_to(now)
    calls = _generic_services(hass)
    coordinator, controller = _site(
        hass, ev_reservation_mode="fixed", ev_daily_backfill_energy_kwh=5,
        ev_pre_free_backfill_timing=timing, ev_before_export_enabled=False,
        ev_capacity_source="configured", ev_capacity_fallback_kwh=60,
    )
    coordinator.data.available_after_reserve_kwh = 10
    coordinator.active_controller.export_plan = ExportPlan(0, 0, 0, "no_protected_energy")
    coordinator.active_controller.export_protected_ev_kwh = 5
    _fresh(coordinator, now)
    assert controller.daily_backfill_protection_kwh(now) == 5
    assert controller._backfill_energy_pool(
        now, coordinator.active_controller.export_plan, fixed_allocation_owned=True,
    ) == 5
    await controller.async_reconcile(now)
    assert controller.daily_backfill_active
    assert controller.daily_backfill_plan.planned_energy_kwh == 5
    assert controller.target_current_a == 8
    assert any(service == "turn_on" for _, service, _ in calls)


@pytest.mark.parametrize("timing", ["conservative", "ready_by"])
@pytest.mark.parametrize("sellable", [0, 0.4])
@pytest.mark.parametrize("proof", ["missing", "invalid"])
async def test_fixed_settings_cannot_restore_an_unproven_or_shrunken_reservation(
    hass, freezer, timing, sellable, proof,
):
    now = _at(7, 59)
    freezer.move_to(now)
    calls = _generic_services(hass)
    coordinator, controller = _site(
        hass, ev_reservation_mode="fixed", ev_daily_backfill_energy_kwh=5,
        ev_pre_free_backfill_timing=timing, ev_before_export_enabled=False,
        ev_capacity_source="configured", ev_capacity_fallback_kwh=60,
    )
    coordinator.data.available_after_reserve_kwh = 14
    coordinator.learning_remaining_kwh = 3
    active = coordinator.active_controller
    active.export_plan = ExportPlan(sellable, sellable, 0, "unknown_protected")
    if proof == "invalid":
        active.export_protected_ev_kwh = float("nan")
    _fresh(coordinator, now)
    assert controller.daily_backfill_protection_kwh(now) == 5
    assert controller._backfill_energy_pool(
        now, active.export_plan, fixed_allocation_owned=True,
    ) == sellable
    await controller.async_reconcile(now)
    # The configured allocation is not proof that this export publication
    # actually withheld it. Only the remaining published unreserved pool may
    # fund charging until the export controller publishes the reservation.
    assert controller.daily_backfill_plan.planned_energy_kwh == sellable
    assert controller.daily_backfill_active is bool(sellable)
    assert any(service == "turn_on" for _, service, _ in calls) is bool(sellable)


@pytest.mark.parametrize("proof", ["missing", "invalid"])
async def test_dynamic_backfill_fails_closed_without_published_reservation_proof(
    hass, freezer, proof,
):
    rig = await _rig(hass, freezer)
    rig.fox.export_plan = ExportPlan(0, 0, 0, "unknown_protected")
    if proof == "missing":
        del rig.fox.export_protected_ev_kwh
    else:
        rig.fox.export_protected_ev_kwh = float("nan")
    assert _budget(rig).valid
    assert rig.controller._backfill_energy_pool(rig.now, rig.fox.export_plan) is None


@pytest.mark.parametrize("timing", ["conservative", "ready_by"])
async def test_post_ready_pre_free_cannot_spend_tomorrows_fixed_reservation(
    hass, freezer, timing,
):
    now = _at(11, 59)
    freezer.move_to(now)
    calls = _generic_services(hass)
    coordinator, controller = _site(
        hass, ev_reservation_mode="fixed", ev_daily_backfill_energy_kwh=5,
        ev_pre_free_backfill_timing=timing, ev_before_export_enabled=False,
        ev_capacity_source="configured", ev_capacity_fallback_kwh=60,
    )
    coordinator.data.available_after_reserve_kwh = 10
    coordinator.active_controller.export_plan = ExportPlan(0, 0, 0, "no_protected_energy")
    coordinator.active_controller.export_protected_ev_kwh = 5
    _fresh(coordinator, now)
    assert controller.daily_backfill_protection_kwh(now) == 5
    assert controller._backfill_energy_pool(now, coordinator.active_controller.export_plan) == 0
    await controller.async_reconcile(now)
    assert not controller.daily_backfill_active
    assert not controller.pre_free_session.active
    assert not controller.target_current_a
    assert controller.pre_free_plan.planned_energy_kwh == 0
    assert controller.daily_backfill_delivered_kwh == 0
    assert controller.daily_backfill_protection_kwh(now) == 5
    assert not any(service == "turn_on" for _, service, _ in calls)


@pytest.mark.parametrize("after_ready,expected", [(False, 5), (True, 0)])
async def test_when_connected_fixed_beneficiary_ends_at_its_ready_deadline(
    hass, freezer, after_ready, expected,
):
    rig = await _rig(
        hass, freezer, ev_reservation_mode="fixed", ev_before_export_enabled=False,
        ev_daily_backfill_energy_kwh=5, ev_pre_free_backfill_enabled=True,
        ev_pre_free_backfill_timing="when_connected", ev_daily_ready_time="17:00:00",
        free_charge_window_start="19:01:00", free_charge_window_end="20:00:00",
        bonus_window_start="14:00:00", bonus_window_end="15:00:00",
        force_discharge_finish="15:01:00",
    )
    if after_ready:
        rig.now = rig.now.replace(hour=18, minute=59)
        freezer.move_to(rig.now)
        _publish_vehicle(hass, rig)
        for entity in (
            "sensor.site_grid", "sensor.site_battery_soc", "sensor.battery_power",
            "sensor.house", "select.foxess_mode", "number.foxess_charge",
            "number.foxess_discharge",
        ):
            state = hass.states.get(entity)
            hass.states.async_set(entity, state.state, dict(state.attributes), force_update=True)
    rig.coordinator.data.available_after_reserve_kwh = 10
    rig.fox.export_plan = ExportPlan(0, 0, 0, "no_protected_energy")
    rig.fox.export_protected_ev_kwh = 5
    _fresh(rig.coordinator, rig.now)
    assert rig.controller._when_connected_backfill_hold(rig.now) is None
    assert rig.controller.daily_backfill_protection_kwh(rig.now) == 5
    assert rig.controller._when_connected_energy_budget(rig.now) == expected


@pytest.mark.parametrize("mode", ["fixed", "dynamic"])
@pytest.mark.parametrize("published", [0, 5])
async def test_observed_budget_and_positive_guard_require_published_withholding_proof(
    hass, freezer, monkeypatch, mode, published,
):
    rig = await _rig(
        hass, freezer, ev_reservation_mode=mode, ev_before_export_enabled=mode == "dynamic",
        ev_daily_backfill_energy_kwh=5, ev_pre_free_backfill_enabled=True,
        ev_pre_free_backfill_timing="when_connected", ev_daily_ready_time="17:00:00",
        free_charge_window_start="19:01:00", free_charge_window_end="20:00:00",
        bonus_window_start="14:00:00", bonus_window_end="15:00:00",
        force_discharge_finish="15:01:00",
    )
    calls = _services(hass, monkeypatch, rig)
    _publish_vehicle(hass, rig, soc=41 - 5 / 0.6)
    rig.coordinator.data.available_after_reserve_kwh = 14
    rig.coordinator.learning_remaining_kwh = 3
    rig.fox.export_plan = ExportPlan(0, 0, 0, "unknown_protected")
    rig.fox.export_protected_ev_kwh = published
    assert rig.controller.daily_backfill_protection_kwh(rig.now) == pytest.approx(5)
    budget = (
        rig.controller._when_connected_energy_budget(rig.now) if mode == "fixed"
        else rig.controller._before_export_energy_budget(rig.now)
    )
    assert budget == published
    rig.controller.target_current_a = 8
    rig.controller.outside_target_active = True
    rig.controller.decision_phase = (
        "daily_ready_backfill" if mode == "fixed" else "ev_before_export_charging"
    )
    rig.controller._when_connected_decision_config = rig.coordinator.runtime_config
    assert rig.controller._writes_still_authorized() is bool(published)
    await rig.controller.async_reconcile(rig.now)
    assert any(
        entity == "number.car_current" and value > 0 for entity, value in calls
    ) is bool(published)
    assert (("switch.car_charge", "on") in calls) is bool(published)


@pytest.mark.parametrize("priority", [False, True])
async def test_dynamic_cannot_activate_daily_backfill_from_an_old_fixed_quota(
    hass, freezer, priority,
):
    now = _at(7, 55)
    freezer.move_to(now)
    calls = _generic_services(hass)
    coordinator, controller = _site(
        hass, ev_reservation_mode="dynamic", ev_daily_backfill_energy_kwh=7,
        ev_pre_free_backfill_enabled=False, ev_before_export_enabled=priority,
        ev_before_export_soc_target_percent=20, ev_before_export_soc_buffer_percent=1,
        ev_capacity_source="configured", ev_capacity_fallback_kwh=60,
    )
    coordinator.ev_controller = controller
    _fresh(coordinator, now)
    assert not controller._daily_backfill_enabled()
    await controller.async_reconcile(now)
    assert controller.daily_backfill_plan is None
    assert not controller.daily_backfill_active
    assert not controller.target_current_a
    assert not any(service == "turn_on" for _, service, _ in calls)


@pytest.mark.parametrize("home", [False, True])
async def test_price_intent_does_not_circularly_block_connected_dynamic_recovery(
    hass, freezer, monkeypatch, home,
):
    rig = await _rig(
        hass, freezer, ev_pre_free_backfill_enabled=True,
        ev_pre_free_backfill_timing="when_connected",
        bonus_window_start="14:00:00", bonus_window_end="15:00:00",
        force_discharge_finish="15:01:00", critical_event_sell_enabled=True,
        aemo_monitor_enabled=True, aemo_region="NSW1", aemo_export_threshold_per_kwh=3,
    )
    calls = _services(hass, monkeypatch, rig)
    rig.coordinator.market_monitor = SimpleNamespace(export_result=SimpleNamespace(
        region="NSW1", price_per_kwh=4,
        interval_start=rig.now, interval_end=rig.now + timedelta(minutes=5),
    ))
    _publish_vehicle(hass, rig, home=home, connected=home)
    assert rig.fox._price_window(rig.now) is not None
    assert rig.controller.dynamic_topup_requested(rig.now) is home
    assert rig.fox.opportunistic_price_export_requested(rig.now) is not home
    if not home:
        # Away and below minimum still retains its reservation while granting
        # the genuinely unreserved balance to qualified price export.
        policy = evaluate_foxess_export_policy(_context(hass, rig))
        assert policy.authority_source == "price" and policy.eligible
        # Price admission retains its existing electrical-age energy haircut.
        assert 0 < policy.export_plan.sellable_energy_kwh <= 15.4
        assert rig.controller.daily_backfill_protection_kwh(rig.now) == pytest.approx(3.6)
        return
    assert rig.controller._when_connected_backfill_hold(rig.now) is None
    # The real inverter controller publishes the shared energy ledger, but
    # must not start price export while connected recovery owns the handoff.
    await rig.fox.async_reconcile()
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.decision_phase == "ev_before_export_charging"
    assert rig.controller.target_current_a > 0
    assert any(entity == "number.car_current" and value > 0 for entity, value in calls)
    assert not any(value == "Force Discharge" for _, value in calls)
