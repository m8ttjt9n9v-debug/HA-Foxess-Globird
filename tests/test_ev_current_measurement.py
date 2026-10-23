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
    measure_ev_planning_soc,
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


def _planning_soc(hass, *, now=NOW, live_age=90, planning_age=86400, feedback=None):
    return measure_ev_planning_soc(
        hass, feedback or capture_ev_feedback(hass, ENTITIES), now=now,
        max_age_seconds=live_age, planning_max_age_seconds=planning_age,
    )


@pytest.mark.parametrize("age,valid,reason", [
    (0, True, "fresh_asleep"), (89.999, True, "fresh_asleep"),
    (90, True, "fresh_asleep"), (90.001, True, "bounded_asleep"),
    (86399.999, True, "bounded_asleep"), (86400, True, "bounded_asleep"),
    (86400.001, False, "sleeping_soc_expired"), (-0.001, False, "native_soc_future"),
])
async def test_sleeping_planning_soc_has_its_own_exact_original_measurement_boundary(
    hass, freezer, age, valid, reason,
):
    rig = _native_soc(hass, freezer)
    stamp = NOW - timedelta(seconds=age)
    rig.provider.data.update({
        "state": "asleep", "charge_state_timestamp": stamp.timestamp() * 1000,
    })
    result = _planning_soc(hass)
    assert result.valid is valid
    assert result.value_percent == (41 if valid else None)
    assert result.source == "tessie_charge_state" and result.observed_at == stamp
    assert result.reason == reason
    assert _soc(hass) == (41 if 0 <= age <= 90 else None)
    assert not _measure(hass).valid  # Planning cannot qualify sleeping physical current.
    with pytest.raises(FrozenInstanceError):
        result.observed_at = NOW


@pytest.mark.parametrize("age,valid", [(0, True), (90, True), (90.001, False), (86400, False)])
async def test_online_planning_soc_never_uses_the_sleeping_age(hass, freezer, age, valid):
    rig = _native_soc(hass, freezer)
    stamp = NOW - timedelta(seconds=age)
    rig.provider.data["charge_state_timestamp"] = stamp.timestamp() * 1000
    result = _planning_soc(hass)
    assert result.valid is valid
    assert result.value_percent == _soc(hass)
    assert result.observed_at == stamp
    assert result.reason == ("fresh_online" if valid else "native_soc_expired")


@pytest.mark.parametrize("age,valid", [(0, True), (90, True), (90.001, False), (86400, False)])
async def test_generic_planning_soc_retains_only_its_explicit_live_report_contract(
    hass, freezer, age, valid,
):
    stamp = NOW - timedelta(seconds=age)
    freezer.move_to(stamp)
    hass.states.async_set(ENTITIES.soc_entity, "53", {"unit_of_measurement": "%"})
    freezer.move_to(NOW)
    result = _planning_soc(hass)
    assert result.valid is valid
    assert result.value_percent == (53 if valid else None)
    assert result.source == "entity_report" and result.observed_at == stamp
    assert result.reason == ("fresh_reported" if valid else "reported_soc_expired")


@pytest.mark.parametrize("planning_age", [
    None, 0, -1, True, "86400", float("nan"), float("inf"), 10**400,
])
@pytest.mark.parametrize("state", ["online", "asleep", "generic"])
async def test_invalid_planning_bound_fails_closed_even_for_fresh_soc(
    hass, freezer, planning_age, state,
):
    if state == "generic":
        freezer.move_to(NOW)
        hass.states.async_set(ENTITIES.soc_entity, "41")
    else:
        rig = _native_soc(hass, freezer)
        rig.provider.data["state"] = state
    result = _planning_soc(hass, planning_age=planning_age)
    assert not result.valid and result.value_percent is None
    assert result.reason == "planning_age_invalid" and result.observed_at is None
    assert _soc(hass) == 41  # The new setting changes no live measurement contract.


@pytest.mark.parametrize("live_age", [-1, True, float("nan"), float("inf"), 10**400])
async def test_planning_bound_cannot_hide_an_invalid_live_age(hass, freezer, live_age):
    rig = _native_soc(hass, freezer)
    rig.provider.data["state"] = "asleep"
    assert not _planning_soc(hass, live_age=live_age).valid


