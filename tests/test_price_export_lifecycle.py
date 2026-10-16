"""Actual HA setup/reload and dispatch-source recovery for the price export path."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.home_energy_orchestrator.aemo_monitor import AemoMarketMonitor
from custom_components.home_energy_orchestrator.const import DOMAIN
from tests.helpers.lifecycle import LifecycleHarness
from tests.test_aemo_dispatch_feed import dispatch_report
from tests.test_price_export_active import (
    DISCHARGE,
    MODE,
    NOW,
    PRICE_CONFIG,
    register_price_services,
    seed_price_states,
)
from tests.test_setup import ENTRY_DATA


@pytest.fixture
async def price_lifecycle(hass, monkeypatch, freezer):
    freezer.move_to(NOW)
    harness = LifecycleHarness(hass)
    calls = []
    # Install the domain services first so platform setup cannot replace the
    # fake inverter backend registered below during integration setup.
    await async_setup_component(hass, "number", {})
    await async_setup_component(hass, "select", {})
    register_price_services(hass, monkeypatch, calls, harness)
    seed_price_states(hass)
    feed = AsyncMock(side_effect=lambda: dispatch_report(dt_util.utcnow(), price=5000))
    monkeypatch.setattr(AemoMarketMonitor, "_async_fetch_summary", feed)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY_DATA, **PRICE_CONFIG},
        version=6,
        title="Price lifecycle test",
    )
    entry.add_to_hass(hass)
    await harness.setup(entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    try:
        yield harness, entry, calls, feed
    finally:
        await harness.unload(entry)
        harness.close()


async def test_exact_threshold_after_reload_uses_actual_feed_and_stops_below(
    price_lifecycle,
):
    harness, entry, calls, feed = price_lifecycle
    await harness.unload(entry)
    feed.side_effect = lambda: dispatch_report(dt_util.utcnow(), price=3000)
    seed_price_states(harness.hass)
    calls.clear()
    await harness.setup(entry)
    await harness.hass.async_block_till_done(wait_background_tasks=True)
    active = entry.runtime_data.active_controller
    monitor = entry.runtime_data.market_monitor
    assert monitor.current_result.price_per_kwh == 3
    assert monitor.current_result.status == "possible_export_event"
    assert monitor.current_result.price_trigger_valid
    # Restart restoration is a separate tick: fresh equality permission must
    # not bypass clearing the previous session before a new positive command.
    assert (MODE, "Self Use") in calls
    await active.async_reconcile()
    await harness.hass.async_block_till_done(wait_background_tasks=True)
    assert (MODE, "Force Discharge") in calls
    assert active.export_session.authority_source == "price"
    assert active.export_plan.sellable_energy_kwh > 0
    feed.side_effect = lambda: dispatch_report(dt_util.utcnow(), price=2999.99, serial=2)
    calls.clear()
    await monitor.async_refresh()
    await harness.hass.async_block_till_done(wait_background_tasks=True)
    assert monitor.current_result.status == "watching"
    assert (MODE, "Self Use") in calls
    assert float(harness.hass.states.get(DISCHARGE).state) == 0
    assert (MODE, "Force Discharge") not in calls


async def test_setup_and_reload_require_fresh_dispatch_before_same_owner_readmission(
    price_lifecycle
):
    harness, entry, calls, _ = price_lifecycle
    coordinator = entry.runtime_data
    assert coordinator.market_monitor.current_result.price_trigger_valid
    assert coordinator.market_monitor.current_result.source_kind == "dispatchis"
    assert (MODE, "Force Discharge") in calls
    stored = await harness.load_store(f"{DOMAIN}.{entry.entry_id}.export_session")
    assert stored["authority_source"] == "price"
    assert stored["price_actuator_entities"][0] == MODE
    calls.clear()
    await harness.reload(entry)
    await harness.hass.async_block_till_done(wait_background_tasks=True)
    assert (MODE, "Self Use") in calls
    await entry.runtime_data.active_controller.async_reconcile()
    await harness.hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.active_controller.export_session.authority_source == "price"
    assert calls.index((MODE, "Self Use")) < calls.index((MODE, "Force Discharge"))


async def test_restarted_expired_price_restores_before_new_permission(price_lifecycle, freezer):
    harness, entry, calls, feed = price_lifecycle
    await harness.unload(entry)
    freezer.tick(timedelta(minutes=6))
    feed.side_effect = None
    feed.return_value = dispatch_report(NOW, price=5000)
    seed_price_states(harness.hass)
    calls.clear()
    await harness.setup(entry)
    await harness.hass.async_block_till_done(wait_background_tasks=True)
    assert (MODE, "Self Use") in calls
    assert not any(entity == MODE and value == "Force Discharge" for entity, value in calls)
    assert float(harness.hass.states.get(DISCHARGE).state) == 0
    await entry.runtime_data.active_controller.async_reconcile()
    assert entry.runtime_data.active_controller.export_session.phase == "idle"


async def test_deadline_callback_and_late_old_callback_cannot_revive_export(
    price_lifecycle, monkeypatch
):
    harness, entry, calls, feed = price_lifecycle
    active = entry.runtime_data.active_controller
    callbacks = []

    def schedule(_hass, callback, _deadline):
        callbacks.append(callback)
        return lambda: None

    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.async_track_point_in_utc_time",
        schedule,
    )
    active._schedule_price_deadline()
    old = callbacks[-1]
    response = await active.manual.async_request("self_use")
    assert response["hold"] and response["command_confirmed"]
    calls.clear()
    await old(dt_util.utcnow())
    await harness.hass.async_block_till_done(wait_background_tasks=True)
    assert not calls
    assert active.manual.is_active and active.export_session.phase == "idle"
    assert feed.await_count >= 1


async def test_exact_deadline_restores_without_an_operator_reconcile(price_lifecycle, freezer):
    harness, entry, calls, _ = price_lifecycle
    deadline = entry.runtime_data.active_controller.export_session.price_deadline
    calls.clear()
    freezer.move_to(deadline + timedelta(seconds=1))
    async_fire_time_changed(harness.hass, dt_util.utcnow())
    await harness.hass.async_block_till_done(wait_background_tasks=True)
    assert (MODE, "Self Use") in calls
    assert not any(entity == MODE and value == "Force Discharge" for entity, value in calls)
    assert float(harness.hass.states.get(DISCHARGE).state) == 0
