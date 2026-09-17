"""Declarative entity descriptions shared by the HEO platforms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower
from homeassistant.helpers.entity import EntityDescription

EntityPlatform = Literal["binary_sensor", "button", "number", "select", "switch"]


@dataclass(frozen=True, slots=True)
class EntitySpec:
    """Bind one stable public entity key to its platform description."""

    platform: EntityPlatform
    description: EntityDescription


BUTTON_DESCRIPTIONS = (
    ButtonEntityDescription(
        key="test_force_charge",
        name="Start Charge Diagnostic",
        icon="mdi:battery-arrow-up-outline",
    ),
    ButtonEntityDescription(
        key="test_force_discharge",
        name="Start Discharge Diagnostic",
        icon="mdi:battery-arrow-down-outline",
    ),
    ButtonEntityDescription(
        key="test_stop",
        name="Stop Diagnostic and Restore Self Use",
        icon="mdi:stop-circle-outline",
    ),
)

NUMBER_DESCRIPTIONS = (
    NumberEntityDescription(
        key="test_charge_power",
        name="Test Charge Power",
        icon="mdi:battery-arrow-up",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=0.1,
        native_max_value=0.1,
        native_step=0.1,
    ),
    NumberEntityDescription(
        key="test_discharge_power",
        name="Test Discharge Power",
        icon="mdi:battery-arrow-down",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=0.1,
        native_max_value=0.1,
        native_step=0.1,
    ),
    NumberEntityDescription(
        key="test_duration",
        name="Test Duration",
        icon="mdi:timer-outline",
        native_unit_of_measurement="min",
        native_min_value=1.0,
        native_max_value=120.0,
        native_step=1.0,
    ),
)

EV_BEFORE_EXPORT_TARGET_DESCRIPTION = NumberEntityDescription(
    key="ev_before_export_soc_target",
    name="EV Before Export SoC Target",
    icon="mdi:battery-charging-40",
    native_unit_of_measurement=PERCENTAGE,
    native_min_value=0.0,
    native_max_value=100.0,
    native_step=1.0,
    entity_category=EntityCategory.CONFIG,
)

HOUSE_OCCUPANCY_DESCRIPTION = SelectEntityDescription(
    key="house_occupancy_mode",
    name="House Energy Occupancy Mode",
    icon="mdi:home-account",
    entity_category=EntityCategory.CONFIG,
)

SAFETY_DESCRIPTION = SwitchEntityDescription(
    key="safety_lock",
    name="Safety Lock",
    icon="mdi:lock",
    entity_category=EntityCategory.CONFIG,
)
EXPORT_DESCRIPTION = SwitchEntityDescription(
    key="automatic_export",
    name="Automatic ZEROHERO Export",
    icon="mdi:transmission-tower-export",
    entity_category=EntityCategory.CONFIG,
)
CHARGE_DESCRIPTION = SwitchEntityDescription(
    key="automatic_charge",
    name="Automatic Battery Free Charge",
    icon="mdi:battery-arrow-up",
    entity_category=EntityCategory.CONFIG,
)
EV_DESCRIPTION = SwitchEntityDescription(
    key="automatic_ev_control",
    name="Automatic EV Control",
    icon="mdi:ev-station",
    entity_category=EntityCategory.CONFIG,
)
EV_BEFORE_EXPORT_DESCRIPTION = SwitchEntityDescription(
    key="ev_before_export",
    name="Prioritise EV Before Export",
    icon="mdi:car-electric-outline",
    entity_category=EntityCategory.CONFIG,
)
CHARGE_TO_FULL_DESCRIPTION = SwitchEntityDescription(
    key="ev_charge_to_full",
    name="EV Charge to Full",
    icon="mdi:battery-arrow-up",
    entity_category=EntityCategory.CONFIG,
)

SIGN_CONVENTIONS_DESCRIPTION = BinarySensorEntityDescription(
    key="sign_conventions_verified",
    name="Sign Conventions Verified",
    icon="mdi:swap-horizontal-bold",
    entity_category=EntityCategory.DIAGNOSTIC,
)

ENTITY_SPECS = (
    *(EntitySpec("button", description) for description in BUTTON_DESCRIPTIONS),
    *(EntitySpec("number", description) for description in NUMBER_DESCRIPTIONS),
    EntitySpec("number", EV_BEFORE_EXPORT_TARGET_DESCRIPTION),
    EntitySpec("select", HOUSE_OCCUPANCY_DESCRIPTION),
    EntitySpec("switch", SAFETY_DESCRIPTION),
    EntitySpec("switch", CHARGE_DESCRIPTION),
    EntitySpec("switch", EXPORT_DESCRIPTION),
    EntitySpec("switch", EV_DESCRIPTION),
    EntitySpec("switch", EV_BEFORE_EXPORT_DESCRIPTION),
    EntitySpec("switch", CHARGE_TO_FULL_DESCRIPTION),
    EntitySpec("binary_sensor", SIGN_CONVENTIONS_DESCRIPTION),
)