@pytest.mark.parametrize("fault", [
    "online", "offline", "unknown_state", "failed", "unloaded", "wrong_provider",
    "duplicate_vehicle", "wrong_vehicle", "missing_clock", "bool_clock", "nan_clock",
    "infinite_clock", "overflow_clock",
    "future_clock", "missing_native_soc", "bool_native_soc", "mismatched_soc",
    "unknown_soc", "restored_soc", "negative_soc", "over_100_soc", "future_ha_report",
    "disabled_soc", "wrong_soc_field", "missing_soc_device", "wrong_vehicle_anchor",
])
async def test_sleeping_planning_extension_preserves_all_source_and_value_guards(
    hass, freezer, fault,
):
    rig = _native_soc(hass, freezer)
    rig.provider.data.update({"state": "asleep", "charge_state_timestamp": (
        NOW - timedelta(seconds=120)
    ).timestamp() * 1000})
    assert _planning_soc(hass).valid and _soc(hass) is None
    data = rig.provider.data
    if fault in {"online", "offline", "unknown_state"}:
        data["state"] = "unknown" if fault == "unknown_state" else fault
    elif fault == "failed":
        rig.provider.last_update_success = False
    elif fault == "unloaded":
        rig.entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    elif fault == "wrong_provider":
        rig.provider.config_entry = SimpleNamespace(entry_id=rig.entry.entry_id)
    elif fault == "duplicate_vehicle":
        rig.entry.runtime_data.vehicles.append(rig.vehicle)
    elif fault == "wrong_vehicle":
        rig.vehicle.vin = "DIFFERENTVEHICLE"
    elif fault == "missing_clock":
        data.pop("charge_state_timestamp")
    elif fault in {"bool_clock", "nan_clock", "infinite_clock", "overflow_clock", "future_clock"}:
        data["charge_state_timestamp"] = {
            "bool_clock": True, "nan_clock": float("nan"),
            "infinite_clock": float("inf"), "overflow_clock": 10**400,
            "future_clock": (NOW + timedelta(seconds=0.001)).timestamp() * 1000,
        }[fault]
    elif fault == "missing_native_soc":
        data.pop("charge_state_usable_battery_level")
    elif fault == "bool_native_soc":
        data["charge_state_usable_battery_level"] = True
    elif fault in {"mismatched_soc", "unknown_soc", "restored_soc", "negative_soc",
                   "over_100_soc", "future_ha_report"}:
        value = {"mismatched_soc": "42", "unknown_soc": "unknown", "restored_soc": "41",
                 "negative_soc": "-1", "over_100_soc": "101", "future_ha_report": "41"}[fault]
        if fault == "future_ha_report":
            freezer.move_to(NOW + timedelta(seconds=1))
        hass.states.async_set(ENTITIES.soc_entity, value, {
            "unit_of_measurement": "%", "restored": fault == "restored_soc",
        }, force_update=True)
        freezer.move_to(NOW)
        if fault in {"negative_soc", "over_100_soc"}:
            data["charge_state_usable_battery_level"] = float(value)
    elif fault == "wrong_vehicle_anchor":
        other = dr.async_get(hass).async_get_or_create(
            config_entry_id=rig.entry.entry_id, identifiers={("tessie", "OTHERTESTVEHICLE")},
        )
        er.async_get(hass).async_update_entity(ENTITIES.actual_current_entity, device_id=other.id)
    else:
        changes = (
            {"disabled_by": er.RegistryEntryDisabler.USER} if fault == "disabled_soc"
            else {"device_id": None} if fault == "missing_soc_device"
            else {"new_unique_id": f"{VIN}-charge_state_battery_level"}
        )
        er.async_get(hass).async_update_entity(ENTITIES.soc_entity, **changes)
    result = _planning_soc(hass)
    assert not result.valid and result.value_percent is None
    assert _soc(hass) is None and not _measure(hass).valid


async def test_planning_sleep_does_not_require_physical_or_optimistic_ack_values(hass, freezer):
    rig = _native_soc(hass, freezer)
    rig.provider.data.update({
        "state": "asleep", "charge_state_timestamp": (NOW - timedelta(hours=2)).timestamp() * 1000,
        "charge_state_charger_actual_current": None, "charge_state_charging_state": True,
        "charge_state_charge_current_request": 99,
    })
    hass.states.async_set(ENTITIES.actual_current_entity, "unavailable")
    hass.states.async_set(ENTITIES.charging_state_entity, "unknown")
    hass.states.async_set(ENTITIES.current_limit_entity, "unavailable")
    result = _planning_soc(hass)
    assert result.valid and result.value_percent == 41 and result.reason == "bounded_asleep"
    assert result.observed_at == NOW - timedelta(hours=2)
    assert _soc(hass) is None and not _measure(hass).valid


