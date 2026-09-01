"""Read configured entities and calculate a safe observer-only ledger."""

from __future__ import annotations

import logging
from datetime import timedelta
from math import isfinite

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_FLOOR,
    CONF_BATTERY_SOC,
    CONF_EV_MAX_CURRENT,
    CONF_EV_MIN_CURRENT,
    CONF_EV_SOC,
    CONF_EV_VOLTAGE,
    CONF_GRID_IMPORT_POSITIVE,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_RESERVE,
    DOMAIN,
    REASON_INVALID_CONFIGURATION,
)
from .models import EnergyLedger, SiteSnapshot
from .normalise import percent, power_to_kw, signed_grid_power_to_import_kw
from .planner.ledger import calculate_ledger

_LOGGER = logging.getLogger(__name__)


class EnergyCoordinator(DataUpdateCoordinator[EnergyLedger]):
    """Coordinator that deliberately performs no service calls."""

    def __init__(self, hass: HomeAssistant, config: dict[str, object]) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=30))
        self.config = config
        self.snapshot: SiteSnapshot | None = None
        self._unsub_source_updates: CALLBACK_TYPE | None = async_track_state_change_event(
            hass,
            tuple(
                entity_id
                for key in (CONF_BATTERY_SOC, CONF_GRID_POWER, CONF_HOUSE_LOAD, CONF_EV_SOC)
                if (entity_id := config.get(key))
            ),
            self._async_source_changed,
        )

    @callback
    def _async_source_changed(self, event: Event) -> None:
        """Refresh promptly when a selected source changes."""
        self.hass.async_create_task(self.async_request_refresh())

    def shutdown(self) -> None:
        """Remove state listeners when the config entry is unloaded."""
        if self._unsub_source_updates is not None:
            self._unsub_source_updates()
            self._unsub_source_updates = None

    def _number(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        return value if isfinite(value) else None

    def _configured_float(self, key: str) -> float:
        """Read a finite, safe setup value from the config entry."""
        value = float(self.config[key])
        if not isfinite(value):
            raise ValueError(f"{key} must be finite")
        return value

    def _power(self, entity_id: str | None) -> float | None:
        value = self._number(entity_id)
        if value is None or not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        try:
            unit = state.attributes.get("unit_of_measurement") if state else None
            return power_to_kw(value, unit)
        except ValueError:
            return None

    async def _async_update_data(self) -> EnergyLedger:
        battery_soc = self._number(self.config.get(CONF_BATTERY_SOC))
        if battery_soc is not None:
            try:
                battery_soc = percent(battery_soc)
            except ValueError:
                battery_soc = None
        raw_grid = self._power(self.config.get(CONF_GRID_POWER))
        grid = (
            signed_grid_power_to_import_kw(raw_grid, bool(self.config[CONF_GRID_IMPORT_POSITIVE]))
            if raw_grid is not None
            else None
        )
        try:
            self.snapshot = SiteSnapshot(
                battery_soc=battery_soc,
                battery_capacity_kwh=self._configured_float(CONF_BATTERY_CAPACITY),
                battery_floor_percent=self._configured_float(CONF_BATTERY_FLOOR),
                reserve_kwh=self._configured_float(CONF_RESERVE),
                grid_power_kw=grid,
                house_load_kw=self._power(self.config.get(CONF_HOUSE_LOAD)),
                ev_soc=self._number(self.config.get(CONF_EV_SOC)),
                ev_min_current_a=self._configured_float(CONF_EV_MIN_CURRENT),
                ev_max_current_a=self._configured_float(CONF_EV_MAX_CURRENT),
                ev_voltage_v=self._configured_float(CONF_EV_VOLTAGE),
            )
        except (KeyError, TypeError, ValueError):
            return EnergyLedger(
                battery_energy_kwh=None,
                floor_energy_kwh=0,
                available_after_floor_kwh=None,
                available_after_reserve_kwh=None,
                grid_import_kw=None,
                grid_export_kw=None,
                house_load_kw=None,
                ev_max_power_kw=0,
                reason=REASON_INVALID_CONFIGURATION,
            )
        return calculate_ledger(self.snapshot)
