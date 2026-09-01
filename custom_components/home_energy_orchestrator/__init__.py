"""Home Energy Orchestrator integration setup."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import EnergyCoordinator

type EnergyConfigEntry = ConfigEntry[EnergyCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: EnergyConfigEntry) -> bool:
    """Set up a configured observer."""
    coordinator = EnergyCoordinator(hass, {**entry.data, **entry.options})
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EnergyConfigEntry) -> bool:
    """Unload all observer entities."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.shutdown()
    return unloaded
