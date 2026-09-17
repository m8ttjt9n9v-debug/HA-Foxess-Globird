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
    CONF_BATTERY_SOC,
    CONF_CONFIGURE_EV,
    CONF_CONFIGURE_SOLAR,
    CONF_EV_ACTUAL_CURRENT,
    CONF_EV_ALLOWANCE_GUARD_ENABLED,
    CONF_EV_AT_HOME,
    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
    CONF_EV_CABLE_CONNECTED,
    CONF_EV_CHARGE_LIMIT,
    CONF_EV_CHARGE_PATH,
    CONF_EV_CHARGE_SWITCH,
    CONF_EV_CHARGE_TO_FULL,
    CONF_EV_CHARGE_TO_FULL_ENABLED,
    CONF_EV_CHARGING_STATE,
    CONF_EV_CONTROL_COMMISSIONED,
    CONF_EV_CURRENT_LIMIT,
    CONF_EV_FREE_WINDOW_PRIORITY,
    CONF_EV_LIFETIME_ENERGY,
    CONF_EV_LOCATION_MODE,
    CONF_EV_PHASE_COUNT,
    CONF_EV_PRE_FREE_ENABLED,
    CONF_EV_PROTECTED_BASELINE_A,
    CONF_EV_SMART_SOCKET,
    CONF_EV_SMART_SOCKET_CURRENT_LIMIT,
    CONF_EV_SMART_SOCKET_POWER_SWITCHING,
    CONF_EV_SOC,
    CONF_EV_SOLAR_SPILL_ENABLED,
    CONF_EV_STORED_ENERGY,
    CONF_EV_VOLTAGE,
    CONF_EXPORT_RATE,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_FREE_CHARGE_SCHEDULE_CONFIRMED,
    CONF_GRID_POWER_DIRECTION,
    CONF_HOUSE_LOAD_INCLUDES_EV,
    CONF_HOUSE_OCCUPANCY_MODE,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_REHEARSAL_MODE,
    CONF_SIGN_CONVENTIONS_VERIFIED,
    CONF_SITE_GRID_CURRENT,
    CONF_SITE_PHASE_COUNT,
    CONF_ZERO_IMPORT_THRESHOLD_KW,
    DEFAULT_EV_ALLOWANCE_GUARD_ENABLED,
    DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
    DEFAULT_EV_CHARGE_PATH,
    DEFAULT_EV_FREE_WINDOW_PRIORITY,
    DEFAULT_EV_LOCATION_MODE,
    DEFAULT_EV_PHASE_COUNT,
    DEFAULT_EV_PRE_FREE_ENABLED,
    DEFAULT_EV_PROTECTED_BASELINE_A,
    DEFAULT_EV_SMART_SOCKET_CURRENT_LIMIT,
    DEFAULT_EV_SMART_SOCKET_POWER_SWITCHING,
    DEFAULT_EV_SOLAR_SPILL_ENABLED,
    DEFAULT_EV_VOLTAGE,
    DEFAULT_EXPORT_RATE,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DEFAULT_GRID_POWER_DIRECTION,
    DEFAULT_HOUSE_LOAD_INCLUDES_EV,
    DEFAULT_HOUSE_OCCUPANCY_MODE,
    DEFAULT_INVERTER_CHARGE_LIMIT_KW,
    DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
    DEFAULT_REHEARSAL_MODE,
    DEFAULT_SIGN_CONVENTIONS_VERIFIED,
    DEFAULT_SITE_PHASE_COUNT,
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
    assert parsed.ev_preferences.charge_to_full_configured is False
    assert parsed.ev_preferences.charge_to_full_enabled is False
    assert parsed.ev_preferences.legacy_charge_to_full_entity is None
    assert parsed.ev_connection.configured is False
    assert parsed.ev_connection.explicitly_disabled is False
    assert parsed.ev_connection.control_commissioned is False
    assert parsed.ev_connection.location_mode == DEFAULT_EV_LOCATION_MODE
    assert parsed.ev_connection.at_home_entity is None
    assert parsed.ev_connection.cable_connected_entity is None
    assert (
        parsed.ev_connection.protected_baseline_a
        == DEFAULT_EV_PROTECTED_BASELINE_A
    )
    assert parsed.ev_connection.voltage_v == DEFAULT_EV_VOLTAGE
    assert parsed.ev_connection.phase_count == DEFAULT_EV_PHASE_COUNT
    assert parsed.ev_actuators.direct_entities is None
    assert parsed.ev_actuators.smart_socket_entity is None
    assert parsed.ev_telemetry.soc_entity is None
    assert parsed.ev_telemetry.charging_state_entity is None
    assert parsed.ev_telemetry.actual_current_entity is None
    assert parsed.ev_telemetry.stored_energy_entity is None
    assert parsed.ev_telemetry.lifetime_energy_entity is None
    assert parsed.ev_policy.charge_path == DEFAULT_EV_CHARGE_PATH
    assert parsed.ev_policy.free_window_priority == DEFAULT_EV_FREE_WINDOW_PRIORITY
    assert (
        parsed.ev_policy.allowance_guard_enabled
        is DEFAULT_EV_ALLOWANCE_GUARD_ENABLED
    )
    assert parsed.ev_policy.solar_spill_enabled is DEFAULT_EV_SOLAR_SPILL_ENABLED
    assert parsed.ev_policy.pre_free_enabled is DEFAULT_EV_PRE_FREE_ENABLED
    assert (
        parsed.ev_policy.smart_socket_power_switching
        is DEFAULT_EV_SMART_SOCKET_POWER_SWITCHING
    )
    assert (
        parsed.ev_policy.smart_socket_current_limit_a
        == DEFAULT_EV_SMART_SOCKET_CURRENT_LIMIT
    )
    assert parsed.house.load_includes_ev is DEFAULT_HOUSE_LOAD_INCLUDES_EV
    assert parsed.site.solar_configured is True
    assert parsed.site.phase_count == DEFAULT_SITE_PHASE_COUNT
    assert parsed.site.grid_current_entity is None
    assert parsed.battery.soc_entity is None
    assert parsed.ev_required_mapping_complete is False
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
    ("data", "configured", "enabled", "legacy_entity"),
    [
        ({}, False, False, None),
        (
            {CONF_EV_CHARGE_TO_FULL: "input_boolean.old_charge_to_full"},
            False,
            False,
            "input_boolean.old_charge_to_full",
        ),
        (
            {
                CONF_EV_CHARGE_TO_FULL_ENABLED: True,
                CONF_EV_CHARGE_TO_FULL: "input_boolean.old_charge_to_full",
            },
            True,
            True,
            "input_boolean.old_charge_to_full",
        ),
        ({CONF_EV_CHARGE_TO_FULL_ENABLED: ""}, True, False, None),
    ],
)
def test_charge_to_full_snapshot_preserves_owned_switch_precedence_inputs(
    data: dict[str, object],
    configured: bool,
    enabled: bool,
    legacy_entity: str | None,
) -> None:
    """Characterize the owned-key presence test and legacy helper mapping."""
    preference = RuntimeConfiguration.from_mapping(data).ev_preferences
    assert preference.charge_to_full_configured is configured
    assert preference.charge_to_full_enabled is enabled
    assert preference.legacy_charge_to_full_entity == legacy_entity


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, (False, False, "auto", None, None, 0.0, 230.0, 1.0)),
        (
            {
                CONF_EV_CONTROL_COMMISSIONED: True,
                CONF_EV_AT_HOME: "device_tracker.car",
                CONF_EV_CABLE_CONNECTED: "binary_sensor.car_cable",
                CONF_EV_PROTECTED_BASELINE_A: "1",
                CONF_EV_VOLTAGE: "230",
                CONF_EV_PHASE_COUNT: "3",
            },
            (
                True,
                True,
                "auto",
                "device_tracker.car",
                "binary_sensor.car_cable",
                1.0,
                230.0,
                3.0,
            ),
        ),
        (
            {
                CONF_CONFIGURE_EV: False,
                CONF_EV_CONTROL_COMMISSIONED: True,
                CONF_EV_PROTECTED_BASELINE_A: -1,
                CONF_EV_VOLTAGE: "invalid",
                CONF_EV_PHASE_COUNT: -3,
            },
            (False, True, "auto", None, None, 0.0, 230.0, 0.0),
        ),
        (
            {CONF_EV_LOCATION_MODE: None},
            (False, False, "None", None, None, 0.0, 230.0, 1.0),
        ),
    ],
)
def test_ev_connection_snapshot_preserves_keepalive_input_semantics(
    data: dict[str, object],
    expected: tuple[
        bool,
        bool,
        str,
        str | None,
        str | None,
        float,
        float,
        float,
    ],
) -> None:
    """Characterize legacy fallback, coercion and non-negative clamping."""
    ev = RuntimeConfiguration.from_mapping(data).ev_connection
    assert (
        ev.configured,
        ev.control_commissioned,
        ev.location_mode,
        ev.at_home_entity,
        ev.cable_connected_entity,
        ev.protected_baseline_a,
        ev.voltage_v,
        ev.phase_count,
    ) == expected


