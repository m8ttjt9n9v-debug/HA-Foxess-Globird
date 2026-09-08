from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from homeassistant.const import EVENT_CALL_SERVICE, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN
from custom_components.home_energy_orchestrator.coordinator import EnergyCoordinator
from custom_components.home_energy_orchestrator.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.home_energy_orchestrator.models import SiteSnapshot
from custom_components.home_energy_orchestrator.planner.learning import DemandCycleSampler

ENTRY_DATA = {
    "battery_soc_entity": "sensor.test_battery_soc",
    "battery_charge_positive": True,
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
    "export_rate_per_kwh": 0.0,
    "super_export_rate_per_kwh": 0.10,
    "site_phase_count": 1,
    "service_import_limit_a": 0.0,
    "export_limit_kw": 0.0,
    "inverter_charge_limit_kw": 0.0,
    "inverter_discharge_limit_kw": 0.0,
    "house_load_entity": "sensor.test_house_load",
    "free_charge_window_start": "12:01:00",
    "free_charge_window_end": "14:59:00",
    "house_learning_fallback_kwh": 17.5,
    "house_away_fallback_kwh": 6.5,
    "house_away_confirmation_hours": 6.0,
    "house_occupancy_mode": "auto",
    "automatic_control_enabled": False,
    "automatic_export_enabled": False,
    "ev_automatic_control_enabled": False,
    "ev_location_mode": "auto",
    "ev_free_window_priority": "ev",
    "ev_free_window_charge_limit_percent": 90.0,
    "ev_free_window_minimum_current_a": 1.0,
    "ev_free_window_settle_minutes": 5.0,
    "ev_direct_limit_headroom_percent": 2.0,
    "ev_charge_efficiency_percent": 90.0,
    "ev_arrival_reserve_soc_percent": 20.0,
    "ev_learning_minimum_samples": 14,
    "site_grid_headroom_current_a": 1.0,
    "battery_free_window_target_percent": 100.0,
    "battery_charge_efficiency_percent": 95.0,
    "ev_allowance_guard_enabled": True,
    "ev_allowance_safety_margin_kwh": 0.0,
    "ev_solar_spill_enabled": False,
    "ev_solar_spill_battery_soc_percent": 100.0,
    "ev_pre_free_backfill_enabled": False,
    "ev_telemetry_max_age_seconds": 90.0,
    "ev_telemetry_max_skew_seconds": 30.0,
    "ev_control_commissioned": False,
    "ev_charge_path": "direct_evse",
    "ev_smart_socket_current_limit_a": 0.0,
    "ev_smart_socket_settle_seconds": 15.0,
    "ev_smart_socket_retry_seconds": 300.0,
    "ev_smart_socket_power_switching": False,
    "ev_smart_recovery_no_power_seconds": 120.0,
    "ev_smart_recovery_current_confirm_seconds": 60.0,
    "ev_smart_recovery_socket_confirm_seconds": 15.0,
    "ev_smart_recovery_power_off_seconds": 30.0,
    "ev_smart_recovery_post_power_seconds": 20.0,
    "ev_smart_recovery_charging_confirm_seconds": 180.0,
    "ev_smart_recovery_rearm_seconds": 120.0,
    "ev_smart_recovery_idle_current_a": 0.5,
    "foxess_control_owner": "observer_only",
    "rehearsal_mode": True,
    "ev_min_current": 6.0,
    "ev_max_current": 32.0,
    "ev_voltage": 230.0,
    "ev_phase_count": 1,
    "bonus_window_start": "18:00:00",
    "bonus_window_end": "21:00:00",
    "force_discharge_finish": "21:01:00",
    "export_allowance_kwh": 15.0,
    "export_discharge_power_kw": 10.0,
    "discharge_efficiency_percent": 95.0,
    "ev_protected_baseline_a": 0.0,
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
    assert status == "sensor.home_energy_status"
    assert _entity_id(hass, entry, "battery_soc") == "sensor.home_energy_battery_soc"
    assert hass.states.get(available_energy).state == "8.0"
    assert hass.states.get(grid_import).state == "1.2"
    assert hass.states.get(status).state == "observer_only"
    assert hass.states.get(status).attributes["writes_performed"] == 0
    assert hass.states.get(status).attributes["automatic_control_enabled"] is False
    assert hass.states.get(status).attributes["mode"] == "observe"
    assert hass.states.get("sensor.home_energy_ev_solar_spill_status").state == "disabled"
    assert hass.states.get("sensor.home_energy_ev_pre_free_status").state == "disabled"
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["actuators"]["foxess_automatic_control_enabled"] is False
    assert diagnostics["actuators"]["foxess_control_owner"] == "observer_only"
    assert diagnostics["actuators"]["writes_enabled"] is False
    assert service_calls == []


async def test_safety_lock_switch_is_on_by_default_and_persists_unlock(hass):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(domain=DOMAIN, title="Safety site", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    lock = hass.states.get("switch.home_energy_safety_lock")
    assert lock is not None
    assert lock.state == "on"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.home_energy_safety_lock"}, blocking=True
    )
    assert hass.states.get("switch.home_energy_safety_lock").state == "off"
    assert entry.data["rehearsal_mode"] is False
    assert entry.runtime_data.config["rehearsal_mode"] is False


async def test_automatic_export_switch_is_independent_and_persists(hass):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(domain=DOMAIN, title="Export site", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.home_energy_automatic_export").state == "off"

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.home_energy_automatic_export"},
        blocking=True,
    )

    assert hass.states.get("switch.home_energy_automatic_export").state == "on"
    assert entry.data["automatic_export_enabled"] is True
    assert entry.data["automatic_control_enabled"] is False
    assert entry.data["rehearsal_mode"] is True


async def test_automatic_ev_switch_is_independent_but_cannot_write_yet(hass):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(domain=DOMAIN, title="EV site", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    service_calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, service_calls.append)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.home_energy_automatic_ev_control").state == "off"

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.home_energy_automatic_ev_control"},
        blocking=True,
    )

    status = hass.states.get("sensor.home_energy_status")
    assert entry.data["ev_automatic_control_enabled"] is True
    assert entry.data["automatic_control_enabled"] is False
    assert status.attributes["ev_control_gate"] == "safety_locked"
    assert status.attributes["ev_writes_enabled"] is False
    assert [event for event in service_calls if event.data["domain"] != "switch"] == []


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


