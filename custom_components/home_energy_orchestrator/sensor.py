"""Observer entities for the public, compact v0.1 surface."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnergyConfigEntry
from .const import DOMAIN
from .coordinator import EnergyCoordinator

DESCRIPTIONS = (
    SensorEntityDescription(key="status", name="Status", icon="mdi:eye-outline"),
    SensorEntityDescription(
        key="battery_potential_capacity",
        name="Battery Potential Capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
    ),
    SensorEntityDescription(
        key="battery_energy",
        name="Current Battery Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
    ),
    SensorEntityDescription(
        key="available_energy",
        name="Available Battery Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
    ),
    SensorEntityDescription(
        key="grid_import",
        name="Grid Import",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
    ),
    SensorEntityDescription(
        key="grid_export",
        name="Grid Export",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
    ),
    SensorEntityDescription(
        key="ev_max_power",
        name="EV Maximum Configured Power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
    ),
    SensorEntityDescription(
        key="free_energy_remaining",
        name="Free Energy Remaining Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
    ),
    SensorEntityDescription(
        key="daily_import",
        name="Grid Import Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        state_class="total_increasing",
    ),
    SensorEntityDescription(
        key="free_window_import",
        name="Free Window Import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        state_class="total_increasing",
    ),
    SensorEntityDescription(
        key="estimated_energy_cost",
        name="Estimated Energy Cost Today",
        icon="mdi:cash",
    ),
    SensorEntityDescription(
        key="free_charge_allowed",
        name="Free Charge Allowance Remaining",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
    ),
    SensorEntityDescription(
        key="bonus_zero_import_allowed",
        name="ZEROHERO Telemetry Guard Qualified",
        icon="mdi:cash-check",
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
    ),
    SensorEntityDescription(
        key="learned_house_energy",
        name="Learned House Energy Budget",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
    ),
    SensorEntityDescription(
        key="remaining_house_energy",
        name="Remaining House Energy Budget",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
    ),
    SensorEntityDescription(
        key="learning_samples",
        name="House Learning Samples",
        state_class="measurement",
    ),
    SensorEntityDescription(key="learning_status", name="House Learning Status"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: EnergyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add observer entities."""
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
        values = {
            "status": ledger.reason,
            "battery_potential_capacity": ledger.battery_potential_capacity_kwh,
            "battery_energy": ledger.battery_energy_kwh,
            "available_energy": ledger.available_after_reserve_kwh,
            "grid_import": ledger.grid_import_kw,
            "grid_export": ledger.grid_export_kw,
            "ev_max_power": ledger.ev_max_power_kw,
            "free_energy_remaining": ledger.free_energy_remaining_kwh,
            "daily_import": ledger.daily_import_kwh,
            "free_window_import": ledger.free_window_import_kwh,
            "estimated_energy_cost": ledger.estimated_energy_cost,
            "free_charge_allowed": ledger.free_charge_allowed_kwh,
            "bonus_zero_import_allowed": ledger.bonus_zero_import_allowed,
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
        }
        return values[self.entity_description.key]

    @property
    def extra_state_attributes(self):
        if self.entity_description.key != "status":
            return None
        learning = self.coordinator.learning_result
        return {
            "mode": "automatic_foxess" if self.coordinator.active_controller else "observe",
            "control_gate": (
                self.coordinator.active_controller.gate_status
                if self.coordinator.active_controller
                else "unavailable"
            ),
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
            "automatic_control_enabled": self.coordinator.config.get(
                "automatic_control_enabled", False
            ),
            "rehearsal_mode": self.coordinator.config.get("rehearsal_mode", True),
            "integration": DOMAIN,
            "learning_model": learning.model,
            "learning_samples": learning.sample_count,
            "learning_max_age_days": self.coordinator.demand_history.max_age_days,
            "learning_sample_limit": self.coordinator.demand_history.sample_limit,
            "learning_sampler_enabled": self.coordinator.demand_sampler is not None,
        }
