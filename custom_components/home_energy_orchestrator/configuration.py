"""Immutable, incrementally adopted runtime configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from math import isfinite
from typing import cast

from .const import (
    BATTERY_POSITIVE_CHARGE,
    BATTERY_POSITIVE_DISCHARGE,
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_CHARGE_POSITIVE,
    CONF_BATTERY_CHARGE_POWER,
    CONF_BATTERY_DISCHARGE_POWER,
    CONF_BATTERY_POWER_DIRECTION,
    CONF_BATTERY_SOC,
    CONF_BONUS_WINDOW_END,
    CONF_BONUS_WINDOW_START,
    CONF_CONFIGURE_EV,
    CONF_CONFIGURE_SOLAR,
    CONF_DAILY_IMPORT_ENTITY,
    CONF_EV_ACTUAL_CURRENT,
    CONF_EV_ALLOWANCE_GUARD_ENABLED,
    CONF_EV_AT_HOME,
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_EV_BEFORE_EXPORT_ENABLED,
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
    CONF_FREE_CHARGE_END,
    CONF_FREE_CHARGE_SCHEDULE_CONFIRMED,
    CONF_FREE_CHARGE_START,
    CONF_GLOBIRD_LATEST_DAILY_COST,
    CONF_GLOBIRD_ZEROHERO_STATUS,
    CONF_GRID_POWER_DIRECTION,
    CONF_HEATER_POWER,
    CONF_HOUSE_AWAY_CONFIRMATION_HOURS,
    CONF_HOUSE_AWAY_FALLBACK,
    CONF_HOUSE_LEARNING_FALLBACK,
    CONF_HOUSE_LOAD_INCLUDES_EV,
    CONF_HOUSE_OCCUPANCY_MODE,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_OFFPEAK_EXPORT_RATE,
    CONF_REHEARSAL_MODE,
    CONF_SIGN_CONVENTIONS_VERIFIED,
    CONF_SITE_GRID_CURRENT,
    CONF_SITE_GRID_CURRENT_DIRECTION,
    CONF_SITE_PHASE_COUNT,
    CONF_SOLAR_POWER_DIRECTION,
    CONF_SUPER_EXPORT_RATE,
    CONF_TELEMETRY_MAX_AGE_SECONDS,
    CONF_ZERO_IMPORT_THRESHOLD_KW,
    DEFAULT_AUTOMATIC_CHARGE_ENABLED,
    DEFAULT_AUTOMATIC_CONTROL_ENABLED,
    DEFAULT_AUTOMATIC_EXPORT_ENABLED,
    DEFAULT_BATTERY_CHARGE_POSITIVE,
    DEFAULT_BONUS_WINDOW_END,
    DEFAULT_BONUS_WINDOW_START,
    DEFAULT_EV_ALLOWANCE_GUARD_ENABLED,
    DEFAULT_EV_AUTOMATIC_CONTROL_ENABLED,
    DEFAULT_EV_BEFORE_EXPORT_ENABLED,
    DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
    DEFAULT_EV_CHARGE_PATH,
    DEFAULT_EV_CHARGE_TO_FULL_ENABLED,
    DEFAULT_EV_CONTROL_COMMISSIONED,
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
    DEFAULT_HOUSE_AWAY_CONFIRMATION_HOURS,
    DEFAULT_HOUSE_AWAY_FALLBACK_KWH,
    DEFAULT_HOUSE_LEARNING_FALLBACK_KWH,
    DEFAULT_HOUSE_LOAD_INCLUDES_EV,
    DEFAULT_HOUSE_OCCUPANCY_MODE,
    DEFAULT_INVERTER_CHARGE_LIMIT_KW,
    DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
    DEFAULT_OFFPEAK_EXPORT_RATE,
    DEFAULT_REHEARSAL_MODE,
    DEFAULT_SIGN_CONVENTIONS_VERIFIED,
    DEFAULT_SITE_GRID_CURRENT_DIRECTION,
    DEFAULT_SITE_PHASE_COUNT,
    DEFAULT_SOLAR_POWER_DIRECTION,
    DEFAULT_SUPER_EXPORT_RATE,
    DEFAULT_TELEMETRY_MAX_AGE_SECONDS,
    DEFAULT_ZERO_IMPORT_THRESHOLD_KW,
    HOUSE_OCCUPANCY_MODES,
)


def _number(data: Mapping[str, object], key: str, default: float) -> float:
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError):
        return default


def _optional_number(
    data: Mapping[str, object], key: str, default: float
) -> float | None:
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError):
        return None


def _optional_time(
    data: Mapping[str, object], key: str, default: str | None = None
) -> time | None:
    if key not in data:
        return time.fromisoformat(default) if default is not None else None
    value = data[key]
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class AutomationSettings:
    """Operator-owned automation requests and final no-write interlock."""

    master_enabled: bool
    battery_charge_enabled: bool
    battery_export_enabled: bool
    ev_control_enabled: bool
    safety_lock: bool
    control_owner: str
    free_charge_schedule_confirmed: bool


@dataclass(frozen=True, slots=True)
class EvPreferenceSettings:
    """Operator-owned EV/export priority and bounded paid-grid request."""

    before_export_enabled: bool
    before_export_soc_target: float
    charge_to_full_configured: bool
    charge_to_full_enabled: bool
    legacy_charge_to_full_entity: str | None


@dataclass(frozen=True, slots=True)
class EvConnectionSettings:
    """EV commissioning and electrical inputs used by battery protection."""

    configured: bool
    explicitly_disabled: bool
    control_commissioned: bool
    location_mode: str
    at_home_entity: str | None
    cable_connected_entity: str | None
    protected_baseline_a: float
    voltage_v: float
    phase_count: float
    phase_count_valid: bool


@dataclass(frozen=True, slots=True)
class EvActuatorSettings:
    """Explicit Home Assistant entities used for EV command feedback/writes."""

    current_limit_entity: str | None
    charge_limit_entity: str | None
    charge_switch_entity: str | None
    smart_socket_entity: str | None

    @property
    def direct_entities(self) -> tuple[str, str, str] | None:
        """Return the complete direct-EVSE mapping, or fail closed."""
        if (
            self.current_limit_entity is None
            or self.charge_limit_entity is None
            or self.charge_switch_entity is None
        ):
            return None
        return (
            self.current_limit_entity,
            self.charge_limit_entity,
            self.charge_switch_entity,
        )


@dataclass(frozen=True, slots=True)
class EvTelemetrySettings:
    """Explicit Home Assistant entities used to observe the vehicle."""

    soc_entity: str | None
    charging_state_entity: str | None
    actual_current_entity: str | None
    stored_energy_entity: str | None
    lifetime_energy_entity: str | None


@dataclass(frozen=True, slots=True)
class EvPolicySettings:
    """Existing EV path and optional-policy selections."""

    charge_path: str
    free_window_priority: str
    allowance_guard_enabled: bool
    solar_spill_enabled: bool
    pre_free_enabled: bool
    smart_socket_power_switching: bool
    smart_socket_current_limit_a: float | None


@dataclass(frozen=True, slots=True)
class HouseSettings:
    """Operator-owned house-energy occupancy selection."""

    occupancy_mode: str
    occupancy_mode_input: str
    load_includes_ev: bool
    away_confirmation_hours: float | None
    learning_fallback_kwh: float | None
    away_fallback_kwh: float | None
    heater_power_entity: str | None


@dataclass(frozen=True, slots=True)
class WindowSettings:
    """Explicitly configured windows used by persistent samplers."""

    free_charge_start: time | None
    free_charge_end: time | None
    bonus_start: time | None
    bonus_end: time | None


@dataclass(frozen=True, slots=True)
class AccountingSettings:
    """Optional meter and retailer entities used by read-only accounting."""

    daily_import_entity: str | None
    retailer_daily_cost_entity: str | None
    retailer_zerohero_status_entity: str | None


@dataclass(frozen=True, slots=True)
class SiteSettings:
    """Site capability selections with upgrade-compatible defaults."""

    solar_configured: bool
    phase_count: float | None
    grid_current_entity: str | None


@dataclass(frozen=True, slots=True)
class BatterySettings:
    """Explicit Home Assistant entities used to observe the battery."""

    soc_entity: str | None
    capacity_entity: str | None
    charge_power_entity: str | None
    discharge_power_entity: str | None


@dataclass(frozen=True, slots=True)
class TelemetrySettings:
    """Shared telemetry freshness policy after legacy-compatible parsing."""

    max_age_seconds: float


@dataclass(frozen=True, slots=True)
class ElectricalSettings:
    """Commissioned canonical sign directions and explicit verification."""

    verified: bool
    grid_power_positive_direction: str
    battery_power_positive_direction: str
    solar_generation_direction: str
    site_grid_current_positive_direction: str


@dataclass(frozen=True, slots=True)
class TariffSettings:
    """Tariff values currently projected by observer entities."""

    peak_export_rate_per_kwh: float
    offpeak_export_rate_per_kwh: float
    additional_export_rate_per_kwh: float
    zero_import_threshold_kwh_per_hour: float


@dataclass(frozen=True, slots=True)
class InverterSettings:
    """Inverter limits currently projected by commissioning entities."""

    charge_limit_kw: float
    discharge_limit_kw: float
    work_mode_entity: str | None
    force_charge_power_entity: str | None
    force_discharge_power_entity: str | None

    @property
    def actuator_mapping_complete(self) -> bool:
        """Return whether every FoxESS command/feedback entity is mapped."""
        return all(
            (
                self.work_mode_entity,
                self.force_charge_power_entity,
                self.force_discharge_power_entity,
            )
        )


@dataclass(frozen=True, slots=True)
class RuntimeConfiguration:
    """Typed runtime snapshot adopted one domain at a time."""

    automation: AutomationSettings
    ev_preferences: EvPreferenceSettings
    ev_connection: EvConnectionSettings
    ev_actuators: EvActuatorSettings
    ev_telemetry: EvTelemetrySettings
    ev_policy: EvPolicySettings
    house: HouseSettings
    windows: WindowSettings
    accounting: AccountingSettings
    site: SiteSettings
    battery: BatterySettings
    telemetry: TelemetrySettings
    electrical: ElectricalSettings
    tariff: TariffSettings
    inverter: InverterSettings

    @property
    def ev_required_mapping_complete(self) -> bool:
        """Return whether every legacy-required EV observation/control is mapped."""
        return all(
            (
                self.ev_telemetry.soc_entity,
                self.ev_connection.at_home_entity,
                self.ev_connection.cable_connected_entity,
                self.ev_telemetry.charging_state_entity,
                self.ev_telemetry.actual_current_entity,
                self.ev_telemetry.stored_energy_entity,
                *(
                    self.ev_actuators.direct_entities
                    if self.ev_actuators.direct_entities is not None
                    else (None,)
                ),
            )
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> RuntimeConfiguration:
        """Parse currently adopted fields with their established fallbacks."""
        occupancy = str(
            data.get(CONF_HOUSE_OCCUPANCY_MODE, DEFAULT_HOUSE_OCCUPANCY_MODE)
        ).lower()
        if occupancy not in HOUSE_OCCUPANCY_MODES:
            occupancy = DEFAULT_HOUSE_OCCUPANCY_MODE
        work_mode_entity = data.get(CONF_FOXESS_WORK_MODE)
        force_charge_power_entity = data.get(CONF_FOXESS_FORCE_CHARGE_POWER)
        force_discharge_power_entity = data.get(CONF_FOXESS_FORCE_DISCHARGE_POWER)
        ev_at_home_entity = data.get(CONF_EV_AT_HOME)
        ev_cable_connected_entity = data.get(CONF_EV_CABLE_CONNECTED)
        ev_current_limit_entity = data.get(CONF_EV_CURRENT_LIMIT)
        ev_charge_limit_entity = data.get(CONF_EV_CHARGE_LIMIT)
        ev_charge_switch_entity = data.get(CONF_EV_CHARGE_SWITCH)
        ev_smart_socket_entity = data.get(CONF_EV_SMART_SOCKET)
        ev_soc_entity = data.get(CONF_EV_SOC)
        ev_charging_state_entity = data.get(CONF_EV_CHARGING_STATE)
        ev_actual_current_entity = data.get(CONF_EV_ACTUAL_CURRENT)
        ev_stored_energy_entity = data.get(CONF_EV_STORED_ENERGY)
        ev_lifetime_energy_entity = data.get(CONF_EV_LIFETIME_ENERGY)
        battery_soc_entity = data.get(CONF_BATTERY_SOC)
        battery_capacity_entity = data.get(CONF_BATTERY_CAPACITY_ENTITY)
        battery_charge_power_entity = data.get(CONF_BATTERY_CHARGE_POWER)
        battery_discharge_power_entity = data.get(CONF_BATTERY_DISCHARGE_POWER)
        daily_import_entity = data.get(CONF_DAILY_IMPORT_ENTITY)
        retailer_daily_cost_entity = data.get(CONF_GLOBIRD_LATEST_DAILY_COST)
        retailer_zerohero_status_entity = data.get(CONF_GLOBIRD_ZEROHERO_STATUS)
        site_grid_current_entity = data.get(CONF_SITE_GRID_CURRENT)
        heater_power_entity = data.get(CONF_HEATER_POWER)
        ev_phase_count = _optional_number(
            data,
            CONF_EV_PHASE_COUNT,
            DEFAULT_EV_PHASE_COUNT,
        )
        legacy_charge_to_full_entity = data.get(CONF_EV_CHARGE_TO_FULL)
        ev_control_commissioned = bool(
            data.get(
                CONF_EV_CONTROL_COMMISSIONED,
                DEFAULT_EV_CONTROL_COMMISSIONED,
            )
        )
        legacy_battery_direction = (
            BATTERY_POSITIVE_CHARGE
            if bool(
                data.get(
                    CONF_BATTERY_CHARGE_POSITIVE,
                    DEFAULT_BATTERY_CHARGE_POSITIVE,
                )
            )
            else BATTERY_POSITIVE_DISCHARGE
        )
        battery_direction = data.get(
            CONF_BATTERY_POWER_DIRECTION,
            legacy_battery_direction,
        )
        max_telemetry_age = _number(
            data,
            CONF_TELEMETRY_MAX_AGE_SECONDS,
            DEFAULT_TELEMETRY_MAX_AGE_SECONDS,
        )
        if not isfinite(max_telemetry_age) or max_telemetry_age <= 0:
            max_telemetry_age = DEFAULT_TELEMETRY_MAX_AGE_SECONDS
        return cls(
            automation=AutomationSettings(
                master_enabled=bool(
                    data.get(
                        CONF_AUTOMATIC_CONTROL_ENABLED,
                        DEFAULT_AUTOMATIC_CONTROL_ENABLED,
                    )
                ),
                battery_charge_enabled=bool(
                    data.get(
                        CONF_AUTOMATIC_CHARGE_ENABLED,
                        DEFAULT_AUTOMATIC_CHARGE_ENABLED,
                    )
                ),
                battery_export_enabled=bool(
                    data.get(
                        CONF_AUTOMATIC_EXPORT_ENABLED,
                        DEFAULT_AUTOMATIC_EXPORT_ENABLED,
                    )
                ),
                ev_control_enabled=bool(
                    data.get(
                        CONF_EV_AUTOMATIC_CONTROL_ENABLED,
                        DEFAULT_EV_AUTOMATIC_CONTROL_ENABLED,
                    )
                ),
                safety_lock=bool(
                    data.get(CONF_REHEARSAL_MODE, DEFAULT_REHEARSAL_MODE)
                ),
                control_owner=cast(
                    str,
                    data.get(
                        CONF_FOXESS_CONTROL_OWNER,
                        DEFAULT_FOXESS_CONTROL_OWNER,
                    ),
                ),
                free_charge_schedule_confirmed=bool(
                    data.get(CONF_FREE_CHARGE_SCHEDULE_CONFIRMED, False)
                ),
            ),
            ev_preferences=EvPreferenceSettings(
                before_export_enabled=bool(
                    data.get(
                        CONF_EV_BEFORE_EXPORT_ENABLED,
                        DEFAULT_EV_BEFORE_EXPORT_ENABLED,
                    )
                ),
                before_export_soc_target=_number(
                    data,
                    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
                    DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
                ),
                charge_to_full_configured=(
                    CONF_EV_CHARGE_TO_FULL_ENABLED in data
                ),
                charge_to_full_enabled=bool(
                    data.get(
                        CONF_EV_CHARGE_TO_FULL_ENABLED,
                        DEFAULT_EV_CHARGE_TO_FULL_ENABLED,
                    )
                ),
                legacy_charge_to_full_entity=(
                    str(legacy_charge_to_full_entity)
                    if legacy_charge_to_full_entity
                    else None
                ),
            ),
            ev_connection=EvConnectionSettings(
                configured=bool(
                    data.get(
                        CONF_CONFIGURE_EV,
                        data.get(
                            CONF_EV_CONTROL_COMMISSIONED,
                            DEFAULT_EV_CONTROL_COMMISSIONED,
                        ),
                    )
                ),
                explicitly_disabled=data.get(CONF_CONFIGURE_EV) is False,
                control_commissioned=ev_control_commissioned,
                location_mode=str(
                    data.get(CONF_EV_LOCATION_MODE, DEFAULT_EV_LOCATION_MODE)
                ),
                at_home_entity=(
                    str(ev_at_home_entity) if ev_at_home_entity else None
                ),
                cable_connected_entity=(
                    str(ev_cable_connected_entity)
                    if ev_cable_connected_entity
                    else None
                ),
                protected_baseline_a=max(
                    _number(
                        data,
                        CONF_EV_PROTECTED_BASELINE_A,
                        DEFAULT_EV_PROTECTED_BASELINE_A,
                    ),
                    0.0,
                ),
                voltage_v=max(
                    _number(data, CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE),
                    0.0,
                ),
                phase_count=max(
                    _number(data, CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT),
                    0.0,
                ),
                phase_count_valid=ev_phase_count is not None,
            ),
            ev_actuators=EvActuatorSettings(
                current_limit_entity=(
                    str(ev_current_limit_entity) if ev_current_limit_entity else None
                ),
                charge_limit_entity=(
                    str(ev_charge_limit_entity) if ev_charge_limit_entity else None
                ),
                charge_switch_entity=(
                    str(ev_charge_switch_entity) if ev_charge_switch_entity else None
                ),
                smart_socket_entity=(
                    str(ev_smart_socket_entity) if ev_smart_socket_entity else None
                ),
            ),
            ev_telemetry=EvTelemetrySettings(
                soc_entity=str(ev_soc_entity) if ev_soc_entity else None,
                charging_state_entity=(
                    str(ev_charging_state_entity)
                    if ev_charging_state_entity
                    else None
                ),
                actual_current_entity=(
                    str(ev_actual_current_entity)
                    if ev_actual_current_entity
                    else None
                ),
                stored_energy_entity=(
                    str(ev_stored_energy_entity) if ev_stored_energy_entity else None
                ),
                lifetime_energy_entity=(
                    str(ev_lifetime_energy_entity)
                    if ev_lifetime_energy_entity
                    else None
                ),
            ),
            ev_policy=EvPolicySettings(
                charge_path=cast(
                    str,
                    data.get(CONF_EV_CHARGE_PATH, DEFAULT_EV_CHARGE_PATH),
                ),
                free_window_priority=cast(
                    str,
                    data.get(
                        CONF_EV_FREE_WINDOW_PRIORITY,
                        DEFAULT_EV_FREE_WINDOW_PRIORITY,
                    ),
                ),
                allowance_guard_enabled=bool(
                    data.get(
                        CONF_EV_ALLOWANCE_GUARD_ENABLED,
                        DEFAULT_EV_ALLOWANCE_GUARD_ENABLED,
                    )
                ),
                solar_spill_enabled=bool(
                    data.get(
                        CONF_EV_SOLAR_SPILL_ENABLED,
                        DEFAULT_EV_SOLAR_SPILL_ENABLED,
                    )
                ),
                pre_free_enabled=bool(
                    data.get(
                        CONF_EV_PRE_FREE_ENABLED,
                        DEFAULT_EV_PRE_FREE_ENABLED,
                    )
                ),
                smart_socket_power_switching=bool(
                    data.get(
                        CONF_EV_SMART_SOCKET_POWER_SWITCHING,
                        DEFAULT_EV_SMART_SOCKET_POWER_SWITCHING,
                    )
                ),
                smart_socket_current_limit_a=_optional_number(
                    data,
                    CONF_EV_SMART_SOCKET_CURRENT_LIMIT,
                    DEFAULT_EV_SMART_SOCKET_CURRENT_LIMIT,
                ),
            ),
            house=HouseSettings(
                occupancy_mode=occupancy,
                occupancy_mode_input=str(
                    data.get(
                        CONF_HOUSE_OCCUPANCY_MODE,
                        DEFAULT_HOUSE_OCCUPANCY_MODE,
                    )
                ),
                load_includes_ev=bool(
                    data.get(
                        CONF_HOUSE_LOAD_INCLUDES_EV,
                        DEFAULT_HOUSE_LOAD_INCLUDES_EV,
                    )
                ),
                away_confirmation_hours=_optional_number(
                    data,
                    CONF_HOUSE_AWAY_CONFIRMATION_HOURS,
                    DEFAULT_HOUSE_AWAY_CONFIRMATION_HOURS,
                ),
                learning_fallback_kwh=_optional_number(
                    data,
                    CONF_HOUSE_LEARNING_FALLBACK,
                    DEFAULT_HOUSE_LEARNING_FALLBACK_KWH,
                ),
                away_fallback_kwh=_optional_number(
                    data,
                    CONF_HOUSE_AWAY_FALLBACK,
                    DEFAULT_HOUSE_AWAY_FALLBACK_KWH,
                ),
                heater_power_entity=(
                    str(heater_power_entity) if heater_power_entity else None
                ),
            ),
            windows=WindowSettings(
                free_charge_start=_optional_time(data, CONF_FREE_CHARGE_START),
                free_charge_end=_optional_time(data, CONF_FREE_CHARGE_END),
                bonus_start=_optional_time(
                    data,
                    CONF_BONUS_WINDOW_START,
                    DEFAULT_BONUS_WINDOW_START,
                ),
                bonus_end=_optional_time(
                    data,
                    CONF_BONUS_WINDOW_END,
                    DEFAULT_BONUS_WINDOW_END,
                ),
            ),
            accounting=AccountingSettings(
                daily_import_entity=(
                    str(daily_import_entity) if daily_import_entity else None
                ),
                retailer_daily_cost_entity=(
                    str(retailer_daily_cost_entity)
                    if retailer_daily_cost_entity
                    else None
                ),
                retailer_zerohero_status_entity=(
                    str(retailer_zerohero_status_entity)
                    if retailer_zerohero_status_entity
                    else None
                ),
            ),
            site=SiteSettings(
                solar_configured=data.get(CONF_CONFIGURE_SOLAR) is not False,
                phase_count=_optional_number(
                    data,
                    CONF_SITE_PHASE_COUNT,
                    DEFAULT_SITE_PHASE_COUNT,
                ),
                grid_current_entity=(
                    str(site_grid_current_entity) if site_grid_current_entity else None
                ),
            ),
            battery=BatterySettings(
                soc_entity=str(battery_soc_entity) if battery_soc_entity else None,
                capacity_entity=(
                    str(battery_capacity_entity) if battery_capacity_entity else None
                ),
                charge_power_entity=(
                    battery_charge_power_entity
                    if isinstance(battery_charge_power_entity, str)
                    and battery_charge_power_entity
                    else None
                ),
                discharge_power_entity=(
                    battery_discharge_power_entity
                    if isinstance(battery_discharge_power_entity, str)
                    and battery_discharge_power_entity
                    else None
                ),
            ),
            telemetry=TelemetrySettings(
                max_age_seconds=max_telemetry_age,
            ),
            electrical=ElectricalSettings(
                verified=bool(
                    data.get(
                        CONF_SIGN_CONVENTIONS_VERIFIED,
                        DEFAULT_SIGN_CONVENTIONS_VERIFIED,
                    )
                ),
                grid_power_positive_direction=cast(
                    str,
                    data.get(
                        CONF_GRID_POWER_DIRECTION,
                        DEFAULT_GRID_POWER_DIRECTION,
                    ),
                ),
                battery_power_positive_direction=(
                    str(battery_direction)
                    if battery_direction
                    else legacy_battery_direction
                ),
                solar_generation_direction=cast(
                    str,
                    data.get(
                        CONF_SOLAR_POWER_DIRECTION,
                        DEFAULT_SOLAR_POWER_DIRECTION,
                    ),
                ),
                site_grid_current_positive_direction=cast(
                    str,
                    data.get(
                        CONF_SITE_GRID_CURRENT_DIRECTION,
                        DEFAULT_SITE_GRID_CURRENT_DIRECTION,
                    ),
                ),
            ),
            tariff=TariffSettings(
                peak_export_rate_per_kwh=_number(
                    data,
                    CONF_EXPORT_RATE,
                    DEFAULT_EXPORT_RATE,
                ),
                offpeak_export_rate_per_kwh=_number(
                    data,
                    CONF_OFFPEAK_EXPORT_RATE,
                    DEFAULT_OFFPEAK_EXPORT_RATE,
                ),
                additional_export_rate_per_kwh=_number(
                    data,
                    CONF_SUPER_EXPORT_RATE,
                    DEFAULT_SUPER_EXPORT_RATE,
                ),
                zero_import_threshold_kwh_per_hour=_number(
                    data,
                    CONF_ZERO_IMPORT_THRESHOLD_KW,
                    DEFAULT_ZERO_IMPORT_THRESHOLD_KW,
                ),
            ),
            inverter=InverterSettings(
                charge_limit_kw=_number(
                    data,
                    CONF_INVERTER_CHARGE_LIMIT_KW,
                    DEFAULT_INVERTER_CHARGE_LIMIT_KW,
                ),
                discharge_limit_kw=_number(
                    data,
                    CONF_INVERTER_DISCHARGE_LIMIT_KW,
                    DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
                ),
                work_mode_entity=(str(work_mode_entity) if work_mode_entity else None),
                force_charge_power_entity=(
                    str(force_charge_power_entity)
                    if force_charge_power_entity
                    else None
                ),
                force_discharge_power_entity=(
                    str(force_discharge_power_entity)
                    if force_discharge_power_entity
                    else None
                ),
            ),
        )
