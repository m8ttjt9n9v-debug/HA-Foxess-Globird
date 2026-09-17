"""Immutable runtime configuration tests."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
    CONF_EXPORT_RATE,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_FREE_CHARGE_SCHEDULE_CONFIRMED,
    CONF_GRID_POWER_DIRECTION,
    CONF_HOUSE_OCCUPANCY_MODE,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_ZERO_IMPORT_THRESHOLD_KW,
    DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
    DEFAULT_EXPORT_RATE,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DEFAULT_GRID_POWER_DIRECTION,
    DEFAULT_HOUSE_OCCUPANCY_MODE,
    DEFAULT_INVERTER_CHARGE_LIMIT_KW,
    DEFAULT_ZERO_IMPORT_THRESHOLD_KW,
)
from custom_components.home_energy_orchestrator.coordinator import EnergyCoordinator


def test_runtime_configuration_uses_established_defaults() -> None:
    parsed = RuntimeConfiguration.from_mapping({})
    assert parsed.automation.safety_lock is True
    assert parsed.automation.battery_charge_enabled is False
    assert parsed.automation.battery_export_enabled is False
    assert parsed.automation.ev_control_enabled is False
    assert parsed.automation.control_owner == DEFAULT_FOXESS_CONTROL_OWNER
    assert parsed.automation.free_charge_schedule_confirmed is False
    assert parsed.ev_preferences.before_export_enabled is False
    assert parsed.ev_preferences.before_export_soc_target == (
        DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET
    )
    assert parsed.ev_preferences.charge_to_full_enabled is False
    assert parsed.house.occupancy_mode == DEFAULT_HOUSE_OCCUPANCY_MODE
    assert parsed.electrical.verified is False
    assert (
        parsed.electrical.grid_power_positive_direction
        == DEFAULT_GRID_POWER_DIRECTION
    )
    assert parsed.tariff.peak_export_rate_per_kwh == DEFAULT_EXPORT_RATE
    assert (
        parsed.tariff.zero_import_threshold_kwh_per_hour
        == DEFAULT_ZERO_IMPORT_THRESHOLD_KW
    )
    assert parsed.inverter.charge_limit_kw == DEFAULT_INVERTER_CHARGE_LIMIT_KW
    assert parsed.inverter.work_mode_entity is None
    assert parsed.inverter.force_charge_power_entity is None
    assert parsed.inverter.force_discharge_power_entity is None
    assert parsed.inverter.actuator_mapping_complete is False


def test_runtime_configuration_preserves_existing_coercion_behavior() -> None:
    parsed = RuntimeConfiguration.from_mapping(
        {
            CONF_AUTOMATIC_CHARGE_ENABLED: "non-empty",
            CONF_EV_BEFORE_EXPORT_SOC_TARGET: "invalid",
            CONF_GRID_POWER_DIRECTION: None,
            CONF_FOXESS_CONTROL_OWNER: None,
            CONF_FREE_CHARGE_SCHEDULE_CONFIRMED: "confirmed",
            CONF_HOUSE_OCCUPANCY_MODE: "invalid",
            CONF_INVERTER_CHARGE_LIMIT_KW: "12.5",
            CONF_EXPORT_RATE: "0.075",
            CONF_ZERO_IMPORT_THRESHOLD_KW: "invalid",
            CONF_FOXESS_WORK_MODE: "select.foxess_mode",
            CONF_FOXESS_FORCE_CHARGE_POWER: "number.foxess_charge",
            CONF_FOXESS_FORCE_DISCHARGE_POWER: "number.foxess_discharge",
        }
    )
    assert parsed.automation.battery_charge_enabled is True
    assert parsed.ev_preferences.before_export_soc_target == (
        DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET
    )
    assert parsed.house.occupancy_mode == DEFAULT_HOUSE_OCCUPANCY_MODE
    assert parsed.electrical.grid_power_positive_direction is None
    assert parsed.automation.control_owner is None
    assert parsed.automation.free_charge_schedule_confirmed is True
    assert parsed.tariff.peak_export_rate_per_kwh == 0.075
    assert (
        parsed.tariff.zero_import_threshold_kwh_per_hour
        == DEFAULT_ZERO_IMPORT_THRESHOLD_KW
    )
    assert parsed.inverter.charge_limit_kw == 12.5
    assert parsed.inverter.work_mode_entity == "select.foxess_mode"
    assert parsed.inverter.force_charge_power_entity == "number.foxess_charge"
    assert parsed.inverter.force_discharge_power_entity == "number.foxess_discharge"
    assert parsed.inverter.actuator_mapping_complete is True


def test_runtime_configuration_is_immutable() -> None:
    parsed = RuntimeConfiguration.from_mapping({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        parsed.automation.safety_lock = False  # type: ignore[misc]


def test_runtime_configuration_is_a_snapshot() -> None:
    data = {CONF_AUTOMATIC_CHARGE_ENABLED: False}
    parsed = RuntimeConfiguration.from_mapping(data)
    data[CONF_AUTOMATIC_CHARGE_ENABLED] = True
    assert parsed.automation.battery_charge_enabled is False


def test_coordinator_mutation_rebuilds_the_snapshot_synchronously() -> None:
    config = {CONF_AUTOMATIC_CHARGE_ENABLED: False}
    coordinator = SimpleNamespace(
        config=config,
        runtime_config=RuntimeConfiguration.from_mapping(config),
    )
    EnergyCoordinator.update_config_value(
        coordinator,
        CONF_AUTOMATIC_CHARGE_ENABLED,
        True,
    )
    assert coordinator.config[CONF_AUTOMATIC_CHARGE_ENABLED] is True
    assert coordinator.runtime_config.automation.battery_charge_enabled is True
