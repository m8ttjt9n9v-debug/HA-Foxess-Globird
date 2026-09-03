"""Read configured entities and calculate a safe observer-by-default ledger."""

from __future__ import annotations

import logging
from dataclasses import replace
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
    CONF_BONUS_WINDOW_END,
    CONF_BONUS_WINDOW_START,
    CONF_DAILY_CHARGE,
    CONF_DAILY_FREE_ALLOWANCE_KWH,
    CONF_DAILY_IMPORT_ENTITY,
    CONF_EV_MAX_CURRENT,
    CONF_EV_MIN_CURRENT,
    CONF_EV_PHASE_COUNT,
    CONF_EV_SOC,
    CONF_EV_VOLTAGE,
    CONF_EXPORT_LIMIT_KW,
    CONF_FREE_CHARGE_END,
    CONF_FREE_CHARGE_FULL_BATTERY_IMPORT_THRESHOLD_KWH,
    CONF_FREE_CHARGE_START,
    CONF_GRID_IMPORT_POSITIVE,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_OFFPEAK_BALANCE_RATE,
    CONF_OFFPEAK_RATE,
    CONF_PEAK_RATE,
    CONF_PEAK_WINDOW_END,
    CONF_PEAK_WINDOW_START,
    CONF_RESERVE,
    CONF_SERVICE_IMPORT_LIMIT_A,
    CONF_SHOULDER_RATE,
    CONF_SITE_PHASE_COUNT,
    CONF_SOLAR_POWER,
    CONF_ZERO_IMPORT_CONFIRM_MINUTES,
    CONF_ZERO_IMPORT_THRESHOLD_KW,
    DEFAULT_BONUS_WINDOW_END,
    DEFAULT_BONUS_WINDOW_START,
    DEFAULT_DAILY_CHARGE,
    DEFAULT_DAILY_FREE_ALLOWANCE_KWH,
    DEFAULT_EV_PHASE_COUNT,
    DEFAULT_EXPORT_LIMIT_KW,
    DEFAULT_INVERTER_CHARGE_LIMIT_KW,
    DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
    DEFAULT_OFFPEAK_BALANCE_RATE,
    DEFAULT_OFFPEAK_RATE,
    DEFAULT_PEAK_RATE,
    DEFAULT_PEAK_WINDOW_END,
    DEFAULT_PEAK_WINDOW_START,
    DEFAULT_SERVICE_IMPORT_LIMIT_A,
    DEFAULT_SHOULDER_RATE,
    DEFAULT_SITE_PHASE_COUNT,
    DEFAULT_ZERO_IMPORT_CONFIRM_MINUTES,
    DEFAULT_ZERO_IMPORT_THRESHOLD_KW,
    DOMAIN,
    REASON_INVALID_CONFIGURATION,
)
from .models import EnergyLedger, SiteSnapshot
from .normalise import energy_to_kwh, percent, power_to_kw, signed_grid_power_to_import_kw
from .planner.daily_meter import (
    DailyImportAccumulator,
    HourlyWindowImportAccumulator,
    WindowImportAccumulator,
)
from .planner.free_charge import (
    FreeChargeCompletion,
    FreeChargePowerPlan,
    calculate_free_charge_power,
    decide_free_charge_completion,
)
from .planner.learning import (
    DemandCycleSampler,
    DemandHistory,
    DemandLearningResult,
    remaining_protected_cycle_budget_kwh,
)
from .planner.ledger import calculate_ledger
from .planner.tariff import calculate_daily_energy_cost, calculate_tariff_guard

_LOGGER = logging.getLogger(__name__)


