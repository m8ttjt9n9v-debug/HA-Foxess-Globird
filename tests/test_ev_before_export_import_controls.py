"""Import confirmation is one editable, validated and restart-safe policy input."""

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import DOMAIN
from tests.test_setup import ENTRY_DATA
from tests.test_solar_soak_controls import _set, _setup

KEY = "ev_before_export_import_confirm_seconds"
ENTITY = "number.home_energy_ev_before_export_import_confirm_seconds"


async def test_control_persists_only_its_setting_and_survives_reload(hass):
    entry = await _setup(hass, options={KEY: 60, "reserve_kwh": 4})
    before = dict(entry.data)
    await _set(hass, "ev_before_export_import_confirm_seconds", 30)
    assert dict(entry.data) == {**before, KEY: 30}
    assert entry.options == {"reserve_kwh": 4}
    assert hass.states.get(ENTITY).state == "30.0"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(ENTITY).state == "30.0"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("invalid", [True, -1, 301, 0.5, float("nan"), float("inf"), "bad"])
async def test_invalid_control_does_not_change_configuration(hass, invalid):
    entry = await _setup(hass)
    before = dict(entry.data)
    entity = next(p.entities[ENTITY] for p in entity_platform.async_get_platforms(hass, DOMAIN)
                  if ENTITY in p.entities)
    with pytest.raises(HomeAssistantError):
        await entity.async_set_native_value(invalid)
    assert dict(entry.data) == before
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("invalid", [True, -1, 301, 0.5, float("nan"), float("inf"), "bad"])
def test_wizard_rejects_corruption_and_runtime_disables_hold(invalid):
    flow = ConfigFlow()
    data = flow._apply_defaults({**ENTRY_DATA, KEY: invalid})
    assert flow._validate_input(data) == {KEY: "invalid_site_limits"}
    assert flow._page_limit_error("ev_policies", data) == {
        "base" if invalid == "bad" else KEY: "invalid_site_limits",
    }
    assert RuntimeConfiguration.from_mapping(data).ev_numbers.value(KEY, 60) == 0
