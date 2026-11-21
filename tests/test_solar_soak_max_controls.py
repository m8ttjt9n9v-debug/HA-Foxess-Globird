"""Optional maximum solar soak shares one validated setup/native control band."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform, entity_registry

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.configuration import (
    RuntimeConfiguration,
    valid_ev_solar_soak_thresholds,
)
from custom_components.home_energy_orchestrator.const import DOMAIN

from .test_config_flow import _open_reconfigure_page, _schema_values
from .test_reconfigure_concurrency import _apply
from .test_setup import ENTRY_DATA
from .test_solar_soak_controls import _set, _setup

START = "ev_solar_soak_start_soc_percent"
STOP = "ev_solar_soak_stop_soc_percent"
ENABLED = "ev_solar_soak_max_enabled"


def test_old_entry_keeps_maximum_mode_off_and_existing_soak_values():
    runtime = RuntimeConfiguration.from_mapping({
        **ENTRY_DATA, "ev_solar_soak_battery_soc_percent": 87,
        "ev_solar_soak_average_minutes": 13, "ev_solar_soak_adjustment_minutes": 8,
    })
    assert runtime.ev_policy.solar_soak_max_enabled is False
    assert runtime.ev_numbers.value(START, -1) == 95
    assert runtime.ev_numbers.value(STOP, -1) == 90
    assert runtime.ev_numbers.value("ev_solar_soak_battery_soc_percent", -1) == 87
    assert runtime.ev_numbers.value("ev_solar_soak_average_minutes", -1) == 13
    assert runtime.ev_numbers.value("ev_solar_soak_adjustment_minutes", -1) == 8


@pytest.mark.parametrize(("start", "stop"), [(0.1, 0), (95, 90), (100, 99.9)])
def test_valid_boundary_bands_are_available_to_the_existing_controller(start, stop):
    assert valid_ev_solar_soak_thresholds(start, stop)
    runtime = RuntimeConfiguration.from_mapping({
        **ENTRY_DATA, ENABLED: True, START: start, STOP: stop,
    })
    assert runtime.ev_policy.solar_soak_max_enabled is True
    assert runtime.ev_numbers.value(START, -1) == start
    assert runtime.ev_numbers.value(STOP, -1) == stop
    flow = ConfigFlow()
    data = flow._apply_defaults({
        **ENTRY_DATA, "name": "Solar control tests", ENABLED: True, START: start, STOP: stop,
    })
    assert flow._validate_input(data) == {}
    assert flow._page_limit_error("ev_policies", data) == {}


@pytest.mark.parametrize(("start", "stop"), [
    (95, 95), (90, 95), (0, 0), (101, 90), (95, -0.1),
    (float("nan"), 90), (95, float("inf")), (True, 0), (95, False),
    (None, 90), (95, "unknown"),
])
def test_invalid_saved_band_cannot_enable_maximum_mode(start, stop):
    assert not valid_ev_solar_soak_thresholds(start, stop)
    runtime = RuntimeConfiguration.from_mapping({
        **ENTRY_DATA, ENABLED: True, START: start, STOP: stop,
    })
    assert runtime.ev_policy.solar_soak_max_enabled is False
    assert runtime.ev_numbers.value(START, -1) == runtime.ev_numbers.value(STOP, -1) == 100
    flow = ConfigFlow()
    data = flow._apply_defaults({**ENTRY_DATA, ENABLED: True, START: start, STOP: stop})
    assert flow._validate_input(data) == {START: "invalid_solar_soak_band"}
    assert flow._page_limit_error("ev_policies", data) == {START: "invalid_solar_soak_band"}


@pytest.mark.parametrize("invalid", ["true", "false", 1, 0, None])
def test_invalid_opt_in_does_not_become_truthy_authority(invalid):
    data = {**ENTRY_DATA, ENABLED: invalid}
    assert RuntimeConfiguration.from_mapping(data).ev_policy.solar_soak_max_enabled is False
    flow = ConfigFlow()
    applied = flow._apply_defaults(data)
    assert flow._validate_input(applied) == {ENABLED: "invalid_site_limits"}


@pytest.mark.parametrize(("key", "entity", "chosen"), [
    (START, "ev_solar_soak_start_soc", 96.5),
    (STOP, "ev_solar_soak_stop_soc", 89.5),
])
async def test_native_threshold_updates_shared_value_and_only_existing_ev_writer(
    hass, monkeypatch, key, entity, chosen,
):
    entry = await _setup(hass, options={key: 95 if key == START else 90, "reserve_kwh": 4})
    owner = entry.runtime_data
    ev, fox = AsyncMock(), AsyncMock()
    monkeypatch.setattr(owner.ev_controller, "async_reconcile", ev)
    monkeypatch.setattr(owner.active_controller, "async_reconcile", fox)
    await _set(hass, entity, chosen)
    assert entry.data[key] == chosen and key not in entry.options
    assert entry.options["reserve_kwh"] == 4
    assert owner.runtime_config.ev_numbers.value(key, -1) == chosen
    assert hass.states.get("number.home_energy_" + entity).state == str(chosen)
    ev.assert_awaited_once()
    fox.assert_not_awaited()
    assert entry.runtime_data is owner
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(("entity", "bad"), [
    ("ev_solar_soak_start_soc", 90), ("ev_solar_soak_start_soc", 89.9),
    ("ev_solar_soak_stop_soc", 95), ("ev_solar_soak_stop_soc", 95.1),
    ("ev_solar_soak_start_soc", float("nan")),
    ("ev_solar_soak_stop_soc", float("inf")),
    ("ev_solar_soak_start_soc", True),
])
async def test_native_threshold_rejects_invalid_cross_field_edit(hass, entity, bad):
    entry = await _setup(hass)
    before = dict(entry.data)
    entity_id = "number.home_energy_" + entity
    control = next(platform.entities[entity_id]
                   for platform in entity_platform.async_get_platforms(hass, DOMAIN)
                   if entity_id in platform.entities)
    with pytest.raises(HomeAssistantError, match="solar-soak"):
        await control.async_set_native_value(bad)
    assert dict(entry.data) == before
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_native_switch_is_default_off_persists_and_reconciles_existing_ev(hass, monkeypatch):
    entry = await _setup(hass, options={ENABLED: False})
    entity_id = "switch.home_energy_ev_solar_soak_max_enabled"
    assert hass.states.get(entity_id).state == "off"
    owner = entry.runtime_data
    ev, fox = AsyncMock(), AsyncMock()
    monkeypatch.setattr(owner.ev_controller, "async_reconcile", ev)
    monkeypatch.setattr(owner.active_controller, "async_reconcile", fox)
    await hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)
    assert entry.data[ENABLED] is True and ENABLED not in entry.options
    assert owner.runtime_config.ev_policy.solar_soak_max_enabled is True
    ev.assert_awaited_once()
    fox.assert_not_awaited()
    assert entry.runtime_data is owner
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_switch_rejects_corrupt_band_but_still_allows_turning_mode_off(hass):
    entry = await _setup(hass, data={START: 90, STOP: 95, ENABLED: True})
    entity_id = "switch.home_energy_ev_solar_soak_max_enabled"
    assert hass.states.get(entity_id).state == "off"
    with pytest.raises(HomeAssistantError, match="start must be above stop"):
        await hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)
    await hass.services.async_call("switch", "turn_off", {"entity_id": entity_id}, blocking=True)
    assert entry.data[ENABLED] is False
    assert entry.data[START] == 90 and entry.data[STOP] == 95
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_grouped_reconfigure_and_reload_preserve_same_band_and_old_soak(hass):
    entry = await _setup(hass, data={"configure_ev": True, "ev_solar_soak_average_minutes": 13})
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    flow = await _open_reconfigure_page(hass, flow, "ev_policies")
    values = _schema_values(flow["data_schema"])
    values["solar_soak_max"].update({ENABLED: True, START: 96, STOP: 89})
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input=values)
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[ENABLED] is True and entry.data[START] == 96 and entry.data[STOP] == 89
    assert entry.data["ev_solar_soak_average_minutes"] == 13
    assert hass.states.get("number.home_energy_ev_solar_soak_start_soc").state == "96.0"
    assert hass.states.get("switch.home_energy_ev_solar_soak_max_enabled").state == "on"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_new_native_control_rename_survives_reload(hass):
    entry = await _setup(hass)
    registry = entity_registry.async_get(hass)
    registry.async_update_entity("number.home_energy_ev_solar_soak_stop_soc",
                                 new_entity_id="number.my_solar_stop", name="My solar stop")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("number.my_solar_stop").state == "90.0"
    assert hass.states.get("number.home_energy_ev_solar_soak_stop_soc") is None
    assert await hass.config_entries.async_unload(entry.entry_id)
