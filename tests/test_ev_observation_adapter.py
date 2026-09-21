"""Tests for the side-effect-free mapped EV entity boundary."""

from dataclasses import FrozenInstanceError
from math import isnan

import pytest

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.ev_observation_adapter import (
    EvObservationEntityMap,
    capture_ev_entity_feedback,
    capture_ev_feedback,
    ev_observation_entity_map,
)
from custom_components.home_energy_orchestrator.planner.ev import (
    DirectEvseObservation,
)


def test_capture_preserves_state_metadata_and_normalized_interpretations(hass) -> None:
    hass.states.async_set(
        "number.car_current",
        "6000",
        {
            "unit_of_measurement": "mA",
            "min": "1000",
            "max": 16000,
            "step": 1000,
        },
    )
    source = hass.states.get("number.car_current")
    assert source is not None

    result = capture_ev_entity_feedback(hass, "number.car_current")

    assert result.entity_id == "number.car_current"
    assert result.present is True
    assert result.reported_state == "6000"
    assert result.available_state == "6000"
    assert result.raw_number == 6000.0
    assert result.number == 6000.0
    assert result.current_a == 6.0
    assert result.energy_kwh is None
    assert result.minimum == 1000.0
    assert result.maximum == 16000.0
    assert result.step == 1000.0
    assert result.unit == "mA"
    assert result.last_changed == source.last_changed
    assert result.last_updated == source.last_updated


@pytest.mark.parametrize("reported", ["unknown", "unavailable", "UNKNOWN", ""])
def test_unreadable_state_retains_presence_and_raw_value(hass, reported: str) -> None:
    hass.states.async_set("sensor.car", reported)

    result = capture_ev_entity_feedback(hass, "sensor.car")

    assert result.present is True
    assert result.reported_state == reported
    assert result.available_state is None
    assert result.number is None
    assert result.current_a is None
    assert result.energy_kwh is None


def test_missing_or_unmapped_entity_is_an_explicit_empty_snapshot(hass) -> None:
    for entity_id in (None, "sensor.missing"):
        result = capture_ev_entity_feedback(hass, entity_id)

        assert result.entity_id == entity_id
        assert result.present is False
        assert result.reported_state is None
        assert result.available_state is None
        assert result.last_changed is None
        assert result.last_updated is None


def test_numeric_energy_and_actuator_metadata_keep_legacy_distinctions(hass) -> None:
    hass.states.async_set(
        "sensor.car_energy",
        "2500",
        {
            "unit_of_measurement": "Wh",
            "min": "invalid",
            "max": "nan",
            "step": "0.5",
        },
    )

    result = capture_ev_entity_feedback(hass, "sensor.car_energy")

    assert result.number == 2500.0
    assert result.energy_kwh == 2.5
    assert result.minimum is None
    assert result.maximum is not None and isnan(result.maximum)
    assert result.step == 0.5


def test_negative_and_nonfinite_energy_is_unavailable_without_rewriting_number(hass) -> None:
    hass.states.async_set(
        "sensor.negative_energy",
        "-1",
        {"unit_of_measurement": "kWh"},
    )
    negative = capture_ev_entity_feedback(hass, "sensor.negative_energy")
    assert negative.number == -1.0
    assert negative.energy_kwh is None

    hass.states.async_set("sensor.nan", "nan", {"unit_of_measurement": "A"})
    nonfinite = capture_ev_entity_feedback(hass, "sensor.nan")
    assert nonfinite.number is None
    assert nonfinite.current_a is None


@pytest.mark.parametrize("reported", ["nan", "inf", "-inf"])
def test_nonfinite_actual_current_is_invalid_while_charging(hass, reported: str) -> None:
    hass.states.async_set("sensor.car_charging", "charging")
    hass.states.async_set(
        "sensor.car_actual_current",
        reported,
        {"unit_of_measurement": "A"},
    )

    result = capture_ev_feedback(
        hass,
        EvObservationEntityMap(
            charging_state_entity="sensor.car_charging",
            actual_current_entity="sensor.car_actual_current",
        ),
    )

    assert result.actual_current_result == (0.0, False)


def test_snapshot_is_immutable(hass) -> None:
    hass.states.async_set("sensor.car", "home")
    result = capture_ev_entity_feedback(hass, "sensor.car")

    with pytest.raises(FrozenInstanceError):
        result.reported_state = "away"  # type: ignore[misc]


