"""Constant native values must use their publisher's clock, not value-change age."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.test_ev_backfill_timing import _fresh, _services
from tests.test_ev_before_export_charging import _above_baseline, _case, _now

VIN = "TESTVEHICLE0000001"
FIELDS = {
    "sensor.car_soc": "charge_state_usable_battery_level",
    "sensor.car_actual_current": "charge_state_charger_actual_current",
    "sensor.car_charging": "charge_state_charging_state",
    "binary_sensor.car_cable": "charge_state_conn_charge_cable",
    "number.car_current": "charge_state_charge_current_request",
    "number.car_limit": "charge_state_charge_limit_soc",
    "switch.car_charge": "charge_state_charge_enable_request",
}


def _register(hass, entry, device, entity, key):
    old = hass.states.get(entity)
    hass.states.async_remove(entity)
    domain, name = entity.split(".")
    row = er.async_get(hass).async_get_or_create(
        domain, entry.domain, key, config_entry=entry,
        device_id=device.id, suggested_object_id=name,
    )
    assert row.entity_id == entity
    hass.states.async_set(entity, old.state, dict(old.attributes))


def _native(hass, freezer, *, old_seconds=3600):
    now = _now(16)
    freezer.move_to(now - timedelta(seconds=old_seconds))
    coordinator, controller = _case(hass, now - timedelta(seconds=old_seconds))
    entry = MockConfigEntry(domain="tessie")
    entry.add_to_hass(hass)
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("tessie", VIN)},
    )
    for entity, key in FIELDS.items():
        _register(hass, entry, device, entity, f"{VIN}-{key}")
    provider = SimpleNamespace(
        config_entry=entry, last_update_success=True,
        data={
            "state": "online", "charge_state_timestamp": now.timestamp() * 1000,
            "charge_state_usable_battery_level": 25,
            "charge_state_charger_actual_current": 0,
            "charge_state_charging_state": "Stopped",
            "charge_state_conn_charge_cable": "IEC",
            "charge_state_charge_current_request": 6,
            "charge_state_charge_limit_soc": 80,
        },
    )
    vehicle = SimpleNamespace(vin=VIN, data_coordinator=provider)
    entry.runtime_data = SimpleNamespace(vehicles=[vehicle])
    fox = MockConfigEntry(domain="foxess_modbus")
    fox.add_to_hass(hass)
    fox._async_set_state(hass, ConfigEntryState.LOADED, None)
    inverter = dr.async_get(hass).async_get_or_create(
        config_entry_id=fox.entry_id, identifiers={("foxess_modbus", "synthetic-inverter")},
    )
    for entity in ("select.foxess_mode", "sensor.site_grid", "sensor.site_battery_soc"):
        _register(hass, fox, inverter, entity, "foxess_modbus_" + entity.split(".")[1])
    freezer.move_to(now)
    # Only actual live electrical evidence and location report again. All
    # constant values above deliberately retain their original old HA clocks.
    hass.states.async_set("device_tracker.car", "home", force_update=True)
    hass.states.async_set("sensor.site_grid", "0", {"unit_of_measurement": "kW"},
                          force_update=True)
    _fresh(coordinator, now)
    return SimpleNamespace(
        now=now, coordinator=coordinator, controller=controller, provider=provider,
        entry=entry, fox=fox, vehicle=vehicle,
    )


@pytest.fixture(autouse=True)
def utc_clock(monkeypatch):
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.ev_active.dt_util.now",
        lambda: datetime.now(UTC),
    )


@pytest.fixture(autouse=True)
async def native_provider_cleanup(hass):
    """These native-cache fixtures never load a provider or its HTTP client."""
    yield
    for entry in hass.config_entries.async_entries():
        if entry.domain in {"tessie", "foxess_modbus"}:
            entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    await hass.async_block_till_done()


@pytest.mark.parametrize("old_seconds", [91, 3600, 86400])
async def test_unchanged_native_values_with_recent_vehicle_frame_start_top_up(
    hass, freezer, old_seconds,
):
    rig = _native(hass, freezer, old_seconds=old_seconds)
    calls = _services(hass)
    original = {e: hass.states.get(e).last_reported for e in FIELDS}
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.decision_phase == "ev_before_export_charging"
    assert rig.controller.target_current_a == 8
    assert _above_baseline(calls)
    assert original == {e: hass.states.get(e).last_reported for e in FIELDS}


@pytest.mark.parametrize("fault", [
    "stale_frame", "future_frame", "missing_clock", "invalid_clock", "failed_provider",
    "unloaded", "offline", "duplicate_vehicle", "wrong_vehicle", "wrong_entry",
    "soc_mismatch", "actual_mismatch", "request_mismatch", "limit_mismatch",
    "cable_mismatch", "switch_mismatch", "charging_mismatch", "restored_soc",
    "missing_actual", "wrong_unit", "wrong_device", "wrong_field", "disabled",
    "stale_home", "stale_grid", "stale_battery", "stale_house", "mode_restored",
    "mode_unavailable", "wrong_inverter", "inverter_unloaded", "mode_force_discharge",
])
async def test_native_clock_is_not_permission_for_invalid_or_offline_evidence(
    hass, freezer, fault,
):
    rig = _native(hass, freezer)
    calls = _services(hass)
    data = rig.provider.data
    if fault in {"stale_frame", "future_frame"}:
        data["charge_state_timestamp"] = (
            rig.now + timedelta(seconds=-91 if fault == "stale_frame" else 1)
        ).timestamp() * 1000
    elif fault == "missing_clock":
        data.pop("charge_state_timestamp")
    elif fault == "invalid_clock":
        data["charge_state_timestamp"] = True
    elif fault == "failed_provider":
        rig.provider.last_update_success = False
    elif fault == "unloaded":
        rig.entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    elif fault == "offline":
        data["state"] = "asleep"
    elif fault == "duplicate_vehicle":
        rig.entry.runtime_data.vehicles.append(rig.vehicle)
    elif fault == "wrong_vehicle":
        rig.vehicle.vin = "TESTVEHICLE0000002"
    elif fault == "wrong_entry":
        rig.provider.config_entry = SimpleNamespace(entry_id="another-entry")
    elif fault.endswith("_mismatch"):
        field, value = {
            "soc_mismatch": ("charge_state_usable_battery_level", 31),
            "actual_mismatch": ("charge_state_charger_actual_current", 5),
            "request_mismatch": ("charge_state_charge_current_request", 16),
            "limit_mismatch": ("charge_state_charge_limit_soc", 100),
            "cable_mismatch": ("charge_state_conn_charge_cable", "<invalid>"),
            "switch_mismatch": ("charge_state_charging_state", True),
            "charging_mismatch": ("charge_state_charging_state", "Charging"),
        }[fault]
        data[field] = value
    elif fault == "restored_soc":
        hass.states.async_set("sensor.car_soc", "25", {"restored": True})
    elif fault == "missing_actual":
        hass.states.async_remove("sensor.car_actual_current")
    elif fault == "wrong_unit":
        hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "kW"})
    elif fault in {"wrong_device", "wrong_field", "disabled"}:
        kwargs = {
            "wrong_device": {"device_id": None},
            "wrong_field": {"new_unique_id": f"{VIN}-vehicle_state_speed"},
            "disabled": {"disabled_by": er.RegistryEntryDisabler.USER},
        }[fault]
        er.async_get(hass).async_update_entity("sensor.car_actual_current", **kwargs)
    elif fault == "stale_home":
        old = rig.now - timedelta(seconds=91)
        freezer.move_to(old)
        hass.states.async_set("device_tracker.car", "home", force_update=True)
        freezer.move_to(rig.now)
    elif fault in {"stale_grid", "stale_battery", "stale_house"}:
        from dataclasses import replace
        field = {"stale_grid": "grid_power", "stale_battery": "battery_power",
                 "stale_house": "house_load"}[fault]
        sample = getattr(rig.coordinator.telemetry, field)
        rig.coordinator.telemetry = replace(
            rig.coordinator.telemetry, **{field: replace(sample, fresh=False)},
        )
    elif fault == "mode_restored":
        hass.states.async_set("select.foxess_mode", "Self Use", {"restored": True})
    elif fault == "mode_unavailable":
        hass.states.async_set("select.foxess_mode", "unavailable")
    elif fault == "wrong_inverter":
        er.async_get(hass).async_update_entity("sensor.site_grid", device_id=None)
    elif fault == "inverter_unloaded":
        rig.fox._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    elif fault == "mode_force_discharge":
        hass.states.async_set("select.foxess_mode", "Force Discharge")
    await rig.controller.async_reconcile(rig.now)
    assert not _above_baseline(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("age,allowed", [(0, True), (90, True), (90.001, False)])
async def test_native_measurement_clock_keeps_exact_existing_age_limit(
    hass, freezer, age, allowed,
):
    rig = _native(hass, freezer)
    rig.provider.data["charge_state_timestamp"] = (
        rig.now - timedelta(seconds=age)
    ).timestamp() * 1000
    # A fresh GPS/HTTP-cache observation cannot renew old charge measurements.
    rig.provider.data["drive_state_timestamp"] = rig.now.timestamp() * 1000
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert bool(_above_baseline(calls)) is allowed


@pytest.mark.parametrize("fault", ["stale_frame", "provider_failed", "reserve", "mapping"])
async def test_native_authority_is_rechecked_between_awaited_positive_commands(
    hass, freezer, fault,
):
    rig = _native(hass, freezer)
    calls = []

    async def apply(call):
        calls.append((call.domain, call.service, dict(call.data)))
        if call.data.get("entity_id") != "number.car_limit":
            return
        if fault == "stale_frame":
            rig.provider.data["charge_state_timestamp"] -= 91_000
        elif fault == "provider_failed":
            rig.provider.last_update_success = False
        elif fault == "reserve":
            hass.states.async_set("sensor.site_battery_soc", "19", {"unit_of_measurement": "%"})
        else:
            er.async_get(hass).async_update_entity("sensor.car_soc", device_id=None)

    for domain, service in (("number", "set_value"), ("switch", "turn_on"),
                            ("switch", "turn_off")):
        hass.services.async_register(domain, service, apply)
    await rig.controller.async_reconcile(rig.now)
    assert calls and calls[0][2]["entity_id"] == "number.car_limit"
    assert not _above_baseline(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


async def test_healthy_frame_expires_without_rewriting_entity_clocks(hass, freezer):
    rig = _native(hass, freezer)
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert _above_baseline(calls)
    now = rig.now + timedelta(seconds=91)
    freezer.move_to(now)
    _fresh(rig.coordinator, now)
    hass.states.async_set("device_tracker.car", "home", force_update=True)
    calls.clear()
    await rig.controller.async_reconcile(now)
    assert rig.controller.decision_phase == "ev_before_export_energy_unavailable"
    assert not _above_baseline(calls)


async def test_existing_fresh_mixed_mapping_needs_no_native_cache_fallback(hass, freezer):
    rig = _native(hass, freezer, old_seconds=0)
    # Explicit template/device mappings keep their own strict clock contract;
    # they cannot borrow a native car's clock when any input expires.
    er.async_get(hass).async_remove("sensor.car_actual_current")
    hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "A"},
                          force_update=True)
    rig.entry.runtime_data = None
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert _above_baseline(calls)


@pytest.mark.parametrize("fault", ["old_measurement", "failed_provider"])
async def test_fresh_native_entity_reports_cannot_renew_old_or_failed_vehicle_data(
    hass, freezer, fault,
):
    rig = _native(hass, freezer, old_seconds=0)
    if fault == "old_measurement":
        rig.provider.data["charge_state_timestamp"] -= 91_000
    else:
        rig.provider.last_update_success = False
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert not _above_baseline(calls)


async def test_fresh_mode_does_not_require_native_grid_or_battery_mapping(hass, freezer):
    rig = _native(hass, freezer)
    state = hass.states.get("select.foxess_mode")
    hass.states.async_set(state.entity_id, state.state, dict(state.attributes), force_update=True)
    er.async_get(hass).async_update_entity("sensor.site_grid", device_id=None)
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert _above_baseline(calls)
