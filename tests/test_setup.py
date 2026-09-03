from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from homeassistant.const import EVENT_CALL_SERVICE, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN
from custom_components.home_energy_orchestrator.coordinator import EnergyCoordinator
from custom_components.home_energy_orchestrator.models import SiteSnapshot
from custom_components.home_energy_orchestrator.planner.learning import DemandCycleSampler

ENTRY_DATA = {
    "battery_soc_entity": "sensor.test_battery_soc",
    "battery_capacity_kwh": 20.0,
    "battery_floor_percent": 10.0,
    "reserve_kwh": 2.0,
    "grid_power_entity": "sensor.test_grid_power",
    "grid_import_positive": True,
    "daily_free_allowance_kwh": 50.0,
    "daily_charge": 2.035,
    "peak_window_start": "16:00:00",
    "peak_window_end": "23:00:00",
    "peak_rate_per_kwh": 0.594,
    "offpeak_rate_per_kwh": 0.0,
    "offpeak_balance_rate_per_kwh": 0.308,
    "shoulder_rate_per_kwh": 0.528,
    "site_phase_count": 1,
    "service_import_limit_a": 0.0,
    "export_limit_kw": 0.0,
    "inverter_charge_limit_kw": 0.0,
    "inverter_discharge_limit_kw": 0.0,
    "house_load_entity": "sensor.test_house_load",
    "free_charge_window_start": "12:01:00",
    "free_charge_window_end": "14:59:00",
    "free_charge_full_battery_import_threshold_kwh": 49.0,
    "house_learning_fallback_kwh": 17.5,
    "automatic_control_enabled": False,
    "rehearsal_mode": True,
    "ev_charger_profile": "single_phase_32a",
    "ev_min_current": 6.0,
    "ev_max_current": 32.0,
    "ev_voltage": 230.0,
    "ev_phase_count": 1,
    "inverter_capacity_kw": 0.0,
    "bonus_load_following_percent": 20.0,
    "non_free_load_following_percent": 30.0,
    "load_following_override": False,
    "bonus_window_start": "18:00:00",
    "bonus_window_end": "21:00:00",
    "zero_import_threshold_kw": 0.05,
    "zero_import_confirm_minutes": 5.0,
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


async def test_free_charge_target_accounts_for_allowance_house_load_and_solar(hass, monkeypatch):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.test_house_load", "4", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.test_solar", "3", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Charge target site",
        data={
            **ENTRY_DATA,
            "solar_power_entity": "sensor.test_solar",
            "inverter_charge_limit_kw": 15.0,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    coordinator.data = replace(coordinator.data, free_window_import_kwh=5.0)
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.coordinator.dt_util.now",
        lambda: datetime(2026, 9, 3, 12, 1, tzinfo=ZoneInfo("Australia/Sydney")),
    )
    plan = coordinator.free_charge_plan
    assert plan is not None
    assert plan.target_grid_import_kw > 0
    assert round(plan.target_charge_power_kw, 3) == 13.169
    assert coordinator.free_charge_completion is not None
    assert coordinator.free_charge_completion.action == "continue"


async def test_full_battery_completion_mode_is_exposed(hass):
    hass.states.async_set("sensor.test_battery_soc", "100", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Full battery site",
        data={**ENTRY_DATA, "inverter_charge_limit_kw": 15.0},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    coordinator.data = replace(coordinator.data, free_window_import_kwh=48.0)
    completion = coordinator.free_charge_completion
    assert completion is not None
    assert completion.action == "backup"


async def test_zerohero_hourly_accumulator_is_exposed(hass):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(domain=DOMAIN, title="ZEROHERO Site", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    now = datetime(2026, 9, 3, 20, 30, tzinfo=ZoneInfo("Australia/Sydney"))
    coordinator.zerohero_import.local_date = now.date()
    coordinator.zerohero_import.last_at = now
    coordinator.zerohero_import.hourly_import_kwh = {
        "2026-09-03T18:00:00+10:00": 0.01,
        "2026-09-03T19:00:00+10:00": 0.02,
        "2026-09-03T20:00:00+10:00": 0.04,
    }
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    entity = _entity_id(hass, entry, "zerohero_import_window")
    state = hass.states.get(entity)
    assert state.state == "0.07"
    assert state.attributes["hourly_import_kwh"]["2026-09-03T20:00:00+10:00"] == 0.04
    assert state.attributes["threshold_kwh_per_hour"] == 0.05


async def test_potential_capacity_is_multiplied_by_soc(hass):
    hass.states.async_set("sensor.test_battery_soc", "45", {"unit_of_measurement": "%"})
    hass.states.async_set(
        "sensor.test_battery_capacity", "40.32", {"unit_of_measurement": "kWh"}
    )
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="H3 Site",
        data={**ENTRY_DATA, "battery_capacity_entity": "sensor.test_battery_capacity"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    potential = _entity_id(hass, entry, "battery_potential_capacity")
    current = _entity_id(hass, entry, "battery_energy")
    available = _entity_id(hass, entry, "available_energy")
    assert hass.states.get(potential).state == "40.32"
    assert hass.states.get(current).state == "18.144"
    assert hass.states.get(available).state == "12.112"


async def test_tariff_allowance_uses_a_mapped_cumulative_meter_when_available(hass):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set(
        "sensor.test_daily_import", "47.5", {"unit_of_measurement": "kWh"}
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tariff Site",
        data={**ENTRY_DATA, "daily_import_entity": "sensor.test_daily_import"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    remaining = _entity_id(hass, entry, "free_energy_remaining")
    tariff_status = _entity_id(hass, entry, "tariff_status")
    # The mapped meter is all-day accounting; the free allowance is tracked
    # separately from imports observed inside the configured free window.
    assert hass.states.get(remaining).state == "50.0"
    assert hass.states.get(tariff_status).state in {
        "bonus_window_inactive",
        "zero_import_not_sustained",
    }


async def test_tariff_allowance_uses_internal_daily_meter_on_greenfield_site(hass):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "1200", {"unit_of_measurement": "W"})
    entry = MockConfigEntry(domain=DOMAIN, title="Greenfield Site", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    daily_import = _entity_id(hass, entry, "daily_import")
    remaining = _entity_id(hass, entry, "free_energy_remaining")
    assert hass.states.get(daily_import).state == "0.0"
    assert hass.states.get(remaining).state == "50.0"
    assert entry.runtime_data.data.daily_import_source == "internal_accumulator"


async def test_learning_history_is_persisted_and_exposed(hass):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(domain=DOMAIN, title="Learning Site", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    first_cycle = datetime(2026, 8, 27, tzinfo=UTC)
    for offset in range(7):
        await entry.runtime_data.async_record_demand_cycle(
            offset + 1, first_cycle + timedelta(days=offset)
        )
    await hass.async_block_till_done()
    assert len(entry.runtime_data.demand_history.samples) == 7
    assert entry.runtime_data.learning_result.cycle_budget_kwh == 5.8

    budget = _entity_id(hass, entry, "learned_house_energy")
    samples = _entity_id(hass, entry, "learning_samples")
    status = _entity_id(hass, entry, "status")
    assert hass.states.get(budget).state == "5.8"
    assert hass.states.get(samples).state == "7"
    assert hass.states.get(status).attributes["learning_model"] == "p80"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(budget).state == "5.8"
    assert hass.states.get(samples).state == "7"


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


async def test_learning_sampler_uses_home_assistant_local_time(hass, monkeypatch):
    """Configured Australian window boundaries must not be interpreted as UTC."""

    coordinator = EnergyCoordinator(hass, {}, "timezone-test")
    coordinator.snapshot = SiteSnapshot(
        battery_soc=50,
        battery_capacity_kwh=20,
        battery_floor_percent=10,
        reserve_kwh=0,
        grid_power_kw=0,
        house_load_kw=1,
    )
    coordinator.demand_sampler = DemandCycleSampler(time(12), time(15))
    local_now = datetime(2026, 9, 2, 12, 5, tzinfo=ZoneInfo("Australia/Sydney"))
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.coordinator.dt_util.now",
        lambda: local_now,
    )

    await coordinator._async_sample_house_load()

    assert coordinator.demand_sampler._last_at == local_now
    coordinator.shutdown()
