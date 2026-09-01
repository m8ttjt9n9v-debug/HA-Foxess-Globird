from __future__ import annotations

from homeassistant.const import EVENT_CALL_SERVICE, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN

ENTRY_DATA = {
    "battery_soc_entity": "sensor.test_battery_soc",
    "battery_capacity_kwh": 20.0,
    "battery_floor_percent": 10.0,
    "reserve_kwh": 2.0,
    "grid_power_entity": "sensor.test_grid_power",
    "grid_import_positive": True,
    "house_load_entity": "sensor.test_house_load",
    "ev_min_current": 6.0,
    "ev_max_current": 32.0,
    "ev_voltage": 230.0,
}


def _entity_id(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None
    return entity_id


async def test_setup_observes_normalised_values_and_never_calls_services(hass):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "1200", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.test_house_load", "800", {"unit_of_measurement": "W"})
    entry = MockConfigEntry(domain=DOMAIN, title="Test Site", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    service_calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, service_calls.append)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    available_energy = _entity_id(hass, entry, "available_energy")
    grid_import = _entity_id(hass, entry, "grid_import")
    status = _entity_id(hass, entry, "status")
    assert hass.states.get(available_energy).state == "8.0"
    assert hass.states.get(grid_import).state == "1.2"
    assert hass.states.get(status).state == "observer_only"
    assert hass.states.get(status).attributes["writes_performed"] == 0
    assert service_calls == []


async def test_source_change_recalculates_without_a_restart(hass):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "1200", {"unit_of_measurement": "W"})
    entry = MockConfigEntry(domain=DOMAIN, title="Test Site", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.states.async_set("sensor.test_grid_power", "-2000", {"unit_of_measurement": "W"})
    await hass.async_block_till_done()

    grid_export = _entity_id(hass, entry, "grid_export")
    assert hass.states.get(grid_export).state == "2.0"


async def test_unload_removes_entities_and_state_listeners(hass):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "1200", {"unit_of_measurement": "W"})
    entry = MockConfigEntry(domain=DOMAIN, title="Test Site", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    status = _entity_id(hass, entry, "status")

    coordinator = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(status).state == STATE_UNAVAILABLE
    assert coordinator._unsub_source_updates is None
