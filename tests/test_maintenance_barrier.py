"""The process-local maintenance fence is checked at every device boundary."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.home_energy_orchestrator import foxess_adapter as foxess_module
from custom_components.home_energy_orchestrator.active import ActiveFoxessController
from custom_components.home_energy_orchestrator.coordinator import EnergyCoordinator
from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.ev_adapter import (
    EvEntityMap,
    EvServiceAdapter,
    EvWriteBlocked,
)
from custom_components.home_energy_orchestrator.foxess_adapter import (
    FoxessEntityMap,
    FoxessServiceAdapter,
    FoxessWriteBlocked,
)
from custom_components.home_energy_orchestrator.maintenance_barrier import KEY
from custom_components.home_energy_orchestrator.planner.ev import (
    DirectEvseReconciliationState,
    EvCommand,
    EvCommandPlan,
)
from custom_components.home_energy_orchestrator.planner.foxess import (
    FoxessCommand,
    FoxessCommandPlan,
)
from tests.test_setup import ENTRY_DATA

FOXESS = FoxessEntityMap("select.test_mode", "number.test_charge", "number.test_discharge")
EV = EvEntityMap(
    "number.test_ev_current", "number.test_ev_limit", "switch.test_ev_charge",
    smart_socket_entity="switch.test_ev_socket",
)


def _physical_services(hass, callback=None):
    """Use the real HA registry; replace only physical device service handlers."""
    calls = []

    async def record(call):
        calls.append((call.domain, call.service, dict(call.data)))
        if callback is not None:
            await callback(call)

    for domain, service in (
        ("number", "set_value"), ("select", "select_option"),
        ("switch", "turn_on"), ("switch", "turn_off"),
    ):
        hass.services.async_register(domain, service, record)
    return calls


def _foxess_plan(*, wait=0):
    return FoxessCommandPlan((
        FoxessCommand("set_charge_power", 0, wait_seconds=wait),
        FoxessCommand("set_discharge_power", 8),
        FoxessCommand("select_mode", "Force Discharge"),
    ), "reviewed_test_plan")


def _ev_plan():
    return EvCommandPlan((
        EvCommand("set_charge_limit", 90),
        EvCommand("set_charge_current", 6),
        EvCommand("start_charging"),
        EvCommand("turn_on_smart_socket"),
        EvCommand("stop_charging"),
        EvCommand("turn_off_smart_socket"),
    ), "reviewed_test_plan")


@pytest.mark.parametrize("action,value", [
    ("set_charge_power", 5), ("set_discharge_power", 8), ("select_mode", "Self Use"),
])
async def test_existing_fence_blocks_first_foxess_write(hass, action, value):
    calls = _physical_services(hass)
    adapter = FoxessServiceAdapter(hass, FOXESS, allow_writes=True, write_guard=lambda: True)
    hass.data[KEY] = True
    with pytest.raises(FoxessWriteBlocked, match="maintenance"):
        await adapter.async_execute(FoxessCommandPlan((FoxessCommand(action, value),), "test"))
    assert calls == []
    assert adapter.last_executed == ()


@pytest.mark.parametrize("action,value", [
    ("set_charge_limit", 90), ("set_charge_current", 6),
    ("start_charging", None), ("stop_charging", None),
    ("turn_on_smart_socket", None), ("turn_off_smart_socket", None),
])
async def test_existing_fence_blocks_first_ev_or_socket_write(hass, action, value):
    calls = _physical_services(hass)
    adapter = EvServiceAdapter(hass, EV, allow_writes=True, write_guard=lambda: True)
    hass.data[KEY] = True
    with pytest.raises(EvWriteBlocked, match="maintenance"):
        await adapter.async_execute(EvCommandPlan((EvCommand(action, value),), "test"))
    assert calls == []
    assert adapter.last_executed == ()


@pytest.mark.parametrize("kind", ["foxess", "ev"])
async def test_fence_engaged_by_first_service_blocks_all_remaining_commands(hass, kind):
    async def engage(_call):
        hass.data[KEY] = True

    calls = _physical_services(hass, engage)
    if kind == "foxess":
        adapter = FoxessServiceAdapter(hass, FOXESS, allow_writes=True)
        plan, blocked = _foxess_plan(), FoxessWriteBlocked
        first = "set_charge_power"
    else:
        adapter = EvServiceAdapter(hass, EV, allow_writes=True)
        plan, blocked = _ev_plan(), EvWriteBlocked
        first = "set_charge_limit"
    with pytest.raises(blocked, match="maintenance"):
        await adapter.async_execute(plan)
    assert len(calls) == 1
    assert adapter.last_executed == (first,)


async def test_fence_during_foxess_settle_delay_blocks_later_power_and_mode(hass, monkeypatch):
    calls = _physical_services(hass)
    adapter = FoxessServiceAdapter(hass, FOXESS, allow_writes=True)
    delays = []

    async def settle(seconds):
        delays.append(seconds)
        assert len(calls) == 1
        hass.data[KEY] = True
        await asyncio.sleep(0)

    # Replace the adapter's module binding only; never patch the global asyncio
    # module used by HA's own timers and service dispatch.
    monkeypatch.setattr(foxess_module, "asyncio", SimpleNamespace(sleep=settle))
    with pytest.raises(FoxessWriteBlocked, match="maintenance"):
        await adapter.async_execute(_foxess_plan(wait=5))
    assert delays == [5]
    assert len(calls) == 1
    assert calls[0][:2] == ("number", "set_value")
    assert adapter.last_executed == ("set_charge_power",)


async def test_fence_while_ev_cloud_service_is_awaited_blocks_followup_writes(hass):
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(_call):
        entered.set()
        await release.wait()

    calls = _physical_services(hass, delayed)
    adapter = EvServiceAdapter(hass, EV, allow_writes=True)
    task = asyncio.create_task(adapter.async_execute(_ev_plan()))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert len(calls) == 1
        hass.data[KEY] = True
        release.set()
        with pytest.raises(EvWriteBlocked, match="maintenance"):
            await asyncio.wait_for(task, timeout=1)
    finally:
        release.set()
        if not task.done():
            task.cancel()
    assert len(calls) == 1
    assert adapter.last_executed == ("set_charge_limit",)


@pytest.mark.parametrize("fence", [None, False])
async def test_absent_or_false_fence_preserves_normal_ordered_foxess_plan(hass, fence):
    calls = _physical_services(hass)
    if fence is not None:
        hass.data[KEY] = fence
    adapter = FoxessServiceAdapter(hass, FOXESS, allow_writes=True)
    assert await adapter.async_execute(_foxess_plan()) == (
        "set_charge_power", "set_discharge_power", "select_mode",
    )
    assert calls == [
        ("number", "set_value", {"entity_id": FOXESS.force_charge_power_entity, "value": 0}),
        ("number", "set_value", {"entity_id": FOXESS.force_discharge_power_entity, "value": 8}),
        ("select", "select_option", {
            "entity_id": FOXESS.work_mode_entity, "option": "Force Discharge",
        }),
    ]


@pytest.mark.parametrize("fence", [None, False])
async def test_absent_or_false_fence_preserves_normal_ordered_ev_and_socket_plan(hass, fence):
    calls = _physical_services(hass)
    if fence is not None:
        hass.data[KEY] = fence
    adapter = EvServiceAdapter(hass, EV, allow_writes=True)
    assert await adapter.async_execute(_ev_plan()) == tuple(c.action for c in _ev_plan().commands)
    assert calls == [
        ("number", "set_value", {"entity_id": EV.charge_limit_entity, "value": 90}),
        ("number", "set_value", {"entity_id": EV.charge_current_entity, "value": 6}),
        ("switch", "turn_on", {"entity_id": EV.charge_switch_entity}),
        ("switch", "turn_on", {"entity_id": EV.smart_socket_entity}),
        ("switch", "turn_off", {"entity_id": EV.charge_switch_entity}),
        ("switch", "turn_off", {"entity_id": EV.smart_socket_entity}),
    ]


async def test_foxess_early_reconcile_fence_preserves_real_session_models_and_journals(
    hass, monkeypatch,
):
    calls = _physical_services(hass)
    coordinator = EnergyCoordinator(hass, dict(ENTRY_DATA), "maintenance-barrier")
    active = ActiveFoxessController(hass, coordinator)
    await active.manual.async_restore_handoff()
    active.charge_session = replace(active.charge_session, phase="active")
    active.export_session = replace(active.export_session, phase="recovering")
    active.last_reason = "prior_decision"
    active.last_actions = ("prior_action",)
    before = deepcopy((active.charge_session, active.export_session, active.last_reason,
                       active.last_actions, active.writes_performed))
    saves = []
    for repository in (active._charge_repository, active._export_repository):
        save = AsyncMock(side_effect=AssertionError("Fence must precede session writes"))
        monkeypatch.setattr(repository.store, "async_save", save)
        saves.append(save)
    hass.data[KEY] = True
    try:
        await active.async_reconcile()
        assert (active.charge_session, active.export_session, active.last_reason,
                active.last_actions, active.writes_performed) == before
        assert calls == []
        for save in saves:
            save.assert_not_called()
    finally:
        coordinator.shutdown()
        await coordinator.async_shutdown()


async def test_ev_early_reconcile_fence_preserves_real_intent_and_journal(hass, monkeypatch):
    calls = _physical_services(hass)
    coordinator = EnergyCoordinator(hass, dict(ENTRY_DATA), "maintenance-barrier")
    ev = ActiveEvController(hass, coordinator)
    ev.reconciliation = DirectEvseReconciliationState(
        target_current_a=6, target_limit_percent=80, attempts=3, phase="awaiting_feedback",
    )
    ev.outside_control_active = True
    ev.last_reason = "prior_decision"
    ev.last_actions = ("prior_action",)
    before = deepcopy((
        ev.reconciliation, ev.outside_control_active, ev.last_reason, ev.last_actions,
    ))
    save = AsyncMock(side_effect=AssertionError("Fence must precede EV journal writes"))
    monkeypatch.setattr(ev._repository.store, "async_save", save)
    hass.data[KEY] = True
    try:
        await ev.async_reconcile()
        assert (
            ev.reconciliation, ev.outside_control_active, ev.last_reason, ev.last_actions,
        ) == before
        assert calls == []
        save.assert_not_called()
    finally:
        coordinator.shutdown()
        await coordinator.async_shutdown()
