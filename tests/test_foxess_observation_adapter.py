"""Tests for the side-effect-free FoxESS observation boundary."""

import pytest

from custom_components.home_energy_orchestrator.foxess_adapter import (
    FoxessEntityMap,
)
from custom_components.home_energy_orchestrator.foxess_observation_adapter import (
    capture_foxess_feedback,
)
from custom_components.home_energy_orchestrator.planner.foxess import (
    FoxessObservation,
)

ENTITIES = FoxessEntityMap(
    work_mode_entity="select.foxess_mode",
    force_charge_power_entity="number.foxess_charge",
    force_discharge_power_entity="number.foxess_discharge",
)


def test_capture_returns_one_normalized_immutable_snapshot(hass) -> None:
    hass.states.async_set(
        ENTITIES.work_mode_entity,
        "Self Use",
        {"options": ["Self Use", "Force Charge", "Force Discharge"]},
    )
    hass.states.async_set(
        ENTITIES.force_charge_power_entity,
        "2500",
        {"unit_of_measurement": "W", "max": 10000},
    )
    hass.states.async_set(
        ENTITIES.force_discharge_power_entity,
        "3.5",
        {"unit_of_measurement": "kW", "max": 15},
    )

    result = capture_foxess_feedback(hass, ENTITIES)

    assert result.observation == FoxessObservation("Self Use", 2.5, 3.5)
    assert result.manual_observation == FoxessObservation("Self Use", 2.5, 3.5)
    assert result.reported_mode == "Self Use"
    assert result.mode == "Self Use"
    assert result.charge_power_kw == 2.5
    assert result.discharge_power_kw == 3.5
    assert result.charge_power_max_kw == 10.0
    assert result.discharge_power_max_kw == 15.0
    assert result.charge_source_available is True
    assert result.export_source_available is True
    assert result.mapped_entities_available is True


def test_capture_keeps_independent_source_capability_and_feedback_validity(hass) -> None:
    hass.states.async_set(
        ENTITIES.work_mode_entity,
        "Self Use",
        {"options": ["Self Use", "Force Charge"]},
    )
    hass.states.async_set(
        ENTITIES.force_charge_power_entity,
        "unknown",
        {"unit_of_measurement": "kW", "max": "invalid"},
    )
    hass.states.async_set(
        ENTITIES.force_discharge_power_entity,
        "0",
        {"unit_of_measurement": "kW", "max": 8},
    )

    result = capture_foxess_feedback(hass, ENTITIES)

    assert result.observation is None
    assert result.manual_observation is None
    assert result.mode == "Self Use"
    assert result.charge_power_kw is None
    assert result.discharge_power_kw == 0.0
    assert result.charge_power_max_kw == 0.0
    assert result.discharge_power_max_kw == 8.0
    assert result.charge_source_available is True
    assert result.export_source_available is False
    assert result.mapped_entities_available is True


def test_capture_fails_closed_for_missing_or_unavailable_entities(hass) -> None:
    hass.states.async_set(
        ENTITIES.work_mode_entity,
        "unavailable",
        {"options": "Self Use, Force Discharge"},
    )
    hass.states.async_set(
        ENTITIES.force_discharge_power_entity,
        "not-a-number",
        {"unit_of_measurement": "kW"},
    )

    result = capture_foxess_feedback(hass, ENTITIES)

    assert result.observation is None
    assert result.manual_observation is None
    assert result.reported_mode == "unavailable"
    assert result.mode is None
    assert result.charge_power_kw is None
    assert result.discharge_power_kw is None
    assert result.mode_options == ()
    assert result.charge_source_available is False
    assert result.export_source_available is False
    assert result.mapped_entities_available is False


@pytest.mark.parametrize("invalid_power", ["-1", "nan", "inf", "-inf"])
def test_capture_fails_closed_for_invalid_numeric_power_feedback(
    hass, invalid_power: str
) -> None:
    hass.states.async_set(
        ENTITIES.work_mode_entity,
        "Self Use",
        {"options": ["Self Use", "Force Charge", "Force Discharge"]},
    )
    hass.states.async_set(
        ENTITIES.force_charge_power_entity,
        invalid_power,
        {"unit_of_measurement": "kW"},
    )
    hass.states.async_set(
        ENTITIES.force_discharge_power_entity,
        "0",
        {"unit_of_measurement": "kW"},
    )

    result = capture_foxess_feedback(hass, ENTITIES)

    assert result.observation is None
    assert result.manual_observation is None
    assert result.charge_power_kw is None
    assert result.discharge_power_kw == 0.0


def test_manual_feedback_preserves_raw_unavailable_mode(hass) -> None:
    """Diagnostic reads retain their legacy raw-mode behavior."""
    hass.states.async_set(ENTITIES.work_mode_entity, "unavailable")
    hass.states.async_set(
        ENTITIES.force_charge_power_entity,
        "0",
        {"unit_of_measurement": "kW"},
    )
    hass.states.async_set(
        ENTITIES.force_discharge_power_entity,
        "0",
        {"unit_of_measurement": "kW"},
    )

    result = capture_foxess_feedback(hass, ENTITIES)

    assert result.observation is None
    assert result.manual_observation == FoxessObservation("unavailable", 0.0, 0.0)
    assert result.reported_mode == "unavailable"
    assert result.mode is None
    assert result.mapped_entities_available is True


def test_snapshot_freezes_legacy_controller_read_results(hass) -> None:
    hass.states.async_set(
        ENTITIES.work_mode_entity,
        "Force Discharge",
        {"options": ("Self Use", "Force Charge", "Force Discharge")},
    )
    hass.states.async_set(
        ENTITIES.force_charge_power_entity,
        "1250",
        {"unit_of_measurement": "W", "max": 9000},
    )
    hass.states.async_set(
        ENTITIES.force_discharge_power_entity,
        "4.25",
        {"unit_of_measurement": "kW", "max": 12},
    )
    result = capture_foxess_feedback(hass, ENTITIES)

    assert result.observation == FoxessObservation("Force Discharge", 1.25, 4.25)
    assert result.manual_observation == FoxessObservation(
        "Force Discharge", 1.25, 4.25
    )
    assert result.mode == "Force Discharge"
    assert result.charge_power_kw == 1.25
    assert result.discharge_power_kw == 4.25
    assert result.charge_power_max_kw == 9.0
    assert result.discharge_power_max_kw == 12.0
    assert result.charge_source_available is True
    assert result.export_source_available is True
