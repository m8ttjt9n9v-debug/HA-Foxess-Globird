"""Read configured entities and calculate a safe observer-only ledger."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from math import isfinite

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_FLOOR,
    CONF_BATTERY_SOC,
    CONF_EV_MAX_CURRENT,
    CONF_EV_MIN_CURRENT,
    CONF_EV_SOC,
    CONF_EV_VOLTAGE,
    CONF_FREE_CHARGE_END,
    CONF_FREE_CHARGE_START,
    CONF_GRID_IMPORT_POSITIVE,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_RESERVE,
    DOMAIN,
    REASON_INVALID_CONFIGURATION,
)
from .models import EnergyLedger, SiteSnapshot
from .normalise import energy_to_kwh, percent, power_to_kw, signed_grid_power_to_import_kw
from .planner.learning import DemandCycleSampler, DemandHistory, DemandLearningResult
from .planner.ledger import calculate_ledger

_LOGGER = logging.getLogger(__name__)


class EnergyCoordinator(DataUpdateCoordinator[EnergyLedger]):
    """Coordinator that deliberately performs no service calls."""

    def __init__(self, hass: HomeAssistant, config: dict[str, object], entry_id: str) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=30))
        self.config = config
        self.snapshot: SiteSnapshot | None = None
        self.demand_history = DemandHistory([])
        self.demand_sampler = self._create_demand_sampler(config)
        self._demand_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.demand_history", private=True
        )
        self._unsub_source_updates: CALLBACK_TYPE | None = async_track_state_change_event(
            hass,
            tuple(
                entity_id
                for key in (
                    CONF_BATTERY_SOC,
                    CONF_BATTERY_CAPACITY_ENTITY,
                    CONF_GRID_POWER,
                    CONF_HOUSE_LOAD,
                    CONF_EV_SOC,
                )
                if (entity_id := config.get(key))
            ),
            self._async_source_changed,
        )

    async def async_load_demand_history(self) -> None:
        """Load and validate the rolling learner history from HA storage."""
        payload = await self._demand_store.async_load()
        self.demand_history = DemandHistory.from_payload(payload, dt_util.utcnow())

    async def async_record_demand_cycle(
        self, energy_kwh: float, observed_at: datetime | None = None
    ) -> None:
        """Persist one completed protected-demand cycle for future planning."""
        observed_at = observed_at or dt_util.utcnow()
        self.demand_history.add(observed_at, energy_kwh)
        await self._demand_store.async_save(self.demand_history.to_payload())
        if self.data is not None:
            self.async_update_listeners()

    @staticmethod
    def _create_demand_sampler(config: dict[str, object]) -> DemandCycleSampler | None:
        """Create a sampler only when both commissioned window times are valid."""
        try:
            start_value = config[CONF_FREE_CHARGE_START]
            end_value = config[CONF_FREE_CHARGE_END]
            start = (
                start_value
                if isinstance(start_value, time)
                else time.fromisoformat(str(start_value))
            )
            end = end_value if isinstance(end_value, time) else time.fromisoformat(str(end_value))
            return DemandCycleSampler(start, end)
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def learning_result(self) -> DemandLearningResult:
        """Return the learned budget and warm-up evidence."""
        try:
            fallback = float(self.config.get("house_learning_fallback_kwh", 0.0))
        except (TypeError, ValueError):
            fallback = 0.0
        if not isfinite(fallback) or fallback < 0:
            fallback = 0.0
        return self.demand_history.select(fallback)

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

    def _energy(self, entity_id: str | None) -> float | None:
        value = self._number(entity_id)
        if value is None or not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        try:
            unit = state.attributes.get("unit_of_measurement") if state else None
            return energy_to_kwh(value, unit)
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
            configured_capacity = self._configured_float(CONF_BATTERY_CAPACITY)
            measured_capacity = self._energy(self.config.get(CONF_BATTERY_CAPACITY_ENTITY))
            effective_capacity = (
                measured_capacity
                if measured_capacity is not None and measured_capacity > 0
                else configured_capacity
            )
            self.snapshot = SiteSnapshot(
                battery_soc=battery_soc,
                battery_capacity_kwh=effective_capacity,
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
                battery_potential_capacity_kwh=None,
                floor_energy_kwh=0,
                available_after_floor_kwh=None,
                available_after_reserve_kwh=None,
                grid_import_kw=None,
                grid_export_kw=None,
                house_load_kw=None,
                ev_max_power_kw=0,
                reason=REASON_INVALID_CONFIGURATION,
            )
        ledger = calculate_ledger(self.snapshot)
        await self._async_sample_house_load()
        return ledger

    async def _async_sample_house_load(self) -> None:
        """Feed qualified house-load readings into the rolling sampler."""
        if self.demand_sampler is None or self.snapshot is None:
            return
        house_load_kw = self.snapshot.house_load_kw
        if house_load_kw is None:
            return
        sample = self.demand_sampler.observe(dt_util.utcnow(), house_load_kw)
        if sample is None:
            return
        self.demand_history.add(sample.observed_at, sample.energy_kwh)
        await self._demand_store.async_save(self.demand_history.to_payload())