async def test_mapped_telemetry_is_exposed_for_portable_dashboard(hass):
    """Expose mapped source telemetry without requiring site-specific IDs."""
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "1200", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.test_house_load", "800", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.test_solar", "3", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.test_ev_soc", "70", {"unit_of_measurement": "%"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Portable dashboard site",
        data={
            **ENTRY_DATA,
            "solar_power_entity": "sensor.test_solar",
            "ev_soc_entity": "sensor.test_ev_soc",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(_entity_id(hass, entry, "battery_soc")).state == "60.0"
    assert hass.states.get(_entity_id(hass, entry, "house_load")).state == "0.8"
    assert hass.states.get(_entity_id(hass, entry, "solar_power")).state == "3.0"
    assert hass.states.get(_entity_id(hass, entry, "ev_soc")).state == "70.0"


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
    hass.states.async_set("sensor.test_battery_capacity", "40.32", {"unit_of_measurement": "kWh"})
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
    hass.states.async_set("sensor.test_daily_import", "47.5", {"unit_of_measurement": "kWh"})
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
    assert hass.states.get(status).attributes["learning_model"] == "measured_occupied_p80"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(budget).state == "5.8"
    assert hass.states.get(samples).state == "7"


async def test_separate_heater_history_is_persisted_and_combined_only_when_mature(hass):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.test_house_load", "1", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.test_heater", "2", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Heater learning site",
        data={**ENTRY_DATA, "heater_power_entity": "sensor.test_heater"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    first_cycle = datetime(2026, 8, 27, tzinfo=UTC)
    for offset in range(7):
        entry.runtime_data.demand_history.add(
            first_cycle + timedelta(days=offset), offset + 1
        )
    for offset in range(6):
        entry.runtime_data.heater_history.add(
            first_cycle + timedelta(days=offset), offset + 1
        )
    await entry.runtime_data._async_save_demand_state()
    assert entry.runtime_data.learning_result.cycle_budget_kwh == 17.5
    assert entry.runtime_data.learning_result.model == "occupied_fallback"

    entry.runtime_data.heater_history.add(first_cycle + timedelta(days=6), 7)
    await entry.runtime_data._async_save_demand_state()
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()
    assert entry.runtime_data.learning_result.cycle_budget_kwh == 11.6
    assert hass.states.get("sensor.home_energy_heater_learning_samples").state == "7"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(entry.runtime_data.heater_history.samples) == 7
    assert entry.runtime_data.learning_result.cycle_budget_kwh == 11.6


async def test_house_occupancy_select_persists_manual_away_budget(hass):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(domain=DOMAIN, title="Occupancy site", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("select.home_energy_house_occupancy_mode").state == "Auto"
    assert hass.states.get("sensor.home_energy_house_occupancy_state").state == "home"
    await hass.services.async_call(
        "select",
        "select_option",
        {
            "entity_id": "select.home_energy_house_occupancy_mode",
            "option": "Away",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    assert entry.data["house_occupancy_mode"] == "away"
    assert hass.states.get("sensor.home_energy_house_occupancy_state").state == "away"
    assert hass.states.get("sensor.home_energy_learned_house_energy").state == "6.5"
    assert entry.runtime_data.learning_result.model == "away_fallback"


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
