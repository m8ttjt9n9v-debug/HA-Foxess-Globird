"""Maintenance admission uses real controller models and fresh HA states only."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import CoreState
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.active import ActiveFoxessController
from custom_components.home_energy_orchestrator.coordinator import EnergyCoordinator
from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.maintenance_safety import (
    maintenance_blockers,
    maintenance_locks,
    runtime_verification_blockers,
)
from custom_components.home_energy_orchestrator.manual_test import ManualTestController
from custom_components.home_energy_orchestrator.planner.ev import (
    DirectEvseReconciliationState,
    SmartSocketRecoveryState,
)
from custom_components.home_energy_orchestrator.planner.ev_outside_window import PreFreeSessionState
from custom_components.home_energy_orchestrator.trip_charge import TripChargeController
from tests.test_setup import ENTRY_DATA


@pytest.fixture
async def idle_host(hass):
    """Load actual typed stores without starting any actuator controller."""
    hass.set_state(CoreState.running)
    coordinators = []

    async def make(entry_id="alpha", *, ev_configured=True):
        prefix = f"sensor.{entry_id}"
        config = {
            **ENTRY_DATA,
            "configure_ev": ev_configured,
            "configure_solar": False,
            "battery_soc_entity": prefix + "_battery_soc",
            "battery_power_entity": prefix + "_battery_power",
            "grid_power_entity": prefix + "_grid",
            "house_load_entity": prefix + "_house",
            "foxess_work_mode_entity": f"select.{entry_id}_mode",
            "foxess_force_charge_power_entity": f"number.{entry_id}_charge",
            "foxess_force_discharge_power_entity": f"number.{entry_id}_export",
            "ev_soc_entity": prefix + "_car_soc",
            "ev_at_home_entity": f"device_tracker.{entry_id}_car",
            "ev_cable_connected_entity": f"binary_sensor.{entry_id}_cable",
            "ev_charging_state_entity": prefix + "_charging",
            "ev_actual_current_entity": prefix + "_current",
            "ev_stored_energy_entity": prefix + "_car_energy",
            "ev_current_limit_entity": f"number.{entry_id}_current",
            "ev_charge_limit_entity": f"number.{entry_id}_limit",
            "ev_charge_switch_entity": f"switch.{entry_id}_charge",
        }
        for suffix, value, unit in [
            ("_battery_soc", 60, "%"), ("_battery_power", -0.4, "kW"),
            ("_grid", 0, "kW"), ("_house", 0.4, "kW"),
            ("_car_soc", 60, "%"), ("_car_energy", 40, "kWh"),
            ("_current", 0, "A"), ("_charging", "stopped", None),
        ]:
            hass.states.async_set(prefix + suffix, value,
                                  {"unit_of_measurement": unit} if unit else {})
        hass.states.async_set(f"device_tracker.{entry_id}_car", "home")
        hass.states.async_set(f"binary_sensor.{entry_id}_cable", "on")
        hass.states.async_set(f"switch.{entry_id}_charge", "off")
        hass.states.async_set(f"select.{entry_id}_mode", "Self Use")
        for suffix in ("charge", "export"):
            hass.states.async_set(f"number.{entry_id}_{suffix}", 0,
                                  {"unit_of_measurement": "kW"})
        coordinator = EnergyCoordinator(hass, config, entry_id)
        await coordinator.async_refresh()
        active = coordinator.active_controller = ActiveFoxessController(hass, coordinator)
        coordinator.manual_test = ManualTestController(hass, coordinator)
        await coordinator.manual_test._async_load()
        await active.manual.async_restore_handoff()
        await active._async_load_charge_session()
        await active._async_load_export_session()
        ev = coordinator.ev_controller = ActiveEvController(hass, coordinator)
        await ev._async_restore()
        # The real setup sets this timer only after the EV repository is read.
        ev._unsub_interval = lambda: None
        entry = MockConfigEntry(domain="home_energy_orchestrator", entry_id=entry_id,
                                data=config, version=6)
        coordinator.trip_charge = TripChargeController(hass, coordinator, entry)
        await coordinator.trip_charge.async_restore_handoff()
        coordinators.append(coordinator)
        return coordinator

    yield make
    for coordinator in coordinators:
        coordinator.shutdown()
    await hass.async_block_till_done()
    for coordinator in coordinators:
        await coordinator.async_shutdown()


async def test_fresh_idle_real_models_have_no_blockers_or_service_calls(hass, idle_host):
    coordinator = await idle_host()
    calls = []
    remove = hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    try:
        assert maintenance_blockers(hass, [coordinator]) == ()
        assert maintenance_blockers(hass, [coordinator]) == ()
        await hass.async_block_till_done()
        assert calls == []
    finally:
        remove()


@pytest.mark.parametrize("kind,phase,expected", [
    ("charge_session", "starting", "battery_charge_session_active"),
    ("charge_session", "active", "battery_charge_session_active"),
    ("charge_session", "stopping", "battery_charge_session_active"),
    ("charge_session", "recovering", "battery_charge_session_active"),
    ("export_session", "starting", "battery_export_session_active"),
    ("export_session", "active", "battery_export_session_active"),
    ("export_session", "stopping", "battery_export_session_active"),
    ("export_session", "recovering", "battery_export_session_active"),
])
async def test_unfinished_sessions_block(hass, idle_host, kind, phase, expected):
    coordinator = await idle_host()
    active = coordinator.active_controller
    setattr(active, kind, replace(getattr(active, kind), phase=phase))
    assert expected in maintenance_blockers(hass, [coordinator])


async def test_completed_charge_is_not_an_unfinished_session(hass, idle_host):
    coordinator = await idle_host()
    coordinator.active_controller.charge_session = replace(
        coordinator.active_controller.charge_session, phase="completed")
    assert maintenance_blockers(hass, [coordinator]) == ()


@pytest.mark.parametrize("owner,attribute,value", [
    ("active_controller", "_charge_storage_status", "not_loaded"),
    ("active_controller", "_export_storage_status", "malformed"),
    ("manual_test", "storage_status", "malformed"),
    ("trip_charge", "_loaded", False),
    ("trip_charge", "_invalid_storage", True),
    ("trip_charge", "_storage_error", True),
    ("trip_charge", "_dirty", True),
])
async def test_untrusted_or_unloaded_journals_block(hass, idle_host, owner, attribute, value):
    coordinator = await idle_host()
    setattr(getattr(coordinator, owner), attribute, value)
    assert "heo_storage_untrusted" in maintenance_blockers(hass, [coordinator])


async def test_invalid_ev_journal_blocks_even_when_ev_disabled(hass, idle_host):
    coordinator = await idle_host(ev_configured=False)
    coordinator.ev_controller._repository.last_restore_status = "invalid"
    assert "heo_storage_untrusted" in maintenance_blockers(hass, [coordinator])


@pytest.mark.parametrize("mode", ["Force Charge", "Force Discharge", "Feed-in First", "Back-up"])
async def test_external_native_mode_blocks_without_adopting_it(hass, idle_host, mode):
    coordinator = await idle_host()
    hass.states.async_set("select.alpha_mode", mode)
    assert "battery_not_self_use" in maintenance_blockers(hass, [coordinator])


async def test_unknown_native_feedback_and_nonzero_forced_target_block(hass, idle_host):
    coordinator = await idle_host()
    hass.states.async_set("select.alpha_mode", "unavailable")
    assert "battery_mode_feedback_unavailable" in maintenance_blockers(hass, [coordinator])
    hass.states.async_set("select.alpha_mode", "Self Use")
    hass.states.async_set("number.alpha_export", 8, {"unit_of_measurement": "kW"})
    assert "battery_force_target_not_clear" in maintenance_blockers(hass, [coordinator])


@pytest.mark.parametrize("entity", ["sensor.alpha_grid", "sensor.alpha_battery_power",
                                   "select.alpha_mode",
                                   "sensor.alpha_current", "sensor.alpha_charging",
                                   "binary_sensor.alpha_cable", "switch.alpha_charge"])
async def test_stale_but_numeric_or_stable_states_block(hass, idle_host, freezer, entity):
    coordinator = await idle_host()
    freezer.tick(timedelta(seconds=91))
    # Refresh everything except the source under test; unrelated fresh reports
    # must not make an old numeric source look safe.
    for state in hass.states.async_all():
        if state.entity_id != entity:
            hass.states.async_set(state.entity_id, state.state, dict(state.attributes),
                                  force_update=True)
    assert maintenance_blockers(hass, [coordinator])


@pytest.mark.parametrize("entity", ["sensor.alpha_battery_soc", "number.alpha_charge",
                                   "number.alpha_export"])
async def test_stable_level_and_target_age_is_not_a_fast_telemetry_clock(
    hass, idle_host, freezer, entity,
):
    coordinator = await idle_host()
    freezer.tick(timedelta(hours=6))
    for state in hass.states.async_all():
        if state.entity_id != entity:
            hass.states.async_set(state.entity_id, state.state, dict(state.attributes))
    # Fresh work mode, electrical power and EV evidence still prove current
    # idle operation. The unchanged SoC/zero configuration target stays valid.
    assert maintenance_blockers(hass, [coordinator]) == ()


@pytest.mark.parametrize("entity,value,attributes,expected", [
    ("sensor.alpha_battery_soc", "unknown", {}, "battery_telemetry_unavailable"),
    ("sensor.alpha_battery_soc", "unavailable", {}, "battery_telemetry_unavailable"),
    ("sensor.alpha_battery_soc", "nan", {}, "battery_telemetry_unavailable"),
    ("sensor.alpha_battery_soc", -1, {}, "battery_telemetry_unavailable"),
    ("sensor.alpha_battery_soc", 101, {}, "battery_telemetry_unavailable"),
    ("number.alpha_charge", "unknown", {"unit_of_measurement": "kW"},
     "battery_mode_feedback_unavailable"),
    ("number.alpha_export", "unavailable", {"unit_of_measurement": "kW"},
     "battery_mode_feedback_unavailable"),
    ("number.alpha_charge", "nan", {"unit_of_measurement": "kW"},
     "battery_mode_feedback_unavailable"),
    ("number.alpha_export", -1, {"unit_of_measurement": "kW"},
     "battery_mode_feedback_unavailable"),
    ("number.alpha_charge", 0, {"unit_of_measurement": "A"},
     "battery_mode_feedback_unavailable"),
    ("number.alpha_export", 0, {}, "battery_mode_feedback_unavailable"),
    ("number.alpha_charge", 1, {"unit_of_measurement": "kW"},
     "battery_force_target_not_clear"),
    ("number.alpha_export", 1, {"unit_of_measurement": "kW"},
     "battery_force_target_not_clear"),
])
async def test_stable_role_still_requires_valid_soc_and_clear_power_targets(
    hass, idle_host, entity, value, attributes, expected,
):
    coordinator = await idle_host()
    hass.states.async_set(entity, value, attributes)
    assert expected in maintenance_blockers(hass, [coordinator])


@pytest.mark.parametrize("entity", [
    "sensor.alpha_grid", "sensor.alpha_battery_power", "sensor.alpha_battery_soc",
    "select.alpha_mode", "number.alpha_charge", "number.alpha_export",
    "sensor.alpha_current", "sensor.alpha_charging", "binary_sensor.alpha_cable",
    "switch.alpha_charge",
])
async def test_restored_placeholder_cannot_supply_any_required_role(hass, idle_host, entity):
    coordinator = await idle_host()
    state = hass.states.get(entity)
    hass.states.async_set(entity, state.state, dict(state.attributes) | {"restored": True})
    assert maintenance_blockers(hass, [coordinator])


async def test_restored_rejection_follows_accepted_battery_fallback_provenance(
    hass, idle_host, freezer,
):
    coordinator = await idle_host()
    coordinator.update_config_value("battery_charge_power_entity", "sensor.alpha_battery_charge")
    coordinator.update_config_value(
        "battery_discharge_power_entity", "sensor.alpha_battery_discharge",
    )
    hass.states.async_set("sensor.alpha_battery_charge", 0,
                          {"unit_of_measurement": "kW", "restored": True})
    hass.states.async_set("sensor.alpha_battery_discharge", 0.4, {"unit_of_measurement": "kW"})
    freezer.tick(timedelta(seconds=91))
    for state in hass.states.async_all():
        if state.entity_id != "sensor.alpha_battery_charge":
            hass.states.async_set(state.entity_id, state.state, dict(state.attributes))
    sample = coordinator._normalized_telemetry(dt_util.utcnow()).battery_power
    assert sample.reason == "signed_fallback_pair_stale"
    # The stale inactive pair is rejected already; only the accepted signed
    # source is eligible to provide current physical evidence.
    assert maintenance_blockers(hass, [coordinator]) == ()
    signed = hass.states.get("sensor.alpha_battery_power")
    hass.states.async_set(signed.entity_id, signed.state,
                          dict(signed.attributes) | {"restored": True})
    assert "battery_telemetry_unavailable" in maintenance_blockers(hass, [coordinator])


async def test_admission_reads_live_report_clock_not_cached_state_serialization(
    hass, idle_host, freezer,
):
    coordinator = await idle_host()
    states = hass.states.async_all()
    # HA caches serialized State dictionaries. Its same-value report path
    # refreshes the actual last_reported property, not that cached dictionary.
    serialized = {state.entity_id: state.as_dict()["last_reported"] for state in states}
    freezer.tick(timedelta(seconds=91))
    for state in states:
        hass.states.async_set(state.entity_id, state.state, dict(state.attributes))
    cable = hass.states.get("binary_sensor.alpha_cable")
    assert cable.as_dict()["last_reported"] == serialized[cable.entity_id]
    assert cable.last_reported.isoformat() != serialized[cable.entity_id]
    assert cable.last_reported == dt_util.utcnow()
    # Neither a REST-style stale serialization nor an unchanged numeric value
    # should mask this exact mapped entity's genuinely fresh native report.
    assert maintenance_blockers(hass, [coordinator]) == ()


@pytest.mark.parametrize("entity,value,attributes,expected", [
    ("sensor.alpha_current", "1", {"unit_of_measurement": "A"}, "ev_physically_charging"),
    ("sensor.alpha_current", "1000", {"unit_of_measurement": "mA"}, "ev_physically_charging"),
    ("sensor.alpha_current", "nan", {"unit_of_measurement": "A"}, "ev_feedback_unavailable"),
    ("sensor.alpha_current", "0", {"unit_of_measurement": "kW"}, "ev_feedback_unavailable"),
    ("sensor.alpha_charging", "charging", {}, "ev_physically_charging"),
    ("sensor.alpha_charging", "starting", {}, "ev_feedback_unavailable"),
    ("switch.alpha_charge", "on", {}, "ev_charge_switch_on"),
    ("binary_sensor.alpha_cable", "unknown", {}, "ev_feedback_unavailable"),
])
async def test_physical_ev_feedback_blocks(hass, idle_host, entity, value, attributes, expected):
    coordinator = await idle_host()
    hass.states.async_set(entity, value, attributes)
    assert expected in maintenance_blockers(hass, [coordinator])


@pytest.mark.parametrize("field", ["daily_backfill_active", "daily_backfill_stop_pending",
                                  "outside_control_active"])
async def test_pending_ev_sessions_block(hass, idle_host, field):
    coordinator = await idle_host()
    setattr(coordinator.ev_controller, field, True)
    assert "ev_session_active" in maintenance_blockers(hass, [coordinator])


async def test_prefree_recovery_full_and_trip_cleanup_block(hass, idle_host):
    coordinator = await idle_host()
    ev = coordinator.ev_controller
    ev.pre_free_session = PreFreeSessionState(active=True)
    ev.reconciliation = DirectEvseReconciliationState(phase="awaiting_feedback")
    ev.smart_recovery = SmartSocketRecoveryState(phase="power_off_dwell")
    ev.charge_to_full_started_at = dt_util.utcnow()
    trip = coordinator.trip_charge
    trip._state = replace(trip._state, cleanup_pending=True)
    blockers = maintenance_blockers(hass, [coordinator])
    assert {"ev_session_active", "ev_reconciliation_pending", "ev_recovery_pending",
            "ev_full_charge_active", "trip_charge_active"}.issubset(blockers)


async def test_zero_actual_current_does_not_exempt_keepalive_target(hass, idle_host):
    coordinator = await idle_host()
    coordinator.ev_controller.target_current_a = 1.0
    assert "ev_charging_target_active" in maintenance_blockers(hass, [coordinator])


def _remember_prior_ev_targets(hass, coordinator):
    """Reproduce the retained display fields after actual disconnected cleanup."""
    ev = coordinator.ev_controller
    ev.target_current_a = 15.0
    ev.pre_free_current_a = 1.0
    ev.reconciliation = DirectEvseReconciliationState(
        phase="confirmed", target_current_a=15.0,
    )
    hass.states.async_set("device_tracker.alpha_car", "not_home")
    hass.states.async_set("binary_sensor.alpha_cable", "off")
    hass.states.async_set("sensor.alpha_charging", "disconnected")


async def test_confirmed_disconnection_excludes_only_historical_ev_targets(hass, idle_host):
    coordinator = await idle_host()
    _remember_prior_ev_targets(hass, coordinator)
    assert maintenance_blockers(hass, [coordinator]) == ()
    # Read-only admission must not erase or rewrite controller state.
    assert coordinator.ev_controller.target_current_a == 15.0
    assert coordinator.ev_controller.reconciliation.target_current_a == 15.0
    assert coordinator.ev_controller.pre_free_current_a == 1.0


@pytest.mark.parametrize("entity,value,attributes", [
    ("binary_sensor.alpha_cable", "on", {}),
    ("binary_sensor.alpha_cable", "unknown", {}),
    ("sensor.alpha_charging", "charging", {}),
    ("sensor.alpha_charging", "unavailable", {}),
    ("switch.alpha_charge", "on", {}),
    ("switch.alpha_charge", "unknown", {}),
    ("sensor.alpha_current", 1, {"unit_of_measurement": "A"}),
    ("sensor.alpha_current", 0, {"unit_of_measurement": "kW"}),
])
async def test_unproven_disconnection_keeps_historical_target_block(
    hass, idle_host, entity, value, attributes,
):
    coordinator = await idle_host()
    _remember_prior_ev_targets(hass, coordinator)
    hass.states.async_set(entity, value, attributes)
    assert "ev_charging_target_active" in maintenance_blockers(hass, [coordinator])


@pytest.mark.parametrize("entity", ["binary_sensor.alpha_cable", "sensor.alpha_charging",
                                   "switch.alpha_charge", "sensor.alpha_current"])
async def test_stale_disconnected_feedback_cannot_excuse_retained_targets(
    hass, idle_host, freezer, entity,
):
    coordinator = await idle_host()
    _remember_prior_ev_targets(hass, coordinator)
    freezer.tick(timedelta(seconds=91))
    for state in hass.states.async_all():
        if state.entity_id != entity:
            hass.states.async_set(state.entity_id, state.state, dict(state.attributes),
                                  force_update=True)
    blockers = maintenance_blockers(hass, [coordinator])
    assert "ev_feedback_unavailable" in blockers
    assert "ev_charging_target_active" in blockers


@pytest.mark.parametrize("phase", ["awaiting_feedback", "waiting", "stopping"])
async def test_confirmed_disconnection_never_excuses_pending_reconciliation(
    hass, idle_host, phase,
):
    coordinator = await idle_host()
    _remember_prior_ev_targets(hass, coordinator)
    coordinator.ev_controller.reconciliation = replace(
        coordinator.ev_controller.reconciliation, phase=phase,
    )
    assert "ev_reconciliation_pending" in maintenance_blockers(hass, [coordinator])


@pytest.mark.parametrize("owner", ["prefree", "backfill", "stop", "outside", "recovery",
                                  "stage", "full", "trip"])
async def test_disconnected_physical_idle_never_excuses_active_owned_work(hass, idle_host, owner):
    coordinator = await idle_host()
    _remember_prior_ev_targets(hass, coordinator)
    ev = coordinator.ev_controller
    if owner == "prefree":
        ev.pre_free_session = PreFreeSessionState(active=True)
    elif owner == "backfill":
        ev.daily_backfill_active = True
    elif owner == "stop":
        ev.daily_backfill_stop_pending = True
    elif owner == "outside":
        ev.outside_control_active = True
    elif owner == "recovery":
        ev.smart_recovery = SmartSocketRecoveryState(phase="power_off_dwell")
    elif owner == "stage":
        ev.smart_stage_started_at = dt_util.utcnow()
    elif owner == "full":
        ev.charge_to_full_started_at = dt_util.utcnow()
    else:
        coordinator.trip_charge._state = replace(
            coordinator.trip_charge._state, cleanup_pending=True,
        )
    assert maintenance_blockers(hass, [coordinator])


@pytest.mark.parametrize("target", [float("nan"), -1, True])
async def test_disconnection_does_not_excuse_invalid_remembered_target(hass, idle_host, target):
    coordinator = await idle_host()
    _remember_prior_ev_targets(hass, coordinator)
    coordinator.ev_controller.target_current_a = target
    assert "ev_charging_target_active" in maintenance_blockers(hass, [coordinator])


@pytest.mark.parametrize("target", [float("nan"), -1, True])
async def test_invalid_ev_target_is_not_an_idle_target(hass, idle_host, target):
    coordinator = await idle_host()
    coordinator.ev_controller.target_current_a = target
    assert "ev_charging_target_active" in maintenance_blockers(hass, [coordinator])


async def test_future_reports_fail_closed(hass, idle_host, freezer):
    coordinator = await idle_host()
    freezer.move_to(dt_util.utcnow() - timedelta(seconds=1))
    assert {"battery_telemetry_unavailable", "battery_mode_feedback_unavailable",
            "ev_feedback_unavailable"}.issubset(maintenance_blockers(hass, [coordinator]))


async def test_manual_export_and_diagnostic_block_even_without_physical_flow(hass, idle_host):
    coordinator = await idle_host()
    manual = coordinator.active_controller.manual
    manual._hold, manual._target, manual._phase = True, "export_max", "held"
    coordinator.manual_test.active_kind = "discharge"
    assert {"battery_manual_control_active", "battery_diagnostic_active"}.issubset(
        maintenance_blockers(hass, [coordinator]))


async def test_durable_confirmed_self_use_hold_is_preserved_not_released(hass, idle_host):
    coordinator = await idle_host()
    manual = coordinator.active_controller.manual
    manual._hold, manual._target, manual._phase = True, "self_use", "held"
    manual._command_confirmed = True
    assert maintenance_blockers(hass, [coordinator]) == ()
    assert manual.is_active and manual.target == "self_use"


async def test_every_supplied_entry_blocks_and_locks_have_stable_order(hass, idle_host):
    alpha, bravo = await idle_host(), await idle_host("bravo")
    bravo.ev_controller.daily_backfill_stop_pending = True
    assert "ev_session_active" in maintenance_blockers(hass, [alpha, bravo])
    expected = [alpha.active_controller._reconcile_lock, alpha.ev_controller._lock,
                bravo.active_controller._reconcile_lock, bravo.ev_controller._lock]
    assert maintenance_locks([bravo, alpha, alpha]) == expected
    assert not any(lock.locked() for lock in expected)


async def test_omitted_configured_entry_or_not_running_host_blocks(hass, idle_host):
    coordinator = await idle_host()
    entry = MockConfigEntry(domain="home_energy_orchestrator", entry_id="omitted", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    assert entry.state is not ConfigEntryState.LOADED
    assert "heo_runtime_unavailable" in maintenance_blockers(hass, [coordinator])
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    assert "heo_runtime_unavailable" in maintenance_blockers(hass, [coordinator])
    entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    hass.set_state(CoreState.stopping)
    assert "home_assistant_not_running" in maintenance_blockers(hass, [coordinator])


async def test_missing_runtime_and_controller_capabilities_fail_closed(hass, idle_host):
    coordinator = await idle_host()
    coordinator.ev_controller._lock = None
    assert "heo_runtime_unavailable" in maintenance_blockers(hass, [coordinator])
    assert "heo_runtime_unavailable" in maintenance_blockers(hass, [SimpleNamespace()])
    assert "heo_runtime_unavailable" in maintenance_blockers(hass, [])
    assert maintenance_locks([SimpleNamespace()]) == []


async def test_unconfigured_ev_needs_no_invented_ev_feedback(hass, idle_host):
    coordinator = await idle_host(ev_configured=False)
    for entity_id in ("sensor.alpha_current", "sensor.alpha_charging", "switch.alpha_charge"):
        hass.states.async_remove(entity_id)
    assert maintenance_blockers(hass, [coordinator]) == ()


async def test_verification_allows_resumed_policy_but_not_missing_sources(hass, idle_host):
    coordinator = await idle_host()
    coordinator.active_controller.charge_session = replace(
        coordinator.active_controller.charge_session, phase="active")
    hass.states.async_set("select.alpha_mode", "Force Charge")
    coordinator.ev_controller.target_current_a = 16
    hass.states.async_set("sensor.alpha_current", 16, {"unit_of_measurement": "A"})
    hass.states.async_set("sensor.alpha_charging", "charging")
    hass.states.async_set("switch.alpha_charge", "on")
    assert maintenance_blockers(hass, [coordinator])
    assert runtime_verification_blockers(hass, [coordinator]) == ()
    hass.states.async_set("sensor.alpha_current", "unavailable")
    assert "ev_feedback_unavailable" in runtime_verification_blockers(hass, [coordinator])
    coordinator.trip_charge._invalid_storage = True
    assert "heo_storage_untrusted" in runtime_verification_blockers(hass, [coordinator])