@pytest.mark.parametrize(
    ("data", "expected_direct", "expected_socket"),
    [
        ({}, None, None),
        (
            {
                CONF_EV_CURRENT_LIMIT: "number.car_current",
                CONF_EV_CHARGE_LIMIT: "number.car_limit",
                CONF_EV_CHARGE_SWITCH: "switch.car_charge",
                CONF_EV_SMART_SOCKET: "switch.car_socket",
            },
            ("number.car_current", "number.car_limit", "switch.car_charge"),
            "switch.car_socket",
        ),
        (
            {
                CONF_EV_CURRENT_LIMIT: 123,
                CONF_EV_CHARGE_LIMIT: 456,
                CONF_EV_CHARGE_SWITCH: 789,
                CONF_EV_SMART_SOCKET: 101,
            },
            ("123", "456", "789"),
            "101",
        ),
        (
            {
                CONF_EV_CURRENT_LIMIT: "number.car_current",
                CONF_EV_CHARGE_LIMIT: "",
                CONF_EV_CHARGE_SWITCH: "switch.car_charge",
                CONF_EV_SMART_SOCKET: False,
            },
            None,
            None,
        ),
    ],
)
def test_ev_actuator_snapshot_preserves_mapping_coercion(
    data: dict[str, object],
    expected_direct: tuple[str, str, str] | None,
    expected_socket: str | None,
) -> None:
    """Truthy mappings stringify; falsey or incomplete mappings fail closed."""
    actuators = RuntimeConfiguration.from_mapping(data).ev_actuators
    assert actuators.direct_entities == expected_direct
    assert actuators.smart_socket_entity == expected_socket


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, (None, None, None, None, None)),
        (
            {
                CONF_EV_SOC: "sensor.car_soc",
                CONF_EV_CHARGING_STATE: "sensor.car_charging",
                CONF_EV_ACTUAL_CURRENT: "sensor.car_current",
                CONF_EV_STORED_ENERGY: "sensor.car_energy",
                CONF_EV_LIFETIME_ENERGY: "sensor.car_lifetime",
            },
            (
                "sensor.car_soc",
                "sensor.car_charging",
                "sensor.car_current",
                "sensor.car_energy",
                "sensor.car_lifetime",
            ),
        ),
        (
            {
                CONF_EV_SOC: 1,
                CONF_EV_CHARGING_STATE: 2,
                CONF_EV_ACTUAL_CURRENT: 3,
                CONF_EV_STORED_ENERGY: 4,
                CONF_EV_LIFETIME_ENERGY: 5,
            },
            ("1", "2", "3", "4", "5"),
        ),
        (
            {
                CONF_EV_SOC: "",
                CONF_EV_CHARGING_STATE: False,
                CONF_EV_ACTUAL_CURRENT: None,
                CONF_EV_STORED_ENERGY: 0,
                CONF_EV_LIFETIME_ENERGY: "",
            },
            (None, None, None, None, None),
        ),
    ],
)
def test_ev_telemetry_snapshot_preserves_mapping_coercion(
    data: dict[str, object],
    expected: tuple[
        str | None,
        str | None,
        str | None,
        str | None,
        str | None,
    ],
) -> None:
    """Truthy telemetry mappings stringify; falsey mappings remain absent."""
    telemetry = RuntimeConfiguration.from_mapping(data).ev_telemetry
    assert (
        telemetry.soc_entity,
        telemetry.charging_state_entity,
        telemetry.actual_current_entity,
        telemetry.stored_energy_entity,
        telemetry.lifetime_energy_entity,
    ) == expected


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (
            {},
            (
                DEFAULT_EV_CHARGE_PATH,
                DEFAULT_EV_FREE_WINDOW_PRIORITY,
                DEFAULT_EV_ALLOWANCE_GUARD_ENABLED,
                DEFAULT_EV_SOLAR_SPILL_ENABLED,
                DEFAULT_EV_PRE_FREE_ENABLED,
                DEFAULT_EV_SMART_SOCKET_POWER_SWITCHING,
            ),
        ),
        (
            {
                CONF_EV_CHARGE_PATH: "smart_socket",
                CONF_EV_FREE_WINDOW_PRIORITY: "battery",
                CONF_EV_ALLOWANCE_GUARD_ENABLED: False,
                CONF_EV_SOLAR_SPILL_ENABLED: True,
                CONF_EV_PRE_FREE_ENABLED: True,
                CONF_EV_SMART_SOCKET_POWER_SWITCHING: True,
            },
            ("smart_socket", "battery", False, True, True, True),
        ),
        (
            {
                CONF_EV_CHARGE_PATH: None,
                CONF_EV_FREE_WINDOW_PRIORITY: "",
                CONF_EV_ALLOWANCE_GUARD_ENABLED: "false",
                CONF_EV_SOLAR_SPILL_ENABLED: 0,
                CONF_EV_PRE_FREE_ENABLED: None,
                CONF_EV_SMART_SOCKET_POWER_SWITCHING: 1,
            },
            (None, "", True, False, False, True),
        ),
    ],
)
def test_ev_policy_snapshot_preserves_enum_and_truthiness_semantics(
    data: dict[str, object],
    expected: tuple[object, object, bool, bool, bool, bool],
) -> None:
    """Preserve valid and malformed legacy values exactly at this boundary."""
    policy = RuntimeConfiguration.from_mapping(data).ev_policy
    assert (
        policy.charge_path,
        policy.free_window_priority,
        policy.allowance_guard_enabled,
        policy.solar_spill_enabled,
        policy.pre_free_enabled,
        policy.smart_socket_power_switching,
    ) == expected


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, (False, True, None)),
        (
            {
                CONF_HOUSE_LOAD_INCLUDES_EV: True,
                CONF_CONFIGURE_SOLAR: False,
                CONF_BATTERY_SOC: "sensor.battery_soc",
            },
            (True, False, "sensor.battery_soc"),
        ),
        (
            {
                CONF_HOUSE_LOAD_INCLUDES_EV: "false",
                CONF_CONFIGURE_SOLAR: None,
                CONF_BATTERY_SOC: 123,
            },
            (True, True, "123"),
        ),
        (
            {
                CONF_HOUSE_LOAD_INCLUDES_EV: 0,
                CONF_CONFIGURE_SOLAR: 0,
                CONF_BATTERY_SOC: "",
            },
            (False, True, None),
        ),
    ],
)
def test_active_site_snapshot_preserves_upgrade_fallbacks(
    data: dict[str, object],
    expected: tuple[bool, bool, str | None],
) -> None:
    """Characterize truthiness, exact-false solar and mapping coercion."""
    parsed = RuntimeConfiguration.from_mapping(data)
    assert (
        parsed.house.load_includes_ev,
        parsed.site.solar_configured,
        parsed.battery.soc_entity,
    ) == expected


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, (False, DEFAULT_EV_SMART_SOCKET_CURRENT_LIMIT, 1.0, None)),
        (
            {
                CONF_CONFIGURE_EV: False,
                CONF_EV_SMART_SOCKET_CURRENT_LIMIT: "16",
                CONF_SITE_PHASE_COUNT: "3",
                CONF_SITE_GRID_CURRENT: "sensor.grid_current",
            },
            (True, 16.0, 3.0, "sensor.grid_current"),
        ),
        (
            {
                CONF_CONFIGURE_EV: None,
                CONF_EV_SMART_SOCKET_CURRENT_LIMIT: "invalid",
                CONF_SITE_PHASE_COUNT: None,
                CONF_SITE_GRID_CURRENT: 123,
            },
            (False, None, None, "123"),
        ),
    ],
)
def test_ev_gate_snapshot_preserves_explicit_and_numeric_semantics(
    data: dict[str, object],
    expected: tuple[bool, float | None, float | None, str | None],
) -> None:
    """Characterize explicit disable and gate-only numeric parsing."""
    parsed = RuntimeConfiguration.from_mapping(data)
    assert (
        parsed.ev_connection.explicitly_disabled,
        parsed.ev_policy.smart_socket_current_limit_a,
        parsed.site.phase_count,
        parsed.site.grid_current_entity,
    ) == expected


