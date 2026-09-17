"""System-level lifecycle characterization tests."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN
from tests.helpers.lifecycle import LifecycleHarness
from tests.test_setup import ENTRY_DATA


@pytest.mark.freeze_time("2026-09-17 01:00:00+00:00")
async def test_observer_public_state_is_equivalent_after_reload(hass) -> None:
    """A reload with identical evidence must not change public truth or write."""
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.test_house_load", "0.8", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(domain=DOMAIN, title="Lifecycle baseline", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    harness = LifecycleHarness(hass)

    await harness.setup(entry)
    public_entities = {
        "sensor.home_energy_status",
        "sensor.home_energy_fleet_summary",
        "sensor.home_energy_battery_soc",
        "sensor.home_energy_grid_power",
        "sensor.home_energy_house_load",
        "switch.home_energy_safety_lock",
    }
    before = harness.states(public_entities, ignored_attributes=frozenset({"last_update"}))
    assert harness.service_calls == ()

    await harness.reload(entry)
    after = harness.states(public_entities, ignored_attributes=frozenset({"last_update"}))

    assert after == before
    assert harness.service_calls == ()
    harness.close()
