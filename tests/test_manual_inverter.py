"""Lifecycle and concurrency tests for the persistent manual inverter handoff."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from homeassistant.util import dt as dt_util

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_BATTERY_FLOOR,
    CONF_BATTERY_SOC,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_REHEARSAL_MODE,
    CONF_SIGN_CONVENTIONS_VERIFIED,
    FOXESS_CONTROL_OWNER_CLOUD,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from custom_components.home_energy_orchestrator.foxess_adapter import FoxessServiceAdapter
from custom_components.home_energy_orchestrator.manual_inverter import ManualInverterController


class MemoryStore:
    """Real asynchronous checkpoints with controllable failure and delay."""

    def __init__(self, payload=None):
        self.payload = deepcopy(payload)
        self.saves = []
        self.loads = 0
        self.fail = False
        self.block_once = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def async_load(self):
        self.loads += 1
        return deepcopy(self.payload)

    async def async_save(self, payload):
        if self.fail:
            raise OSError("storage unavailable")
        snapshot = deepcopy(payload)
        if self.block_once:
            self.block_once = False
            self.started.set()
            await self.release.wait()
        self.payload = snapshot
        self.saves.append(snapshot)


async def _fixture(hass, monkeypatch, *, store=None, unit="kW", **changes):
    values = {
        CONF_AUTOMATIC_CONTROL_ENABLED: True,
        CONF_FOXESS_CONTROL_OWNER: FOXESS_CONTROL_OWNER_MODBUS,
        CONF_REHEARSAL_MODE: False,
        CONF_SIGN_CONVENTIONS_VERIFIED: True,
        CONF_FOXESS_WORK_MODE: "select.inverter_mode",
        CONF_FOXESS_FORCE_CHARGE_POWER: "number.inverter_charge",
        CONF_FOXESS_FORCE_DISCHARGE_POWER: "number.inverter_discharge",
        CONF_INVERTER_DISCHARGE_LIMIT_KW: 7.4,
        CONF_BATTERY_SOC: "sensor.inverter_soc",
        CONF_BATTERY_FLOOR: 10.0,
        **changes,
    }
    coordinator = SimpleNamespace(
        entry_id="manual-inverter-test",
        runtime_config=RuntimeConfiguration.from_mapping(values),
        async_update_listeners=lambda: None,
        data=None,
        snapshot=None,
        telemetry=SimpleNamespace(battery_power=SimpleNamespace(valid=True, fresh=True)),
    )
    relinquished = []

    async def relinquish(entities):
        relinquished.append(entities)

    active = SimpleNamespace(
        _reconcile_lock=asyncio.Lock(), _adapter=None,
        async_relinquish_for_manual=relinquish,
    )
    factor = 1000 if unit == "W" else 1
    hass.states.async_set(
        "select.inverter_mode", "Self Use",
        {"options": ["Self Use", "Force Charge", "Force Discharge"]},
    )
    for entity, maximum in (("number.inverter_charge", 15), ("number.inverter_discharge", 8)):
        hass.states.async_set(entity, "0", {
            "unit_of_measurement": unit, "min": 0, "max": maximum * factor,
            "step": 0.5 * factor,
        })
    hass.states.async_set("sensor.inverter_soc", "70", {"unit_of_measurement": "%"})
    calls = []
    original = FoxessServiceAdapter._async_execute_command

    async def execute(adapter, command):
        # Keep real HA service dispatch/guards while omitting wall-clock dwell.
        from custom_components.home_energy_orchestrator.planner.foxess import FoxessCommand

        await original(adapter, FoxessCommand(command.action, command.value))

    monkeypatch.setattr(FoxessServiceAdapter, "_async_execute_command", execute)

    async def number(call):
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            entity = entity[0]
        calls.append((entity, call.data["value"]))
        state = hass.states.get(entity)
        hass.states.async_set(entity, str(call.data["value"]), dict(state.attributes))

    async def select(call):
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            entity = entity[0]
        calls.append((entity, call.data["option"]))
        state = hass.states.get(entity)
        hass.states.async_set(entity, call.data["option"], dict(state.attributes))

    hass.services.async_register("number", "set_value", number)
    hass.services.async_register("select", "select_option", select)
    controller = ManualInverterController(hass, coordinator, active)
    controller._store = store or MemoryStore()
    controller._repository.store = controller._store
    await controller.async_restore_handoff()
    return controller, coordinator, active, calls, relinquished, values


async def _reconcile(controller):
    async with controller.active_controller._reconcile_lock:
        return await controller.async_reconcile_locked()


async def test_export_sets_native_maximum_then_mode_and_stop_holds_self_use(hass, monkeypatch):
    controller, _, _, calls, relinquished, _ = await _fixture(hass, monkeypatch)
    response = await controller.async_request("export_max", local_control_confirmed=True)

    assert response["accepted"] and response["command_confirmed"]
    assert response["power_kw"] == 7.0  # Commissioned 7.4, native 8, native step 0.5.
    assert calls == [
        ("number.inverter_discharge", 7.0), ("select.inverter_mode", "Force Discharge"),
    ]
    assert controller.is_active and controller.target == "export_max"
    assert controller._store.payload["phase"] == "held"

    calls.clear()
    stopped = await controller.async_request("self_use")
    assert stopped["accepted"] and stopped["command_confirmed"]
    assert calls == [("select.inverter_mode", "Self Use"), ("number.inverter_discharge", 0.0)]
    assert controller.is_active and controller.target == "self_use"
    assert len(relinquished) == 2


async def test_export_converts_native_watts_without_assuming_kw_actuator(hass, monkeypatch):
    controller, _, _, calls, _, _ = await _fixture(hass, monkeypatch, unit="W")
    response = await controller.async_request("export_max", local_control_confirmed=True)
    assert response["power_kw"] == 7.0
    assert calls[0] == ("number.inverter_discharge", 7000.0)
    assert response["command_confirmed"]


async def test_stop_clears_both_targets_without_test_or_ledger(hass, monkeypatch):
    controller, coordinator, _, calls, _, _ = await _fixture(hass, monkeypatch)
    hass.states.async_set("select.inverter_mode", "Force Charge", {
        "options": ["Self Use", "Force Charge", "Force Discharge"],
    })
    for entity in ("number.inverter_charge", "number.inverter_discharge"):
        state = hass.states.get(entity)
        hass.states.async_set(entity, "3", dict(state.attributes))
    assert coordinator.data is None and coordinator.snapshot is None

    response = await controller.async_request("self_use")
    assert response["command_confirmed"] and controller.is_active
    assert calls == [
        ("select.inverter_mode", "Self Use"), ("number.inverter_charge", 0.0),
        ("number.inverter_discharge", 0.0),
    ]


@pytest.mark.parametrize("gate", ["safety", "owner", "master", "mapping", "native_metadata"])
async def test_closed_gates_preserve_stop_obligation_without_commands(hass, monkeypatch, gate):
    controller, coordinator, _, calls, _, values = await _fixture(hass, monkeypatch)
    if gate == "safety":
        values[CONF_REHEARSAL_MODE] = True
    elif gate == "owner":
        values[CONF_FOXESS_CONTROL_OWNER] = FOXESS_CONTROL_OWNER_CLOUD
    elif gate == "master":
        values[CONF_AUTOMATIC_CONTROL_ENABLED] = False
    elif gate == "mapping":
        values[CONF_FOXESS_WORK_MODE] = None
    else:
        hass.states.async_set("number.inverter_discharge", "0", {"unit_of_measurement": "kW"})
    coordinator.runtime_config = RuntimeConfiguration.from_mapping(values)
    response = await controller.async_request("self_use")
    assert response["accepted"] and response["hold"] and not response["command_confirmed"]
    assert not calls
    assert controller._store.payload["target"] == "self_use"


async def test_restart_restores_manual_hold_before_reconciliation(hass, monkeypatch):
    controller, coordinator, active, _, _, _ = await _fixture(hass, monkeypatch)
    await controller.async_request("export_max", local_control_confirmed=True)
    restarted = ManualInverterController(hass, coordinator, active)
    restarted._store = controller._store
    restarted._repository.store = restarted._store
    assert restarted.is_active
    await restarted.async_restore_handoff()
    assert restarted.is_active and restarted.target == "export_max"
    await _reconcile(restarted)
    assert restarted.status == "manual_export_max_held"
    assert restarted.attributes()["manual_inverter_command_confirmed"]


async def test_load_is_once_only_even_when_multiple_consumers_load(hass, monkeypatch):
    controller, _, _, _, _, _ = await _fixture(hass, monkeypatch)
    await asyncio.gather(controller.async_restore_handoff(), controller.async_restore_handoff())
    assert controller._store.loads == 1
    assert not controller.is_active


async def test_resume_waits_for_complete_clean_feedback_before_releasing(hass, monkeypatch):
    controller, _, _, _, _, _ = await _fixture(hass, monkeypatch)
    await controller.async_request("export_max", local_control_confirmed=True)

    async def ignore(_call):
        pass

    hass.services.async_register("number", "set_value", ignore)
    hass.services.async_register("select", "select_option", ignore)
    response = await controller.async_request("automatic")
    assert response["hold"] and not response["command_confirmed"]
    assert controller._store.payload["phase"] == "confirming"

    state = hass.states.get("select.inverter_mode")
    hass.states.async_set("select.inverter_mode", "Self Use", dict(state.attributes))
    state = hass.states.get("number.inverter_discharge")
    hass.states.async_set("number.inverter_discharge", "0", dict(state.attributes))
    await _reconcile(controller)
    assert not controller.is_active
    assert controller.status == "automatic"
    assert controller._store.payload["phase"] == "idle"


@pytest.mark.parametrize("payload", ["invalid", {}, {"target": "automatic", "phase": "idle"}])
async def test_corrupt_journals_hold_until_acknowledged_self_use_recovery(
    hass, monkeypatch, payload
):
    controller, _, _, calls, _, _ = await _fixture(hass, monkeypatch, store=MemoryStore(payload))
    assert controller.is_active and controller.status == "manual_journal_untrusted"
    export = await controller.async_request("export_max", local_control_confirmed=True)
    assert not export["accepted"]
    assert not (await controller.async_request("self_use"))["accepted"]
    assert not calls
    result = await controller.async_request("self_use", local_control_confirmed=True)
    assert result["accepted"] and result["command_confirmed"] and result["hold"]


async def test_stop_during_start_persistence_fences_delayed_positive_write(hass, monkeypatch):
    store = MemoryStore()
    controller, _, _, calls, _, _ = await _fixture(hass, monkeypatch, store=store)
    store.block_once = True
    start = asyncio.create_task(
        controller.async_request("export_max", local_control_confirmed=True)
    )
    await store.started.wait()
    stop = asyncio.create_task(controller.async_request("self_use"))
    await asyncio.sleep(0)
    assert controller.target == "self_use" and controller.generation == 2
    store.release.set()
    await asyncio.gather(start, stop)
    assert not calls  # Already clean; the delayed export never gets a command.
    assert controller.is_active and controller.target == "self_use"
    assert store.payload["target"] == "self_use"


async def test_stop_during_power_service_prevents_following_force_mode(hass, monkeypatch):
    controller, _, _, calls, _, _ = await _fixture(hass, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_number(call):
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            entity = entity[0]
        calls.append((entity, call.data["value"]))
        entered.set()
        await release.wait()
        state = hass.states.get(entity)
        hass.states.async_set(entity, str(call.data["value"]), dict(state.attributes))

    hass.services.async_register("number", "set_value", delayed_number)
    start = asyncio.create_task(
        controller.async_request("export_max", local_control_confirmed=True)
    )
    await entered.wait()
    stop = asyncio.create_task(controller.async_request("self_use"))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(start, stop)
    assert ("select.inverter_mode", "Force Discharge") not in calls
    assert hass.states.get("number.inverter_discharge").state == "0.0"
    assert controller.target == "self_use" and controller.is_active


async def test_gate_closure_during_service_prevents_remaining_plan(hass, monkeypatch):
    controller, coordinator, _, calls, _, values = await _fixture(hass, monkeypatch)

    async def closing_number(call):
        calls.append(("number", call.data["value"]))
        values[CONF_REHEARSAL_MODE] = True
        coordinator.runtime_config = RuntimeConfiguration.from_mapping(values)

    hass.services.async_register("number", "set_value", closing_number)
    response = await controller.async_request("export_max", local_control_confirmed=True)
    assert calls == [("number", 7.0)]
    assert response["hold"] and not response["command_confirmed"]


async def test_native_ceiling_change_during_service_blocks_stale_mode_selection(hass, monkeypatch):
    controller, _, _, calls, _, _ = await _fixture(hass, monkeypatch)

    async def changing_number(call):
        calls.append(("number", call.data["value"]))
        state = hass.states.get("number.inverter_discharge")
        hass.states.async_set("number.inverter_discharge", "7", {
            **state.attributes, "max": 5,
        })

    hass.services.async_register("number", "set_value", changing_number)
    response = await controller.async_request("export_max", local_control_confirmed=True)
    assert calls == [("number", 7.0)]
    assert not response["command_confirmed"] and controller.is_active


async def test_replayed_and_expired_export_is_rejected_without_state_change(hass, monkeypatch):
    controller, _, _, calls, _, _ = await _fixture(hass, monkeypatch)
    stamp = dt_util.utcnow()
    accepted = await controller.async_request(
        "export_max", local_control_confirmed=True,
        request_id="export-one", issued_at=stamp.isoformat(),
    )
    duplicate = await controller.async_request(
        "export_max", local_control_confirmed=True,
        request_id="export-one", issued_at=stamp.isoformat(),
    )
    assert accepted["accepted"] and duplicate["accepted"]
    assert controller.generation == 1
    await controller.async_request(
        "self_use", request_id="stop-one",
        issued_at=(stamp + timedelta(microseconds=1)).isoformat(),
    )
    calls.clear()
    replay = await controller.async_request(
        "export_max", local_control_confirmed=True,
        request_id="export-one", issued_at=stamp.isoformat(),
    )
    assert not replay["accepted"] and replay["request_id"] == "export-one"
    assert replay["current_request_id"] == "stop-one"
    assert controller.generation == 2 and not calls

    fresh, _, _, _, _, _ = await _fixture(hass, monkeypatch)
    for offset in (-31, 6):
        rejected = await fresh.async_request(
            "export_max", local_control_confirmed=True, request_id=f"expired-{offset}",
            issued_at=(dt_util.utcnow() + timedelta(seconds=offset)).isoformat(),
        )
        assert not rejected["accepted"] and fresh.generation == 0


async def test_storage_failure_keeps_fence_and_never_sends_hardware_command(hass, monkeypatch):
    controller, _, _, calls, _, _ = await _fixture(hass, monkeypatch)
    controller._store.fail = True
    response = await controller.async_request("export_max", local_control_confirmed=True)
    assert response["hold"] and response["status"] == "manual_storage_unavailable"
    assert not calls


async def test_cancelled_stop_checkpoint_finishes_before_restart(hass, monkeypatch):
    store = MemoryStore()
    controller, coordinator, active, _, _, _ = await _fixture(hass, monkeypatch, store=store)
    await controller.async_request("export_max", local_control_confirmed=True)
    store.block_once = True
    stopped = asyncio.create_task(controller.async_request("self_use"))
    await store.started.wait()
    stopped.cancel()
    store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await stopped
    assert store.payload["target"] == "self_use"
    restarted = ManualInverterController(hass, coordinator, active)
    restarted._store = store
    restarted._repository.store = store
    await restarted.async_restore_handoff()
    await _reconcile(restarted)
    assert restarted.target == "self_use" and restarted.is_active
    assert hass.states.get("select.inverter_mode").state == "Self Use"


async def test_unload_invalidates_inflight_plan_without_erasing_hold(hass, monkeypatch):
    controller, _, _, calls, _, _ = await _fixture(hass, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_number(_call):
        entered.set()
        await release.wait()

    hass.services.async_register("number", "set_value", delayed_number)
    start = asyncio.create_task(
        controller.async_request("export_max", local_control_confirmed=True)
    )
    await entered.wait()
    unload = asyncio.create_task(controller.async_unload())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(start, unload)
    assert not calls
    assert controller.is_active and controller._store.payload["target"] == "export_max"
    assert not (await controller.async_request("self_use"))["accepted"]


async def test_retry_obligation_has_no_terminal_attempt_latch(hass, monkeypatch):
    controller, _, _, calls, _, _ = await _fixture(hass, monkeypatch)

    async def failing(_call):
        raise RuntimeError("actuator unavailable")

    hass.services.async_register("number", "set_value", failing)
    await controller.async_request("export_max", local_control_confirmed=True)
    controller._attempts = 100
    controller._next_retry_at = dt_util.utcnow() - timedelta(seconds=1)
    await _reconcile(controller)
    assert controller._attempts == 101
    assert controller.is_active and not calls
    assert controller._store.payload["attempts"] == 101


@pytest.mark.parametrize("problem", ["missing", "invalid", "stale", "floor", "soc_unknown"])
async def test_export_requires_current_electrical_evidence_and_battery_room(
    hass, monkeypatch, problem
):
    controller, coordinator, _, calls, _, _ = await _fixture(hass, monkeypatch)
    if problem == "missing":
        coordinator.telemetry = None
    elif problem == "invalid":
        coordinator.telemetry.battery_power.valid = False
    elif problem == "stale":
        coordinator.telemetry.battery_power.fresh = False
    elif problem == "floor":
        hass.states.async_set("sensor.inverter_soc", "10", {"unit_of_measurement": "%"})
    else:
        hass.states.async_set("sensor.inverter_soc", "unavailable")
    response = await controller.async_request("export_max", local_control_confirmed=True)
    assert response["accepted"] and response["hold"] and not response["command_confirmed"]
    assert not calls
    stopped = await controller.async_request("self_use")
    assert stopped["command_confirmed"]  # Cleanup does not require electrical telemetry.


async def test_cached_native_settings_and_soc_do_not_expire_as_fast_power(
    hass, monkeypatch, freezer
):
    controller, _, _, calls, _, _ = await _fixture(hass, monkeypatch)
    freezer.tick(timedelta(hours=3))
    response = await controller.async_request("export_max", local_control_confirmed=True)
    assert response["command_confirmed"] and calls


async def test_original_mapping_obligation_survives_restart_and_blocks_rebinding(hass, monkeypatch):
    controller, coordinator, active, _, _, values = await _fixture(hass, monkeypatch)
    await controller.async_request("export_max", local_control_confirmed=True)
    original = controller._entities
    values[CONF_FOXESS_WORK_MODE] = "select.different_inverter_mode"
    coordinator.runtime_config = RuntimeConfiguration.from_mapping(values)
    restarted = ManualInverterController(hass, coordinator, active)
    restarted._store = controller._store
    restarted._repository.store = restarted._store
    await restarted.async_restore_handoff()
    response = await restarted.async_request("self_use")
    assert response["accepted"] and not response["command_confirmed"] and response["hold"]
    assert response["status"] == "manual_blocked_mapping_changed"
    assert restarted._entities == original
    assert restarted._store.payload["entities"]["work_mode_entity"] == "select.inverter_mode"


async def test_request_ordering_survives_restart_and_equal_time_stop_wins(hass, monkeypatch):
    controller, coordinator, active, calls, _, _ = await _fixture(hass, monkeypatch)
    stamp = dt_util.utcnow().isoformat()
    await controller.async_request(
        "export_max", local_control_confirmed=True, request_id="first", issued_at=stamp,
    )
    await controller.async_request("self_use", request_id="stop", issued_at=stamp)
    restarted = ManualInverterController(hass, coordinator, active)
    restarted._store = controller._store
    restarted._repository.store = restarted._store
    await restarted.async_restore_handoff()
    calls.clear()
    result = await restarted.async_request(
        "export_max", local_control_confirmed=True, request_id="first", issued_at=stamp,
    )
    assert not result["accepted"] and result["request_id"] == "first"
    assert result["current_request_id"] == "stop"
    assert restarted.target == "self_use" and restarted.is_active and not calls


async def test_local_export_then_stop_wins_at_same_timestamp_without_request_id(
    hass, monkeypatch, freezer
):
    controller, _, _, _, _, _ = await _fixture(hass, monkeypatch)
    freezer.move_to(dt_util.utcnow())
    exported = await controller.async_request("export_max", local_control_confirmed=True)
    export_stamp = controller._last_issued_at
    stopped = await controller.async_request("self_use")
    assert exported["accepted"] and stopped["accepted"] and stopped["command_confirmed"]
    assert controller._last_issued_at == export_stamp
    assert controller.generation == 2 and controller.target == "self_use"
    assert controller.is_active


async def test_gate_change_during_relinquish_cannot_release_clean_resume(hass, monkeypatch):
    controller, coordinator, active, calls, _, values = await _fixture(hass, monkeypatch)

    async def relinquish(_entities):
        values[CONF_REHEARSAL_MODE] = True
        coordinator.runtime_config = RuntimeConfiguration.from_mapping(values)

    active.async_relinquish_for_manual = relinquish
    response = await controller.async_request("automatic")
    assert response["accepted"] and response["hold"] and not response["command_confirmed"]
    assert controller.status == "manual_blocked_safety_lock"
    assert controller._store.payload["phase"] == "pending"
    assert not calls


async def test_mapping_change_during_resume_checkpoint_preserves_original_obligation(
    hass, monkeypatch
):
    controller, coordinator, _, _, _, values = await _fixture(hass, monkeypatch)
    store = controller._store
    save = store.async_save

    async def change_after_idle(payload):
        await save(payload)
        if payload["phase"] == "idle":
            values[CONF_FOXESS_WORK_MODE] = "select.different_inverter_mode"
            coordinator.runtime_config = RuntimeConfiguration.from_mapping(values)

    store.async_save = change_after_idle
    response = await controller.async_request("automatic")
    assert response["hold"] and not response["command_confirmed"]
    assert controller.status == "manual_blocked_mapping_changed"
    assert store.payload["phase"] == "pending"
    assert store.payload["entities"]["work_mode_entity"] == "select.inverter_mode"


async def test_duplicate_reports_current_feedback_without_reassertion(hass, monkeypatch):
    controller, _, _, calls, _, _ = await _fixture(hass, monkeypatch)
    stamp = dt_util.utcnow().isoformat()
    await controller.async_request(
        "export_max", local_control_confirmed=True, request_id="first", issued_at=stamp,
    )
    mode = hass.states.get("select.inverter_mode")
    hass.states.async_set("select.inverter_mode", "Self Use", dict(mode.attributes))
    calls.clear()
    response = await controller.async_request(
        "export_max", local_control_confirmed=True, request_id="first", issued_at=stamp,
    )
    assert response["accepted"] and not response["command_confirmed"]
    assert not calls and controller.generation == 1


async def test_incomplete_mapping_request_cannot_forget_later_bound_mapping(hass, monkeypatch):
    controller, coordinator, _, calls, _, values = await _fixture(
        hass, monkeypatch, **{CONF_FOXESS_WORK_MODE: None},
    )
    response = await controller.async_request("self_use")
    assert response["accepted"] and not response["command_confirmed"] and not calls
    values[CONF_FOXESS_WORK_MODE] = "select.inverter_mode"
    coordinator.runtime_config = RuntimeConfiguration.from_mapping(values)
    await _reconcile(controller)
    assert controller.status == "manual_self_use_held"
    assert controller._store.payload["entities"]["work_mode_entity"] == "select.inverter_mode"


async def test_unload_fences_automatic_idle_without_creating_restart_manual_hold(hass, monkeypatch):
    controller, coordinator, active, _, _, _ = await _fixture(hass, monkeypatch)
    assert not controller.is_active
    await controller.async_unload()
    assert controller.is_active
    restarted = ManualInverterController(hass, coordinator, active)
    restarted._store = controller._store
    restarted._repository.store = restarted._store
    await restarted.async_restore_handoff()
    assert not restarted.is_active