def test_composite_snapshot_preserves_actual_current_and_direct_actuator_views(
    hass,
) -> None:
    hass.states.async_set("sensor.car_charging", "charging")
    hass.states.async_set(
        "sensor.car_actual_current",
        "6500",
        {"unit_of_measurement": "mA"},
    )
    hass.states.async_set(
        "number.car_current",
        "6",
        {"min": 0, "max": 16, "step": 1, "unit_of_measurement": "A"},
    )
    hass.states.async_set(
        "number.car_limit",
        "80",
        {"min": 50, "max": 100, "step": 1},
    )
    hass.states.async_set("switch.car_charge", "off")

    result = capture_ev_feedback(
        hass,
        EvObservationEntityMap(
            charging_state_entity="sensor.car_charging",
            actual_current_entity="sensor.car_actual_current",
            current_limit_entity="number.car_current",
            charge_limit_entity="number.car_limit",
            charge_switch_entity="switch.car_charge",
        ),
    )

    assert result.actual_current_result == (6.5, True)
    assert result.direct_observation == DirectEvseObservation(
        requested_current_a=6.0,
        charge_limit_percent=80.0,
        charge_switch_on=False,
        current_minimum_a=0.0,
        current_maximum_a=16.0,
        current_step_a=1.0,
        limit_minimum_percent=50.0,
        limit_maximum_percent=100.0,
        limit_step_percent=1.0,
        requested_current_changed_at=result.current_limit.last_changed,
    )


def test_actual_current_is_state_qualified_before_numeric_feedback(hass) -> None:
    hass.states.async_set("sensor.car_actual_current", "invalid")
    entities = EvObservationEntityMap(
        charging_state_entity="sensor.car_charging",
        actual_current_entity="sensor.car_actual_current",
    )

    missing = capture_ev_feedback(hass, entities)
    assert missing.actual_current_result == (0.0, False)

    hass.states.async_set("sensor.car_charging", "stopped")
    stopped = capture_ev_feedback(hass, entities)
    assert stopped.actual_current_result == (0.0, True)

    hass.states.async_set("sensor.car_charging", "charging")
    charging = capture_ev_feedback(hass, entities)
    assert charging.actual_current_result == (0.0, False)


def test_composite_capture_reads_duplicate_entity_only_once(hass, monkeypatch) -> None:
    hass.states.async_set("sensor.shared", "on")
    state_machine_type = type(hass.states)
    original_get = state_machine_type.get
    calls: list[str] = []

    def counted_get(state_machine, entity_id: str):
        calls.append(entity_id)
        return original_get(state_machine, entity_id)

    monkeypatch.setattr(state_machine_type, "get", counted_get)
    result = capture_ev_feedback(
        hass,
        EvObservationEntityMap(
            at_home_entity="sensor.shared",
            cable_connected_entity="sensor.shared",
            charging_state_entity="sensor.shared",
        ),
    )

    assert result.at_home is result.cable_connected is result.charging_state
    assert calls == ["sensor.shared"]


def test_typed_runtime_map_includes_every_ev_related_source() -> None:
    runtime = RuntimeConfiguration.from_mapping(
        {
            "ev_at_home_entity": "device_tracker.car",
            "ev_cable_connected_entity": "binary_sensor.cable",
            "ev_charging_state_entity": "sensor.charging",
            "ev_actual_current_entity": "sensor.current",
            "ev_soc_entity": "sensor.soc",
            "ev_stored_energy_entity": "sensor.stored",
            "ev_lifetime_energy_entity": "sensor.lifetime",
            "ev_current_limit_entity": "number.current",
            "ev_charge_limit_entity": "number.limit",
            "ev_charge_switch_entity": "switch.charge",
            "ev_smart_socket_entity": "switch.socket",
            "ev_charge_to_full_entity": "input_boolean.full",
            "battery_soc_entity": "sensor.battery_soc",
        }
    )

    assert ev_observation_entity_map(runtime) == EvObservationEntityMap(
        at_home_entity="device_tracker.car",
        cable_connected_entity="binary_sensor.cable",
        charging_state_entity="sensor.charging",
        actual_current_entity="sensor.current",
        soc_entity="sensor.soc",
        stored_energy_entity="sensor.stored",
        lifetime_energy_entity="sensor.lifetime",
        current_limit_entity="number.current",
        charge_limit_entity="number.limit",
        charge_switch_entity="switch.charge",
        smart_socket_entity="switch.socket",
        legacy_charge_to_full_entity="input_boolean.full",
        battery_soc_entity="sensor.battery_soc",
    )
