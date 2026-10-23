"""Runtime selection of the canonical house-energy occupancy policy."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnergyConfigEntry
from .aemo_monitor_controls import AemoRegionSelect
from .configuration import RuntimeConfiguration
from .const import (
    CONF_EV_PRE_FREE_BACKFILL_TIMING,
    CONF_HOUSE_OCCUPANCY_MODE,
    EV_PRE_FREE_BACKFILL_TIMINGS,
    HOUSE_OCCUPANCY_MODES,
)
from .coordinator import EnergyCoordinator
from .entity_catalogue import EV_BACKFILL_TIMING_DESCRIPTION
from .entity_catalogue import HOUSE_OCCUPANCY_DESCRIPTION as DESCRIPTION
from .ev_backfill_settings import backfill_timing_error
from .maintenance_entities import MaintenanceVersion
from .trip_entities import TripTargetSelect


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Expose the persistent Auto/Home/Away policy from the pilot."""
    if (hub := entry.runtime_data.fleet_maintenance) is not None:
        async_add_entities(MaintenanceVersion(hub, entry, target) for target in hub.targets)
    async_add_entities(
        (
            HouseOccupancyModeSelect(entry.runtime_data, entry),
            EvBackfillTimingSelect(entry.runtime_data, entry),
            AemoRegionSelect(entry.runtime_data, entry),
            TripTargetSelect(entry.runtime_data, entry),
        )
    )


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
        return self.coordinator.runtime_config.house.occupancy_mode.title()

    async def async_select_option(self, option: str) -> None:
        """Persist a supported mode and immediately refresh policy evidence."""
        mode = option.lower()
        if mode not in HOUSE_OCCUPANCY_MODES:
            raise ValueError(f"Unsupported occupancy mode: {option}")
        config = {**self._entry.data, CONF_HOUSE_OCCUPANCY_MODE: mode}
        self.hass.config_entries.async_update_entry(self._entry, data=config)
        self.coordinator.update_config_value(CONF_HOUSE_OCCUPANCY_MODE, mode)
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()


class EvBackfillTimingSelect(CoordinatorEntity[EnergyCoordinator], SelectEntity):
    """Edit one existing saved timing value without enabling either controller."""

    entity_description = EV_BACKFILL_TIMING_DESCRIPTION
    _attr_options = list(EV_PRE_FREE_BACKFILL_TIMINGS)

    def __init__(self, coordinator: EnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{self.entity_description.key}"
        self.entity_id = "select.home_energy_ev_backfill_timing"
        self._attr_has_entity_name = True

    @property
    def available(self) -> bool:
        """Configuration remains editable while telemetry or controls are off."""
        return True

    @property
    def current_option(self) -> str:
        return self.coordinator.runtime_config.ev_policy.pre_free_backfill_timing

    async def async_select_option(self, option: str) -> None:
        if option not in EV_PRE_FREE_BACKFILL_TIMINGS:
            raise HomeAssistantError("Choose a supported EV backfill timing")
        candidate = RuntimeConfiguration.from_mapping({
            **self._entry.data, **self._entry.options,
            CONF_EV_PRE_FREE_BACKFILL_TIMING: option,
        })
        if error := backfill_timing_error(candidate):
            messages = {
                "when_connected_requires_direct_evse":
                    "Use spare energy when plugged in requires Direct / EVSE",
                "outside_ev_policy_requires_local_modbus":
                    "Backfill requires Local Modbus ownership",
                "invalid_ready_by_ev_backfill":
                    "Backfill requires positive inverter power and a ready time before free power",
                "invalid_when_connected_ev_backfill":
                    "Export must finish before the next ready time and free-power start",
            }
            raise HomeAssistantError(messages.get(error, "Choose a supported EV backfill timing"))
        self.hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, CONF_EV_PRE_FREE_BACKFILL_TIMING: option},
            options={
                key: value for key, value in self._entry.options.items()
                if key != CONF_EV_PRE_FREE_BACKFILL_TIMING
            },
        )
        self.coordinator.update_config_value(CONF_EV_PRE_FREE_BACKFILL_TIMING, option)
        self.async_write_ha_state()
        if (controller := self.coordinator.ev_controller) is not None:
            await controller.async_reconcile()
        self.coordinator.async_update_listeners()
