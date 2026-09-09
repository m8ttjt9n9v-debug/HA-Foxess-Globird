from __future__ import annotations

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import HomeAssistant

from custom_components.home_energy_orchestrator.ev_adapter import (
    EvEntityMap,
    EvServiceAdapter,
    EvWriteBlocked,
)
from custom_components.home_energy_orchestrator.planner.ev import EvCommand, EvCommandPlan

ENTITIES = EvEntityMap("number.car_current", "number.car_limit", "switch.car_charge")


async def test_ev_adapter_blocks_writes_by_default(hass: HomeAssistant) -> None:
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    adapter = EvServiceAdapter(hass, ENTITIES)
    with pytest.raises(EvWriteBlocked):
        await adapter.async_execute(
            EvCommandPlan((EvCommand("set_charge_current", 10),), "test")
        )
    assert calls == []


async def test_ev_adapter_rejects_incomplete_mapping(hass: HomeAssistant) -> None:
    with pytest.raises(ValueError):
        EvServiceAdapter(hass, EvEntityMap("", "number.car_limit", "switch.car_charge"))


async def test_ev_adapter_preserves_reviewed_command_order(hass: HomeAssistant) -> None:
    calls = []
    execution = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def record_number(call) -> None:
        execution.append(("number", call.data["entity_id"]))

    async def record_switch(call) -> None:
        execution.append(("switch", call.data["entity_id"]))

    hass.services.async_register("number", "set_value", record_number)
    hass.services.async_register("switch", "turn_on", record_switch)
    adapter = EvServiceAdapter(hass, ENTITIES, allow_writes=True)
    plan = EvCommandPlan(
        (
            EvCommand("set_charge_limit", 90),
            EvCommand("set_charge_current", 14),
            EvCommand("start_charging"),
        ),
        "test",
    )
    assert await adapter.async_execute(plan) == (
        "set_charge_limit",
        "set_charge_current",
        "start_charging",
    )
    await hass.async_block_till_done()
    assert execution == [
        ("number", "number.car_limit"),
        ("number", "number.car_current"),
        ("switch", "switch.car_charge"),
    ]
    service_data = [event.data["service_data"] for event in calls]
    assert {
        "entity_id": "number.car_limit",
        "value": 90,
    } in service_data
    assert {
        "entity_id": "number.car_current",
        "value": 14,
    } in service_data


async def test_ev_adapter_retains_partial_trace_when_a_later_service_fails(
    hass: HomeAssistant,
) -> None:
    calls = 0

    async def fail_second(_call) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("transport failed")

    hass.services.async_register("number", "set_value", fail_second)
    adapter = EvServiceAdapter(hass, ENTITIES, allow_writes=True)
    plan = EvCommandPlan(
        (
            EvCommand("set_charge_limit", 90),
            EvCommand("set_charge_current", 14),
        ),
        "test",
    )

    with pytest.raises(RuntimeError, match="transport failed"):
        await adapter.async_execute(plan)

    assert adapter.last_executed == ("set_charge_limit",)


async def test_ev_adapter_rechecks_safety_gate_between_ordered_commands(
    hass: HomeAssistant,
) -> None:
    gate_open = True

    async def close_gate(_call) -> None:
        nonlocal gate_open
        gate_open = False

    hass.services.async_register("number", "set_value", close_gate)
    adapter = EvServiceAdapter(
        hass, ENTITIES, allow_writes=True, write_guard=lambda: gate_open
    )
    plan = EvCommandPlan(
        (
            EvCommand("set_charge_limit", 90),
            EvCommand("set_charge_current", 14),
        ),
        "test",
    )

    with pytest.raises(EvWriteBlocked, match="closed during"):
        await adapter.async_execute(plan)

    assert adapter.last_executed == ("set_charge_limit",)


async def test_ev_adapter_maps_smart_socket_commands_only_to_explicit_outlet(
    hass: HomeAssistant,
) -> None:
    execution = []

    async def record(call) -> None:
        execution.append((call.service, call.data["entity_id"]))

    hass.services.async_register("switch", "turn_on", record)
    hass.services.async_register("switch", "turn_off", record)
    adapter = EvServiceAdapter(
        hass,
        EvEntityMap(
            "number.car_current",
            "number.car_limit",
            "switch.car_charge",
            smart_socket_entity="switch.car_socket",
        ),
        allow_writes=True,
    )
    plan = EvCommandPlan(
        (
            EvCommand("turn_on_smart_socket"),
            EvCommand("turn_off_smart_socket"),
        ),
        "test",
    )

    await adapter.async_execute(plan)

    assert execution == [
        ("turn_on", "switch.car_socket"),
        ("turn_off", "switch.car_socket"),
    ]


async def test_ev_adapter_stops_only_the_explicit_vehicle_charge_switch(
    hass: HomeAssistant,
) -> None:
    execution = []

    async def record(call) -> None:
        execution.append((call.service, call.data["entity_id"]))

    hass.services.async_register("switch", "turn_off", record)
    adapter = EvServiceAdapter(hass, ENTITIES, allow_writes=True)

    await adapter.async_execute(
        EvCommandPlan((EvCommand("stop_charging"),), "allocation_complete")
    )

    assert execution == [("turn_off", "switch.car_charge")]


async def test_ev_adapter_blocks_unmapped_smart_socket(hass: HomeAssistant) -> None:
    adapter = EvServiceAdapter(hass, ENTITIES, allow_writes=True)
    with pytest.raises(EvWriteBlocked, match="not mapped"):
        await adapter.async_execute(
            EvCommandPlan((EvCommand("turn_on_smart_socket"),), "test")
        )
