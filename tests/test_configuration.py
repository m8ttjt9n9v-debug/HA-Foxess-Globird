"""Immutable runtime configuration tests."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
    CONF_HOUSE_OCCUPANCY_MODE,
    DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
    DEFAULT_HOUSE_OCCUPANCY_MODE,
)
from custom_components.home_energy_orchestrator.coordinator import EnergyCoordinator


def test_runtime_configuration_uses_established_defaults() -> None:
    parsed = RuntimeConfiguration.from_mapping({})
    assert parsed.automation.safety_lock is True
    assert parsed.automation.battery_charge_enabled is False
    assert parsed.automation.battery_export_enabled is False
    assert parsed.automation.ev_control_enabled is False
    assert parsed.ev_preferences.before_export_enabled is False
    assert parsed.ev_preferences.before_export_soc_target == (
        DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET
    )
    assert parsed.ev_preferences.charge_to_full_enabled is False
    assert parsed.house.occupancy_mode == DEFAULT_HOUSE_OCCUPANCY_MODE


def test_runtime_configuration_preserves_existing_coercion_behavior() -> None:
    parsed = RuntimeConfiguration.from_mapping(
        {
            CONF_AUTOMATIC_CHARGE_ENABLED: "non-empty",
            CONF_EV_BEFORE_EXPORT_SOC_TARGET: "invalid",
            CONF_HOUSE_OCCUPANCY_MODE: "invalid",
        }
    )
    assert parsed.automation.battery_charge_enabled is True
    assert parsed.ev_preferences.before_export_soc_target == (
        DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET
    )
    assert parsed.house.occupancy_mode == DEFAULT_HOUSE_OCCUPANCY_MODE


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
