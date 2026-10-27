"""Action receipts describe completed calls, never native vehicle feedback."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.ev_adapter import (
    EvEntityMap,
    EvServiceAdapter,
    EvWriteBlocked,
)
from custom_components.home_energy_orchestrator.planner.ev import EvCommand, EvCommandPlan

ENTITIES = EvEntityMap("number.car_current", "number.car_limit", "switch.car_charge")
NOW = datetime(2026, 1, 15, 12, tzinfo=UTC)


async def test_receipts_timestamp_each_completed_ordered_action(hass, freezer):
    freezer.move_to(NOW)

    async def advance(_call):
        freezer.tick(timedelta(seconds=2))

    hass.services.async_register("number", "set_value", advance)
    hass.services.async_register("switch", "turn_on", advance)
    adapter = EvServiceAdapter(hass, ENTITIES, allow_writes=True)
    commands = (
        EvCommand("set_charge_limit", 80),
        EvCommand("set_charge_current", 1),
        EvCommand("start_charging"),
    )

    await adapter.async_execute(EvCommandPlan(commands, "test"))

    assert adapter.last_invoked == adapter.last_executed == tuple(c.action for c in commands)
    assert tuple(receipt.completed_at for receipt in adapter.last_receipts) == (
        NOW + timedelta(seconds=2),
        NOW + timedelta(seconds=4),
        NOW + timedelta(seconds=6),
    )


@pytest.mark.parametrize("failure_index", [0, 1, 2])
async def test_failed_action_gets_no_receipt_and_never_invokes_later_action(hass, failure_index):
    calls = 0

    async def fail_at_index(_call):
        nonlocal calls
        index = calls
        calls += 1
        if index == failure_index:
            raise RuntimeError("uncertain service delivery")

    hass.services.async_register("number", "set_value", fail_at_index)
    hass.services.async_register("switch", "turn_on", fail_at_index)
    adapter = EvServiceAdapter(hass, ENTITIES, allow_writes=True)
    commands = (
        EvCommand("set_charge_limit", 80),
        EvCommand("set_charge_current", 1),
        EvCommand("start_charging"),
    )

    with pytest.raises(RuntimeError, match="uncertain"):
        await adapter.async_execute(EvCommandPlan(commands, "test"))

    assert adapter.last_invoked == tuple(c.action for c in commands[:failure_index + 1])
    assert adapter.last_executed == tuple(c.action for c in commands[:failure_index])
    assert tuple(receipt.action for receipt in adapter.last_receipts) == adapter.last_executed


async def test_closed_guard_clears_previous_receipts_before_any_new_call(hass):
    async def complete(_call):
        return None

    hass.services.async_register("number", "set_value", complete)
    adapter = EvServiceAdapter(hass, ENTITIES, allow_writes=True)
    plan = EvCommandPlan((EvCommand("set_charge_current", 1),), "test")
    await adapter.async_execute(plan)
    assert len(adapter.last_receipts) == 1
    adapter.write_guard = lambda: False

    with pytest.raises(EvWriteBlocked):
        await adapter.async_execute(plan)

    assert adapter.last_invoked == adapter.last_executed == adapter.last_receipts == ()


async def test_cancellation_cannot_claim_completed_current(hass):
    invoked = asyncio.Event()

    async def hang(_call):
        invoked.set()
        await asyncio.Future()

    hass.services.async_register("number", "set_value", hang)
    adapter = EvServiceAdapter(hass, ENTITIES, allow_writes=True)
    task = hass.async_create_task(adapter.async_execute(
        EvCommandPlan((EvCommand("set_charge_current", 1),), "test"),
    ))
    await invoked.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert adapter.last_invoked == ("set_charge_current",)
    assert adapter.last_executed == adapter.last_receipts == ()
