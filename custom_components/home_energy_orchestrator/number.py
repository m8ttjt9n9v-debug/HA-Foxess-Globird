"""Editable inputs for the explicit FoxESS commissioning test tab."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnergyConfigEntry
from .const import CONF_INVERTER_CHARGE_LIMIT_KW, CONF_INVERTER_DISCHARGE_LIMIT_KW
from .coordinator import EnergyCoordinator

DESCRIPTIONS = (
    NumberEntityDescription(
        key="test_charge_power",
        name="Test Charge Power",
        icon="mdi:battery-arrow-up",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=0.1,
        native_max_value=15.0,
        native_step=0.1,
    ),
    NumberEntityDescription(
        key="test_discharge_power",
        name="Test Discharge Power",
        icon="mdi:battery-arrow-down",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=0.1,
        native_max_value=15.0,
        native_step=0.1,
    ),
    NumberEntityDescription(
        key="test_duration",
        name="Test Duration",
        icon="mdi:timer-outline",
        native_unit_of_measurement="min",
        native_min_value=1.0,
        native_max_value=30.0,
        native_step=1.0,
    ),
    NumberEntityDescription(
        key="test_export_rate",
        name="Test Export Rate",
        icon="mdi:cash-plus",
        native_unit_of_measurement="$/kWh",
        native_min_value=0.0,
        native_max_value=1.0,
        native_step=0.001,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: EnergyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the four local-only test inputs."""
    async_add_entities(
        TestNumber(entry.runtime_data, entry, description) for description in DESCRIPTIONS
    )


class TestNumber(CoordinatorEntity[EnergyCoordinator], NumberEntity):
    """An editable, non-actuating commissioning input."""

    entity_description: NumberEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = f"number.home_energy_{description.key}"
        self._attr_has_entity_name = True
        self._attr_native_value = self._get_value()
        self._attr_native_max_value = self._max_value()

    @property
    def native_value(self) -> float:
        return self._get_value()

    async def async_set_native_value(self, value: float) -> None:
        value = float(value)
        if self.entity_description.key == "test_charge_power":
            self.coordinator.manual_test.charge_power_kw = value
        elif self.entity_description.key == "test_discharge_power":
            self.coordinator.manual_test.discharge_power_kw = value
        elif self.entity_description.key == "test_duration":
            self.coordinator.manual_test.duration_minutes = value
        elif self.entity_description.key == "test_export_rate":
            self.coordinator.manual_test.export_rate_per_kwh = value
        self._attr_native_value = value
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()

    def _get_value(self) -> float:
        test = self.coordinator.manual_test
        return {
            "test_charge_power": test.charge_power_kw,
            "test_discharge_power": test.discharge_power_kw,
            "test_duration": test.duration_minutes,
            "test_export_rate": test.export_rate_per_kwh,
        }[self.entity_description.key]

    def _max_value(self) -> float:
        if self.entity_description.key == "test_charge_power":
            return max(
                float(self.coordinator.config.get(CONF_INVERTER_CHARGE_LIMIT_KW, 15.0)), 0.1
            )
        if self.entity_description.key == "test_discharge_power":
            return max(
                float(self.coordinator.config.get(CONF_INVERTER_DISCHARGE_LIMIT_KW, 15.0)), 0.1
            )
        return float(self.entity_description.native_max_value or 30.0)
