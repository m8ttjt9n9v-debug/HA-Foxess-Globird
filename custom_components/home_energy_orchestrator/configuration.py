"""Immutable, incrementally adopted runtime configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from .const import (
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_BATTERY_POWER_DIRECTION,
    CONF_CONFIGURE_EV,
    CONF_EV_AT_HOME,
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_EV_BEFORE_EXPORT_ENABLED,
    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
    CONF_EV_CABLE_CONNECTED,
    CONF_EV_CHARGE_TO_FULL_ENABLED,
    CONF_EV_CONTROL_COMMISSIONED,
    CONF_EV_PHASE_COUNT,
    CONF_EV_PROTECTED_BASELINE_A,
    CONF_EV_VOLTAGE,
    CONF_EXPORT_RATE,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_FREE_CHARGE_SCHEDULE_CONFIRMED,
    CONF_GRID_POWER_DIRECTION,
    CONF_HOUSE_OCCUPANCY_MODE,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_OFFPEAK_EXPORT_RATE,
    CONF_REHEARSAL_MODE,
    CONF_SIGN_CONVENTIONS_VERIFIED,
    CONF_SITE_GRID_CURRENT_DIRECTION,
    CONF_SOLAR_POWER_DIRECTION,
    CONF_SUPER_EXPORT_RATE,
    CONF_ZERO_IMPORT_THRESHOLD_KW,
    DEFAULT_AUTOMATIC_CHARGE_ENABLED,
    DEFAULT_AUTOMATIC_CONTROL_ENABLED,
    DEFAULT_AUTOMATIC_EXPORT_ENABLED,
    DEFAULT_BATTERY_POWER_DIRECTION,
    DEFAULT_EV_AUTOMATIC_CONTROL_ENABLED,
    DEFAULT_EV_BEFORE_EXPORT_ENABLED,
    DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
    DEFAULT_EV_CHARGE_TO_FULL_ENABLED,
    DEFAULT_EV_CONTROL_COMMISSIONED,
    DEFAULT_EV_PHASE_COUNT,
    DEFAULT_EV_PROTECTED_BASELINE_A,
    DEFAULT_EV_VOLTAGE,
    DEFAULT_EXPORT_RATE,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DEFAULT_GRID_POWER_DIRECTION,
    DEFAULT_HOUSE_OCCUPANCY_MODE,
    DEFAULT_INVERTER_CHARGE_LIMIT_KW,
    DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
    DEFAULT_OFFPEAK_EXPORT_RATE,
    DEFAULT_REHEARSAL_MODE,
    DEFAULT_SIGN_CONVENTIONS_VERIFIED,
    DEFAULT_SITE_GRID_CURRENT_DIRECTION,
    DEFAULT_SOLAR_POWER_DIRECTION,
    DEFAULT_SUPER_EXPORT_RATE,
    DEFAULT_ZERO_IMPORT_THRESHOLD_KW,
    HOUSE_OCCUPANCY_MODES,
)


def _number(data: Mapping[str, object], key: str, default: float) -> float:
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError):
        return default


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
    charge_to_full_enabled: bool


@dataclass(frozen=True, slots=True)
class EvConnectionSettings:
    """EV commissioning and electrical inputs used by battery protection."""

    configured: bool
    control_commissioned: bool
    at_home_entity: str | None
    cable_connected_entity: str | None
    protected_baseline_a: float
    voltage_v: float
    phase_count: float


@dataclass(frozen=True, slots=True)
class HouseSettings:
    """Operator-owned house-energy occupancy selection."""

    occupancy_mode: str


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
    house: HouseSettings
    electrical: ElectricalSettings
    tariff: TariffSettings
    inverter: InverterSettings

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
        ev_control_commissioned = bool(
            data.get(
                CONF_EV_CONTROL_COMMISSIONED,
                DEFAULT_EV_CONTROL_COMMISSIONED,
            )
        )
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
                charge_to_full_enabled=bool(
                    data.get(
                        CONF_EV_CHARGE_TO_FULL_ENABLED,
                        DEFAULT_EV_CHARGE_TO_FULL_ENABLED,
                    )
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
                control_commissioned=ev_control_commissioned,
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
            ),
            house=HouseSettings(occupancy_mode=occupancy),
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
                battery_power_positive_direction=cast(
                    str,
                    data.get(
                        CONF_BATTERY_POWER_DIRECTION,
                        DEFAULT_BATTERY_POWER_DIRECTION,
                    ),
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
