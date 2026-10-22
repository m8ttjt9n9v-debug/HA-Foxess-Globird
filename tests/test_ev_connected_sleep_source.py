"""Independent local idle proof never makes retained Tessie data fresh."""

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.home_energy_orchestrator.ev_local_connection import LocalEvConnectionObserver
from custom_components.home_energy_orchestrator.ev_observation_adapter import (
    capture_ev_feedback,
    ev_observation_entity_map,
)
from custom_components.home_energy_orchestrator.ev_source_feedback import (
    before_export_vehicle_feedback_valid,
)
from tests.test_ev_before_export_source_clocks import _native
from tests.test_ev_export_handoff_source_contract import _charge_frame
from tests.test_ev_local_connection import ENTITY, Publisher, capture, native


@pytest.fixture(autouse=True)
async def source_cleanup(hass):
    yield
    for entry in hass.config_entries.async_entries():
        if entry.domain in {"tessie", "foxess_modbus", "tesla_wall_connector"}:
            entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    await hass.async_block_till_done()


@pytest.mark.parametrize("age,allowed", [(0, True), (90, True), (90.001, False), (-1, False)])
async def test_connected_open_native_requires_own_new_bounded_publication(
    hass, freezer, age, allowed
):
    rig = native(hass)
    hass.states.async_set(ENTITY, "on")
    observer = LocalEvConnectionObserver(hass)
    assert not capture(observer).connected_idle  # Do not seed cache.
    rig.provider.publish(Publisher.payload(True, False))
    freezer.tick(timedelta(seconds=age))
    rig.provider.publish(rig.provider.data)  # No renewal by cache callback.
    result = capture(observer)
    assert result.connected_idle is allowed
    observer.close()


async def test_generic_connected_sensor_is_not_contactor_proof(hass):
    hass.states.async_set(ENTITY, "on")
    assert not capture(LocalEvConnectionObserver(hass)).connected_idle


async def test_native_contactor_close_retracts_without_waiting_for_new_publication(hass):
    rig = native(hass)
    hass.states.async_set(ENTITY, "on")
    observer = LocalEvConnectionObserver(hass)
    capture(observer)
    rig.provider.publish(Publisher.payload(True, False))
    assert capture(observer).connected_idle
    rig.provider.data = Publisher.payload(True, True)
    assert not capture(observer).connected_idle
    rig.provider.data = Publisher.payload(True, False)
    assert not capture(observer).connected_idle
    rig.provider.publish(Publisher.payload(True, False))
    assert capture(observer).connected_idle
    observer.close()


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "future",
        "missing_clock",
        "wrong_field",
        "wrong_device",
        "disabled",
        "restored",
        "soc_mismatch",
        "actual_positive",
        "wrong_unit",
        "charging",
        "command_bool",
        "disconnected",
        "failed",
        "unloaded",
        "new_connection",
        "generic_mapping",
        "invalid_soc",
    ],
)
async def test_retained_stopped_frame_is_bound_valid_and_not_a_fresh_cohort(hass, freezer, fault):
    rig = _native(hass, freezer)
    _charge_frame(hass, rig, freezer, charging=False, current=0, connected=True)
    rig.provider.data["state"] = "asleep"
    rig.provider.data["charge_state_timestamp"] -= 3_600_000
    if fault == "future":
        rig.provider.data["charge_state_timestamp"] = (
            rig.now + timedelta(seconds=1)
        ).timestamp() * 1000
    elif fault == "missing_clock":
        rig.provider.data.pop("charge_state_timestamp")
    elif fault in {"wrong_field", "wrong_device", "disabled"}:
        change = {
            "wrong_field": {"new_unique_id": "other-field"},
            "wrong_device": {"device_id": None},
            "disabled": {"disabled_by": er.RegistryEntryDisabler.USER},
        }[fault]
        er.async_get(hass).async_update_entity("sensor.car_soc", **change)
    elif fault == "restored":
        hass.states.async_set("sensor.car_soc", "25", {"restored": True})
    elif fault == "soc_mismatch":
        rig.provider.data["charge_state_usable_battery_level"] = 26
    elif fault == "actual_positive":
        rig.provider.data["charge_state_charger_actual_current"] = 8
        hass.states.async_set("sensor.car_actual_current", "8", {"unit_of_measurement": "A"})
    elif fault == "wrong_unit":
        hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "kW"})
    elif fault in {"charging", "command_bool"}:
        rig.provider.data["charge_state_charging_state"] = (
            "Charging" if fault == "charging" else False
        )
    elif fault == "disconnected":
        rig.provider.data["charge_state_conn_charge_cable"] = "<invalid>"
    elif fault == "failed":
        rig.provider.last_update_success = False
    elif fault == "unloaded":
        rig.entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    elif fault == "generic_mapping":
        er.async_get(hass).async_remove("sensor.car_soc")
    elif fault == "invalid_soc":
        hass.states.async_set("sensor.car_soc", "unavailable")
    feedback = capture_ev_feedback(hass, ev_observation_entity_map(rig.coordinator.runtime_config))
    kwargs = {"now": rig.now, "max_age_seconds": 90}
    assert not before_export_vehicle_feedback_valid(hass, feedback, **kwargs)
    assert before_export_vehicle_feedback_valid(
        hass,
        feedback,
        **kwargs,
        local_connected_idle=True,
        measured_since=rig.now if fault == "new_connection" else None,
    ) is (fault is None)
