"""System case executed against the extracted previous known-good release."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_setup import ENTRY_DATA

from custom_components.home_energy_orchestrator.const import DOMAIN


async def test_previous_release_reads_current_unchanged_surface(hass) -> None:
    """The previous release must set up the unchanged version-6 data surface."""
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.test_house_load", "0.8", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Rollback rehearsal",
        data=dict(ENTRY_DATA),
        version=6,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 6
    assert hass.states.get("sensor.home_energy_status") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
