"""Tests for the side-effect-free mapped EV entity boundary."""

from dataclasses import FrozenInstanceError
from math import isnan

import pytest

from custom_components.home_energy_orchestrator.ev_observation_adapter import (
    capture_ev_entity_feedback,
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
    assert result.number == 6000.0
    assert result.current_a == 6.0
    assert result.energy_kwh is None
    assert result.minimum == 1000.0
    assert result.maximum == 16000.0
    assert result.step == 1000.0
    assert result.unit == "mA"
    assert result.last_changed == source.last_changed
    assert result.last_updated == source.last_updated


@pytest.mark.parametrize("reported", ["unknown", "unavailable", "UNKNOWN"])
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
    assert nonfinite.current_a is not None and isnan(nonfinite.current_a)


def test_snapshot_is_immutable(hass) -> None:
    hass.states.async_set("sensor.car", "home")
    result = capture_ev_entity_feedback(hass, "sensor.car")

    with pytest.raises(FrozenInstanceError):
        result.reported_state = "away"  # type: ignore[misc]