class EnergyCoordinator(DataUpdateCoordinator[EnergyLedger]):
    """Coordinator that deliberately performs no service calls."""

    def __init__(self, hass: HomeAssistant, config: dict[str, object], entry_id: str) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=30))
        self.config = config
        self.active_controller = None
        self.snapshot: SiteSnapshot | None = None
        self.demand_history = DemandHistory([])
        self.demand_sampler = self._create_demand_sampler(config)
        self._zero_import_since: datetime | None = None
        self.daily_import = DailyImportAccumulator()
        self.free_window_import = WindowImportAccumulator(
            window_start=self._configured_time(CONF_FREE_CHARGE_START, "12:01:00"),
            window_end=self._configured_time(CONF_FREE_CHARGE_END, "14:59:00"),
        )
        self.peak_import = WindowImportAccumulator(
            window_start=self._configured_time(CONF_PEAK_WINDOW_START, DEFAULT_PEAK_WINDOW_START),
            window_end=self._configured_time(CONF_PEAK_WINDOW_END, DEFAULT_PEAK_WINDOW_END),
        )
        self.zerohero_import = HourlyWindowImportAccumulator(
            window_start=self._configured_time(CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START),
            window_end=self._configured_time(CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END),
        )
        self._daily_import_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.daily_import", private=True
        )
        self._daily_import_last_saved: float | None = None
        self._free_import_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.free_window_import", private=True
        )
        self._peak_import_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.peak_import", private=True
        )
        self._zerohero_import_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.zerohero_hourly_import", private=True
        )
        self._free_import_last_saved: float | None = None
        self._peak_import_last_saved: float | None = None
        self._zerohero_import_last_saved: float | None = None
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
                    CONF_DAILY_IMPORT_ENTITY,
                    CONF_HOUSE_LOAD,
                    CONF_SOLAR_POWER,
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

    async def async_load_daily_import(self) -> None:
        """Load the persisted same-day import accumulator."""
        self.daily_import.restore(await self._daily_import_store.async_load(), dt_util.now())
        now = dt_util.now()
        self.free_window_import.restore(await self._free_import_store.async_load(), now)
        self.peak_import.restore(await self._peak_import_store.async_load(), now)
        self.zerohero_import.restore(await self._zerohero_import_store.async_load(), now)

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

    def _configured_time(self, key: str, default: str) -> time:
        """Parse a local-time setting, falling back only for legacy entries."""
        try:
            return time.fromisoformat(str(self.config.get(key, default)))
        except (TypeError, ValueError):
            return time.fromisoformat(default)

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

    @property
    def learning_remaining_kwh(self) -> float | None:
        """Return the learned/fallback budget remaining before free power."""
        if self.demand_sampler is None:
            return None
        learning = self.learning_result
        try:
            return remaining_protected_cycle_budget_kwh(
                learning.cycle_budget_kwh,
                dt_util.now(),
                self.demand_sampler.free_window_start,
                self.demand_sampler.free_window_end,
            )
        except ValueError:
            return None

    @property
    def free_charge_plan(self) -> FreeChargePowerPlan | None:
        """Return a read-only allowance-paced charge target when evidence exists."""
        if self.snapshot is None or self.data is None:
            return None
        imported = self.data.free_window_import_kwh
        house = self.snapshot.house_load_kw
        solar = self._power(self.config.get(CONF_SOLAR_POWER))
        if imported is None or house is None or solar is None:
            return None
        try:
            allowance = self._configured_nonnegative(
                CONF_DAILY_FREE_ALLOWANCE_KWH, DEFAULT_DAILY_FREE_ALLOWANCE_KWH
            )
            limit = self._configured_nonnegative(
                CONF_INVERTER_CHARGE_LIMIT_KW, DEFAULT_INVERTER_CHARGE_LIMIT_KW
            )
            now = dt_util.now()
            hours_remaining = self._free_window_hours_remaining(now)
            return calculate_free_charge_power(
                allowance_remaining_kwh=max(allowance - imported, 0.0),
                hours_remaining=hours_remaining,
                house_load_kw=max(house, 0.0),
                pv_generation_kw=max(solar, 0.0),
                inverter_charge_limit_kw=limit,
            )
        except (TypeError, ValueError):
            return None

    @property
    def free_charge_completion(self) -> FreeChargeCompletion | None:
        """Return the mode outcome for a completed free-window charge."""
        if self.snapshot is None or self.data is None:
            return None
        imported = self.data.free_window_import_kwh
        soc = self.snapshot.battery_soc
        if imported is None or soc is None:
            return None
        try:
            return decide_free_charge_completion(
                imported_kwh=imported,
                battery_soc=soc,
                daily_allowance_kwh=self._configured_nonnegative(
                    CONF_DAILY_FREE_ALLOWANCE_KWH, DEFAULT_DAILY_FREE_ALLOWANCE_KWH
                ),
                full_battery_import_threshold_kwh=self._configured_nonnegative(
                    CONF_FREE_CHARGE_FULL_BATTERY_IMPORT_THRESHOLD_KWH, 49.0
                ),
            )
        except (TypeError, ValueError):
            return None

    def _free_window_hours_remaining(self, now: datetime) -> float:
        """Return remaining hours in today's configured free-charge window."""
        start = self._configured_time(CONF_FREE_CHARGE_START, "12:01:00")
        end = self._configured_time(CONF_FREE_CHARGE_END, "14:59:00")
        current = now.timetz().replace(tzinfo=None)
        if start < end:
            if not start <= current < end:
                return 0.0
            finish = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
        else:
            if current >= end and current < start:
                return 0.0
            finish = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
            if current >= start:
                finish += timedelta(days=1)
        return max(0.0, (finish - now).total_seconds() / 3600)

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

    def _configured_phase_count(self) -> int:
        """Read the explicitly commissioned one- or three-phase EV topology."""
        value = float(self.config.get(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT))
        if not isfinite(value) or value not in (1, 3):
            raise ValueError(f"{CONF_EV_PHASE_COUNT} must be 1 or 3")
        return int(value)

    def _configured_site_phase_count(self) -> int:
        """Read the commissioned supply topology without inferring it from power."""
        value = float(self.config.get(CONF_SITE_PHASE_COUNT, DEFAULT_SITE_PHASE_COUNT))
        if not isfinite(value) or value not in (1, 3):
            raise ValueError(f"{CONF_SITE_PHASE_COUNT} must be 1 or 3")
        return int(value)

    def _configured_nonnegative(self, key: str, default: float) -> float:
        """Read an optional physical limit; zero means not commissioned."""
        value = float(self.config.get(key, default))
        if not isfinite(value) or value < 0:
            raise ValueError(f"{key} must be finite and non-negative")
        return value

    def _bonus_window_active(self, now: datetime) -> bool:
        """Evaluate the configured local-time bonus window, including overnight windows."""
        try:
            start_value = self.config.get(CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START)
            end_value = self.config.get(CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END)
            start = (
                start_value
                if isinstance(start_value, time)
                else time.fromisoformat(str(start_value))
            )
            end = (
                end_value if isinstance(end_value, time) else time.fromisoformat(str(end_value))
            )
        except (TypeError, ValueError):
            return False
        current = now.timetz().replace(tzinfo=None)
        if start == end:
            return False
        return (start <= current < end) if start < end else (current >= start or current < end)

    def _bonus_window_elapsed_hours(self, now: datetime) -> float:
        """Return elapsed local time in the active ZEROHERO window."""
        if not self._bonus_window_active(now):
            return 0.0
        start = self._configured_time(CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START)
        end = self._configured_time(CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END)
        start_at = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
        if end <= start and now.timetz().replace(tzinfo=None) < end:
            start_at -= timedelta(days=1)
        return max(0.0, (now - start_at).total_seconds() / 3600)

    def _zero_import_duration_minutes(self, grid_import_kw: float | None, now: datetime) -> float:
        """Track only continuous qualified zero-import time for the bonus guard."""
        threshold = self._configured_nonnegative(
            CONF_ZERO_IMPORT_THRESHOLD_KW, DEFAULT_ZERO_IMPORT_THRESHOLD_KW
        )
        if grid_import_kw is None or grid_import_kw > threshold:
            self._zero_import_since = None
            return 0.0
        if self._zero_import_since is None:
            self._zero_import_since = now
            return 0.0
        return max(0.0, (now - self._zero_import_since).total_seconds() / 60)

    def _apply_tariff_guard(self, ledger: EnergyLedger) -> EnergyLedger:
        """Add read-only tariff evidence using external or internal daily import."""
        configured_daily_import = self._energy(self.config.get(CONF_DAILY_IMPORT_ENTITY))
        daily_import = (
            configured_daily_import
            if configured_daily_import is not None
            else (self.daily_import.imported_kwh if self.daily_import.last_at else None)
        )
        daily_source = (
            "configured_entity"
            if configured_daily_import is not None
            else "internal_accumulator"
        )
        free_import = (
            self.free_window_import.imported_kwh if self.free_window_import.last_at else None
        )
        if daily_import is None or free_import is None:
            return replace(
                ledger,
                tariff_reason="daily_import_meter_unavailable",
                daily_import_kwh=daily_import,
                daily_import_source=daily_source if daily_import is not None else "unavailable",
                free_window_import_kwh=free_import,
            )
        try:
            allowance = self._configured_nonnegative(
                CONF_DAILY_FREE_ALLOWANCE_KWH, DEFAULT_DAILY_FREE_ALLOWANCE_KWH
            )
            confirmation = self._configured_nonnegative(
                CONF_ZERO_IMPORT_CONFIRM_MINUTES, DEFAULT_ZERO_IMPORT_CONFIRM_MINUTES
            )
            now = dt_util.now()
            decision = calculate_tariff_guard(
                daily_free_allowance_kwh=allowance,
                imported_today_kwh=free_import,
                requested_free_charge_kwh=max(allowance - free_import, 0.0),
                bonus_window_active=self._bonus_window_active(now),
                grid_import_kw=ledger.grid_import_kw,
                grid_telemetry_valid=ledger.grid_import_kw is not None,
                zero_import_minutes=self._zero_import_duration_minutes(
                    ledger.grid_import_kw, now
                ),
                zero_import_threshold_kw=self._configured_nonnegative(
                    CONF_ZERO_IMPORT_THRESHOLD_KW, DEFAULT_ZERO_IMPORT_THRESHOLD_KW
                ),
                minimum_zero_import_minutes=confirmation,
                zerohero_hourly_import_kwh=tuple(self.zerohero_import.hourly_import_kwh.values()),
                zerohero_window_elapsed_hours=self._bonus_window_elapsed_hours(now),
            )
        except (TypeError, ValueError):
            return replace(ledger, tariff_reason="tariff_configuration_invalid")
        return replace(
            ledger,
            free_energy_remaining_kwh=decision.free_energy_remaining_kwh,
            free_charge_allowed_kwh=decision.free_charge_energy_kwh,
            bonus_zero_import_allowed=decision.bonus_zero_import_allowed,
            tariff_reason=decision.reason,
            daily_import_kwh=daily_import,
            daily_import_source=daily_source,
            free_window_import_kwh=free_import,
            estimated_energy_cost=calculate_daily_energy_cost(
                total_import_kwh=self.daily_import.imported_kwh,
                free_window_import_kwh=free_import,
                peak_import_kwh=self.peak_import.imported_kwh,
                free_allowance_kwh=allowance,
                peak_rate=self._configured_nonnegative(CONF_PEAK_RATE, DEFAULT_PEAK_RATE),
                offpeak_rate=self._configured_nonnegative(CONF_OFFPEAK_RATE, DEFAULT_OFFPEAK_RATE),
                offpeak_balance_rate=self._configured_nonnegative(
                    CONF_OFFPEAK_BALANCE_RATE, DEFAULT_OFFPEAK_BALANCE_RATE
                ),
                shoulder_rate=self._configured_nonnegative(
                    CONF_SHOULDER_RATE, DEFAULT_SHOULDER_RATE
                ),
                daily_charge=self._configured_nonnegative(CONF_DAILY_CHARGE, DEFAULT_DAILY_CHARGE),
            ),
        )

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
        now = dt_util.now()
        if self.daily_import.observe(grid, now):
            # Persist at useful increments rather than writing HA storage on
            # every 30-second coordinator refresh.
            if (
                self._daily_import_last_saved is None
                or self.daily_import.imported_kwh < self._daily_import_last_saved
                or self.daily_import.imported_kwh - self._daily_import_last_saved >= 0.05
            ):
                await self._daily_import_store.async_save(self.daily_import.to_payload())
                self._daily_import_last_saved = self.daily_import.imported_kwh
        if self.free_window_import.observe(grid, now):
            if (
                self._free_import_last_saved is None
                or self.free_window_import.imported_kwh < self._free_import_last_saved
                or self.free_window_import.imported_kwh - self._free_import_last_saved >= 0.05
            ):
                await self._free_import_store.async_save(self.free_window_import.to_payload())
                self._free_import_last_saved = self.free_window_import.imported_kwh
        if self.peak_import.observe(grid, now):
            if (
                self._peak_import_last_saved is None
                or self.peak_import.imported_kwh < self._peak_import_last_saved
                or self.peak_import.imported_kwh - self._peak_import_last_saved >= 0.05
            ):
                await self._peak_import_store.async_save(self.peak_import.to_payload())
                self._peak_import_last_saved = self.peak_import.imported_kwh
        if self.zerohero_import.observe(grid, now):
            zerohero_total = sum(self.zerohero_import.hourly_import_kwh.values())
            last_zerohero_total = self._zerohero_import_last_saved or 0.0
            if (
                self._zerohero_import_last_saved is None
                or zerohero_total < last_zerohero_total
                or zerohero_total - last_zerohero_total >= 0.01
            ):
                await self._zerohero_import_store.async_save(self.zerohero_import.to_payload())
                self._zerohero_import_last_saved = zerohero_total
        try:
            configured_capacity = self._configured_float(CONF_BATTERY_CAPACITY)
            measured_capacity = self._energy(self.config.get(CONF_BATTERY_CAPACITY_ENTITY))
            effective_capacity = (
                measured_capacity if measured_capacity is not None and measured_capacity > 0
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
                ev_phase_count=self._configured_phase_count(),
                site_phase_count=self._configured_site_phase_count(),
                service_import_limit_a=self._configured_nonnegative(
                    CONF_SERVICE_IMPORT_LIMIT_A, DEFAULT_SERVICE_IMPORT_LIMIT_A
                ),
                export_limit_kw=self._configured_nonnegative(
                    CONF_EXPORT_LIMIT_KW, DEFAULT_EXPORT_LIMIT_KW
                ),
                inverter_charge_limit_kw=self._configured_nonnegative(
                    CONF_INVERTER_CHARGE_LIMIT_KW, DEFAULT_INVERTER_CHARGE_LIMIT_KW
                ),
                inverter_discharge_limit_kw=self._configured_nonnegative(
                    CONF_INVERTER_DISCHARGE_LIMIT_KW, DEFAULT_INVERTER_DISCHARGE_LIMIT_KW
                ),
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
        ledger = self._apply_tariff_guard(calculate_ledger(self.snapshot))
        await self._async_sample_house_load()
        return ledger

    async def _async_sample_house_load(self) -> None:
        """Feed qualified house-load readings into the rolling sampler."""
        if self.demand_sampler is None or self.snapshot is None:
            return
        house_load_kw = self.snapshot.house_load_kw
        if house_load_kw is None:
            return
        # Window boundaries are configured as local site time (for this
        # project, Australia).  Using UTC here would shift a 12:01–14:59
        # window by ten or eleven hours and silently learn the wrong period.
        sample = self.demand_sampler.observe(dt_util.now(), house_load_kw)
        if sample is None:
            return
        self.demand_history.add(sample.observed_at, sample.energy_kwh)
        await self._demand_store.async_save(self.demand_history.to_payload())