async def test_sleeping_planning_bound_changes_apply_without_a_retained_lease(hass, freezer):
    rig = _native_soc(hass, freezer)
    rig.provider.data.update({"state": "asleep", "charge_state_timestamp": (
        NOW - timedelta(seconds=120)
    ).timestamp() * 1000})
    assert _planning_soc(hass, planning_age=120).valid
    assert not _planning_soc(hass, planning_age=119.999).valid
    assert _planning_soc(hass, planning_age=120).observed_at == NOW - timedelta(seconds=120)
    # The asleep planning ceiling is literal, even if the live age is larger.
    assert not _planning_soc(hass, live_age=300, planning_age=119.999).valid
    assert _soc(hass, maximum_age=300) == 41


async def test_wake_failure_and_offline_immediately_withdraw_sleeping_planning(hass, freezer):
    rig = _native_soc(hass, freezer)
    rig.provider.data.update({"state": "asleep", "charge_state_timestamp": (
        NOW - timedelta(seconds=120)
    ).timestamp() * 1000})
    assert _planning_soc(hass).valid
    rig.provider.data["state"] = "online"
    assert not _planning_soc(hass).valid
    rig.provider.data["state"] = "offline"
    assert not _planning_soc(hass).valid
    rig.provider.data["state"] = "asleep"
    rig.provider.last_update_success = False
    assert not _planning_soc(hass).valid
    rig.provider.last_update_success = True
    assert _planning_soc(hass).observed_at == NOW - timedelta(seconds=120)
    rig.provider.data.update({"state": "online", "charge_state_timestamp": NOW.timestamp() * 1000})
    assert _planning_soc(hass).reason == "fresh_online" and _soc(hass) == 41


async def test_ha_fetch_drive_and_repeated_reads_cannot_renew_sleeping_soc(hass, freezer):
    rig = _native_soc(hass, freezer)
    stamp = NOW - timedelta(seconds=120)
    rig.provider.data.update({
        "state": "asleep", "charge_state_timestamp": stamp.timestamp() * 1000,
    })
    first = _planning_soc(hass, planning_age=180)
    assert first.valid
    later = NOW + timedelta(seconds=61)
    freezer.move_to(later)
    hass.states.async_set(
        ENTITIES.soc_entity, "41", {"unit_of_measurement": "%"}, force_update=True,
    )
    rig.provider.data.update({"timestamp": later.timestamp() * 1000,
                              "drive_state_timestamp": later.timestamp() * 1000})
    for _ in range(2):
        result = _planning_soc(hass, now=later, planning_age=180)
        assert not result.valid and result.observed_at == stamp
    assert first.observed_at == stamp and first.valid


async def test_restart_reads_same_original_frame_without_seeding_or_renewing_it(hass, freezer):
    rig = _native_soc(hass, freezer)
    stamp = NOW - timedelta(seconds=120)
    rig.provider.data.update({
        "state": "asleep", "charge_state_timestamp": stamp.timestamp() * 1000,
    })
    assert _planning_soc(hass, planning_age=180).observed_at == stamp
    frame = dict(rig.provider.data)
    rig.entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    assert not _planning_soc(hass, planning_age=180).valid
    rig.entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    rig.vehicle.data_coordinator = SimpleNamespace(
        config_entry=rig.entry, last_update_success=True, data=dict(frame),
    )
    assert _planning_soc(hass, planning_age=180).observed_at == stamp
    assert not _planning_soc(hass, now=NOW + timedelta(seconds=61), planning_age=180).valid
    rig.vehicle.data_coordinator.data.pop("charge_state_timestamp")
    assert not _planning_soc(hass, planning_age=180).valid


async def test_new_equal_native_soc_frame_advances_only_the_actual_measurement_clock(hass, freezer):
    rig = _native_soc(hass, freezer)
    stamp = NOW - timedelta(seconds=120)
    rig.provider.data.update({
        "state": "asleep", "charge_state_timestamp": stamp.timestamp() * 1000,
    })
    old_ha_clock = hass.states.get(ENTITIES.soc_entity).last_reported
    assert _planning_soc(hass).observed_at == stamp
    assert _soc(hass) is None
    rig.provider.data["charge_state_timestamp"] = NOW.timestamp() * 1000
    result = _planning_soc(hass)
    assert result.value_percent == 41 and result.observed_at == NOW
    assert result.reason == "fresh_asleep"
    assert _soc(hass) == 41
    assert hass.states.get(ENTITIES.soc_entity).last_reported == old_ha_clock
