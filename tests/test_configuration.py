"""Immutable runtime configuration tests."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
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
    CONF_REHEARSAL_MODE,
    CONF_SIGN_CONVENTIONS_VERIFIED,
    CONF_ZERO_IMPORT_THRESHOLD_KW,
    DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
    DEFAULT_EXPORT_RATE,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DEFAULT_GRID_POWER_DIRECTION,
    DEFAULT_HOUSE_OCCUPANCY_MODE,
    DEFAULT_INVERTER_CHARGE_LIMIT_KW,
    DEFAULT_REHEARSAL_MODE,
    DEFAULT_SIGN_CONVENTIONS_VERIFIED,
    DEFAULT_ZERO_IMPORT_THRESHOLD_KW,
)
from custom_components.home_energy_orchestrator.coordinator import EnergyCoordinator


def _legacy_active_gate_status(data: dict[str, object]) -> str:
    """Reproduce the pre-typed active-controller gate contract."""
    owner = data.get(CONF_FOXESS_CONTROL_OWNER, DEFAULT_FOXESS_CONTROL_OWNER)
    if owner == "foxcloud_scheduler":
        return "foxcloud_scheduler_owner"
    if owner != "local_modbus":
        return "observer_owner"
    if not data.get(CONF_AUTOMATIC_CONTROL_ENABLED, False):
        return "disabled"
    if data.get(CONF_REHEARSAL_MODE, DEFAULT_REHEARSAL_MODE):
        return "rehearsal"
    if not data.get(
        CONF_SIGN_CONVENTIONS_VERIFIED,
        DEFAULT_SIGN_CONVENTIONS_VERIFIED,
    ):
        return "sign_conventions_unverified"
    mapping = (
        data.get(CONF_FOXESS_WORK_MODE),
        data.get(CONF_FOXESS_FORCE_CHARGE_POWER),
        data.get(CONF_FOXESS_FORCE_DISCHARGE_POWER),
    )
    return "ready" if all(mapping) else "blocked_incomplete_mapping"


def _typed_active_gate_status(data: dict[str, object]) -> str:
    """Project the same gate through the immutable runtime snapshot."""
    runtime = RuntimeConfiguration.from_mapping(data)
    if runtime.automation.control_owner == "foxcloud_scheduler":
        return "foxcloud_scheduler_owner"
    if runtime.automation.control_owner != "local_modbus":
        return "observer_owner"
    if not runtime.automation.master_enabled:
        return "disabled"
    if runtime.automation.safety_lock:
        return "rehearsal"
    if not runtime.electrical.verified:
        return "sign_conventions_unverified"
    return (
        "ready"
        if runtime.inverter.actuator_mapping_complete
        else "blocked_incomplete_mapping"
    )


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


@pytest.mark.parametrize(
    "data",
    [
        {},
        {CONF_FOXESS_CONTROL_OWNER: None},
        {CONF_FOXESS_CONTROL_OWNER: "observer_only"},
        {CONF_FOXESS_CONTROL_OWNER: "foxcloud_scheduler"},
        {
            CONF_FOXESS_CONTROL_OWNER: "local_modbus",
            CONF_AUTOMATIC_CONTROL_ENABLED: False,
        },
        {
            CONF_FOXESS_CONTROL_OWNER: "local_modbus",
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_REHEARSAL_MODE: True,
        },
        {
            CONF_FOXESS_CONTROL_OWNER: "local_modbus",
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_SIGN_CONVENTIONS_VERIFIED: False,
        },
        {
            CONF_FOXESS_CONTROL_OWNER: "local_modbus",
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_SIGN_CONVENTIONS_VERIFIED: True,
        },
        {
            CONF_FOXESS_CONTROL_OWNER: "local_modbus",
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_SIGN_CONVENTIONS_VERIFIED: True,
            CONF_FOXESS_WORK_MODE: "select.foxess_mode",
            CONF_FOXESS_FORCE_CHARGE_POWER: "number.foxess_charge",
            CONF_FOXESS_FORCE_DISCHARGE_POWER: "number.foxess_discharge",
        },
        {
            CONF_FOXESS_CONTROL_OWNER: "local_modbus",
            CONF_AUTOMATIC_CONTROL_ENABLED: "enabled",
            CONF_REHEARSAL_MODE: "",
            CONF_SIGN_CONVENTIONS_VERIFIED: "verified",
            CONF_FOXESS_WORK_MODE: "select.foxess_mode",
            CONF_FOXESS_FORCE_CHARGE_POWER: "number.foxess_charge",
            CONF_FOXESS_FORCE_DISCHARGE_POWER: "number.foxess_discharge",
        },
    ],
)
def test_typed_active_gate_preserves_legacy_precedence_and_coercion(
    data: dict[str, object],
) -> None:
    """Lock the old gate outcome before active control adopts typed config."""
    assert _typed_active_gate_status(data) == _legacy_active_gate_status(data)


def test_typed_active_policy_requests_preserve_legacy_boolean_semantics() -> None:
    """Lock independent request/default behavior before controller migration."""
    cases = (
        {},
        {
            CONF_AUTOMATIC_CHARGE_ENABLED: "requested",
            CONF_AUTOMATIC_EXPORT_ENABLED: 1,
            CONF_FREE_CHARGE_SCHEDULE_CONFIRMED: "confirmed",
        },
        {
            CONF_AUTOMATIC_CHARGE_ENABLED: "",
            CONF_AUTOMATIC_EXPORT_ENABLED: 0,
            CONF_FREE_CHARGE_SCHEDULE_CONFIRMED: None,
        },
    )
    for data in cases:
        runtime = RuntimeConfiguration.from_mapping(data)
        assert runtime.automation.battery_charge_enabled is bool(
            data.get(CONF_AUTOMATIC_CHARGE_ENABLED, False)
        )
        assert runtime.automation.battery_export_enabled is bool(
            data.get(CONF_AUTOMATIC_EXPORT_ENABLED, False)
        )
        assert runtime.automation.free_charge_schedule_confirmed is bool(
            data.get(CONF_FREE_CHARGE_SCHEDULE_CONFIRMED, False)
        )


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
