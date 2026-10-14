"""Real HA platform installation for HACS-owned, entry-scoped Trip controls."""

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN

from .test_setup import ENTRY_DATA

TRIP_PLATFORMS = {
    "trip_ready_by": "datetime",
    "trip_target_soc": "select",
    "trip_charge_scheduled": "switch",
    "trip_extra_minutes": "number",
    "trip_charge_status": "sensor",
    "trip_charge_planned_start": "sensor",
    "trip_charge_duration": "sensor",
}


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Trip controls", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _ids(hass, entry):
    registry = er.async_get(hass)
    return {
        key: registry.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
        for key, platform in TRIP_PLATFORMS.items()
    }


async def test_all_seven_entities_install_without_helpers_or_full_request(hass):
    entry = await _setup(hass)
    ids = _ids(hass, entry)
    assert ids == {key: f"{platform}.home_energy_{key}" for key, platform in TRIP_PLATFORMS.items()}
    assert all(hass.states.get(entity_id) is not None for entity_id in ids.values())
    assert hass.states.get(ids["trip_charge_scheduled"]).state == "off"
    assert hass.states.get(ids["trip_target_soc"]).state == "100%"
    assert hass.states.get(ids["trip_charge_status"]).state == "not_scheduled"
    assert hass.states.get(ids["trip_ready_by"]).state == "unknown"
    assert entry.runtime_data.runtime_config.ev_preferences.charge_to_full_enabled is False
    assert not hass.states.async_all("input_boolean")
    assert not hass.states.async_all("automation")


async def test_native_controls_use_service_api_and_restore_without_arming(hass):
    entry = await _setup(hass)
    ids = _ids(hass, entry)
    due = datetime.now(UTC) + timedelta(days=1)
    await hass.services.async_call(
        "datetime", "set_value", {"entity_id": ids["trip_ready_by"], "datetime": due.isoformat()},
        blocking=True,
    )
    await hass.services.async_call(
        "select", "select_option", {"entity_id": ids["trip_target_soc"], "option": "80%"},
        blocking=True,
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": ids["trip_extra_minutes"], "value": 15},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.trip_charge.departure == due
    assert entry.runtime_data.trip_charge.target_soc == 80
    assert entry.runtime_data.trip_charge.extra_minutes == 15
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert _ids(hass, entry) == ids
    assert entry.runtime_data.trip_charge.departure == due
    assert entry.runtime_data.trip_charge.target_soc == 80
    assert entry.runtime_data.trip_charge.extra_minutes == 15
    assert hass.states.get(ids["trip_charge_scheduled"]).state == "off"
    assert entry.runtime_data.runtime_config.ev_preferences.charge_to_full_enabled is False


async def test_trip_entity_rename_is_preserved_on_reload(hass):
    entry = await _setup(hass)
    registry = er.async_get(hass)
    entity_id = _ids(hass, entry)["trip_ready_by"]
    registry.async_update_entity(entity_id, new_entity_id="datetime.my_trip_departure", name="Trip")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    record = registry.async_get("datetime.my_trip_departure")
    assert record is not None and record.name == "Trip"
    assert _ids(hass, entry)["trip_ready_by"] == "datetime.my_trip_departure"


async def test_trip_entities_are_scoped_to_each_config_entry(hass):
    first = await _setup(hass)
    second = await _setup(hass)
    first_ids, second_ids = _ids(hass, first), _ids(hass, second)
    assert not set(first_ids.values()) & set(second_ids.values())
    await hass.services.async_call(
        "select", "select_option", {"entity_id": second_ids["trip_target_soc"], "option": "90%"},
        blocking=True,
    )
    assert second.runtime_data.trip_charge.target_soc == 90
    assert first.runtime_data.trip_charge.target_soc == 100


@pytest.mark.parametrize("option", ["0%", "101%", "80.5%"])
async def test_invalid_trip_target_service_does_not_change_state(hass, option):
    entry = await _setup(hass)
    ids = _ids(hass, entry)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "select", "select_option", {"entity_id": ids["trip_target_soc"], "option": option},
            blocking=True,
        )
    assert entry.runtime_data.trip_charge.target_soc == 100
    assert not entry.runtime_data.trip_charge.armed
