"""Editable inputs for the explicit FoxESS diagnostics tab."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnergyConfigEntry
from .const import (
    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
    DEFAULT_INVERTER_CHARGE_LIMIT_KW,
    DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
)
from .coordinator import EnergyCoordinator

DESCRIPTIONS = (
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


async def async_setup_entry(
    hass: HomeAssistant, entry: EnergyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the three local-only diagnostic inputs."""
    async_add_entities(
        (
            *(TestNumber(entry.runtime_data, entry, description) for description in DESCRIPTIONS),
            EvBeforeExportTargetNumber(
                entry.runtime_data,
                entry,
                EV_BEFORE_EXPORT_TARGET_DESCRIPTION,
            ),
        )
    )


class EvBeforeExportTargetNumber(CoordinatorEntity[EnergyCoordinator], NumberEntity):
    """Persist the user-adjustable EV threshold without an external helper."""

    entity_description: NumberEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = "number.home_energy_ev_before_export_soc_target"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> float:
        try:
            return float(
                self.coordinator.config.get(
                    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
                    DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
                )
            )
        except (TypeError, ValueError):
            return DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET

    async def async_set_native_value(self, value: float) -> None:
        target = min(max(float(value), 0.0), 100.0)
        config = {**self._entry.data, CONF_EV_BEFORE_EXPORT_SOC_TARGET: target}
        self.hass.config_entries.async_update_entry(self._entry, data=config)
        self.coordinator.config[CONF_EV_BEFORE_EXPORT_SOC_TARGET] = target
        self.async_write_ha_state()
        controller = self.coordinator.active_controller
        if controller is not None:
            await controller.async_reconcile()
        self.coordinator.async_update_listeners()


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
        self._attr_native_value = value
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()

    def _get_value(self) -> float:
        test = self.coordinator.manual_test
        return {
            "test_charge_power": test.charge_power_kw,
            "test_discharge_power": test.discharge_power_kw,
            "test_duration": test.duration_minutes,
        }[self.entity_description.key]

    def _max_value(self) -> float:
        if self.entity_description.key == "test_charge_power":
            return max(
                float(
                    self.coordinator.config.get(
                        CONF_INVERTER_CHARGE_LIMIT_KW,
                        DEFAULT_INVERTER_CHARGE_LIMIT_KW,
                    )
                ),
                0.1,
            )
        if self.entity_description.key == "test_discharge_power":
            return max(
                float(
                    self.coordinator.config.get(
                        CONF_INVERTER_DISCHARGE_LIMIT_KW,
                        DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
                    )
                ),
                0.1,
            )
        return float(self.entity_description.native_max_value)
