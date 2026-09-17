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


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_safety_lock_blocks_all_commands_across_reload(hass) -> None:
    """Requested automation cannot write before or after a locked reload."""
    harness = LifecycleHarness(hass)
    await harness.set_state(
        "sensor.test_battery_soc", "50", {"unit_of_measurement": "%"}
    )
    await harness.set_state(
        "sensor.test_grid_power", "0", {"unit_of_measurement": "kW"}
    )
    await harness.set_state(
        "sensor.test_house_load", "0.8", {"unit_of_measurement": "kW"}
    )
    await harness.set_state("select.test_work_mode", "Self Use")
    await harness.set_state("number.test_force_charge", "0")
    await harness.set_state("number.test_force_discharge", "0")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Locked lifecycle baseline",
        data={
            **ENTRY_DATA,
            "foxess_control_owner": "local_modbus",
            "automatic_control_enabled": True,
            "automatic_charge_enabled": True,
            "automatic_export_enabled": True,
            "rehearsal_mode": True,
            "sign_conventions_verified": True,
            "free_charge_schedule_confirmed": True,
            "inverter_charge_limit_kw": 10.0,
            "inverter_discharge_limit_kw": 10.0,
            "foxess_work_mode_entity": "select.test_work_mode",
            "foxess_force_charge_power_entity": "number.test_force_charge",
            "foxess_force_discharge_power_entity": "number.test_force_discharge",
        },
    )
    entry.add_to_hass(hass)

    await harness.setup(entry)
    before = harness.states(
        {
            "sensor.home_energy_status",
            "sensor.home_energy_free_charge_completion",
            "sensor.home_energy_zerohero_export_status",
            "switch.home_energy_safety_lock",
        }
    )
    status = hass.states.get("sensor.home_energy_status")
    assert status is not None
    assert status.attributes["control_gate"] == "rehearsal"
    assert harness.service_calls == ()

    await harness.reload(entry)
    after = harness.states(
        {
            "sensor.home_energy_status",
            "sensor.home_energy_free_charge_completion",
            "sensor.home_energy_zerohero_export_status",
            "switch.home_energy_safety_lock",
        }
    )

    assert after == before
    status = hass.states.get("sensor.home_energy_status")
    assert status is not None
    assert status.attributes["control_gate"] == "rehearsal"
    assert harness.service_calls == ()
    harness.close()
