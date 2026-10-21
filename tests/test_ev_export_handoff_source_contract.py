"""Source-specific clocks at the local-charger/export handoff boundary."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.ev_observation_adapter import (
    capture_ev_entity_feedback,
    capture_ev_feedback,
    ev_observation_entity_map,
)
from custom_components.home_energy_orchestrator.ev_source_feedback import (
    before_export_item_measured_fresh,
    before_export_physical_feedback_valid,
    before_export_vehicle_feedback_valid,
)
from tests.test_ev_before_export_source_clocks import FIELDS, _native
from tests.test_ev_local_connection import ENTITY, Publisher, native
from tests.test_zerohero_active import _loaded_controller


@pytest.fixture(autouse=True)
async def source_cleanup(hass):
    yield
    for entry in hass.config_entries.async_entries():
        if entry.domain in {"tessie", "foxess_modbus", "tesla_wall_connector"}:
            entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    await hass.async_block_till_done()


def _controller(hass, rig, *, mapped=True):
    rig.coordinator.config.update({
        "ev_local_connection_entity": ENTITY if mapped else None,
        "ev_before_export_soc_target_percent": 20,
    })
    rig.coordinator.runtime_config = RuntimeConfiguration.from_mapping(rig.coordinator.config)
    controller = _loaded_controller(hass, rig.coordinator)
    return controller


def _charge_frame(hass, rig, freezer, *, charging, current, connected, entity_age=3600):
    """Actual vehicle values, with independently controlled HA publication age."""
    freezer.move_to(rig.now - timedelta(seconds=entity_age))
    state = "Charging" if charging else "Disconnected" if not connected else "Stopped"
    values = {
        "sensor.car_charging": state.lower(),
        "sensor.car_actual_current": str(current),
        "binary_sensor.car_cable": "on" if connected else "off",
        "switch.car_charge": "on" if charging else "off",
    }
    for entity, value in values.items():
        old = hass.states.get(entity)
        hass.states.async_set(entity, value, dict(old.attributes), force_update=True)
    rig.provider.data.update({
        "state": "online",
        "charge_state_timestamp": rig.now.timestamp() * 1000,
        "charge_state_charger_actual_current": current,
        "charge_state_charging_state": state,
        "charge_state_conn_charge_cable": "IEC" if connected else "<invalid>",
    })
    freezer.move_to(rig.now)


async def test_old_native_raw_current_republished_alone_does_not_veto_local_unplug(
    hass, freezer,
):
    rig = _native(hass, freezer)
    _charge_frame(hass, rig, freezer, charging=False, current=16, connected=False)
    rig.provider.data["state"] = "asleep"
    rig.provider.data["charge_state_timestamp"] -= 3_600_000
    # Only this cached raw value was republished by HA. It is not a new
    # vehicle measurement and the other charge entities remain genuinely old.
    old = hass.states.get("sensor.car_actual_current")
    hass.states.async_set(old.entity_id, "16", dict(old.attributes), force_update=True)
    hass.states.async_set(ENTITY, "off")
    clocks = {entity: hass.states.get(entity).last_reported for entity in FIELDS}
    controller = _controller(hass, rig)
    assert controller._ev_before_export_handoff_ready(rig.now)
    assert controller.ev_export_handoff_reason == "local_disconnected"
    assert clocks == {entity: hass.states.get(entity).last_reported for entity in FIELDS}
    controller._local_ev_connection.close()


async def test_real_recent_native_charging_vetoes_local_unplug_even_with_old_ha_clocks(
    hass, freezer,
):
    rig = _native(hass, freezer)
    _charge_frame(hass, rig, freezer, charging=True, current=8, connected=True)
    hass.states.async_set(ENTITY, "off")
    controller = _controller(hass, rig)
    assert not controller._ev_before_export_handoff_ready(rig.now)
    assert controller.ev_export_handoff_reason == "connection_conflict"
    controller._local_ev_connection.close()


async def test_future_soc_report_cannot_become_retained_minimum_evidence(hass, freezer):
    rig = _native(hass, freezer)
    controller = _controller(hass, rig)
    hass.states.async_set(ENTITY, "off")
    freezer.move_to(rig.now + timedelta(seconds=1))
    hass.states.async_set("sensor.car_soc", "25", {"unit_of_measurement": "%"}, force_update=True)
    freezer.move_to(rig.now)
    assert not controller._ev_before_export_handoff_ready(rig.now)
    assert controller.ev_export_handoff_reason == "ev_recovery_or_soc_unconfirmed"
    controller._local_ev_connection.close()


@pytest.mark.parametrize("connected,contactor", [(True, False), (False, True)])
async def test_native_local_contradiction_cannot_fall_back_to_vehicle_disconnected(
    hass, freezer, connected, contactor,
):
    rig = _native(hass, freezer, old_seconds=0)
    _charge_frame(hass, rig, freezer, charging=False, current=0, connected=False, entity_age=0)
    local = native(hass)
    controller = _controller(hass, rig)
    controller._ev_before_export_handoff_ready(rig.now)  # Subscribe, do not seed cache.
    local.provider.publish()
    assert controller._ev_before_export_handoff_ready(rig.now)
    local.provider.publish(Publisher.payload(connected, contactor))
    # The entity deliberately still reports off. Contradictory positive native
    # evidence must not be hidden behind the old valid vehicle-only fallback.
    assert not controller._ev_before_export_handoff_ready(rig.now)
    assert controller.ev_export_handoff_reason in {"native_mismatch", "native_contactor_closed"}
    controller._local_ev_connection.close()


async def test_unmapped_zero_buffer_accepts_recent_native_off_with_unchanged_entities(
    hass, freezer,
):
    rig = _native(hass, freezer)
    controller = _controller(hass, rig, mapped=False)
    assert controller._ev_before_export_handoff_ready(rig.now)
    assert controller.ev_export_handoff_source == "vehicle_feedback"
    controller._local_ev_connection.close()


async def test_native_charging_contradiction_survives_unrelated_command_cache_mutation(
    hass, freezer,
):
    rig = _native(hass, freezer)
    _charge_frame(hass, rig, freezer, charging=True, current=8, connected=True)
    hass.states.async_set(ENTITY, "off")
    controller = _controller(hass, rig)
    # A successful native current command updates the shared cache without
    # advancing the real charge-state timestamp or the actual-current sensor.
    rig.provider.data["charge_state_charge_current_request"] = 12
    assert not controller._ev_before_export_handoff_ready(rig.now)
    assert controller.ev_export_handoff_reason == "connection_conflict"
    controller._local_ev_connection.close()


@pytest.mark.parametrize("fault", [
    "wrong_unit", "wrong_field", "wrong_device", "disabled", "failed", "unloaded",
    "expired", "future", "missing_clock", "bool_clock", "restored", "mismatch",
    "bool_actual", "wrong_provider_entry", "wrong_vehicle", "duplicate_vehicle",
])
async def test_per_item_native_measurement_still_rejects_invalid_sources(hass, freezer, fault):
    rig = _native(hass, freezer)
    _charge_frame(hass, rig, freezer, charging=True, current=8, connected=True)
    entity = "sensor.car_actual_current"
    if fault in {"wrong_unit", "restored"}:
        old = hass.states.get(entity)
        attrs = dict(old.attributes)
        attrs.update({"unit_of_measurement": "kW"} if fault == "wrong_unit" else {"restored": True})
        hass.states.async_set(entity, "8", attrs, force_update=True)
    elif fault in {"wrong_field", "wrong_device", "disabled"}:
        changes = {
            "wrong_field": {"new_unique_id": "wrong-vehicle-drive_state_power"},
            "wrong_device": {"device_id": None},
            "disabled": {"disabled_by": er.RegistryEntryDisabler.USER},
        }[fault]
        er.async_get(hass).async_update_entity(entity, **changes)
    elif fault == "failed":
        rig.provider.last_update_success = False
    elif fault == "unloaded":
        rig.entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    elif fault in {"expired", "future"}:
        rig.provider.data["charge_state_timestamp"] = (
            rig.now + timedelta(seconds=-91 if fault == "expired" else 1)
        ).timestamp() * 1000
    elif fault == "missing_clock":
        rig.provider.data.pop("charge_state_timestamp")
    elif fault == "bool_clock":
        rig.provider.data["charge_state_timestamp"] = True
    elif fault in {"mismatch", "bool_actual"}:
        rig.provider.data["charge_state_charger_actual_current"] = (
            9 if fault == "mismatch" else True
        )
    elif fault == "wrong_provider_entry":
        rig.provider.config_entry = rig.fox
    elif fault == "wrong_vehicle":
        rig.vehicle.vin = "different-vehicle"
    elif fault == "duplicate_vehicle":
        rig.entry.runtime_data.vehicles.append(rig.vehicle)
    item = capture_ev_entity_feedback(hass, entity)
    assert not before_export_item_measured_fresh(
        hass, item, now=rig.now, max_age_seconds=90, cohort_valid=True,
    ), fault  # Even an erroneously optimistic caller cannot bypass this field's source.


@pytest.mark.parametrize("entity", [
    "sensor.car_actual_current", "sensor.car_charging",
    "switch.car_charge", "binary_sensor.car_cable",
])
async def test_independent_native_contradiction_does_not_relax_full_cohort_authority(
    hass, freezer, entity,
):
    rig = _native(hass, freezer)
    _charge_frame(hass, rig, freezer, charging=True, current=8, connected=True)
    rig.provider.data["charge_state_charge_current_request"] = 12
    feedback = capture_ev_feedback(hass, ev_observation_entity_map(rig.coordinator.runtime_config))
    assert not before_export_vehicle_feedback_valid(
        hass, feedback, now=rig.now, max_age_seconds=90,
    )
    assert before_export_item_measured_fresh(
        hass, feedback.for_entity(entity), now=rig.now, max_age_seconds=90, cohort_valid=False,
    )


@pytest.mark.parametrize("entity", ["sensor.car_charging", "switch.car_charge"])
async def test_optimistic_native_switch_bool_is_not_a_vehicle_measurement(hass, freezer, entity):
    rig = _native(hass, freezer)
    _charge_frame(hass, rig, freezer, charging=True, current=8, connected=True)
    rig.provider.data["charge_state_charging_state"] = True
    assert not before_export_item_measured_fresh(
        hass, capture_ev_entity_feedback(hass, entity), now=rig.now,
        max_age_seconds=90, cohort_valid=True,
    )


@pytest.mark.parametrize("general,vehicle", [(30, 90), (90, 30)])
async def test_native_physical_handoff_retains_both_existing_age_bounds(
    hass, freezer, general, vehicle,
):
    rig = _native(hass, freezer)
    controller = _controller(hass, rig, mapped=False)
    rig.coordinator.config.update({
        "telemetry_max_age_seconds": general, "ev_telemetry_max_age_seconds": vehicle,
    })
    rig.coordinator.runtime_config = RuntimeConfiguration.from_mapping(rig.coordinator.config)
    rig.provider.data["charge_state_timestamp"] = (
        rig.now - timedelta(seconds=31)
    ).timestamp() * 1000
    assert not controller._ev_before_export_handoff_ready(rig.now)
    controller._local_ev_connection.close()


@pytest.mark.parametrize("mapped", [False, True])
async def test_recent_native_baseline_request_does_not_need_a_value_change(
    hass, freezer, mapped,
):
    rig = _native(hass, freezer)
    _charge_frame(hass, rig, freezer, charging=True, current=1, connected=True)
    freezer.move_to(rig.now - timedelta(hours=1))
    old = hass.states.get("number.car_current")
    hass.states.async_set(old.entity_id, "1", dict(old.attributes), force_update=True)
    freezer.move_to(rig.now)
    rig.provider.data["charge_state_charge_current_request"] = 1
    if mapped:
        hass.states.async_set(ENTITY, "on")
    controller = _controller(hass, rig, mapped=mapped)
    rig.coordinator.config["ev_protected_baseline_a"] = 1
    rig.coordinator.runtime_config = RuntimeConfiguration.from_mapping(rig.coordinator.config)
    assert controller._ev_before_export_handoff_ready(rig.now)
    controller._local_ev_connection.close()


def _physical_feedback(hass, rig):
    return capture_ev_feedback(hass, ev_observation_entity_map(rig.coordinator.runtime_config))


def _other_vehicle(hass, rig):
    vin = "SECONDTESTVEHICLE"
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=rig.entry.entry_id, identifiers={("tessie", vin)},
    )
    provider = SimpleNamespace(
        config_entry=rig.entry, last_update_success=True, data=dict(rig.provider.data),
    )
    rig.entry.runtime_data.vehicles.append(SimpleNamespace(vin=vin, data_coordinator=provider))
    return vin, device


@pytest.mark.parametrize("entity", [
    "binary_sensor.car_cable", "sensor.car_charging", "sensor.car_actual_current",
    "switch.car_charge", "sensor.car_soc", "number.car_current", "number.car_limit",
])
async def test_physical_native_ack_cannot_mix_other_vehicle_or_policy_registry_identity(
    hass, freezer, entity,
):
    rig = _native(hass, freezer)
    _charge_frame(hass, rig, freezer, charging=False, current=0, connected=False)
    vin, device = _other_vehicle(hass, rig)
    er.async_get(hass).async_update_entity(
        entity, device_id=device.id, new_unique_id=f"{vin}-{FIELDS[entity]}",
    )
    feedback = _physical_feedback(hass, rig)
    # Each of the four fields is individually genuine and fresh; it is their
    # cross-vehicle composition that cannot acknowledge this car's stop duty.
    assert all(before_export_item_measured_fresh(
        hass, item, now=rig.now, max_age_seconds=90, cohort_valid=False,
    ) for item in (
        feedback.cable_connected, feedback.charging_state,
        feedback.actual_current, feedback.charge_switch,
    ))
    assert not before_export_physical_feedback_valid(
        hass, feedback, now=rig.now, max_age_seconds=90,
    )


@pytest.mark.parametrize("entity", ["sensor.car_soc", "number.car_current", "number.car_limit"])
async def test_physical_native_ack_uses_unavailable_policy_mapping_identity_not_its_value(
    hass, freezer, entity,
):
    rig = _native(hass, freezer)
    _charge_frame(hass, rig, freezer, charging=False, current=0, connected=False)
    old = hass.states.get(entity)
    hass.states.async_set(entity, "unavailable", dict(old.attributes), force_update=True)
    feedback = _physical_feedback(hass, rig)
    assert before_export_physical_feedback_valid(
        hass, feedback, now=rig.now, max_age_seconds=90,
    )
    physical = feedback.physical_observation(
        now=rig.now, max_age_seconds=90, measured_cohort_valid=True,
    )
    assert physical.disconnected_idle and not physical.charging_activity


async def test_generic_physical_ack_does_not_borrow_or_require_native_policy_values(hass, freezer):
    rig = _native(hass, freezer, old_seconds=0)
    _charge_frame(hass, rig, freezer, charging=False, current=0, connected=False, entity_age=0)
    for entity in ("binary_sensor.car_cable", "sensor.car_charging",
                   "sensor.car_actual_current", "switch.car_charge"):
        er.async_get(hass).async_remove(entity)
    # These explicit generic physical publishers keep their own fresh report
    # semantics; native policy values do not become a new stop prerequisite.
    hass.states.async_set("sensor.car_soc", "unavailable")
    assert before_export_physical_feedback_valid(
        hass, _physical_feedback(hass, rig), now=rig.now, max_age_seconds=90,
    )


async def test_physical_native_ack_rejects_wrong_policy_field_even_when_unavailable(hass, freezer):
    rig = _native(hass, freezer)
    _charge_frame(hass, rig, freezer, charging=False, current=0, connected=False)
    er.async_get(hass).async_update_entity(
        "sensor.car_soc", new_unique_id="TESTVEHICLE0000001-drive_state_power",
    )
    hass.states.async_set("sensor.car_soc", "unavailable")
    assert not before_export_physical_feedback_valid(
        hass, _physical_feedback(hass, rig), now=rig.now, max_age_seconds=90,
    )
