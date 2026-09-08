"""Runtime selection of the canonical house-energy occupancy policy."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnergyConfigEntry
from .const import (
    CONF_HOUSE_OCCUPANCY_MODE,
    DEFAULT_HOUSE_OCCUPANCY_MODE,
    HOUSE_OCCUPANCY_MODES,
)
from .coordinator import EnergyCoordinator

DESCRIPTION = SelectEntityDescription(
    key="house_occupancy_mode",
    name="House Energy Occupancy Mode",
    icon="mdi:home-account",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Expose the persistent Auto/Home/Away policy from the pilot."""
    async_add_entities((HouseOccupancyModeSelect(entry.runtime_data, entry),))


class HouseOccupancyModeSelect(CoordinatorEntity[EnergyCoordinator], SelectEntity):
    """Config-backed occupancy override; Auto remains conservative."""

    entity_description = DESCRIPTION
    _attr_options = [mode.title() for mode in HOUSE_OCCUPANCY_MODES]

    def __init__(self, coordinator: EnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{DESCRIPTION.key}"
        self.entity_id = "select.home_energy_house_occupancy_mode"
        self._attr_has_entity_name = True

    @property
    def current_option(self) -> str:
        """Return the configured mode using human-readable casing."""
        mode = str(
            self.coordinator.config.get(
                CONF_HOUSE_OCCUPANCY_MODE,
                DEFAULT_HOUSE_OCCUPANCY_MODE,
            )
        ).lower()
        if mode not in HOUSE_OCCUPANCY_MODES:
            mode = DEFAULT_HOUSE_OCCUPANCY_MODE
        return mode.title()

    async def async_select_option(self, option: str) -> None:
        """Persist a supported mode and immediately refresh policy evidence."""
        mode = option.lower()
        if mode not in HOUSE_OCCUPANCY_MODES:
            raise ValueError(f"Unsupported occupancy mode: {option}")
        config = {**self._entry.data, CONF_HOUSE_OCCUPANCY_MODE: mode}
        self.hass.config_entries.async_update_entry(self._entry, data=config)
        self.coordinator.config[CONF_HOUSE_OCCUPANCY_MODE] = mode
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()
