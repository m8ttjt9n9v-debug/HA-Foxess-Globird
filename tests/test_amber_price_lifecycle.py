"""Native Amber evidence through actual HEO setup, listeners, services and reload."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

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

_SITE_ID = "sanitised-test-account"
_AMBER_ENTITY = "sensor.test_amber_feed_in_price"


def _amber_attributes(*, price=4.4, estimate=False):
    now = dt_util.utcnow()
    start = now.replace(minute=now.minute - now.minute % 5, second=0, microsecond=0)
    return {
        "unit_of_measurement": "$/kWh",
        "duration": 5,
        "estimate": estimate,
        "spot_per_kwh": price,
        "start_time": (start + timedelta(seconds=1)).isoformat(),
        "end_time": (start + timedelta(minutes=5)).isoformat(),
        "channel_type": "feedIn",
    }


@pytest.fixture
async def amber_lifecycle(hass, monkeypatch, freezer, request):
    """Use a registered native provider without setting up its real HTTP client."""
    freezer.move_to(NOW)
    harness = LifecycleHarness(hass)
    calls = []
    await async_setup_component(hass, "number", {})
    await async_setup_component(hass, "select", {})
    register_price_services(hass, monkeypatch, calls, harness)
    seed_price_states(hass)
    provider = MockConfigEntry(
        domain="amberelectric",
        title="Sanitised Amber account",
        data={"site_id": _SITE_ID},
        state=ConfigEntryState.LOADED,
    )
    provider.add_to_hass(hass)
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "sensor", "amberelectric", f"{_SITE_ID}-current-feed_in",
        config_entry=provider, suggested_object_id="test_amber_feed_in_price",
    )
    assert entity.entity_id == _AMBER_ENTITY
    # Deliberately unrelated tariff state: using this value instead of the
    # wholesale attribute must fail the startup/high-price assertions below.
    hass.states.async_set(_AMBER_ENTITY, "0.12", _amber_attributes(), force_update=True)
    feed = AsyncMock(side_effect=lambda: dispatch_report(dt_util.utcnow(), price=5000))
    monkeypatch.setattr(AemoMarketMonitor, "_async_fetch_summary", feed)
    settings = {
        **ENTRY_DATA,
        **PRICE_CONFIG,
        "amber_price_entity": _AMBER_ENTITY,
        "amber_price_region": "NSW1",
    }
    guard = getattr(request, "param", None)
    if guard == "safety_lock":
        settings["rehearsal_mode"] = True
    elif guard == "free_window":
        local = dt_util.now()
        settings["free_charge_window_start"] = (local - timedelta(hours=1)).time().isoformat()
        settings["free_charge_window_end"] = (local + timedelta(hours=1)).time().isoformat()
    elif guard == "paid_full":
        settings["ev_charge_to_full_enabled"] = True
    elif guard == "no_sellable":
        settings["reserve_kwh"] = 100
    entry = MockConfigEntry(
        domain=DOMAIN, data=settings, version=6, title="Amber lifecycle test",
    )
    entry.add_to_hass(hass)
    await harness.setup(entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    rig = SimpleNamespace(
        hass=hass, harness=harness, entry=entry, provider=provider, calls=calls, feed=feed,
    )
    try:
        yield rig
    finally:
        await harness.unload(entry)
        provider.mock_state(hass, ConfigEntryState.NOT_LOADED)
        harness.close()


async def test_confirmed_amber_starts_then_low_price_stops_despite_high_aemo(
    amber_lifecycle, freezer,
):
    rig = amber_lifecycle
    monitor = rig.entry.runtime_data.market_monitor
    active = rig.entry.runtime_data.active_controller
    assert monitor.current_result.source_kind == "amber"
    assert monitor.current_result.price_per_kwh == 4
    assert monitor.current_result.price_trigger_valid
    assert (MODE, "Force Discharge") in rig.calls
    assert active.export_session.authority_source == "price"
    rig.calls.clear()
    freezer.tick(timedelta(seconds=1))
    await rig.harness.set_state(_AMBER_ENTITY, 99, _amber_attributes(price=3.29999))
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert monitor.current_result.source_kind == "amber"
    assert monitor.current_result.price_per_kwh < 3
    assert (MODE, "Self Use") in rig.calls
    assert float(rig.hass.states.get(DISCHARGE).state) == 0
    assert (MODE, "Force Discharge") not in rig.calls


@pytest.mark.parametrize("invalid", ["unavailable", "estimate", "thirty_minutes"])
async def test_invalid_amber_uses_current_aemo_without_resetting_session(amber_lifecycle, invalid):
    rig = amber_lifecycle
    monitor = rig.entry.runtime_data.market_monitor
    active = rig.entry.runtime_data.active_controller
    original_deadline = active.export_session.price_deadline
    rig.calls.clear()
    if invalid == "unavailable":
        await rig.harness.set_unavailable(_AMBER_ENTITY)
    else:
        attrs = _amber_attributes(estimate=invalid == "estimate")
        if invalid == "thirty_minutes":
            attrs["duration"] = 30
        await rig.harness.set_state(_AMBER_ENTITY, 0.12, attrs)
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert monitor.current_result.source_kind == "dispatchis"
    assert monitor.current_result.price_per_kwh == 5
    assert monitor.current_result.price_trigger_valid
    assert active.export_session.price_deadline == original_deadline
    assert (MODE, "Self Use") not in rig.calls


async def test_same_block_fallback_and_return_cannot_extend_owned_deadline(
    amber_lifecycle, freezer,
):
    rig = amber_lifecycle
    active = rig.entry.runtime_data.active_controller
    original_deadline = active.export_session.price_deadline
    freezer.tick(timedelta(seconds=30))
    seed_price_states(rig.hass)
    await rig.harness.set_unavailable(_AMBER_ENTITY)
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert rig.entry.runtime_data.market_monitor.current_result.source_kind == "dispatchis"
    assert active.export_session.price_deadline == original_deadline
    await rig.harness.set_state(_AMBER_ENTITY, 0.12, _amber_attributes(price=5.5))
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert rig.entry.runtime_data.market_monitor.current_result.source_kind == "amber"
    assert active.export_session.price_deadline == original_deadline


async def test_both_providers_unavailable_keep_only_original_bounded_permission(amber_lifecycle):
    rig = amber_lifecycle
    deadline = rig.entry.runtime_data.active_controller.export_session.price_deadline
    rig.calls.clear()
    await rig.harness.set_unavailable(_AMBER_ENTITY)
    rig.feed.side_effect = TimeoutError
    await rig.entry.runtime_data.market_monitor.async_refresh()
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert not rig.entry.runtime_data.market_monitor.current_result.price_trigger_valid
    assert (MODE, "Self Use") not in rig.calls
    assert rig.entry.runtime_data.active_controller.export_session.price_deadline == deadline
    assert (MODE, "Force Discharge") not in rig.calls


async def test_failed_primary_cannot_regrant_same_block_it_already_withdrew(
    amber_lifecycle, freezer,
):
    rig = amber_lifecycle
    freezer.tick(timedelta(seconds=1))
    await rig.harness.set_state(_AMBER_ENTITY, 0.12, _amber_attributes(price=2.2))
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert float(rig.hass.states.get(DISCHARGE).state) == 0
    rig.calls.clear()
    await rig.harness.set_unavailable(_AMBER_ENTITY)
    await rig.entry.runtime_data.market_monitor.async_refresh()
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert rig.entry.runtime_data.market_monitor.current_result.status == "provider_disagreement"
    assert not rig.entry.runtime_data.market_monitor.current_result.price_trigger_valid
    assert (MODE, "Force Discharge") not in rig.calls


async def test_same_clock_contradiction_cannot_reassert_a_price_export(amber_lifecycle):
    rig = amber_lifecycle
    original = rig.hass.states.get(_AMBER_ENTITY).last_updated
    rig.calls.clear()
    await rig.harness.set_state(_AMBER_ENTITY, 0.12, _amber_attributes(price=2.2))
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert rig.hass.states.get(_AMBER_ENTITY).last_updated == original
    assert rig.entry.runtime_data.market_monitor.current_result.status == "source_replay"
    assert not rig.entry.runtime_data.market_monitor.current_result.price_trigger_valid
    assert (MODE, "Self Use") in rig.calls
    assert float(rig.hass.states.get(DISCHARGE).state) == 0
    assert (MODE, "Force Discharge") not in rig.calls


@pytest.mark.parametrize("flag", ["APCFLAG", "MARKETSUSPENDEDFLAG", "INTERVENTION"])
async def test_known_current_aemo_restriction_vetoes_confirmed_high_amber(
    amber_lifecycle, flag,
):
    rig = amber_lifecycle
    rig.calls.clear()
    rig.feed.side_effect = lambda: dispatch_report(
        dt_util.utcnow(), price=5000, serial=2, **{flag: "1"},
    )
    await rig.entry.runtime_data.market_monitor.async_refresh()
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert not rig.entry.runtime_data.market_monitor.current_result.price_trigger_valid
    assert (MODE, "Self Use") in rig.calls
    assert float(rig.hass.states.get(DISCHARGE).state) == 0
    assert (MODE, "Force Discharge") not in rig.calls


@pytest.mark.parametrize("flag", ["APCFLAG", "MARKETSUSPENDEDFLAG", "INTERVENTION"])
async def test_aemo_restriction_survives_feed_failure_and_reload_with_high_amber(
    amber_lifecycle, flag,
):
    rig = amber_lifecycle
    rig.feed.side_effect = lambda: dispatch_report(
        dt_util.utcnow(), price=5000, serial=2, **{flag: "1"},
    )
    await rig.entry.runtime_data.market_monitor.async_refresh()
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert not rig.entry.runtime_data.market_monitor.current_result.price_trigger_valid
    rig.feed.side_effect = TimeoutError
    rig.calls.clear()
    await rig.entry.runtime_data.market_monitor.async_refresh()
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert not rig.entry.runtime_data.market_monitor.current_result.price_trigger_valid
    assert (MODE, "Force Discharge") not in rig.calls
    await rig.harness.reload(rig.entry)
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert not rig.entry.runtime_data.market_monitor.current_result.price_trigger_valid
    assert (MODE, "Force Discharge") not in rig.calls


async def test_reload_restores_old_amber_session_before_any_readmission(amber_lifecycle):
    rig = amber_lifecycle
    original_deadline = rig.entry.runtime_data.active_controller.export_session.price_deadline
    stored = await rig.harness.load_store(f"{DOMAIN}.{rig.entry.entry_id}.export_session")
    assert stored["authority_source"] == "price"
    rig.calls.clear()
    await rig.harness.reload(rig.entry)
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert (MODE, "Self Use") in rig.calls
    await rig.entry.runtime_data.active_controller.async_reconcile()
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert rig.entry.runtime_data.market_monitor.current_result.source_kind == "amber"
    assert rig.calls.index((MODE, "Self Use")) < rig.calls.index((MODE, "Force Discharge"))
    assert (
        rig.entry.runtime_data.active_controller.export_session.price_deadline <= original_deadline
    )


async def test_reload_keeps_later_low_correction_when_amber_is_now_unavailable(
    amber_lifecycle, freezer,
):
    rig = amber_lifecycle
    freezer.tick(timedelta(seconds=30))
    seed_price_states(rig.hass)
    await rig.harness.set_state(_AMBER_ENTITY, 0.12, _amber_attributes(price=2.2))
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    await rig.entry.runtime_data.active_controller.async_reconcile()
    await rig.harness.set_unavailable(_AMBER_ENTITY)
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert rig.entry.runtime_data.market_monitor.current_result.status == "provider_disagreement"
    rig.calls.clear()
    await rig.harness.reload(rig.entry)
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert rig.entry.runtime_data.market_monitor.current_result.status == "provider_disagreement"
    assert (MODE, "Force Discharge") not in rig.calls


async def test_loaded_amber_cannot_authorize_unstarted_or_stopped_monitor(amber_lifecycle):
    rig = amber_lifecycle
    probe = AemoMarketMonitor(
        rig.hass, "amber-readiness-probe", rig.entry.runtime_data.runtime_config.aemo_monitor,
    )
    try:
        assert not probe.current_result.price_trigger_valid
        await probe.async_restore_history()
        assert not probe.current_result.price_trigger_valid
        await probe.async_start()
        assert probe.current_result.price_trigger_valid
        assert probe.current_result.source_kind == "amber"
    finally:
        await probe.async_stop()
    assert not probe.current_result.price_trigger_valid


@pytest.mark.parametrize(
    "amber_lifecycle", ["safety_lock", "free_window", "paid_full", "no_sellable"], indirect=True,
)
async def test_confirmed_high_amber_does_not_bypass_existing_protections(amber_lifecycle):
    rig = amber_lifecycle
    assert rig.entry.runtime_data.market_monitor.current_result.price_trigger_valid
    assert rig.entry.runtime_data.market_monitor.current_result.source_kind == "amber"
    assert (MODE, "Force Discharge") not in rig.calls
    assert not any(entity == DISCHARGE and value > 0 for entity, value in rig.calls)
