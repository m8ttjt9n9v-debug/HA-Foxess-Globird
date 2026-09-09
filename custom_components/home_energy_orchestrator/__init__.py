"""Home Energy Orchestrator integration setup."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .active import ActiveFoxessController
from .const import (
    BATTERY_POSITIVE_CHARGE,
    BATTERY_POSITIVE_DISCHARGE,
    CONF_BATTERY_CHARGE_POSITIVE,
    CONF_BATTERY_POWER_DIRECTION,
    CONF_GRID_IMPORT_POSITIVE,
    CONF_GRID_POWER_DIRECTION,
    CONF_SIGN_CONVENTIONS_VERIFIED,
    CONF_SITE_GRID_CURRENT_DIRECTION,
    CONF_SOLAR_POWER_DIRECTION,
    CONF_TELEMETRY_MAX_AGE_SECONDS,
    DEFAULT_SIGN_CONVENTIONS_VERIFIED,
    DEFAULT_SITE_GRID_CURRENT_DIRECTION,
    DEFAULT_SOLAR_POWER_DIRECTION,
    DEFAULT_TELEMETRY_MAX_AGE_SECONDS,
    GRID_POSITIVE_EXPORT,
    GRID_POSITIVE_IMPORT,
    PLATFORMS,
)
from .coordinator import EnergyCoordinator
from .ev_active import ActiveEvController
from .manual_test import ManualTestController
from .services import register_services, unregister_services

type EnergyConfigEntry = ConfigEntry[EnergyCoordinator]


async def async_migrate_entry(hass: HomeAssistant, entry: EnergyConfigEntry) -> bool:
    """Migrate ambiguous legacy booleans to explicit, locked conventions."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        data = dict(entry.data)
        data[CONF_GRID_POWER_DIRECTION] = (
            GRID_POSITIVE_IMPORT
            if bool(data.pop(CONF_GRID_IMPORT_POSITIVE, True))
            else GRID_POSITIVE_EXPORT
        )
        data[CONF_BATTERY_POWER_DIRECTION] = (
            BATTERY_POSITIVE_CHARGE
            if bool(data.pop(CONF_BATTERY_CHARGE_POSITIVE, True))
            else BATTERY_POSITIVE_DISCHARGE
        )
        data.setdefault(CONF_SOLAR_POWER_DIRECTION, DEFAULT_SOLAR_POWER_DIRECTION)
        data.setdefault(
            CONF_SITE_GRID_CURRENT_DIRECTION,
            DEFAULT_SITE_GRID_CURRENT_DIRECTION,
        )
        data.setdefault(
            CONF_TELEMETRY_MAX_AGE_SECONDS,
            DEFAULT_TELEMETRY_MAX_AGE_SECONDS,
        )
        # An upgrade cannot prove that previously configured signs were
        # electrically checked. Existing automatic requests fail closed until
        # the operator reviews the normalized sensors and confirms them.
        data[CONF_SIGN_CONVENTIONS_VERIFIED] = DEFAULT_SIGN_CONVENTIONS_VERIFIED
        hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EnergyConfigEntry) -> bool:
    """Set up a configured observer."""
    coordinator = EnergyCoordinator(hass, {**entry.data, **entry.options}, entry.entry_id)
    await coordinator.async_load_demand_history()
    await coordinator.async_load_daily_import()
    await coordinator.async_config_entry_first_refresh()
    coordinator.manual_test = ManualTestController(hass, coordinator)
    entry.runtime_data = coordinator
    active = ActiveFoxessController(hass, coordinator)
    coordinator.active_controller = active
    ev_controller = ActiveEvController(hass, coordinator)
    coordinator.ev_controller = ev_controller
    # Platform entities read controller diagnostics during their first state
    # write, so attach both controllers before forwarding setup.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await active.async_start()
    await ev_controller.async_start()
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
    ev_controller = getattr(entry.runtime_data, "ev_controller", None)
    if ev_controller is not None:
        await ev_controller.async_stop()
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
