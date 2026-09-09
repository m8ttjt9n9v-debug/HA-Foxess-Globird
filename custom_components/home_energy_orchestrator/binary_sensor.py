"""Commissioning-state binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnergyConfigEntry
from .const import (
    CONF_BATTERY_POWER_DIRECTION,
    CONF_GRID_POWER_DIRECTION,
    CONF_SIGN_CONVENTIONS_VERIFIED,
    CONF_SITE_GRID_CURRENT_DIRECTION,
    CONF_SOLAR_POWER_DIRECTION,
    DEFAULT_BATTERY_POWER_DIRECTION,
    DEFAULT_GRID_POWER_DIRECTION,
    DEFAULT_SIGN_CONVENTIONS_VERIFIED,
    DEFAULT_SITE_GRID_CURRENT_DIRECTION,
    DEFAULT_SOLAR_POWER_DIRECTION,
    DOMAIN,
)
from .coordinator import EnergyCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Expose the explicit normalization commissioning state."""
    async_add_entities((SignConventionsVerifiedBinarySensor(entry.runtime_data, entry),))


class SignConventionsVerifiedBinarySensor(
    CoordinatorEntity[EnergyCoordinator], BinarySensorEntity
):
    """True only after an operator verifies the normalized electrical signs."""

    _attr_name = "Sign Conventions Verified"
    _attr_icon = "mdi:swap-horizontal-bold"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(self, coordinator: EnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_sign_conventions_verified"
        self.entity_id = "binary_sensor.home_energy_sign_conventions_verified"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="FoxESS Globird Energy Observer",
            model="Observer",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        return bool(
            self.coordinator.config.get(
                CONF_SIGN_CONVENTIONS_VERIFIED,
                DEFAULT_SIGN_CONVENTIONS_VERIFIED,
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        config = self.coordinator.config
        return {
            "grid_power_positive_direction": config.get(
                CONF_GRID_POWER_DIRECTION, DEFAULT_GRID_POWER_DIRECTION
            ),
            "battery_power_positive_direction": config.get(
                CONF_BATTERY_POWER_DIRECTION, DEFAULT_BATTERY_POWER_DIRECTION
            ),
            "solar_generation_direction": config.get(
                CONF_SOLAR_POWER_DIRECTION, DEFAULT_SOLAR_POWER_DIRECTION
            ),
            "site_grid_current_positive_direction": config.get(
                CONF_SITE_GRID_CURRENT_DIRECTION,
                DEFAULT_SITE_GRID_CURRENT_DIRECTION,
            ),
        }
