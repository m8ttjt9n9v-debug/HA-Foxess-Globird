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
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_EV_BEFORE_EXPORT_ENABLED,
    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
    CONF_EV_CHARGE_TO_FULL_ENABLED,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_GRID_POWER_DIRECTION,
    CONF_HOUSE_OCCUPANCY_MODE,
    CONF_REHEARSAL_MODE,
    CONF_SIGN_CONVENTIONS_VERIFIED,
    CONF_SITE_GRID_CURRENT_DIRECTION,
    CONF_SOLAR_POWER_DIRECTION,
    DEFAULT_AUTOMATIC_CHARGE_ENABLED,
    DEFAULT_AUTOMATIC_CONTROL_ENABLED,
    DEFAULT_AUTOMATIC_EXPORT_ENABLED,
    DEFAULT_BATTERY_POWER_DIRECTION,
    DEFAULT_EV_AUTOMATIC_CONTROL_ENABLED,
    DEFAULT_EV_BEFORE_EXPORT_ENABLED,
    DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
    DEFAULT_EV_CHARGE_TO_FULL_ENABLED,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DEFAULT_GRID_POWER_DIRECTION,
    DEFAULT_HOUSE_OCCUPANCY_MODE,
    DEFAULT_REHEARSAL_MODE,
    DEFAULT_SIGN_CONVENTIONS_VERIFIED,
    DEFAULT_SITE_GRID_CURRENT_DIRECTION,
    DEFAULT_SOLAR_POWER_DIRECTION,
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


@dataclass(frozen=True, slots=True)
class EvPreferenceSettings:
    """Operator-owned EV/export priority and bounded paid-grid request."""

    before_export_enabled: bool
    before_export_soc_target: float
    charge_to_full_enabled: bool


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
class RuntimeConfiguration:
    """Typed runtime snapshot adopted one domain at a time."""

    automation: AutomationSettings
    ev_preferences: EvPreferenceSettings
    house: HouseSettings
    electrical: ElectricalSettings

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> RuntimeConfiguration:
        """Parse currently adopted fields with their established fallbacks."""
        occupancy = str(
            data.get(CONF_HOUSE_OCCUPANCY_MODE, DEFAULT_HOUSE_OCCUPANCY_MODE)
        ).lower()
        if occupancy not in HOUSE_OCCUPANCY_MODES:
            occupancy = DEFAULT_HOUSE_OCCUPANCY_MODE
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
        )
