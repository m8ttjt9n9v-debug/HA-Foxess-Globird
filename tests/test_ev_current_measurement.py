"""Shared measured-current provenance, independent of charging policy values."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.ev_current_measurement import (
    measure_ev_current,
    measure_ev_soc,
)
from custom_components.home_energy_orchestrator.ev_observation_adapter import (
    EvObservationEntityMap,
    capture_ev_feedback,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
VIN = "MEASUREMENTTEST01"
ENTITIES = EvObservationEntityMap(
    actual_current_entity="sensor.measurement_actual",
    charging_state_entity="sensor.measurement_charging",
    current_limit_entity="number.measurement_request",
    charge_limit_entity="number.measurement_limit",
    soc_entity="sensor.measurement_soc",
)


@pytest.fixture(autouse=True)
async def provider_cleanup(hass):
    """These fixtures never load a native provider or contact a vehicle."""
    yield
    for entry in hass.config_entries.async_entries("tessie"):
        entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    await hass.async_block_till_done()


def _generic(hass, freezer, *, current=8, charging="charging", age=0):
    freezer.move_to(NOW - timedelta(seconds=age))
    hass.states.async_set(
        ENTITIES.actual_current_entity, str(current), {"unit_of_measurement": "A"},
    )
    hass.states.async_set(ENTITIES.charging_state_entity, charging)
    freezer.move_to(NOW)
    return capture_ev_feedback(hass, ENTITIES)


def _native(hass, freezer, *, current=8, charging="Charging", age=3600):
    _generic(hass, freezer, current=current, charging=charging.lower(), age=age)
    entry = MockConfigEntry(domain="tessie")
    entry.add_to_hass(hass)
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("tessie", VIN)},
    )
    for entity, field in (
        (ENTITIES.actual_current_entity, "charge_state_charger_actual_current"),
        (ENTITIES.charging_state_entity, "charge_state_charging_state"),
    ):
        old = hass.states.get(entity)
        hass.states.async_remove(entity)
        domain, name = entity.split(".")
        row = er.async_get(hass).async_get_or_create(
            domain, "tessie", f"{VIN}-{field}", config_entry=entry,
            device_id=device.id, suggested_object_id=name,
        )
        assert row.entity_id == entity
        freezer.move_to(NOW - timedelta(seconds=age))
        hass.states.async_set(entity, old.state, dict(old.attributes))
        freezer.move_to(NOW)
    provider = SimpleNamespace(
        config_entry=entry, last_update_success=True,
        data={
            "state": "online", "charge_state_timestamp": NOW.timestamp() * 1000,
            "charge_state_charger_actual_current": current,
            "charge_state_charging_state": charging,
            "charge_state_charge_current_request": 12,
        },
    )
    vehicle = SimpleNamespace(vin=VIN, data_coordinator=provider)
    entry.runtime_data = SimpleNamespace(vehicles=[vehicle])
    return SimpleNamespace(entry=entry, device=device, provider=provider, vehicle=vehicle)


def _measure(hass, *, now=NOW, max_age=90, feedback=None, retain_generic_values=False):
    return measure_ev_current(
        hass, feedback or capture_ev_feedback(hass, ENTITIES),
        now=now, max_age_seconds=max_age, retain_generic_values=retain_generic_values,
    )


@pytest.mark.parametrize("retain_generic_values", [False, True])
async def test_native_frame_with_unchanged_old_entities_is_stamped_and_immutable(
    hass, freezer, retain_generic_values,
):
    rig = _native(hass, freezer)
    clocks = {entity: hass.states.get(entity).last_reported for entity in (
        ENTITIES.actual_current_entity, ENTITIES.charging_state_entity,
    )}
    first = _measure(hass, retain_generic_values=retain_generic_values)
    assert first.valid and first.current_a == 8
    assert first.measured_at == NOW and first.source == "tessie_charge_state"
    assert first.requested_current_a == 12
    assert first.binding[-3:] == (rig.entry.entry_id, rig.device.id, VIN)
    with pytest.raises(FrozenInstanceError):
        first.current_a = 12

    later = NOW + timedelta(seconds=30)
    freezer.move_to(later)
    rig.provider.data["charge_state_timestamp"] = later.timestamp() * 1000
    second = _measure(hass, now=later, retain_generic_values=retain_generic_values)
    assert second.valid and second.current_a == first.current_a
    assert second.measured_at == later
    assert clocks == {entity: hass.states.get(entity).last_reported for entity in clocks}


@pytest.mark.parametrize("frame_request", [16, None, True, -1, float("nan")])
async def test_native_actual_ignores_policy_and_optimistic_request(hass, freezer, frame_request):
    rig = _native(hass, freezer)
    hass.states.async_set(ENTITIES.soc_entity, "unavailable")
    hass.states.async_set(ENTITIES.current_limit_entity, "3", {"unit_of_measurement": "A"})
    rig.provider.data["charge_state_charge_current_request"] = frame_request
    result = _measure(hass)
    assert result.valid and result.current_a == 8
    assert result.requested_current_a == (16 if frame_request == 16 else None)


@pytest.mark.parametrize("age,valid", [(0, True), (90, True), (90.001, False), (-0.001, False)])
async def test_native_uses_exact_configured_measurement_age(hass, freezer, age, valid):
    rig = _native(hass, freezer)
    rig.provider.data["charge_state_timestamp"] = (NOW - timedelta(seconds=age)).timestamp() * 1000
    rig.provider.data["drive_state_timestamp"] = NOW.timestamp() * 1000
    rig.provider.data["timestamp"] = NOW.timestamp() * 1000
    assert _measure(hass).valid is valid


@pytest.mark.parametrize("fault", [
    "failed", "unloaded", "asleep", "offline", "missing_clock", "bool_clock",
    "nonfinite_clock", "wrong_provider", "wrong_vehicle", "duplicate_vehicle",
    "actual_mismatch", "charging_mismatch", "bool_actual", "negative_actual",
    "unknown_actual", "unknown_charging", "restored_actual", "restored_charging",
    "wrong_unit", "wrong_field", "wrong_device", "disabled_actual", "disabled_charging",
    "cross_vehicle", "mixed_native", "future_report",
])
@pytest.mark.parametrize("retain_generic_values", [False, True])
async def test_invalid_native_observations_cannot_fall_back_to_ha_clocks(
    hass, freezer, fault, retain_generic_values,
):
    rig = _native(hass, freezer, age=0)
    if fault == "failed":
        rig.provider.last_update_success = False
    elif fault == "unloaded":
        rig.entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    elif fault in {"asleep", "offline"}:
        rig.provider.data["state"] = fault
    elif fault == "missing_clock":
        rig.provider.data.pop("charge_state_timestamp")
    elif fault in {"bool_clock", "nonfinite_clock"}:
        rig.provider.data["charge_state_timestamp"] = (
            True if fault == "bool_clock" else float("nan")
        )
    elif fault == "wrong_provider":
        rig.provider.config_entry = SimpleNamespace(entry_id=rig.entry.entry_id)
    elif fault == "wrong_vehicle":
        rig.vehicle.vin = "DIFFERENTVEHICLE"
    elif fault == "duplicate_vehicle":
        rig.entry.runtime_data.vehicles.append(rig.vehicle)
    elif fault in {"actual_mismatch", "bool_actual", "negative_actual"}:
        rig.provider.data["charge_state_charger_actual_current"] = {
            "actual_mismatch": 9, "bool_actual": True, "negative_actual": -1,
        }[fault]
    elif fault == "charging_mismatch":
        rig.provider.data["charge_state_charging_state"] = "Stopped"
    elif fault in {"unknown_actual", "unknown_charging", "restored_actual", "restored_charging",
                   "wrong_unit", "future_report"}:
        entity = (
            ENTITIES.charging_state_entity if fault.endswith("charging")
            else ENTITIES.actual_current_entity
        )
        old = hass.states.get(entity)
        attrs = dict(old.attributes)
        if fault.startswith("restored"):
            attrs["restored"] = True
        if fault == "wrong_unit":
            attrs["unit_of_measurement"] = "kW"
        if fault == "future_report":
            freezer.move_to(NOW + timedelta(seconds=1))
        hass.states.async_set(entity, "unknown" if fault.startswith("unknown") else old.state,
                              attrs, force_update=True)
        freezer.move_to(NOW)
    else:
        entity = ENTITIES.charging_state_entity if fault in {
            "disabled_charging", "cross_vehicle", "mixed_native",
        } else ENTITIES.actual_current_entity
        if fault == "mixed_native":
            er.async_get(hass).async_remove(entity)
        elif fault == "cross_vehicle":
            other = dr.async_get(hass).async_get_or_create(
                config_entry_id=rig.entry.entry_id, identifiers={("tessie", "OTHERTESTVEHICLE")},
            )
            er.async_get(hass).async_update_entity(entity, device_id=other.id)
        else:
            changes = (
                {"disabled_by": er.RegistryEntryDisabler.USER} if fault.startswith("disabled")
                else {"device_id": None} if fault == "wrong_device"
                else {"new_unique_id": f"{VIN}-drive_state_power"}
            )
            er.async_get(hass).async_update_entity(entity, **changes)
    result = _measure(hass, retain_generic_values=retain_generic_values)
    assert not result.valid and result.current_a == 0 and result.measured_at is None


@pytest.mark.parametrize("charging", ["Stopped", "Complete", "Disconnected", "NoPower"])
async def test_native_stopped_state_qualifies_retained_current_as_zero(hass, freezer, charging):
    _native(hass, freezer, current=8, charging=charging)
    if charging == "NoPower":
        hass.states.async_set(ENTITIES.charging_state_entity, "no_power")
    result = _measure(hass)
    assert result.valid and result.current_a == 0 and result.measured_at == NOW
    assert result.reason == "measured_stopped"


async def test_captured_values_must_still_match_the_native_measurement(hass, freezer):
    rig = _native(hass, freezer)
    captured = capture_ev_feedback(hass, ENTITIES)
    hass.states.async_set(ENTITIES.actual_current_entity, "16", {"unit_of_measurement": "A"})
    assert _measure(hass, feedback=captured).current_a == 8
    rig.provider.data["charge_state_charger_actual_current"] = 16
    assert not _measure(hass, feedback=captured).valid
    assert _measure(hass).current_a == 16


@pytest.mark.parametrize("charging,current,expected", [
    ("charging", 8, 8), ("charging", 0, 0), ("stopped", 8, 0),
    ("complete", 8, 0), ("disconnected", 8, 0), ("no_power", 8, 0),
])
async def test_generic_explicit_state_and_report_clocks(hass, freezer, charging, current, expected):
    _generic(hass, freezer, current=current, charging=charging)
    result = _measure(hass)
    assert result.valid and result.current_a == expected
    assert result.measured_at == NOW and result.source == "entity_report"
    assert result.requested_current_a is None


@pytest.mark.parametrize("entity", [ENTITIES.actual_current_entity, ENTITIES.charging_state_entity])
@pytest.mark.parametrize("fault", ["stale", "future", "restored", "unknown"])
async def test_each_generic_source_requires_valid_bounded_report(hass, freezer, entity, fault):
    _generic(hass, freezer)
    if fault == "stale":
        freezer.move_to(NOW + timedelta(seconds=91))
        other = (
            ENTITIES.charging_state_entity if entity == ENTITIES.actual_current_entity
            else ENTITIES.actual_current_entity
        )
        old = hass.states.get(other)
        hass.states.async_set(other, old.state, dict(old.attributes), force_update=True)
        now = NOW + timedelta(seconds=91)
    else:
        old = hass.states.get(entity)
        if fault == "future":
            freezer.move_to(NOW + timedelta(seconds=1))
        attrs = {**old.attributes, **({"restored": True} if fault == "restored" else {})}
        hass.states.async_set(entity, "unknown" if fault == "unknown" else old.state,
                              attrs, force_update=True)
        now = NOW
    assert not _measure(hass, now=now).valid


async def test_generic_stamp_is_oldest_report_and_new_equal_reports_are_real(hass, freezer):
    _generic(hass, freezer, age=20)
    original = hass.states.get(ENTITIES.actual_current_entity)
    hass.states.async_set(ENTITIES.charging_state_entity, "charging", force_update=True)
    assert _measure(hass).measured_at == NOW - timedelta(seconds=20)
    hass.states.async_set(ENTITIES.actual_current_entity, "8", dict(original.attributes))
    result = _measure(hass)
    assert result.valid and result.measured_at == NOW
    assert hass.states.get(ENTITIES.actual_current_entity).last_changed == original.last_changed


@pytest.mark.parametrize("state", ["unknown", "unavailable", "invalid", "true"])
async def test_unrecognised_generic_state_cannot_fabricate_stopped_zero(hass, freezer, state):
    _generic(hass, freezer, charging=state)
    assert not _measure(hass).valid


@pytest.mark.parametrize("current,unit", [
    ("unknown", "A"), ("nan", "A"), ("inf", "A"), (-1, "A"), (8, "kW"),
])
@pytest.mark.parametrize("charging", ["charging", "stopped"])
async def test_bad_generic_current_is_not_valid_even_when_stopped(
    hass, freezer, current, unit, charging,
):
    _generic(hass, freezer, current=current, charging=charging)
    hass.states.async_set(ENTITIES.actual_current_entity, str(current),
                          {"unit_of_measurement": unit})
    assert not _measure(hass).valid


async def test_generic_current_keeps_explicit_unit_conversion(hass, freezer):
    _generic(hass, freezer)
    hass.states.async_set(ENTITIES.actual_current_entity, "8000", {"unit_of_measurement": "mA"})
    result = _measure(hass)
    assert result.valid and result.current_a == 8


@pytest.mark.parametrize("charging,expected", [("charging", 8), ("stopped", 0)])
async def test_legacy_generic_values_are_explicitly_not_stamped_measurements(
    hass, freezer, charging, expected,
):
    feedback = _generic(hass, freezer, age=86400, charging=charging)
    assert not _measure(hass, feedback=feedback).valid
    result = _measure(hass, feedback=feedback, retain_generic_values=True)
    assert result.valid and result.current_a == expected
    assert result.source == "entity_value" and result.measured_at is None
    assert result.reason == ("retained_charging" if expected else "retained_stopped")
    assert result.requested_current_a is None


@pytest.mark.parametrize("fault", [
    "restored_actual", "restored_charging", "bad_actual", "bad_state",
])
async def test_legacy_generic_values_still_require_valid_available_sources(hass, freezer, fault):
    _generic(hass, freezer, age=86400)
    entity = (
        ENTITIES.charging_state_entity if fault in {"restored_charging", "bad_state"}
        else ENTITIES.actual_current_entity
    )
    old = hass.states.get(entity)
    attrs = {**old.attributes, **({"restored": True} if fault.startswith("restored") else {})}
    value = "unknown" if fault in {"bad_actual", "bad_state"} else old.state
    hass.states.async_set(entity, value, attrs)
    assert not _measure(hass, retain_generic_values=True).valid


async def test_legacy_generic_value_contract_does_not_invent_a_report_clock(hass, freezer):
    feedback = _generic(hass, freezer)
    feedback = replace(
        feedback, actual_current=replace(feedback.actual_current, last_reported=None),
    )
    result = _measure(hass, feedback=feedback, retain_generic_values=True)
    assert result.valid and result.current_a == 8 and result.measured_at is None


@pytest.mark.parametrize("charging", ["stopped", "complete", "disconnected", "no_power"])
@pytest.mark.parametrize("actual", [None, "unavailable", "nan", "16"])
async def test_legacy_generic_explicit_stop_does_not_wait_for_actual_current_startup(
    hass, freezer, charging, actual,
):
    freezer.move_to(NOW)
    hass.states.async_set(ENTITIES.charging_state_entity, charging)
    if actual is not None:
        hass.states.async_set(ENTITIES.actual_current_entity, actual, {"unit_of_measurement": "A"})
    result = _measure(hass, retain_generic_values=True)
    assert result.valid and result.current_a == 0 and result.measured_at is None
    assert result.source == "entity_value" and result.reason == "retained_stopped"
    if actual != "16":
        assert not _measure(hass).valid  # Strict/native measurement contracts are unchanged.


@pytest.mark.parametrize("max_age", [-1, True, float("nan"), float("inf")])
async def test_invalid_configured_age_grants_no_measurement(hass, freezer, max_age):
    _generic(hass, freezer)
    assert not _measure(hass, max_age=max_age).valid


async def test_naive_or_missing_report_clock_grants_no_measurement(hass, freezer):
    feedback = _generic(hass, freezer)
    assert not _measure(hass, now=NOW.replace(tzinfo=None), feedback=feedback).valid
    feedback = replace(
        feedback, actual_current=replace(feedback.actual_current, last_reported=None),
    )
    assert not _measure(hass, feedback=feedback).valid


@pytest.mark.parametrize("entity,field", [
    (ENTITIES.soc_entity, "charge_state_usable_battery_level"),
    (ENTITIES.current_limit_entity, "charge_state_charge_current_request"),
    (ENTITIES.charge_limit_entity, "charge_state_charge_limit_soc"),
])
@pytest.mark.parametrize("fault", ["other_vehicle", "other_entry", "wrong_field",
                                 "missing_device", "disabled"])
async def test_native_measurement_cannot_belong_to_another_mapped_policy_vehicle(
    hass, freezer, entity, field, fault,
):
    rig = _native(hass, freezer)
    entry, device, vin = rig.entry, rig.device, VIN
    if fault in {"other_vehicle", "other_entry"}:
        vin = "OTHERTESTVEHICLE"
        if fault == "other_entry":
            entry = MockConfigEntry(domain="tessie")
            entry.add_to_hass(hass)
            entry._async_set_state(hass, ConfigEntryState.LOADED, None)
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={("tessie", vin)},
        )
    domain, name = entity.split(".")
    row = er.async_get(hass).async_get_or_create(
        domain, "tessie", f"{vin}-{field if fault != 'wrong_field' else 'drive_state_speed'}",
        config_entry=entry, device_id=device.id, suggested_object_id=name,
    )
    assert row.entity_id == entity
    if fault == "missing_device":
        er.async_get(hass).async_update_entity(entity, device_id=None)
    elif fault == "disabled":
        er.async_get(hass).async_update_entity(entity, disabled_by=er.RegistryEntryDisabler.USER)
    result = _measure(hass, retain_generic_values=True)
    assert not result.valid and result.reason == "native_policy_source_mismatch"


@pytest.mark.parametrize("entity,field", [
    (ENTITIES.soc_entity, "charge_state_usable_battery_level"),
    (ENTITIES.current_limit_entity, "charge_state_charge_current_request"),
    (ENTITIES.charge_limit_entity, "charge_state_charge_limit_soc"),
])
@pytest.mark.parametrize("value", ["unavailable", "unknown", "3", "999"])
async def test_matching_policy_anchor_identity_requires_no_unrelated_freshness_or_values(
    hass, freezer, entity, field, value,
):
    rig = _native(hass, freezer)
    domain, name = entity.split(".")
    er.async_get(hass).async_get_or_create(
        domain, "tessie", f"{VIN}-{field}", config_entry=rig.entry,
        device_id=rig.device.id, suggested_object_id=name,
    )
    freezer.move_to(NOW - timedelta(days=1))
    hass.states.async_set(entity, value)
    freezer.move_to(NOW)
    result = _measure(hass)
    assert result.valid and result.current_a == 8 and result.measured_at == NOW


def _native_soc(hass, freezer):
    rig = _native(hass, freezer)
    er.async_get(hass).async_get_or_create(
        "sensor", "tessie", f"{VIN}-charge_state_usable_battery_level", config_entry=rig.entry,
        device_id=rig.device.id, suggested_object_id="measurement_soc",
    )
    freezer.move_to(NOW - timedelta(hours=1))
    hass.states.async_set(ENTITIES.soc_entity, "41", {"unit_of_measurement": "%"})
    freezer.move_to(NOW)
    rig.provider.data["charge_state_usable_battery_level"] = 41
    return rig


def _soc(hass, *, now=NOW, maximum_age=90):
    return measure_ev_soc(hass, capture_ev_feedback(hass, ENTITIES), now=now,
                          max_age_seconds=maximum_age)


@pytest.mark.parametrize("state", ["online", "asleep"])
async def test_native_soc_is_independent_of_physical_values_and_actuator_acknowledgements(
    hass, freezer, state,
):
    rig = _native_soc(hass, freezer)
    rig.provider.data.update({"state": state, "charge_state_charging_state": True,
                              "charge_state_charger_actual_current": None,
                              "charge_state_charge_current_request": 99})
    hass.states.async_set(ENTITIES.actual_current_entity, "unavailable")
    hass.states.async_set(ENTITIES.charging_state_entity, "unknown")
    hass.states.async_set(ENTITIES.current_limit_entity, "unavailable")
    assert _soc(hass) == 41
    assert not _measure(hass).valid  # Reservation is not positive-command permission.


@pytest.mark.parametrize("fault", [
    "expired", "future", "missing_clock", "bool_clock", "nonfinite_clock", "offline",
    "failed", "unloaded", "wrong_provider", "duplicate_vehicle", "mismatched_soc",
    "optimistic_soc", "restored_soc", "wrong_field", "wrong_vehicle_anchor",
])
async def test_native_soc_cannot_borrow_another_clock_value_or_vehicle(hass, freezer, fault):
    rig = _native_soc(hass, freezer)
    if fault in {"expired", "future"}:
        rig.provider.data["charge_state_timestamp"] = (
            NOW + timedelta(seconds=-90.001 if fault == "expired" else 0.001)
        ).timestamp() * 1000
        rig.provider.data["drive_state_timestamp"] = NOW.timestamp() * 1000
    elif fault == "missing_clock":
        rig.provider.data.pop("charge_state_timestamp")
    elif fault in {"bool_clock", "nonfinite_clock"}:
        rig.provider.data["charge_state_timestamp"] = (
            True if fault == "bool_clock" else float("nan")
        )
    elif fault == "offline":
        rig.provider.data["state"] = "offline"
    elif fault == "failed":
        rig.provider.last_update_success = False
    elif fault == "unloaded":
        rig.entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    elif fault == "wrong_provider":
        rig.provider.config_entry = SimpleNamespace(entry_id=rig.entry.entry_id)
    elif fault == "duplicate_vehicle":
        rig.entry.runtime_data.vehicles.append(rig.vehicle)
    elif fault in {"mismatched_soc", "optimistic_soc"}:
        rig.provider.data["charge_state_usable_battery_level"] = (
            42 if fault == "mismatched_soc" else True
        )
    elif fault == "restored_soc":
        hass.states.async_set(ENTITIES.soc_entity, "41", {"restored": True})
    elif fault == "wrong_field":
        er.async_get(hass).async_update_entity(ENTITIES.soc_entity,
                                             new_unique_id=f"{VIN}-charge_state_battery_level")
    elif fault == "wrong_vehicle_anchor":
        other = dr.async_get(hass).async_get_or_create(
            config_entry_id=rig.entry.entry_id, identifiers={("tessie", "OTHERTESTVEHICLE")},
        )
        er.async_get(hass).async_update_entity(ENTITIES.actual_current_entity, device_id=other.id)
    assert _soc(hass) is None


@pytest.mark.parametrize("age,allowed", [(0, True), (90, True), (90.001, False), (-0.001, False)])
async def test_generic_soc_needs_only_its_own_bounded_report(hass, freezer, age, allowed):
    freezer.move_to(NOW - timedelta(seconds=age))
    hass.states.async_set(ENTITIES.soc_entity, "41", {"unit_of_measurement": "%"})
    freezer.move_to(NOW)
    assert _soc(hass) == (41 if allowed else None)
    assert not _measure(hass).valid  # Actual/current/state feedback is entirely absent.


@pytest.mark.parametrize("value", ["-1", "101", "nan", "inf", "unknown", "unavailable"])
async def test_invalid_soc_never_becomes_a_reservation_percentage(hass, freezer, value):
    freezer.move_to(NOW)
    hass.states.async_set(ENTITIES.soc_entity, value)
    assert _soc(hass) is None


async def test_new_unchanged_native_soc_measurement_uses_no_ha_clock_renewal(hass, freezer):
    rig = _native_soc(hass, freezer)
    original = hass.states.get(ENTITIES.soc_entity).last_reported
    assert _soc(hass) == 41
    later = NOW + timedelta(seconds=30)
    freezer.move_to(later)
    rig.provider.data["charge_state_timestamp"] = later.timestamp() * 1000
    assert _soc(hass, now=later) == 41
    assert hass.states.get(ENTITIES.soc_entity).last_reported == original
