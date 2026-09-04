"""Home Energy Orchestrator integration setup."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .active import ActiveFoxessController
from .const import PLATFORMS
from .coordinator import EnergyCoordinator
from .manual_test import ManualTestController
from .services import register_services, unregister_services

type EnergyConfigEntry = ConfigEntry[EnergyCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: EnergyConfigEntry) -> bool:
    """Set up a configured observer."""
    coordinator = EnergyCoordinator(hass, {**entry.data, **entry.options}, entry.entry_id)
    await coordinator.async_load_demand_history()
    await coordinator.async_load_daily_import()
    await coordinator.async_config_entry_first_refresh()
    coordinator.manual_test = ManualTestController(hass, coordinator)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    active = ActiveFoxessController(hass, coordinator)
    coordinator.active_controller = active
    await active.async_start()
    hass.data.setdefault("home_energy_orchestrator", {})[entry.entry_id] = {
        "coordinator": coordinator,
        "manual_test": coordinator.manual_test,
    }
    register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EnergyConfigEntry) -> bool:
    """Unload all observer entities."""
    active = getattr(entry.runtime_data, "active_controller", None)
    if active is not None:
        await active.async_stop()
    manual_test = getattr(entry.runtime_data, "manual_test", None)
    if manual_test is not None:
        await manual_test.async_stop("integration_unloaded")
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.shutdown()
    entries = hass.data.get("home_energy_orchestrator", {})
    entries.pop(entry.entry_id, None)
    if not entries:
        unregister_services(hass)
    return unloaded