@pytest.mark.parametrize(
    ("data", "expected_charge", "expected_discharge"),
    [
        ({}, DEFAULT_INVERTER_CHARGE_LIMIT_KW, DEFAULT_INVERTER_DISCHARGE_LIMIT_KW),
        (
            {
                CONF_INVERTER_CHARGE_LIMIT_KW: "12.5",
                CONF_INVERTER_DISCHARGE_LIMIT_KW: "15",
            },
            12.5,
            15.0,
        ),
        (
            {
                CONF_INVERTER_CHARGE_LIMIT_KW: -1,
                CONF_INVERTER_DISCHARGE_LIMIT_KW: -2,
            },
            0.0,
            0.0,
        ),
        (
            {
                CONF_INVERTER_CHARGE_LIMIT_KW: "invalid",
                CONF_INVERTER_DISCHARGE_LIMIT_KW: None,
            },
            DEFAULT_INVERTER_CHARGE_LIMIT_KW,
            DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
        ),
    ],
)
def test_active_inverter_limits_preserve_legacy_numeric_semantics(
    data: dict[str, object],
    expected_charge: float,
    expected_discharge: float,
) -> None:
    """Characterize parsing and active controller's non-negative clamp."""
    inverter = RuntimeConfiguration.from_mapping(data).inverter
    assert max(inverter.charge_limit_kw, 0.0) == expected_charge
    assert max(inverter.discharge_limit_kw, 0.0) == expected_discharge


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
