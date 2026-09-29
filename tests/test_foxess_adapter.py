"""Mocked service-layer tests for the fail-closed FoxESS adapter."""

from __future__ import annotations

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import HomeAssistant

from custom_components.home_energy_orchestrator.foxess_adapter import (
    FoxessEntityMap,
    FoxessServiceAdapter,
    FoxessWriteBlocked,
)
from custom_components.home_energy_orchestrator.planner.foxess import (
    FoxessCommand,
    FoxessCommandPlan,
)

ENTITIES = FoxessEntityMap(
    "select.work_mode", "number.force_charge_power", "number.force_discharge_power"
)


async def test_adapter_blocks_writes_by_default(hass: HomeAssistant) -> None:
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    adapter = FoxessServiceAdapter(hass, ENTITIES)
    plan = FoxessCommandPlan((FoxessCommand("select_mode", "Force Charge"),), "test")

    with pytest.raises(FoxessWriteBlocked):
        await adapter.async_execute(plan)
    assert calls == []


async def test_adapter_rejects_an_incomplete_entity_map(hass: HomeAssistant) -> None:
    with pytest.raises(ValueError):
        FoxessServiceAdapter(
            hass,
            FoxessEntityMap(
                "", ENTITIES.force_charge_power_entity, ENTITIES.force_discharge_power_entity
            ),
        )


async def test_adapter_executes_an_explicit_ordered_plan(hass: HomeAssistant) -> None:
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def noop(call) -> None:
        return None

    hass.services.async_register("number", "set_value", noop)
    hass.services.async_register("select", "select_option", noop)
    adapter = FoxessServiceAdapter(hass, ENTITIES, allow_writes=True)
    plan = FoxessCommandPlan(
        (
            FoxessCommand("set_charge_power", 10),
            FoxessCommand("select_mode", "Force Charge"),
        ),
        "test",
    )

    assert await adapter.async_execute(plan) == ("set_charge_power", "select_mode")
    await hass.async_block_till_done()
    service_data = {
        (event.data["domain"], event.data["service"]): event.data["service_data"]
        for event in calls
    }
    assert service_data[("number", "set_value")] == {
        "entity_id": "number.force_charge_power",
        "value": 10,
    }
    assert service_data[("select", "select_option")] == {
        "entity_id": "select.work_mode",
        "option": "Force Charge",
    }


async def test_adapter_retains_partial_trace_when_a_later_service_fails(
    hass: HomeAssistant,
) -> None:
    async def accept_number(call) -> None:
        return None

    async def reject_select(call) -> None:
        raise RuntimeError("service failed")

    hass.services.async_register("number", "set_value", accept_number)
    hass.services.async_register("select", "select_option", reject_select)
    adapter = FoxessServiceAdapter(hass, ENTITIES, allow_writes=True)
    plan = FoxessCommandPlan(
        (
            FoxessCommand("set_charge_power", 10),
            FoxessCommand("select_mode", "Force Charge"),
        ),
        "test",
    )

    with pytest.raises(RuntimeError, match="service failed"):
        await adapter.async_execute(plan)

    assert adapter.last_executed == ("set_charge_power",)


async def test_adapter_rechecks_safety_guard_before_force_mode_after_delay(
    hass: HomeAssistant, monkeypatch
) -> None:
    """A lock engaged mid-plan must prevent the subsequent forced mode."""
    calls = []
    allowed = True

    async def accept_number(_call) -> None:
        calls.append("power")

    async def accept_select(_call) -> None:
        calls.append("mode")

    async def engage_lock(_seconds) -> None:
        nonlocal allowed
        allowed = False

    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep",
        engage_lock,
    )
    hass.services.async_register("number", "set_value", accept_number)
    hass.services.async_register("select", "select_option", accept_select)
    adapter = FoxessServiceAdapter(
        hass, ENTITIES, allow_writes=True, write_guard=lambda: allowed
    )
    plan = FoxessCommandPlan(
        (
            FoxessCommand("set_charge_power", 10, wait_seconds=5),
            FoxessCommand("select_mode", "Force Charge"),
        ),
        "test",
    )

    with pytest.raises(FoxessWriteBlocked):
        await adapter.async_execute(plan)

    assert calls == ["power"]
    assert adapter.last_executed == ("set_charge_power",)
