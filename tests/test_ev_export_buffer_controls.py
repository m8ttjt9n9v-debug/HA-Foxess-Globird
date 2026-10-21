"""Native dashboard control and wizard share one validated setting."""

from math import isnan

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform, entity_registry

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.config_page_schema import iter_page_schema_fields
from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import DOMAIN
from tests.test_setup import ENTRY_DATA
from tests.test_solar_soak_controls import _set, _setup

KEY = "ev_before_export_soc_buffer_percent"
ENTITY = "number.home_energy_ev_before_export_soc_buffer"


async def test_number_persists_only_buffer_and_reconciles_ev_before_export(hass, monkeypatch):
    entry = await _setup(hass, options={KEY: 1, "reserve_kwh": 4})
    owner = entry.runtime_data
    original = dict(entry.data)
    order = []

    async def ev():
        order.append("ev")

    async def fox():
        order.append("export")

    monkeypatch.setattr(owner.ev_controller, "async_reconcile", ev)
    monkeypatch.setattr(owner.active_controller, "async_reconcile", fox)
    await _set(hass, "ev_before_export_soc_buffer", 2)
    assert order == ["ev", "export"]
    assert dict(entry.data) == {**original, KEY: 2.0}
    assert entry.options == {"reserve_kwh": 4}
    assert owner.runtime_config.ev_preferences.before_export_soc_buffer == 2
    assert hass.states.get(ENTITY).state == "2.0"
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(ENTITY).state == "2.0"
    schema = ConfigFlow()._page_schema("ev_policies", dict(entry.data))
    fields = {marker.schema: marker for marker, _ in iter_page_schema_fields(schema)}
    assert fields[KEY].default() == 2
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("invalid", [True, -1, 101, 1.5, float("nan"), float("inf")])
async def test_invalid_dashboard_write_does_not_mutate_config(hass, invalid):
    entry = await _setup(hass)
    before = dict(entry.data)
    entity = next(
        p.entities[ENTITY]
        for p in entity_platform.async_get_platforms(hass, DOMAIN)
        if ENTITY in p.entities
    )
    with pytest.raises(HomeAssistantError):
        await entity.async_set_native_value(invalid)
    assert dict(entry.data) == before
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("invalid", [True, -1, 101, 1.5, float("nan"), float("inf")])
def test_wizard_rejects_invalid_buffer_and_corrupt_runtime_fails_closed(invalid):
    flow = ConfigFlow()
    data = flow._apply_defaults({**ENTRY_DATA, KEY: invalid})
    assert flow._validate_input(data) == {KEY: "invalid_site_limits"}
    assert flow._page_limit_error("ev_policies", data) == {KEY: "invalid_site_limits"}
    assert isnan(RuntimeConfiguration.from_mapping(data).ev_preferences.before_export_soc_buffer)


async def test_buffer_control_rename_survives_reload(hass):
    entry = await _setup(hass)
    entity_registry.async_get(hass).async_update_entity(ENTITY, new_entity_id="number.my_ev_buffer")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("number.my_ev_buffer").state == "1.0"
    assert hass.states.get(ENTITY) is None
    assert await hass.config_entries.async_unload(entry.entry_id)
