"""Whole integration load regressions: native entities, reload and learning."""

from datetime import UTC, datetime

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN

from .test_setup import ENTRY_DATA, _entity_id


async def test_native_load_split_survives_reload_without_private_helper_or_writes(hass, freezer):
    freezer.move_to(datetime(2026, 10, 1, 7, tzinfo=UTC))
    for entity, value, unit in [
        ("sensor.test_battery_soc", 60, "%"),
        ("sensor.test_grid_power", 1200, "W"),
        ("sensor.test_house_load", 5460, "W"),
        ("sensor.car_actual", 15, "A"),
    ]:
        hass.states.async_set(entity, str(value), {"unit_of_measurement": unit})
    hass.states.async_set("sensor.car_charging", "charging")
    data = {
        **ENTRY_DATA,
        "configure_ev": True,
        "house_load_includes_ev": True,
        "ev_actual_current_entity": "sensor.car_actual",
        "ev_charging_state_entity": "sensor.car_charging",
        "ev_phase_count": 1,
        "ev_voltage": 230,
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Load lifecycle", data=data, version=6)
    entry.add_to_hass(hass)
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry_ids = {
        key: _entity_id(hass, entry, key)
        for key in ["house_load", "ev_charging_power", "house_load_excluding_ev"]
    }
    assert float(hass.states.get(registry_ids["ev_charging_power"]).state) == pytest.approx(3.45)
    assert float(hass.states.get(registry_ids["house_load_excluding_ev"]).state) == pytest.approx(
        2.01
    )
    assert float(hass.states.get(registry_ids["house_load"]).state) == pytest.approx(5.46)
    before = dict(entry.data)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.data == before
    assert {_entity_id(hass, entry, key) for key in registry_ids} == set(registry_ids.values())
    assert float(hass.states.get(registry_ids["house_load_excluding_ev"]).state) == pytest.approx(
        2.01
    )
    assert calls == []
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_negative_source_is_not_learned_as_zero_and_balance_recovers_across_reload(hass):
    for entity, value, unit in [
        ("sensor.test_battery_soc", 60, "%"),
        ("sensor.test_grid_power", 3500, "W"),
        ("sensor.test_house_load", -4500, "W"),
        ("sensor.test_battery", 7990, "W"),
        ("sensor.test_solar", 4920, "W"),
    ]:
        hass.states.async_set(entity, str(value), {"unit_of_measurement": unit})
    data = {
        **ENTRY_DATA,
        "configure_ev": False,
        "configure_solar": True,
        "battery_power_entity": "sensor.test_battery",
        "solar_power_entity": "sensor.test_solar",
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Balance lifecycle", data=data, version=6)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert coordinator.snapshot.house_load_kw is None
    assert coordinator._protected_house_learning_power_kw(datetime.now(UTC)) is None
    retained_samples = coordinator.demand_history.samples
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "house_load_source": "power_balance"}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.snapshot.house_load_kw == pytest.approx(0.43)
    assert entry.runtime_data._protected_house_learning_power_kw(
        datetime.now(UTC)
    ) == pytest.approx(0.43)
    await entry.runtime_data._async_sample_house_load()
    assert entry.runtime_data.demand_sampler._last_power_kw == pytest.approx(0.43)
    assert entry.runtime_data.demand_history.samples == retained_samples
    assert (
        hass.states.get(_entity_id(hass, entry, "house_load_excluding_ev")).state != "unavailable"
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    # Previous versions ignore this additive option. A safe downgrade on a broken
    # native source requires commissioning a valid mapped source first; no storage reset.
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "house_load_source": "sensor"}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.snapshot.house_load_kw is None
    assert entry.runtime_data.demand_history.samples == retained_samples
    assert await hass.config_entries.async_unload(entry.entry_id)
