"""An obsolete direct command episode ends only after qualified idle unplug."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.helpers.storage import Store

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.planner.ev import (
    DirectEvseReconciliationState,
    SmartSocketRecoveryState,
)
from custom_components.home_energy_orchestrator.planner.ev_outside_window import PreFreeSessionState
from tests.test_ev_active import _controller_config, _coordinator, _set_ev_states

NOW = datetime(2026, 9, 17, 12, 30, tzinfo=UTC)
pytestmark = pytest.mark.freeze_time(NOW)


def _orphan(hass, **config):
    _set_ev_states(hass)
    coordinator = _coordinator(_controller_config(**config))
    controller = ActiveEvController(hass, coordinator)
    controller.reconciliation = DirectEvseReconciliationState(
        target_current_a=8, target_limit_percent=90, attempts=2,
        last_command_at=NOW - timedelta(minutes=5), phase="awaiting_feedback",
    )
    controller.target_current_a = 8
    controller.target_limit_percent = 90
    controller.last_decision_at = NOW
    hass.states.async_set("device_tracker.car", "not_home")
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("sensor.car_charging", "disconnected")
    hass.states.async_set("sensor.car_actual_current", 2, {"unit_of_measurement": "A"})
    hass.states.async_set("number.car_current", 16, {"min": 1, "max": 16, "step": 1})
    return controller


@pytest.mark.parametrize("config", [
    {}, {"ev_automatic_control_enabled": False}, {"rehearsal_mode": True},
    {"site_phase_count": 3, "site_grid_current_entity": "sensor.missing_current"},
])
async def test_unowned_disconnected_episode_retires_without_any_command(hass, config):
    controller = _orphan(hass, **config)
    await controller._async_save(NOW)
    calls = []
    remove = hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    try:
        await controller.async_reconcile(NOW + timedelta(seconds=1))
        assert controller.reconciliation == DirectEvseReconciliationState()
        assert controller.target_current_a is None and controller.target_limit_percent is None
        assert controller.last_decision_at is None and controller._decision_fingerprint is None
        assert controller.last_actions == () and controller.writes_performed == 0
        assert calls == []
        payload = await controller._repository.store.async_load()
        assert payload["reconciliation"]["phase"] == "idle"
        assert payload["reconciliation"]["target_current_a"] is None
        assert payload["reconciliation"]["attempts"] == 0
    finally:
        remove()


@pytest.mark.parametrize("entity,state,attributes", [
    ("binary_sensor.car_cable", "unknown", {}),
    ("binary_sensor.car_cable", "on", {}),
    ("sensor.car_charging", "unavailable", {}),
    ("sensor.car_charging", "other", {}),
    ("sensor.car_charging", "charging", {}),
    ("switch.car_charge", "unknown", {}),
    ("switch.car_charge", "on", {}),
    ("sensor.car_actual_current", "unknown", {"unit_of_measurement": "A"}),
    ("sensor.car_actual_current", -1, {"unit_of_measurement": "A"}),
])
async def test_uncertain_or_contradictory_feedback_keeps_orphan_pending(
    hass, entity, state, attributes,
):
    controller = _orphan(hass, ev_automatic_control_enabled=False)
    prior = controller.reconciliation
    hass.states.async_set(entity, state, attributes)
    await controller.async_reconcile(NOW)
    assert controller.reconciliation == prior
    assert controller.target_current_a == 8
    assert controller.last_actions == () and controller.writes_performed == 0


@pytest.mark.parametrize("entity", [
    "binary_sensor.car_cable", "sensor.car_charging",
    "sensor.car_actual_current", "switch.car_charge",
])
async def test_stale_feedback_keeps_episode_until_native_reports_recover(hass, freezer, entity):
    controller = _orphan(hass, ev_automatic_control_enabled=False)
    prior = controller.reconciliation
    freezer.tick(timedelta(seconds=91))
    for source in hass.states.async_all():
        if source.entity_id != entity:
            hass.states.async_set(source.entity_id, source.state, dict(source.attributes))
    await controller.async_reconcile(NOW + timedelta(seconds=91))
    assert controller.reconciliation == prior
    source = hass.states.get(entity)
    hass.states.async_set(entity, source.state, dict(source.attributes))
    await controller.async_reconcile(NOW + timedelta(seconds=91))
    assert controller.reconciliation.phase == "idle"
    assert controller.writes_performed == 0


@pytest.mark.parametrize("owner", [
    "prefree", "daily", "stop", "outside", "full", "trip", "trip_cleanup", "recovery", "stage",
    "trip_untrusted",
])
async def test_retirement_does_not_erase_owned_work_when_control_disabled(hass, owner):
    controller = _orphan(hass, ev_automatic_control_enabled=False)
    if owner == "prefree":
        controller.pre_free_session = PreFreeSessionState(True, NOW - timedelta(minutes=1))
    elif owner == "daily":
        controller.daily_backfill_active = True
    elif owner == "stop":
        controller.daily_backfill_stop_pending = True
        hass.states.async_set("switch.car_charge", "on")
    elif owner == "outside":
        controller.outside_control_active = True
    elif owner == "full":
        controller.charge_to_full_started_at = NOW - timedelta(minutes=1)
    elif owner in {"trip", "trip_cleanup", "trip_untrusted"}:
        controller.coordinator.trip_charge = SimpleNamespace(
            owns_full=owner == "trip",
            _state=SimpleNamespace(cleanup_pending=owner == "trip_cleanup"),
            _loaded=True, _invalid_storage=owner == "trip_untrusted",
            _storage_error=False, _dirty=False,
            async_reconcile_before_ev_locked=AsyncMock(return_value=True),
        )
    elif owner == "recovery":
        controller.smart_recovery = SmartSocketRecoveryState(phase="power_off_dwell")
    else:
        controller.smart_stage_started_at = NOW
    prior = controller.reconciliation
    await controller.async_reconcile(NOW)
    assert controller.reconciliation == prior
    assert controller.target_current_a == 8 and controller.writes_performed == 0
    if owner == "stop":
        assert controller.daily_backfill_stop_pending
    if owner == "full":
        assert controller.charge_to_full_started_at == NOW - timedelta(minutes=1)
    if owner == "recovery":
        assert controller.smart_recovery.phase == "power_off_dwell"


@pytest.mark.parametrize("invalid", [-1, float("nan"), True])
async def test_invalid_target_is_not_silently_retired(hass, invalid):
    controller = _orphan(hass, ev_automatic_control_enabled=False)
    controller.target_current_a = invalid
    prior = controller.reconciliation
    await controller.async_reconcile(NOW)
    assert controller.reconciliation == prior


async def test_smart_socket_episode_is_not_a_direct_retirement(hass):
    controller = _orphan(
        hass, ev_automatic_control_enabled=False, ev_charge_path="smart_socket",
        ev_smart_socket_entity="switch.car_socket", ev_smart_socket_current_limit_a=10,
    )
    prior = controller.reconciliation
    await controller.async_reconcile(NOW)
    assert controller.reconciliation == prior
    assert controller.target_current_a == 8 and controller.writes_performed == 0


async def test_retired_episode_stays_retired_after_restore(hass, freezer):
    controller = _orphan(hass)
    await controller._async_save(NOW)
    await controller.async_reconcile(NOW + timedelta(seconds=1))
    freezer.tick(timedelta(seconds=2))
    restored = ActiveEvController(hass, controller.coordinator)
    await restored._async_restore()
    assert restored.reconciliation == DirectEvseReconciliationState()
    assert restored.target_current_a is None and restored.target_limit_percent is None
    await restored.async_reconcile(NOW + timedelta(seconds=2))
    assert restored.writes_performed == 0


async def test_unqualified_restore_preserves_original_retry_episode(hass, freezer):
    controller = _orphan(hass, ev_automatic_control_enabled=False)
    await controller._async_save(NOW)
    prior = controller.reconciliation
    freezer.tick(timedelta(seconds=91))
    restored = ActiveEvController(hass, controller.coordinator)
    await restored._async_restore()
    await restored.async_reconcile(NOW + timedelta(seconds=91))
    assert restored.reconciliation == prior
    assert restored.writes_performed == 0


async def test_replug_recalculates_instead_of_resuming_previous_target(hass):
    _set_ev_states(hass)
    controller = ActiveEvController(hass, _coordinator(_controller_config(rehearsal_mode=True)))
    await controller.async_reconcile(NOW)
    controller.reconciliation = DirectEvseReconciliationState(
        8, 90, 2, NOW, "awaiting_feedback",
    )
    controller.target_current_a = 8
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("sensor.car_charging", "disconnected")
    await controller.async_reconcile(NOW + timedelta(seconds=1))
    hass.states.async_set("binary_sensor.car_cable", "on")
    hass.states.async_set("sensor.car_charging", "stopped")
    await controller.async_reconcile(NOW + timedelta(seconds=2))
    assert controller.last_decision_at == NOW + timedelta(seconds=2)
    assert controller.target_current_a != 8
    assert controller.writes_performed == 0


@pytest.mark.parametrize("stop_pending", [False, True])
async def test_failed_retirement_checkpoint_retains_pending_state(hass, monkeypatch, stop_pending):
    controller = _orphan(hass)
    controller.daily_backfill_stop_pending = stop_pending
    controller.outside_stop_requested = stop_pending
    controller.outside_control_active = stop_pending
    prior = controller.reconciliation
    monkeypatch.setattr(
        controller, "_async_save", AsyncMock(side_effect=OSError("disk unavailable")),
    )
    with pytest.raises(OSError, match="disk unavailable"):
        await controller.async_reconcile(NOW)
    assert controller.reconciliation == prior
    assert controller.target_current_a == 8 and controller.writes_performed == 0
    assert controller.daily_backfill_stop_pending is stop_pending
    assert controller.outside_stop_requested is stop_pending
    assert controller.outside_control_active is stop_pending


async def test_retirement_leaves_interrupted_maintenance_audit_untouched(hass):
    controller = _orphan(hass)
    audit_store = Store(hass, 1, "home_energy_orchestrator.maintenance", private=True)
    audit = {"phase": "interrupted", "version": "v0.12.44", "backup_id": "saved-backup"}
    await audit_store.async_save(audit)
    await controller.async_reconcile(NOW)
    assert controller.reconciliation.phase == "idle"
    assert await audit_store.async_load() == audit


async def test_owned_stop_finishes_through_existing_switch_feedback_before_retirement(hass):
    controller = _orphan(
        hass, free_charge_window_start="20:00:00", free_charge_window_end="21:00:00",
    )
    hass.states.async_set("device_tracker.car", "home")
    hass.states.async_set("binary_sensor.car_cable", "on")
    hass.states.async_set("sensor.car_charging", "charging")
    hass.states.async_set("switch.car_charge", "on")
    controller.daily_backfill_stop_pending = True
    controller.outside_control_active = True
    calls = []

    async def stop(call):
        calls.append(call.service)

    hass.services.async_register("switch", "turn_off", stop)
    await controller.async_reconcile(NOW)
    assert controller.daily_backfill_stop_pending
    assert controller.reconciliation.phase != "idle"
    assert calls == ["turn_off"]
    hass.states.async_set("switch.car_charge", "off")
    hass.states.async_set("sensor.car_charging", "stopped")
    await controller.async_reconcile(NOW + timedelta(seconds=30))
    assert not controller.daily_backfill_stop_pending
    assert calls == ["turn_off"]
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("sensor.car_charging", "disconnected")
    await controller.async_reconcile(NOW + timedelta(seconds=31))
    assert controller.reconciliation.phase == "idle"
    assert calls == ["turn_off"]


@pytest.mark.parametrize("disabled", [False, True])
async def test_immediate_unplug_after_stop_retires_only_with_proved_off_feedback(hass, disabled):
    controller = _orphan(
        hass, free_charge_window_start="20:00:00", free_charge_window_end="21:00:00",
    )
    hass.states.async_set("device_tracker.car", "home")
    hass.states.async_set("binary_sensor.car_cable", "on")
    hass.states.async_set("sensor.car_charging", "charging")
    hass.states.async_set("switch.car_charge", "on")
    controller.daily_backfill_stop_pending = True
    controller.outside_control_active = True
    calls = []

    async def stop(call):
        calls.append(call.service)

    hass.services.async_register("switch", "turn_off", stop)
    await controller.async_reconcile(NOW)
    assert controller.daily_backfill_stop_pending and controller.outside_stop_requested
    assert calls == ["turn_off"]
    if disabled:
        controller.coordinator.update_config_value("ev_automatic_control_enabled", False)
    # An unplug alone cannot erase the still-unproved stop duty.
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("sensor.car_charging", "disconnected")
    await controller.async_reconcile(NOW + timedelta(seconds=1))
    assert controller.daily_backfill_stop_pending and controller.outside_stop_requested
    assert controller.outside_control_active
    # The positively reported switch-off finishes the existing stop transition.
    hass.states.async_set("switch.car_charge", "off")
    await controller.async_reconcile(NOW + timedelta(seconds=2))
    assert not controller.daily_backfill_stop_pending and not controller.outside_stop_requested
    assert not controller.outside_control_active
    assert controller.reconciliation == DirectEvseReconciliationState()
    payload = await controller._repository.store.async_load()
    assert payload["daily_backfill"]["stop_pending"] is False
    assert payload["reconciliation"]["phase"] == "idle"
    assert calls == ["turn_off"]
