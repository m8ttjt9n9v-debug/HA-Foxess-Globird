"""Declarative entity descriptions shared by the HEO platforms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.helpers.entity import EntityDescription

EntityPlatform = Literal[
    "binary_sensor",
    "button",
    "number",
    "select",
    "sensor",
    "switch",
]
AvailabilityRule = Literal["coordinator", "coordinator_and_projection"]


@dataclass(frozen=True, slots=True)
class EntitySpec:
    """Bind one stable public entity key to its platform description."""

    platform: EntityPlatform
    description: EntityDescription
    value_projection: str
    availability: AvailabilityRule
    deprecated: bool = False


SENSOR_DESCRIPTIONS = (
    SensorEntityDescription(key="status", name="Status", icon="mdi:eye-outline"),
    SensorEntityDescription(
        key="fleet_summary",
        name="Fleet Summary",
        icon="mdi:home-group",
    ),
    SensorEntityDescription(
        key="battery_soc",
        name="Battery State of Charge",
        native_unit_of_measurement="%",
        device_class="battery",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="battery_potential_capacity",
        name="Battery Potential Capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="battery_energy",
        name="Current Battery Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="available_energy",
        name="Available Battery Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="grid_power",
        name="Grid Power (Import Positive)",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="grid_import",
        name="Grid Import",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="grid_export",
        name="Grid Export",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="battery_power",
        name="Battery Power (Charge Positive)",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="house_load",
        name="House Load",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="solar_power",
        name="Solar Generation",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="site_grid_current",
        name="Site Grid Current (Import Positive)",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_soc",
        name="EV State of Charge",
        native_unit_of_measurement="%",
        device_class="battery",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_max_power",
        name="EV Maximum Configured Power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(key="ev_control_status", name="EV Control Status"),
    SensorEntityDescription(
        key="ev_current_target",
        name="EV Current Target",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_requested_current",
        name="EV Requested Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_actual_current",
        name="EV Actual Charging Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_charge_limit_target",
        name="EV Charge Limit Target",
        native_unit_of_measurement="%",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ev_applied_charge_limit",
        name="EV Applied Charge Limit",
        native_unit_of_measurement="%",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ev_grid_current_average",
        name="EV Controller Grid Current Average",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_actual_current_average",
        name="EV Actual Current Average",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_reconciliation_attempts",
        name="EV Reconciliation Attempts",
        state_class="measurement",
    ),
    SensorEntityDescription(
        key="ev_smart_socket_recovery_status",
        name="EV Smart Socket Recovery Status",
    ),
    SensorEntityDescription(key="ev_solar_spill_status", name="EV Solar Spill Status"),
    SensorEntityDescription(
        key="ev_solar_spill_current_target",
        name="EV Solar Spill Current Target",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_solar_spill_surplus",
        name="EV Reconstructed Solar Spill",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(key="ev_pre_free_status", name="EV Pre-Free Status"),
    SensorEntityDescription(
        key="ev_pre_free_planned_energy",
        name="EV Pre-Free Planned Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_pre_free_planned_start",
        name="EV Pre-Free Planned Start",
        device_class="timestamp",
    ),
    SensorEntityDescription(
        key="ev_pre_free_current_target",
        name="EV Pre-Free Current Target",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_status", name="EV Daily Ready-By Backfill Status"
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_remaining",
        name="EV Daily Backfill Allocation Remaining",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_delivered",
        name="EV Daily Backfill Delivered",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_planned_energy",
        name="EV Daily Backfill Planned Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_shortfall",
        name="EV Daily Backfill Allocation Shortfall",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_planned_start",
        name="EV Daily Backfill Planned Start",
        device_class="timestamp",
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_current_target",
        name="EV Daily Backfill Current Target",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_daily_driving_energy",
        name="EV Daily Driving Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_driving_p85",
        name="EV Driving P85",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_driving_learning_samples",
        name="EV Driving Learning Samples",
        state_class="measurement",
    ),
    SensorEntityDescription(
        key="ev_usable_capacity",
        name="EV Estimated Usable Capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_free_window_soc_gain",
        name="EV Free Window State of Charge Gain",
        native_unit_of_measurement="%",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_learned_charge_limit",
        name="EV Learned General Charge Limit",
        native_unit_of_measurement="%",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ev_driving_learning_status",
        name="EV Driving Learning Status",
    ),
    SensorEntityDescription(
        key="free_energy_remaining",
        name="Free Energy Remaining Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="daily_import",
        name="Grid Import Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        state_class="total_increasing",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="free_window_import",
        name="Free Window Import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        state_class="total_increasing",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="daily_export",
        name="Grid Export Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        state_class="total_increasing",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="standard_export_window",
        name="Peak Feed-in Export Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        state_class="total_increasing",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="offpeak_export",
        name="Off-peak Feed-in Export Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        state_class="total_increasing",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="estimated_energy_cost",
        name="Estimated Gross Cost Today",
        icon="mdi:cash",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="estimated_import_energy_cost",
        name="Estimated Import Energy Cost Today",
        icon="mdi:transmission-tower-import",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="daily_supply_charge",
        name="Daily Supply Charge",
        icon="mdi:currency-usd",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="estimated_export_revenue",
        name="Estimated Export Revenue Today",
        icon="mdi:transmission-tower-export",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="zerohero_credit",
        name="ZEROHERO Credit Today",
        icon="mdi:cash-plus",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="zerohero_credit_status",
        name="ZEROHERO Credit Status",
        icon="mdi:cash-check",
    ),
    SensorEntityDescription(
        key="estimated_net_cost",
        name="Forecast Net Cost Today",
        icon="mdi:cash-sync",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="measured_net_cost",
        name="Measured Net Cost Today",
        icon="mdi:cash-check",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="forecast_export_realisation",
        name="Forecast Export Realisation",
        native_unit_of_measurement="%",
        icon="mdi:percent-box-outline",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="forecast_yesterday_cost",
        name="Forecast Cost for Latest GloBird Day",
        icon="mdi:calendar-clock",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="globird_yesterday_actual_cost",
        name="Actual Cost for Latest GloBird Day",
        icon="mdi:calendar-check",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="forecast_error_yesterday",
        name="Forecast Error for Latest GloBird Day",
        icon="mdi:delta",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="forecast_scorecard_status",
        name="Forecast Scorecard Status",
        icon="mdi:scoreboard-outline",
    ),
    SensorEntityDescription(
        key="free_charge_allowed",
        name="Free Charge Allowance Remaining",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="free_charge_power_target",
        name="Free-Window Battery Charge Power Target",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="free_charge_completion",
        name="Free-Window Battery Charge Status",
        icon="mdi:battery-clock",
    ),
    SensorEntityDescription(
        key="bonus_zero_import_allowed",
        name="ZEROHERO Telemetry Guard Qualified",
        icon="mdi:cash-check",
    ),
    SensorEntityDescription(
        key="zerohero_import_window",
        name="ZEROHERO Import This Window",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        state_class="total_increasing",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(key="tariff_status", name="Tariff Guard Status"),
    SensorEntityDescription(
        key="zerohero_export_window",
        name="ZEROHERO Export This Window",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        state_class="total_increasing",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="zerohero_sellable_energy",
        name="ZEROHERO Sellable Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="zerohero_planned_export_energy",
        name="ZEROHERO Planned Export Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="zerohero_planned_duration",
        name="ZEROHERO Planned Duration",
        native_unit_of_measurement="min",
        device_class="duration",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="zerohero_planned_start",
        name="ZEROHERO Planned Start",
        device_class="timestamp",
    ),
    SensorEntityDescription(key="zerohero_export_status", name="ZEROHERO Export Status"),
    SensorEntityDescription(
        key="ev_before_export_status",
        name="EV Before Export Status",
        icon="mdi:car-arrow-right",
    ),
    SensorEntityDescription(
        key="learned_house_energy",
        name="Protected House Energy Budget",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="learned_base_house_energy",
        name="Learned Base House Energy P80",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="learned_heater_energy",
        name="Learned Heater Energy P80",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="remaining_house_energy",
        name="Remaining House Energy Budget",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="learning_samples",
        name="House Learning Samples",
        state_class="measurement",
    ),
    SensorEntityDescription(key="learning_status", name="House Learning Status"),
    SensorEntityDescription(
        key="heater_learning_samples",
        name="Heater Learning Samples",
        state_class="measurement",
    ),
    SensorEntityDescription(
        key="house_occupancy_state",
        name="House Energy Occupancy State",
        icon="mdi:home-account",
    ),
    SensorEntityDescription(
        key="test_charge_estimated_cost",
        name="Test Charge Estimated Cost",
        icon="mdi:cash-minus",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="test_charge_import_rate",
        name="Test Charge Import Rate",
        native_unit_of_measurement="$/kWh",
        icon="mdi:cash-minus",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="test_discharge_estimated_earning",
        name="Test Discharge Estimated Earning",
        icon="mdi:cash-plus",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="test_discharge_export_rate",
        name="Test Discharge Export Rate",
        native_unit_of_measurement="$/kWh",
        icon="mdi:cash-plus",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(key="test_status", name="Test Status"),
    SensorEntityDescription(
        key="test_remaining_minutes",
        name="Test Remaining",
        native_unit_of_measurement="min",
        suggested_display_precision=2,
    ),
)


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

_NON_SENSOR_PROJECTIONS = {
    "test_force_charge": "TestButton.async_press",
    "test_force_discharge": "TestButton.async_press",
    "test_stop": "TestButton.async_press",
    "test_charge_power": "TestNumber.native_value",
    "test_discharge_power": "TestNumber.native_value",
    "test_duration": "TestNumber.native_value",
    "ev_before_export_soc_target": "EvBeforeExportTargetNumber.native_value",
    "house_occupancy_mode": "HouseOccupancyModeSelect.current_option",
    "safety_lock": "SafetyLockSwitch.is_on",
    "automatic_charge": "AutomaticChargeSwitch.is_on",
    "automatic_export": "AutomaticExportSwitch.is_on",
    "automatic_ev_control": "AutomaticEvControlSwitch.is_on",
    "ev_before_export": "EvBeforeExportSwitch.is_on",
    "ev_charge_to_full": "EvChargeToFullSwitch.is_on",
    "sign_conventions_verified": "SignConventionsVerifiedBinarySensor.is_on",
}


def _entity_spec(platform: EntityPlatform, description: EntityDescription) -> EntitySpec:
    if platform == "sensor":
        projection = f"EnergySensor.native_value[{description.key!r}]"
        availability: AvailabilityRule = "coordinator_and_projection"
    else:
        projection = _NON_SENSOR_PROJECTIONS[description.key]
        availability = "coordinator"
    return EntitySpec(platform, description, projection, availability)


ENTITY_SPECS = (
    *(_entity_spec("sensor", description) for description in SENSOR_DESCRIPTIONS),
    *(_entity_spec("button", description) for description in BUTTON_DESCRIPTIONS),
    *(_entity_spec("number", description) for description in NUMBER_DESCRIPTIONS),
    _entity_spec("number", EV_BEFORE_EXPORT_TARGET_DESCRIPTION),
    _entity_spec("select", HOUSE_OCCUPANCY_DESCRIPTION),
    _entity_spec("switch", SAFETY_DESCRIPTION),
    _entity_spec("switch", CHARGE_DESCRIPTION),
    _entity_spec("switch", EXPORT_DESCRIPTION),
    _entity_spec("switch", EV_DESCRIPTION),
    _entity_spec("switch", EV_BEFORE_EXPORT_DESCRIPTION),
    _entity_spec("switch", CHARGE_TO_FULL_DESCRIPTION),
    _entity_spec("binary_sensor", SIGN_CONVENTIONS_DESCRIPTION),
)
