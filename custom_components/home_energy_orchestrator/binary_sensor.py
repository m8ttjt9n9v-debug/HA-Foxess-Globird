"""Commissioning-state binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnergyConfigEntry
from .const import DOMAIN
from .coordinator import EnergyCoordinator
from .entity_catalogue import SIGN_CONVENTIONS_DESCRIPTION as DESCRIPTION


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

    _attr_has_entity_name = True
    entity_description = DESCRIPTION

    def __init__(self, coordinator: EnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_sign_conventions_verified"
        self.entity_id = "binary_sensor.home_energy_sign_conventions_verified"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="FoxESS GloBird Tesla Energy Orchestrator",
            model="Observer",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.runtime_config.electrical.verified

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        electrical = self.coordinator.runtime_config.electrical
        return {
            "grid_power_positive_direction": electrical.grid_power_positive_direction,
            "battery_power_positive_direction": electrical.battery_power_positive_direction,
            "solar_generation_direction": electrical.solar_generation_direction,
            "site_grid_current_positive_direction": (
                electrical.site_grid_current_positive_direction
            ),
        }
