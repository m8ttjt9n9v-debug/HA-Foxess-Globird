"""Dashboard settings persist without touching HEO's hardware policies."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.aemo_monitor import AemoMarketMonitor
from custom_components.home_energy_orchestrator.aemo_monitor_controls import _update_settings
from custom_components.home_energy_orchestrator.const import DOMAIN
from scripts.dashboard_contract import entity_references, load_dashboard, walk
from tests.test_setup import ENTRY_DATA

pytestmark = pytest.mark.freeze_time("2026-10-11T00:01:00+00:00", real_asyncio=True)

_CONTROL_IDS = {
    "switch.home_energy_aemo_monitor",
    "select.home_energy_aemo_region",
    "number.home_energy_aemo_export_threshold",
    "number.home_energy_aemo_import_threshold",
    "button.home_energy_aemo_clear_import_threshold",
}


async def _setup(hass, monkeypatch, *, data=None, options=None):
    payload = {
        "ELEC_NEM_SUMMARY": [
            {
                "REGIONID": region,
                "PRICE": price,
                "SETTLEMENTDATE": "2026-10-11T10:05:00",
                "PRICE_STATUS": "FIRM",
                "APCFLAG": 0,
                "MARKETSUSPENDEDFLAG": 0,
            }
            for region, price in (("NSW1", 4000), ("QLD1", -200))
        ]
    }
    fetch = AsyncMock(return_value=payload)
    monkeypatch.setattr(AemoMarketMonitor, "_async_fetch_summary", fetch)
    for entity, value, unit in (
        ("sensor.test_battery_soc", "60", "%"),
        ("sensor.test_grid_power", "1200", "W"),
        ("sensor.test_house_load", "800", "W"),
    ):
        hass.states.async_set(entity, value, {"unit_of_measurement": unit})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Site",
        data={**ENTRY_DATA, **(data or {})},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry, fetch


async def _call(hass, domain, service, entity_id, **data):
    await hass.services.async_call(domain, service, {"entity_id": entity_id, **data}, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_dashboard_controls_exist_while_monitor_and_energy_control_are_off(hass, monkeypatch):
    entry, fetch = await _setup(hass, monkeypatch)
    assert all(hass.states.get(entity) is not None for entity in _CONTROL_IDS)
    assert hass.states.get("switch.home_energy_aemo_monitor").state == "off"
    assert hass.states.get("select.home_energy_aemo_region").state == "Not configured"
    assert hass.states.get("number.home_energy_aemo_export_threshold").state == "3.0"
    assert hass.states.get("number.home_energy_aemo_import_threshold").state == "unknown"
    fetch.assert_not_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_dashboard_changes_apply_live_and_preserve_every_non_market_setting(
    hass, monkeypatch
):
    entry, fetch = await _setup(hass, monkeypatch)
    owner = entry.runtime_data
    original = dict(entry.data)
    ledger = owner.data
    forecast = owner.optimistic_forecast
    parent_refresh = AsyncMock()
    monkeypatch.setattr(owner, "async_request_refresh", parent_refresh)
    foxess = AsyncMock()
    ev = AsyncMock()
    monkeypatch.setattr(owner.active_controller, "async_reconcile", foxess)
    monkeypatch.setattr(owner.ev_controller, "async_reconcile", ev)
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    await _call(hass, "select", "select_option", "select.home_energy_aemo_region", option="NSW1")
    fetch.assert_not_awaited()  # Choosing a region does not enable monitoring.
    await _call(hass, "switch", "turn_on", "switch.home_energy_aemo_monitor")
    assert owner.market_monitor.current_result.status == "possible_export_event"
    await _call(hass, "number", "set_value", "number.home_energy_aemo_export_threshold", value=5)
    assert owner.market_monitor.current_result.status == "watching"
    await _call(hass, "number", "set_value", "number.home_energy_aemo_import_threshold", value=-0.1)
    await _call(hass, "select", "select_option", "select.home_energy_aemo_region", option="QLD1")
    assert owner.market_monitor.current_result.status == "possible_import_event"
    assert hass.states.get("sensor.home_energy_aemo_spot_price").state == "-0.2"
    await _call(hass, "button", "press", "button.home_energy_aemo_clear_import_threshold")
    assert entry.data["aemo_import_threshold_per_kwh"] is None
    assert owner.market_monitor.current_result.status == "watching"
    await _call(hass, "switch", "turn_off", "switch.home_energy_aemo_monitor")
    assert owner.market_monitor.current_result.status == "disabled"
    assert hass.states.get("sensor.home_energy_aemo_spot_price").state == "unavailable"
    assert {
        key: value for key, value in entry.data.items() if not key.startswith("aemo_")
    } == original
    assert owner.data is ledger
    assert owner.optimistic_forecast is forecast
    parent_refresh.assert_not_awaited()
    foxess.assert_not_awaited()
    ev.assert_not_awaited()
    assert all(event.data["service_data"]["entity_id"] in _CONTROL_IDS for event in calls)
    assert entry.runtime_data is owner  # No integration reload was needed.
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_invalid_dashboard_edit_does_not_change_persisted_or_runtime_settings(
    hass, monkeypatch
):
    entry, fetch = await _setup(hass, monkeypatch)
    before = dict(entry.data)
    with pytest.raises(HomeAssistantError, match="market region"):
        await _call(hass, "switch", "turn_on", "switch.home_energy_aemo_monitor")
    assert dict(entry.data) == before
    for threshold in (3, 4, float("nan"), float("inf")):
        with pytest.raises(HomeAssistantError, match="threshold"):
            await _update_settings(
                entry.runtime_data, entry, {"aemo_import_threshold_per_kwh": threshold}
            )
        assert dict(entry.data) == before
    with pytest.raises(HomeAssistantError, match="Only AEMO"):
        await _update_settings(entry.runtime_data, entry, {"automatic_control_enabled": True})
    fetch.assert_not_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_dashboard_edit_overrides_only_its_option_and_survives_reload(hass, monkeypatch):
    entry, _fetch = await _setup(
        hass,
        monkeypatch,
        data={"aemo_region": "NSW1", "aemo_export_threshold_per_kwh": 3},
        options={"aemo_export_threshold_per_kwh": 4, "reserve_kwh": 3},
    )
    await _call(hass, "number", "set_value", "number.home_energy_aemo_export_threshold", value=5)
    assert entry.data["aemo_export_threshold_per_kwh"] == 5
    assert "aemo_export_threshold_per_kwh" not in entry.options
    assert entry.options["reserve_kwh"] == 3
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("number.home_energy_aemo_export_threshold").state == "5.0"
    assert hass.states.get("select.home_energy_aemo_region").state == "NSW1"
    assert entry.options["reserve_kwh"] == 3
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_settings_remain_editable_during_price_outage_and_registered_rename(
    hass, monkeypatch
):
    entry, fetch = await _setup(hass, monkeypatch, data={"aemo_region": "NSW1"})
    fetch.side_effect = TimeoutError
    await _call(hass, "switch", "turn_on", "switch.home_energy_aemo_monitor")
    assert hass.states.get("sensor.home_energy_aemo_market_status").state == "unavailable"
    await _call(hass, "number", "set_value", "number.home_energy_aemo_export_threshold", value=5)
    assert hass.states.get("number.home_energy_aemo_export_threshold").state == "5.0"
    registry = er.async_get(hass)
    registry.async_update_entity(
        "number.home_energy_aemo_export_threshold", new_entity_id="number.custom_supply_threshold"
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("number.custom_supply_threshold").state == "5.0"
    assert hass.states.get("number.home_energy_aemo_export_threshold") is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_dashboard_panel_keeps_primary_export_controls_separate_from_import_observation(hass):
    dashboard = load_dashboard()
    panel_controls = _CONTROL_IDS - {
        "number.home_energy_aemo_import_threshold",
        "button.home_energy_aemo_clear_import_threshold",
    }
    assert panel_controls | {
        "sensor.home_energy_aemo_spot_price",
        "sensor.home_energy_aemo_market_status",
        "switch.home_energy_critical_event_sell",
    } <= entity_references(dashboard)
    config_view = next(view for view in dashboard["views"] if view["path"] == "configuration")
    panels = [
        card
        for card in walk(config_view)
        if isinstance(card, dict) and card.get("title") == "Current price and eligibility"
    ]
    assert len(panels) == 1
    assert panels[0]["show_header_toggle"] is False
    assert not {
        "number.home_energy_aemo_import_threshold",
        "button.home_energy_aemo_clear_import_threshold",
    } & entity_references(panels[0])
    assert any(
        item.get("entity") == "sensor.home_energy_aemo_market_status"
        and item.get("attribute") == "interval_end"
        for item in panels[0]["entities"]
    )
    content = next(
        item["content"]
        for item in walk(config_view)
        if isinstance(item, dict)
        and item.get("type") == "markdown"
        and "Price observations do not" in item.get("content", "")
    )
    hass.states.async_set("sensor.home_energy_aemo_market_status", "disabled", {})
    rendered = Template(content, hass).async_render(parse_result=False)
    assert "start OFF" in rendered
    assert "retailer event or payment" in rendered
    assert "Missing or expired" in rendered
