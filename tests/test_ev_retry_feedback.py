"""Native retry proof uses source identity/time, never optimistic HA clocks."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.ev_observation_adapter import (
    EvObservationEntityMap,
    capture_ev_feedback,
)
from custom_components.home_energy_orchestrator.ev_retry_feedback import (
    capture_direct_evse_current_feedback,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
VIN = "RETRYTESTVEHICLE01"
ENTITIES = EvObservationEntityMap(
    actual_current_entity="sensor.retry_actual",
    charging_state_entity="sensor.retry_charging",
    cable_connected_entity="binary_sensor.retry_cable",
    current_limit_entity="number.retry_request",
    charge_limit_entity="number.retry_limit",
    charge_switch_entity="switch.retry_charge",
    soc_entity="sensor.retry_soc",
)
FIELDS = (
    (ENTITIES.actual_current_entity, "charge_state_charger_actual_current"),
    (ENTITIES.charging_state_entity, "charge_state_charging_state"),
    (ENTITIES.cable_connected_entity, "charge_state_conn_charge_cable"),
    (ENTITIES.current_limit_entity, "charge_state_charge_current_request"),
    (ENTITIES.charge_limit_entity, "charge_state_charge_limit_soc"),
    (ENTITIES.charge_switch_entity, "charge_state_charge_enable_request"),
    (ENTITIES.soc_entity, "charge_state_usable_battery_level"),
)
REQUIRED = tuple(entity for entity, _ in FIELDS if entity not in {
    ENTITIES.charge_limit_entity, ENTITIES.soc_entity,
})


@pytest.fixture(autouse=True)
async def provider_cleanup(hass):
    """Fixtures emulate loaded providers without loading/calling Tessie."""
    yield
    for entry in hass.config_entries.async_entries("tessie"):
        entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    await hass.async_block_till_done()


def _native(hass, freezer, *, request=1, actual=1, report_age=0):
    entry = MockConfigEntry(domain="tessie")
    entry.add_to_hass(hass)
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("tessie", VIN)},
    )
    values = {
        ENTITIES.actual_current_entity: (actual, {"unit_of_measurement": "A"}),
        ENTITIES.charging_state_entity: ("charging", {}),
        ENTITIES.cable_connected_entity: ("on", {}),
        ENTITIES.current_limit_entity: (request, {"unit_of_measurement": "A"}),
        ENTITIES.charge_limit_entity: (80, {}),
        ENTITIES.charge_switch_entity: ("on", {}),
        ENTITIES.soc_entity: (50, {}),
    }
    freezer.move_to(NOW - timedelta(seconds=report_age))
    for entity, field in FIELDS:
        domain, name = entity.split(".")
        row = er.async_get(hass).async_get_or_create(
            domain, "tessie", f"{VIN}-{field}", config_entry=entry,
            device_id=device.id, suggested_object_id=name,
        )
        assert row.entity_id == entity
        value, attrs = values[entity]
        hass.states.async_set(entity, str(value), attrs)
    freezer.move_to(NOW)
    provider = SimpleNamespace(
        config_entry=entry, last_update_success=True,
        data={
            "state": "online", "charge_state_timestamp": NOW.timestamp() * 1000,
            "charge_state_charger_actual_current": actual,
            "charge_state_charging_state": "Charging",
            "charge_state_conn_charge_cable": "IEC",
            "charge_state_charge_current_request": request,
            "charge_state_charge_enable_request": True,
            "charge_state_charge_limit_soc": 80,
            "charge_state_usable_battery_level": 50,
        },
    )
    vehicle = SimpleNamespace(vin=VIN, data_coordinator=provider)
    entry.runtime_data = SimpleNamespace(vehicles=[vehicle])
    return SimpleNamespace(entry=entry, device=device, provider=provider, vehicle=vehicle)


def _capture(hass, *, feedback=None, entities=ENTITIES, now=NOW, max_age=90):
    return capture_direct_evse_current_feedback(
        hass, feedback or capture_ev_feedback(hass, entities),
        now=now, max_age_seconds=max_age,
    )


async def test_current_cohort_is_immutable_source_stamped_and_private(hass, freezer):
    rig = _native(hass, freezer, request=1, actual=2, report_age=3600)
    result = _capture(hass)
    assert result.requested_current_a == 1 and result.actual_current_a == 2
    assert result.measured_at == NOW
    assert len(result.binding) == 64 and int(result.binding, 16) >= 0
    for private in (VIN, rig.entry.entry_id, rig.device.id, *REQUIRED):
        assert private not in result.binding
    with pytest.raises(FrozenInstanceError):
        result.actual_current_a = 1
    assert _capture(hass) == result
    rig.entry.runtime_data = SimpleNamespace(vehicles={"vehicle": rig.vehicle})
    assert _capture(hass) == result  # Collection representation/reload is not identity.


@pytest.mark.parametrize("source_age,valid", [(0, True), (90, True), (90.001, False),
                                            (-0.001, False)])
async def test_original_measurement_clock_not_recent_ha_or_fetch_clock(
    hass, freezer, source_age, valid,
):
    rig = _native(hass, freezer)
    stamp = NOW - timedelta(seconds=source_age)
    rig.provider.data["charge_state_timestamp"] = stamp.timestamp() * 1000
    rig.provider.data["timestamp"] = (NOW + timedelta(seconds=30)).timestamp() * 1000
    rig.provider.data["drive_state_timestamp"] = NOW.timestamp() * 1000
    result = _capture(hass)
    assert (result is not None) is valid
    if valid:
        assert result.measured_at == stamp
        later = NOW + timedelta(seconds=1)
        assert _capture(hass, now=later, max_age=91).measured_at == stamp


async def test_provider_clock_advances_without_entity_value_or_report_changes(hass, freezer):
    rig = _native(hass, freezer, report_age=3600)
    captured = capture_ev_feedback(hass, ENTITIES)
    first = _capture(hass, feedback=captured)
    later = NOW + timedelta(seconds=10)
    freezer.move_to(later)
    rig.provider.data["charge_state_timestamp"] = later.timestamp() * 1000
    second = _capture(hass, feedback=captured, now=later)
    assert second.binding == first.binding and second.measured_at == later
    assert captured == capture_ev_feedback(hass, ENTITIES)


async def test_optimistic_one_amp_echo_does_not_rewrite_actual_or_measurement_clock(hass, freezer):
    rig = _native(hass, freezer, request=3, actual=2)
    old_stamp = NOW - timedelta(seconds=10)
    rig.provider.data["charge_state_timestamp"] = old_stamp.timestamp() * 1000
    rig.provider.data["charge_state_charge_current_request"] = 1
    hass.states.async_set(ENTITIES.current_limit_entity, "1.0", {"unit_of_measurement": "A"})
    result = _capture(hass)
    assert result.requested_current_a == 1 and result.actual_current_a == 2
    assert result.measured_at == old_stamp
    # The native request may itself be optimistic. Only the planner's later-
    # than-completed-receipt test can distinguish that from current proof.


async def test_captured_request_and_actual_must_match_the_same_existing_frame(hass, freezer):
    rig = _native(hass, freezer)
    captured = capture_ev_feedback(hass, ENTITIES)
    rig.provider.data["charge_state_charge_current_request"] = 3
    assert _capture(hass, feedback=captured) is None
    rig.provider.data["charge_state_charge_current_request"] = 1
    rig.provider.data["charge_state_charger_actual_current"] = 2
    assert _capture(hass, feedback=captured) is None


@pytest.mark.parametrize("fault", [
    "failed", "unloaded", "asleep", "offline", "wrong_provider", "wrong_vehicle",
    "duplicate_vehicle", "missing_clock", "bool_clock", "nan_clock", "infinite_clock",
    "string_clock", "huge_clock", "charging_bool", "charging_stopped", "cable_bool", "cable_off",
    "bool_request", "nan_request", "negative_request", "string_request", "missing_request",
    "bool_actual", "nan_actual", "negative_actual", "missing_actual", "huge_actual", "huge_request",
])
async def test_invalid_native_source_or_frame_never_falls_back_to_recent_ha(hass, freezer, fault):
    rig = _native(hass, freezer)
    data = rig.provider.data
    if fault == "failed":
        rig.provider.last_update_success = False
    elif fault == "unloaded":
        rig.entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    elif fault in {"asleep", "offline"}:
        data["state"] = fault
    elif fault == "wrong_provider":
        rig.provider.config_entry = SimpleNamespace(entry_id=rig.entry.entry_id)
    elif fault == "wrong_vehicle":
        rig.vehicle.vin = "OTHERTESTVEHICLE"
    elif fault == "duplicate_vehicle":
        rig.entry.runtime_data.vehicles.append(rig.vehicle)
    elif fault.endswith("clock"):
        value = {"bool_clock": True, "nan_clock": float("nan"),
                 "infinite_clock": float("inf"), "string_clock": "0",
                 "huge_clock": 10**500}.get(fault)
        if fault == "missing_clock":
            data.pop("charge_state_timestamp")
        else:
            data["charge_state_timestamp"] = value
    elif fault.startswith("charging"):
        data["charge_state_charging_state"] = True if fault.endswith("bool") else "Stopped"
    elif fault.startswith("cable"):
        data["charge_state_conn_charge_cable"] = True if fault.endswith("bool") else "<invalid>"
    else:
        kind, field = (
            ("request", "charge_state_charge_current_request") if fault.endswith("request")
            else ("actual", "charge_state_charger_actual_current")
        )
        if fault == f"missing_{kind}":
            data.pop(field)
        else:
            data[field] = {f"bool_{kind}": True, f"nan_{kind}": float("nan"),
                           f"negative_{kind}": -1, f"string_{kind}": "1",
                           f"huge_{kind}": 10**500}[fault]
    assert _capture(hass) is None


@pytest.mark.parametrize("entity", REQUIRED)
@pytest.mark.parametrize("fault", ["generic", "disabled", "wrong_field", "wrong_device",
                                  "wrong_entry", "restored", "unavailable", "future_report"])
async def test_each_required_native_field_has_exact_identity_and_valid_report(
    hass, freezer, entity, fault,
):
    rig = _native(hass, freezer)
    registry = er.async_get(hass)
    if fault == "generic":
        registry.async_remove(entity)
    elif fault == "disabled":
        registry.async_update_entity(entity, disabled_by=er.RegistryEntryDisabler.USER)
    elif fault == "wrong_field":
        registry.async_update_entity(entity, new_unique_id=f"{VIN}-drive_state_power")
    elif fault == "wrong_device":
        other = dr.async_get(hass).async_get_or_create(
            config_entry_id=rig.entry.entry_id, identifiers={("tessie", "OTHERTESTVEHICLE")},
        )
        registry.async_update_entity(entity, device_id=other.id)
    elif fault == "wrong_entry":
        other_entry = MockConfigEntry(domain="tessie")
        other_entry.add_to_hass(hass)
        registry.async_update_entity(entity, config_entry_id=other_entry.entry_id)
    else:
        old = hass.states.get(entity)
        attrs = dict(old.attributes)
        if fault == "restored":
            attrs["restored"] = True
        if fault == "future_report":
            freezer.move_to(NOW + timedelta(seconds=1))
        hass.states.async_set(entity, "unavailable" if fault == "unavailable" else old.state,
                              attrs, force_update=True)
        freezer.move_to(NOW)
    assert _capture(hass) is None


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "true", "unknown"])
async def test_malformed_request_entity_is_not_numeric_native_proof(hass, freezer, value):
    _native(hass, freezer)
    hass.states.async_set(ENTITIES.current_limit_entity, value, {"unit_of_measurement": "A"})
    assert _capture(hass) is None


@pytest.mark.parametrize("entity", [ENTITIES.current_limit_entity, ENTITIES.actual_current_entity])
@pytest.mark.parametrize("unit", [None, "mA", "kW"])
async def test_current_units_cannot_silently_change_proof(hass, freezer, entity, unit):
    _native(hass, freezer)
    hass.states.async_set(entity, "1", {"unit_of_measurement": unit})
    assert _capture(hass) is None


@pytest.mark.parametrize("entity,state", [(ENTITIES.cable_connected_entity, "off"),
                                         (ENTITIES.charge_switch_entity, "off"),
                                         (ENTITIES.charging_state_entity, "stopped")])
async def test_proof_is_only_for_connected_active_charging(hass, freezer, entity, state):
    _native(hass, freezer)
    hass.states.async_set(entity, state)
    assert _capture(hass) is None


@pytest.mark.parametrize("charging,published", [("Stopped", "stopped"),
                                               ("Complete", "complete"),
                                               ("NoPower", "no_power")])
async def test_connected_stopped_frame_can_bind_current_before_ordered_start(
    hass, freezer, charging, published,
):
    rig = _native(hass, freezer, request=1, actual=8)
    rig.provider.data["charge_state_charging_state"] = charging
    hass.states.async_set(ENTITIES.charging_state_entity, published)
    hass.states.async_set(ENTITIES.charge_switch_entity, "off")
    result = _capture(hass)
    assert result is not None and result.measured_at == NOW
    assert result.requested_current_a == 1 and result.actual_current_a == 0
    # This is only a receipt binding. The planner cannot arm override proof
    # while the switch is off, or reuse this old frame after a start request.
    rig.provider.data.pop("charge_state_charger_actual_current")
    assert _capture(hass) is None


async def test_connected_disconnected_state_is_not_a_current_receipt_binding(hass, freezer):
    rig = _native(hass, freezer)
    rig.provider.data["charge_state_charging_state"] = "Disconnected"
    hass.states.async_set(ENTITIES.charging_state_entity, "disconnected")
    hass.states.async_set(ENTITIES.charge_switch_entity, "off")
    assert _capture(hass) is None


async def test_percent_value_independent_but_actuator_rebind_changes_identity(hass, freezer):
    rig = _native(hass, freezer)
    first = _capture(hass)
    rig.provider.data["charge_state_charge_limit_soc"] = 90
    hass.states.async_set(ENTITIES.charge_limit_entity, "90")
    assert _capture(hass) == first
    hass.states.async_set(ENTITIES.charge_limit_entity, "unavailable", {"restored": True})
    assert _capture(hass) == first
    generic_entities = replace(ENTITIES, charge_limit_entity="number.explicit_generic_limit")
    generic = _capture(hass, entities=generic_entities)
    assert generic is not None and generic.binding != first.binding
    registry = er.async_get(hass)
    registry.async_update_entity(ENTITIES.charge_limit_entity,
                                 new_unique_id="OTHERTESTVEHICLE-charge_state_charge_limit_soc")
    assert _capture(hass) is None


@pytest.mark.parametrize("entity", [ENTITIES.current_limit_entity, ENTITIES.charge_switch_entity,
                                   ENTITIES.actual_current_entity, ENTITIES.cable_connected_entity])
async def test_entity_rebinding_changes_opaque_identity(hass, freezer, entity):
    _native(hass, freezer)
    first = _capture(hass)
    registry = er.async_get(hass)
    domain, name = entity.split(".")
    new_id = f"{domain}.{name}_renamed"
    old = hass.states.get(entity)
    registry.async_update_entity(entity, new_entity_id=new_id)
    hass.states.async_remove(entity)
    hass.states.async_set(new_id, old.state, dict(old.attributes))
    key = next(name for name in ENTITIES.__dataclass_fields__ if getattr(ENTITIES, name) == entity)
    result = _capture(hass, entities=replace(ENTITIES, **{key: new_id}))
    assert result is not None and result.binding != first.binding


@pytest.mark.parametrize("max_age", [-1, True, None, float("nan"), float("inf")])
async def test_invalid_configured_clock_bound_fails_closed(hass, freezer, max_age):
    _native(hass, freezer)
    assert _capture(hass, max_age=max_age) is None


async def test_naive_now_or_request_clock_fails_closed(hass, freezer):
    _native(hass, freezer)
    assert _capture(hass, now=NOW.replace(tzinfo=None)) is None
    feedback = capture_ev_feedback(hass, ENTITIES)
    invalid = replace(feedback, current_limit=replace(
        feedback.current_limit, last_reported=NOW.replace(tzinfo=None),
    ))
    assert _capture(hass, feedback=invalid) is None


async def test_read_only_capture_calls_no_service_and_does_not_mutate_states(hass, freezer):
    _native(hass, freezer)
    before = tuple(hass.states.async_all())
    first = _capture(hass)
    assert first is not None
    assert tuple(hass.states.async_all()) == before
    assert _capture(hass) == first
