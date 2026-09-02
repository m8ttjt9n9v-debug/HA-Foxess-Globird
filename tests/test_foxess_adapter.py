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
    assert [(event.data["domain"], event.data["service"]) for event in calls] == [
        ("number", "set_value"),
        ("select", "select_option"),
    ]
    assert calls[0].data["service_data"] == {
        "entity_id": "number.force_charge_power",
        "value": 10,
    }
    assert calls[1].data["service_data"] == {
        "entity_id": "select.work_mode",
        "option": "Force Charge",
    }
