"""Whole controller/service regressions for the Fleet manual battery fence."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.home_energy_orchestrator.active import ActiveFoxessController
from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_BATTERY_FLOOR,
    CONF_BATTERY_SOC,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_REHEARSAL_MODE,
    CONF_SIGN_CONVENTIONS_VERIFIED,
    DOMAIN,
)
from custom_components.home_energy_orchestrator.foxess_adapter import (
    FoxessServiceAdapter,
    FoxessWriteBlocked,
)
from custom_components.home_energy_orchestrator.manual_test import ManualTestController
from custom_components.home_energy_orchestrator.planner.foxess import FoxessCommand
from custom_components.home_energy_orchestrator.services import (
    register_services,
    unregister_services,
)


async def _rig(hass, monkeypatch):
    values = {
        CONF_AUTOMATIC_CONTROL_ENABLED: True,
        CONF_AUTOMATIC_CHARGE_ENABLED: True,
        CONF_AUTOMATIC_EXPORT_ENABLED: True,
        CONF_FOXESS_CONTROL_OWNER: "local_modbus",
        CONF_REHEARSAL_MODE: False,
        CONF_SIGN_CONVENTIONS_VERIFIED: True,
        CONF_FOXESS_WORK_MODE: "select.test_mode",
        CONF_FOXESS_FORCE_CHARGE_POWER: "number.test_charge",
        CONF_FOXESS_FORCE_DISCHARGE_POWER: "number.test_discharge",
        CONF_INVERTER_DISCHARGE_LIMIT_KW: 10.5,
        CONF_BATTERY_SOC: "sensor.test_soc",
        CONF_BATTERY_FLOOR: 10,
    }
    coordinator = SimpleNamespace(
        entry_id="manual-lifecycle",
        runtime_config=RuntimeConfiguration.from_mapping(values),
        snapshot=SimpleNamespace(battery_soc=70, battery_floor_percent=10),
        data=SimpleNamespace(free_energy_remaining_kwh=50),
        telemetry=SimpleNamespace(battery_power=SimpleNamespace(valid=True, fresh=True)),
        async_update_listeners=lambda: None,
        _free_window_hours_remaining=lambda _now: 1,
    )
    coordinator.manual_test = ManualTestController(hass, coordinator)
    active = ActiveFoxessController(hass, coordinator)
    coordinator.active_controller = active
    await active.manual.async_restore_handoff()
    hass.states.async_set(
        "select.test_mode", "Self Use", {"options": ["Self Use", "Force Charge", "Force Discharge"]}
    )
    for entity in ("number.test_charge", "number.test_discharge"):
        hass.states.async_set(
            entity, "0", {"unit_of_measurement": "kW", "min": 0, "max": 10, "step": 0.001}
        )
    hass.states.async_set("sensor.test_soc", "70", {"unit_of_measurement": "%"})
    calls = []

    async def number(call):
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            entity = entity[0]
        state = hass.states.get(entity)
        calls.append((entity, call.data["value"]))
        hass.states.async_set(entity, str(call.data["value"]), dict(state.attributes))

    async def select(call):
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            entity = entity[0]
        state = hass.states.get(entity)
        calls.append((entity, call.data["option"]))
        hass.states.async_set(entity, call.data["option"], dict(state.attributes))

    hass.services.async_register("number", "set_value", number)
    hass.services.async_register("select", "select_option", select)
    original = FoxessServiceAdapter._async_execute_command

    async def fast(adapter, command):
        await original(adapter, FoxessCommand(command.action, command.value))

    monkeypatch.setattr(FoxessServiceAdapter, "_async_execute_command", fast)
    return coordinator, active, calls


async def test_fleet_services_hold_export_and_stop_without_changing_auto_or_ev(hass, monkeypatch):
    coordinator, active, calls = await _rig(hass, monkeypatch)
    hass.data[DOMAIN] = {
        coordinator.entry_id: {"coordinator": coordinator, "manual_test": coordinator.manual_test}
    }
    register_services(hass)
    try:
        result = await hass.services.async_call(
            DOMAIN,
            "manual_export_max",
            {"local_control_confirmed": True},
            blocking=True,
            return_response=True,
        )
        assert result["accepted"] and result["command_confirmed"]
        assert result["power_kw"] == 10
        assert not active._writes_still_authorized()
        calls.clear()
        await active.async_reconcile()
        await active.async_supervisory_repair("Self Use")
        assert calls == []
        stopped = await hass.services.async_call(
            DOMAIN, "manual_self_use", {}, blocking=True, return_response=True
        )
        assert stopped["command_confirmed"] and stopped["hold"]
        assert hass.states.get("select.test_mode").state == "Self Use"
        assert float(hass.states.get("number.test_discharge").state) == 0
        assert coordinator.runtime_config.automation.battery_charge_enabled
        assert coordinator.runtime_config.automation.battery_export_enabled
        assert coordinator.manual_test.active_kind is None
    finally:
        unregister_services(hass)


async def test_diagnostic_stop_during_start_checkpoint_cannot_later_force_discharge(
    hass, monkeypatch
):
    coordinator, _, calls = await _rig(hass, monkeypatch)
    diagnostic = coordinator.manual_test
    started, release = asyncio.Event(), asyncio.Event()
    first = True

    async def checkpoint(_state):
        nonlocal first
        if first:
            first = False
            started.set()
            await release.wait()

    monkeypatch.setattr(diagnostic._store, "async_save", AsyncMock(side_effect=checkpoint))
    task = asyncio.create_task(diagnostic.async_start("discharge", 5, 1))
    await started.wait()
    stop = asyncio.create_task(diagnostic.async_stop())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(task, stop)
    assert calls == []
    assert not diagnostic.is_active
    assert diagnostic._cancel_timer is None


async def test_manual_hold_cancels_pending_diagnostic_without_restoring_over_export(
    hass, monkeypatch
):
    coordinator, active, calls = await _rig(hass, monkeypatch)
    diagnostic = coordinator.manual_test
    started, release = asyncio.Event(), asyncio.Event()
    original = diagnostic._store.async_save
    first = True

    async def checkpoint(state):
        nonlocal first
        if first:
            first = False
            started.set()
            await release.wait()
        await original(state)

    monkeypatch.setattr(diagnostic._store, "async_save", checkpoint)
    old = asyncio.create_task(diagnostic.async_start("discharge", 5, 1))
    await started.wait()
    manual = asyncio.create_task(
        active.manual.async_request("export_max", local_control_confirmed=True)
    )
    await asyncio.sleep(0)
    release.set()
    outcomes = await asyncio.gather(old, manual, return_exceptions=True)
    assert outcomes[0] is None or isinstance(outcomes[0], FoxessWriteBlocked)
    assert outcomes[1]["accepted"]
    assert ("number.test_discharge", 5) not in calls
    assert ("select.test_mode", "Self Use") not in calls
    assert not diagnostic.is_active
    assert active.manual.is_active
    assert hass.states.get("select.test_mode").state == "Force Discharge"
    assert float(hass.states.get("number.test_discharge").state) == 10


async def test_diagnostic_stop_during_running_checkpoint_cannot_arm_old_expiry(hass, monkeypatch):
    coordinator, _, _ = await _rig(hass, monkeypatch)
    diagnostic = coordinator.manual_test
    started, release = asyncio.Event(), asyncio.Event()
    original = diagnostic._store.async_save

    async def checkpoint(payload):
        if payload["phase"] == "running":
            started.set()
            await release.wait()
        await original(payload)

    monkeypatch.setattr(diagnostic._store, "async_save", checkpoint)
    old = asyncio.create_task(diagnostic.async_start("discharge", 5, 1))
    await started.wait()
    stop = asyncio.create_task(diagnostic.async_stop())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(old, stop)
    assert diagnostic._cancel_timer is None
    assert diagnostic.phase != "running"
    diagnostic._cancel_callbacks()


async def test_old_diagnostic_callbacks_cannot_stop_new_generation(hass, monkeypatch):
    coordinator, active, calls = await _rig(hass, monkeypatch)
    diagnostic = coordinator.manual_test
    await diagnostic.async_start("discharge", 5, 1)
    old_generation = diagnostic._generation
    await active.manual.async_request("self_use")
    await active.manual.async_request("automatic", local_control_confirmed=True)
    await diagnostic.async_start("discharge", 3, 1)
    calls.clear()
    await diagnostic._async_expire(None, generation=old_generation)
    await diagnostic._async_retry_restore("old_retry", generation=old_generation)
    assert calls == []
    assert diagnostic.phase == "running"
    assert diagnostic.active_kind == "discharge"
    assert float(hass.states.get("number.test_discharge").state) == 3
    diagnostic._cancel_callbacks()


@pytest.mark.parametrize("fail_cancelled_save", [False, True])
async def test_cancelled_diagnostic_running_checkpoint_persists_and_schedules_cleanup(
    hass, monkeypatch, fail_cancelled_save
):
    coordinator, _, calls = await _rig(hass, monkeypatch)
    diagnostic = coordinator.manual_test
    started, release = asyncio.Event(), asyncio.Event()
    original = diagnostic._store.async_save

    async def checkpoint(payload):
        if payload["phase"] == "running":
            started.set()
            await release.wait()
            if fail_cancelled_save:
                raise OSError("interrupted running checkpoint failed")
        await original(payload)

    monkeypatch.setattr(diagnostic._store, "async_save", checkpoint)
    starting = asyncio.create_task(diagnostic.async_start("discharge", 5, 1))
    await started.wait()
    starting.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert diagnostic.is_active and diagnostic.phase == "stopping"
    assert diagnostic._cancel_timer is None and diagnostic._cancel_restore is not None
    saved = await diagnostic._store.async_load()
    assert saved["active_kind"] == "discharge" and saved["phase"] == "stopping"
    assert ("select.test_mode", "Force Discharge") in calls
    cleanup_generation = diagnostic._generation
    diagnostic._cancel_callbacks()
    await diagnostic._async_retry_restore("cancelled_start", generation=cleanup_generation)
    diagnostic._cancel_callbacks()
    await diagnostic._async_retry_restore("cancelled_start", generation=cleanup_generation)
    assert not diagnostic.is_active
    assert hass.states.get("select.test_mode").state == "Self Use"
    assert float(hass.states.get("number.test_discharge").state) == 0
    diagnostic._cancel_callbacks()


async def test_cancelled_diagnostic_mid_service_never_selects_force_mode(hass, monkeypatch):
    coordinator, _, calls = await _rig(hass, monkeypatch)
    diagnostic = coordinator.manual_test
    accepted, release = asyncio.Event(), asyncio.Event()

    async def number(call):
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            entity = entity[0]
        value = call.data["value"]
        state = hass.states.get(entity)
        calls.append((entity, value))
        hass.states.async_set(entity, str(value), dict(state.attributes))
        if value > 0:
            accepted.set()
            await release.wait()

    hass.services.async_register("number", "set_value", number)
    starting = asyncio.create_task(diagnostic.async_start("discharge", 5, 1))
    await accepted.wait()
    starting.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert diagnostic.phase == "stopping" and diagnostic._cancel_restore is not None
    assert ("select.test_mode", "Force Discharge") not in calls
    generation = diagnostic._generation
    diagnostic._cancel_callbacks()
    await diagnostic._async_retry_restore("cancelled_start", generation=generation)
    diagnostic._cancel_callbacks()
    await diagnostic._async_retry_restore("cancelled_start", generation=generation)
    assert not diagnostic.is_active
    assert float(hass.states.get("number.test_discharge").state) == 0
    diagnostic._cancel_callbacks()


async def test_cancelled_diagnostic_cleanup_cannot_overwrite_later_manual_export(hass, monkeypatch):
    coordinator, active, calls = await _rig(hass, monkeypatch)
    diagnostic = coordinator.manual_test
    started, release = asyncio.Event(), asyncio.Event()
    original = diagnostic._store.async_save

    async def checkpoint(payload):
        if payload["phase"] == "running":
            started.set()
            await release.wait()
        await original(payload)

    monkeypatch.setattr(diagnostic._store, "async_save", checkpoint)
    starting = asyncio.create_task(diagnostic.async_start("discharge", 5, 1))
    await started.wait()
    starting.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await starting
    old_cleanup = diagnostic._generation
    response = await active.manual.async_request("export_max", local_control_confirmed=True)
    assert response["command_confirmed"]
    calls.clear()
    await diagnostic._async_retry_restore("cancelled_start", generation=old_cleanup)
    assert not calls
    assert not diagnostic.is_active and diagnostic._cancel_restore is None
    assert hass.states.get("select.test_mode").state == "Force Discharge"
    assert float(hass.states.get("number.test_discharge").state) == 10


async def test_cancelled_diagnostic_initial_checkpoint_never_issues_positive_command(
    hass, monkeypatch
):
    coordinator, _, calls = await _rig(hass, monkeypatch)
    diagnostic = coordinator.manual_test
    started, release = asyncio.Event(), asyncio.Event()
    original = diagnostic._store.async_save

    async def checkpoint(payload):
        if payload["phase"] == "starting":
            started.set()
            await release.wait()
        await original(payload)

    monkeypatch.setattr(diagnostic._store, "async_save", checkpoint)
    starting = asyncio.create_task(diagnostic.async_start("discharge", 5, 1))
    await started.wait()
    starting.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert diagnostic.phase == "stopping" and diagnostic._cancel_restore is not None
    assert calls == []
    saved = await diagnostic._store.async_load()
    assert saved["phase"] == "stopping"
    generation = diagnostic._generation
    diagnostic._cancel_callbacks()
    await diagnostic._async_retry_restore("cancelled_start", generation=generation)
    assert not diagnostic.is_active and calls == []
