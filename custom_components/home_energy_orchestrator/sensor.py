"""Observer entities for the public, compact v0.1 surface."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnergyConfigEntry
from .const import (
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_REHEARSAL_MODE,
    CONF_SOLAR_POWER,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DOMAIN,
    FOXESS_CONTROL_OWNER_CLOUD,
)
from .coordinator import EnergyCoordinator

DESCRIPTIONS = (
    SensorEntityDescription(key="status", name="Status", icon="mdi:eye-outline"),
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
        key="estimated_energy_cost",
        name="Estimated Energy Cost Today",
        icon="mdi:cash",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="free_charge_allowed",
        name="Free Charge Allowance Remaining",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
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
        key="free_charge_completion",
        name="Free-Window Charge Completion Mode",
    ),
    SensorEntityDescription(
        key="free_charge_power_target",
        name="Free-Window Charge Power Target",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="learned_house_energy",
        name="Learned House Energy Budget",
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


async def async_setup_entry(
    hass: HomeAssistant, entry: EnergyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add observer entities."""
    registry = er.async_get(hass)
    for description in DESCRIPTIONS:
        unique_id = f"{entry.entry_id}_{description.key}"
        current_entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        stable_entity_id = f"sensor.home_energy_{description.key}"
        if current_entity_id and current_entity_id != stable_entity_id:
            if registry.async_get(stable_entity_id) is None:
                registry.async_update_entity(current_entity_id, new_entity_id=stable_entity_id)
    async_add_entities(
        EnergySensor(entry.runtime_data, entry, description) for description in DESCRIPTIONS
    )


class EnergySensor(CoordinatorEntity[EnergyCoordinator], SensorEntity):
    """Expose a single calculated ledger term."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = f"sensor.home_energy_{description.key}"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="FoxESS Globird Energy Observer",
            model="Observer",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self):
        ledger = self.coordinator.data
        learning = self.coordinator.learning_result
        snapshot = self.coordinator.snapshot
        values = {
            "status": ledger.reason,
            "battery_soc": None if snapshot is None else snapshot.battery_soc,
            "battery_potential_capacity": ledger.battery_potential_capacity_kwh,
            "battery_energy": ledger.battery_energy_kwh,
            "available_energy": ledger.available_after_reserve_kwh,
            "grid_import": ledger.grid_import_kw,
            "grid_export": ledger.grid_export_kw,
            "house_load": None if snapshot is None else snapshot.house_load_kw,
            "solar_power": self.coordinator._power(
                self.coordinator.config.get(CONF_SOLAR_POWER)
            ),
            "ev_soc": None if snapshot is None else snapshot.ev_soc,
            "ev_max_power": ledger.ev_max_power_kw,
            "free_energy_remaining": ledger.free_energy_remaining_kwh,
            "daily_import": ledger.daily_import_kwh,
            "free_window_import": ledger.free_window_import_kwh,
            # Cost has no Home Assistant unit (it is site-currency specific),
            # so round the state itself rather than relying on display hints.
            "estimated_energy_cost": (
                None
                if ledger.estimated_energy_cost is None
                else round(ledger.estimated_energy_cost, 2)
            ),
            "free_charge_allowed": ledger.free_charge_allowed_kwh,
            "bonus_zero_import_allowed": ledger.bonus_zero_import_allowed,
            "zerohero_import_window": (
                None
                if self.coordinator.zerohero_import.last_at is None
                else round(sum(self.coordinator.zerohero_import.hourly_import_kwh.values()), 3)
            ),
            "tariff_status": ledger.tariff_reason,
            "free_charge_completion": (
                None
                if self.coordinator.free_charge_completion is None
                else self.coordinator.free_charge_completion.action
            ),
            "free_charge_power_target": (
                None
                if self.coordinator.free_charge_plan is None
                else self.coordinator.free_charge_plan.target_charge_power_kw
            ),
            "learned_house_energy": learning.cycle_budget_kwh,
            "remaining_house_energy": self.coordinator.learning_remaining_kwh,
            "learning_samples": learning.sample_count,
            "learning_status": learning.model,
            "test_charge_estimated_cost": self.coordinator.manual_test.preview_charge().amount,
            "test_charge_import_rate": self.coordinator.manual_test.current_import_rate(),
            "test_discharge_estimated_earning": (
                self.coordinator.manual_test.preview_discharge().amount
            ),
            "test_discharge_export_rate": self.coordinator.manual_test.current_export_rate(),
            "test_status": self.coordinator.manual_test.status,
            "test_remaining_minutes": self.coordinator.manual_test.remaining_minutes,
        }
        return values[self.entity_description.key]

    @property
    def extra_state_attributes(self):
        if self.entity_description.key == "zerohero_import_window":
            accumulator = self.coordinator.zerohero_import
            return {
                "hourly_import_kwh": {
                    bucket: round(value, 6)
                    for bucket, value in accumulator.hourly_import_kwh.items()
                },
                "accumulator_date": (
                    None if accumulator.local_date is None else accumulator.local_date.isoformat()
                ),
                "last_sample": (
                    None if accumulator.last_at is None else accumulator.last_at.isoformat()
                ),
                "threshold_kwh_per_hour": self.coordinator.config.get(
                    "zero_import_threshold_kw", 0.03
                ),
            }
        if self.entity_description.key != "status":
            return None
        learning = self.coordinator.learning_result
        foxess_requested = bool(
            self.coordinator.config.get(CONF_AUTOMATIC_CONTROL_ENABLED, False)
        )
        foxess_owner = self.coordinator.config.get(
            CONF_FOXESS_CONTROL_OWNER, DEFAULT_FOXESS_CONTROL_OWNER
        )
        foxess_gate = (
            self.coordinator.active_controller.gate_status
            if self.coordinator.active_controller
            else "unavailable"
        )
        foxess_enabled = foxess_gate == "ready"
        ev_requested = bool(
            self.coordinator.config.get(CONF_EV_AUTOMATIC_CONTROL_ENABLED, False)
        )
        ev_gate = (
            self.coordinator.active_controller.ev_controller.gate_status
            if self.coordinator.active_controller
            else "unavailable"
        )
        ev_enabled = ev_gate == "ready"
        if foxess_owner == FOXESS_CONTROL_OWNER_CLOUD and ev_enabled:
            control_mode = "foxcloud_scheduler_ev"
        elif foxess_owner == FOXESS_CONTROL_OWNER_CLOUD:
            control_mode = "foxcloud_scheduler"
        elif foxess_enabled and ev_enabled:
            control_mode = "automatic_foxess_ev"
        elif foxess_enabled:
            control_mode = "automatic_foxess"
        elif ev_enabled:
            control_mode = "automatic_ev"
        else:
            control_mode = "observe"
        return {
            "mode": control_mode,
            "control_gate": foxess_gate,
            "last_control_reason": (
                self.coordinator.active_controller.last_reason
                if self.coordinator.active_controller
                else "unavailable"
            ),
            "last_control_actions": (
                self.coordinator.active_controller.last_actions
                if self.coordinator.active_controller
                else ()
            ),
            "writes_performed": (
                self.coordinator.active_controller.writes_performed
                if self.coordinator.active_controller
                else 0
            ),
            "ev_control_gate": ev_gate,
            "ev_last_control_reason": (
                self.coordinator.active_controller.ev_controller.last_reason
                if self.coordinator.active_controller
                else "unavailable"
            ),
            "ev_last_control_actions": (
                self.coordinator.active_controller.ev_controller.last_actions
                if self.coordinator.active_controller
                else ()
            ),
            "ev_writes_performed": (
                self.coordinator.active_controller.ev_controller.writes_performed
                if self.coordinator.active_controller
                else 0
            ),
            "ev_allowance_remaining_kwh": (
                self.coordinator.active_controller.ev_controller.allowance_remaining_kwh
                if self.coordinator.active_controller
                else None
            ),
            "ev_allowance_current_ceiling_a": (
                self.coordinator.active_controller.ev_controller.allowance_current_ceiling_a
                if self.coordinator.active_controller
                else None
            ),
            "ev_allowance_target_site_import_kw": (
                self.coordinator.active_controller.ev_controller.allowance_target_site_import_kw
                if self.coordinator.active_controller
                else None
            ),
            "ev_allowance_non_ev_import_kw": (
                self.coordinator.active_controller.ev_controller.allowance_non_ev_import_kw
                if self.coordinator.active_controller
                else None
            ),
            "ev_allowance_budget_remaining_kwh": (
                self.coordinator.active_controller.ev_controller.allowance_ev_budget_remaining_kwh
                if self.coordinator.active_controller
                else None
            ),
            "automatic_control_enabled": foxess_requested,
            "foxess_modbus_control_effective": foxess_enabled,
            "foxess_control_owner": foxess_owner,
            "ev_automatic_control_enabled": ev_requested,
            "ev_control_effective": ev_enabled,
            "rehearsal_mode": self.coordinator.config.get(CONF_REHEARSAL_MODE, True),
            "integration": DOMAIN,
            "learning_model": learning.model,
            "learning_samples": learning.sample_count,
            "learning_max_age_days": self.coordinator.demand_history.max_age_days,
            "learning_sample_limit": self.coordinator.demand_history.sample_limit,
            "learning_sampler_enabled": self.coordinator.demand_sampler is not None,
        }
