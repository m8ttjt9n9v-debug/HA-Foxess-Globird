"""Read configured entities and calculate a safe observer-by-default ledger."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from math import isfinite

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .configuration import RuntimeConfiguration
from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_FLOOR,
    CONF_BONUS_WINDOW_END,
    CONF_BONUS_WINDOW_START,
    CONF_DAILY_CHARGE,
    CONF_DAILY_FREE_ALLOWANCE_KWH,
    CONF_EV_MAX_CURRENT,
    CONF_EV_MIN_CURRENT,
    CONF_EV_PHASE_COUNT,
    CONF_EV_VOLTAGE,
    CONF_EXPORT_ALLOWANCE_KWH,
    CONF_EXPORT_LIMIT_KW,
    CONF_EXPORT_RATE,
    CONF_EXPORT_RATE_WINDOW_END,
    CONF_EXPORT_RATE_WINDOW_START,
    CONF_FREE_CHARGE_END,
    CONF_FREE_CHARGE_START,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_OFFPEAK_BALANCE_RATE,
    CONF_OFFPEAK_EXPORT_RATE,
    CONF_OFFPEAK_RATE,
    CONF_PEAK_RATE,
    CONF_PEAK_WINDOW_END,
    CONF_PEAK_WINDOW_START,
    CONF_RESERVE,
    CONF_SERVICE_IMPORT_LIMIT_A,
    CONF_SHOULDER_RATE,
    CONF_SITE_PHASE_COUNT,
    CONF_SUPER_EXPORT_RATE,
    CONF_ZERO_IMPORT_CONFIRM_MINUTES,
    CONF_ZERO_IMPORT_THRESHOLD_KW,
    CONF_ZEROHERO_DAILY_CREDIT,
    DEFAULT_BONUS_WINDOW_END,
    DEFAULT_BONUS_WINDOW_START,
    DEFAULT_DAILY_CHARGE,
    DEFAULT_DAILY_FREE_ALLOWANCE_KWH,
    DEFAULT_EXPORT_ALLOWANCE_KWH,
    DEFAULT_EXPORT_LIMIT_KW,
    DEFAULT_EXPORT_RATE,
    DEFAULT_EXPORT_RATE_WINDOW_END,
    DEFAULT_EXPORT_RATE_WINDOW_START,
    DEFAULT_FORECAST_EXPORT_REALISATION,
    DEFAULT_FREE_CHARGE_END,
    DEFAULT_FREE_CHARGE_START,
    DEFAULT_HOUSE_AWAY_FALLBACK_KWH,
    DEFAULT_HOUSE_LEARNING_FALLBACK_KWH,
    DEFAULT_INVERTER_CHARGE_LIMIT_KW,
    DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
    DEFAULT_OFFPEAK_BALANCE_RATE,
    DEFAULT_OFFPEAK_EXPORT_RATE,
    DEFAULT_OFFPEAK_RATE,
    DEFAULT_PEAK_RATE,
    DEFAULT_PEAK_WINDOW_END,
    DEFAULT_PEAK_WINDOW_START,
    DEFAULT_SERVICE_IMPORT_LIMIT_A,
    DEFAULT_SHOULDER_RATE,
    DEFAULT_SUPER_EXPORT_RATE,
    DEFAULT_ZERO_IMPORT_CONFIRM_MINUTES,
    DEFAULT_ZERO_IMPORT_THRESHOLD_KW,
    DEFAULT_ZEROHERO_DAILY_CREDIT,
    DOMAIN,
    REASON_INVALID_CONFIGURATION,
)
from .models import EnergyLedger, SiteSnapshot
from .normalise import current_to_a, percent
from .persistence import TypedStoreRepository, TypedValueStoreRepository
from .planner.accounting import (
    AccountingMeterSnapshot,
    AccountingProjectionInputs,
    TariffConfiguration,
    ZeroHeroWindowEvidence,
    ZeroImportDurationTracker,
    project_daily_accounting,
    window_active,
    window_credit_state,
    window_elapsed_hours,
    window_hours_remaining,
)
from .planner.daily_meter import (
    DailyImportAccumulator,
    HourlyWindowImportAccumulator,
    WindowImportAccumulator,
)
from .planner.forecast import (
    ForecastFeedbackState,
    ForecastFinancialInputs,
    OptimisticCostForecast,
    calculate_tariffed_optimistic_forecast,
    match_retailer_scorecard,
    window_overlap_fraction,
)
from .planner.learning import (
    DailyDemandCycleSampler,
    DemandCycleSampler,
    DemandHistory,
    DemandLearningResult,
    DemandPersistenceState,
    HouseBudgetResult,
    HouseLearningObservation,
    OccupancyResult,
    advance_house_learning,
    classify_energy_occupancy,
    protected_base_house_power_kw,
    remaining_protected_cycle_budget_kwh,
    select_house_cycle_budget,
)
from .planner.ledger import calculate_ledger
from .planner.meter_cycle import (
    DAILY_EXPORT,
    DAILY_IMPORT,
    FREE_WINDOW_IMPORT,
    PEAK_IMPORT,
    STANDARD_RATE_EXPORT,
    ZEROHERO_EXPORT,
    ZEROHERO_IMPORT,
    AccountingMeterSet,
    MeterCheckpointRequest,
    MeterCheckpointState,
    advance_accounting_meters,
)
from .telemetry import (
    NormalizedTelemetry,
    TelemetryNormalizationConfiguration,
    TelemetrySource,
    normalize_site_telemetry,
)
from .telemetry_adapter import (
    TelemetryEntityIds,
    capture_occupancy_people,
    capture_retailer_scorecard,
    capture_site_telemetry,
    capture_telemetry_source,
    read_energy_kwh,
    read_finite_number,
    read_fresh_power_kw,
    read_power_kw,
    state_reported_at,
)

_LOGGER = logging.getLogger(__name__)


class EnergyCoordinator(DataUpdateCoordinator[EnergyLedger]):
    """Coordinator that deliberately performs no service calls."""

    def __init__(self, hass: HomeAssistant, config: dict[str, object], entry_id: str) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=30))
        self.config = config
        self.runtime_config = RuntimeConfiguration.from_mapping(config)
        self.entry_id = entry_id
        self.active_controller = None
        self.ev_controller = None
        self.snapshot: SiteSnapshot | None = None
        self.telemetry: NormalizedTelemetry | None = None
        self.demand_history = DemandHistory([])
        self.demand_sampler = self._create_demand_sampler()
        self.heater_history = DemandHistory([])
        self.heater_sampler = self._create_heater_sampler()
        self._zero_import_tracker = ZeroImportDurationTracker()
        self.daily_import = DailyImportAccumulator()
        self.daily_export = DailyImportAccumulator()
        self.standard_rate_export = WindowImportAccumulator(
            window_start=self._configured_time(
                CONF_EXPORT_RATE_WINDOW_START, DEFAULT_EXPORT_RATE_WINDOW_START
            ),
            window_end=self._configured_time(
                CONF_EXPORT_RATE_WINDOW_END, DEFAULT_EXPORT_RATE_WINDOW_END
            ),
        )
        self.free_window_import = WindowImportAccumulator(
            window_start=self._configured_time(CONF_FREE_CHARGE_START, DEFAULT_FREE_CHARGE_START),
            window_end=self._configured_time(CONF_FREE_CHARGE_END, DEFAULT_FREE_CHARGE_END),
        )
        self.peak_import = WindowImportAccumulator(
            window_start=self._configured_time(CONF_PEAK_WINDOW_START, DEFAULT_PEAK_WINDOW_START),
            window_end=self._configured_time(CONF_PEAK_WINDOW_END, DEFAULT_PEAK_WINDOW_END),
        )
        self.zerohero_import = HourlyWindowImportAccumulator(
            window_start=self._configured_time(CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START),
            window_end=self._configured_time(CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END),
        )
        self.zerohero_export = WindowImportAccumulator(
            window_start=self._configured_time(CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START),
            window_end=self._configured_time(CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END),
        )
        self._daily_import_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.daily_import", private=True
        )
        self._daily_import_repository = TypedStoreRepository(self._daily_import_store)
        self._daily_import_last_saved: float | None = None
        self._daily_export_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.daily_export", private=True
        )
        self._daily_export_repository = TypedStoreRepository(self._daily_export_store)
        self._daily_export_last_saved: float | None = None
        self._standard_rate_export_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.standard_rate_export", private=True
        )
        self._standard_rate_export_repository = TypedStoreRepository(
            self._standard_rate_export_store
        )
        self._standard_rate_export_last_saved: float | None = None
        self._free_import_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.free_window_import", private=True
        )
        self._free_import_repository = TypedStoreRepository(self._free_import_store)
        self._peak_import_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.peak_import", private=True
        )
        self._peak_import_repository = TypedStoreRepository(self._peak_import_store)
        self._zerohero_import_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.zerohero_hourly_import", private=True
        )
        self._zerohero_import_repository = TypedStoreRepository(
            self._zerohero_import_store
        )
        self._zerohero_export_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.zerohero_export", private=True
        )
        self._zerohero_export_repository = TypedStoreRepository(
            self._zerohero_export_store
        )
        self._free_import_last_saved: float | None = None
        self._peak_import_last_saved: float | None = None
        self._zerohero_import_last_saved: float | None = None
        self._zerohero_export_last_saved: float | None = None
        self._demand_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.demand_history", private=True
        )
        self._demand_repository = TypedValueStoreRepository(
            self._demand_store,
            decode=lambda payload: DemandPersistenceState.restore(
                payload, dt_util.utcnow()
            ),
            encode=DemandPersistenceState.to_payload,
        )
        self._forecast_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.forecast_feedback", private=True
        )
        self._forecast_repository = TypedValueStoreRepository(
            self._forecast_store,
            decode=lambda payload: ForecastFeedbackState.restore(
                payload,
                today=dt_util.now().date(),
                default_fraction=DEFAULT_FORECAST_EXPORT_REALISATION,
            ),
            encode=ForecastFeedbackState.to_payload,
        )
        self.forecast_feedback = ForecastFeedbackState.restore(
            None,
            today=dt_util.now().date(),
            default_fraction=DEFAULT_FORECAST_EXPORT_REALISATION,
        )
        self.optimistic_forecast: OptimisticCostForecast | None = None
        self.forecast_scorecard_status = "not_configured"
        self.forecast_scorecard_date: date | None = None

        self._forecast_last_saved_signature: tuple[object, ...] | None = None
        self._demand_sampler_last_saved_at: datetime | None = None
        self._unsub_source_updates: CALLBACK_TYPE | None = async_track_state_change_event(
            hass,
            tuple(
                entity_id
                for entity_id in (
                    self.runtime_config.battery.soc_entity,
                    self.runtime_config.battery.capacity_entity,
                    self.runtime_config.power_sources.battery_entity,
                    self.runtime_config.battery.charge_power_entity,
                    self.runtime_config.battery.discharge_power_entity,
                    self.runtime_config.power_sources.grid_entity,
                    self.runtime_config.accounting.daily_import_entity,
                    self.runtime_config.accounting.retailer_daily_cost_entity,
                    self.runtime_config.accounting.retailer_zerohero_status_entity,
                    self.runtime_config.power_sources.house_load_entity,
                    self.runtime_config.house.heater_power_entity,
                    self.runtime_config.power_sources.solar_entity,
                    self.runtime_config.site.grid_current_entity,
                    *self.runtime_config.site.phase_power_entities,
                    *self.runtime_config.site.phase_voltage_entities,
                    self.runtime_config.ev_telemetry.soc_entity,
                    self.runtime_config.ev_telemetry.charging_state_entity,
                    self.runtime_config.ev_telemetry.actual_current_entity,
                )
                if entity_id
            ),
            self._async_source_changed,
        )

    def update_config_value(
        self,
        key: str,
        value: object,
        *,
        remove_key: str | None = None,
    ) -> None:
        """Atomically update the live mirror and rebuild its typed snapshot."""
        if remove_key is not None:
            self.config.pop(remove_key, None)
        self.config[key] = value
        self.runtime_config = RuntimeConfiguration.from_mapping(self.config)

    def update_persisted_config_value(
        self,
        entry: ConfigEntry,
        key: str,
        value: object,
        *,
        remove_key: str | None = None,
    ) -> None:
        """Persist one operator value and update the live snapshot atomically."""
        data = dict(entry.data)
        if remove_key is not None:
            data.pop(remove_key, None)
        data[key] = value
        self.hass.config_entries.async_update_entry(entry, data=data)
        self.update_config_value(key, value, remove_key=remove_key)

    async def async_load_demand_history(self) -> None:
        """Load and validate the rolling learner history from HA storage."""
        state = await self._demand_repository.async_load()
        self.demand_history = state.demand_history
        self.heater_history = state.heater_history
        if self.demand_sampler is not None:
            self.demand_sampler.restore(state.in_progress_cycle, dt_util.now())
        if self.heater_sampler is not None:
            self.heater_sampler.restore(state.heater_in_progress_cycle, dt_util.now())

    async def async_load_daily_import(self) -> None:
        """Load the persisted same-day tariff accumulators."""
        await self._daily_import_repository.async_restore(self.daily_import, dt_util.now())
        now = dt_util.now()
        await self._daily_export_repository.async_restore(self.daily_export, now)
        await self._standard_rate_export_repository.async_restore(
            self.standard_rate_export, now
        )
        await self._free_import_repository.async_restore(self.free_window_import, now)
        await self._peak_import_repository.async_restore(self.peak_import, now)
        await self._zerohero_import_repository.async_restore(self.zerohero_import, now)
        await self._zerohero_export_repository.async_restore(self.zerohero_export, now)

    async def async_load_forecast_feedback(self) -> None:
        """Load forecast-only calibration and comparison history."""
        self.forecast_feedback = await self._forecast_repository.async_load()
        if self.forecast_feedback.roll_to(dt_util.now().date()):
            await self._async_save_forecast_feedback(force=True)

    async def async_record_demand_cycle(
        self, energy_kwh: float, observed_at: datetime | None = None
    ) -> None:
        """Persist one completed protected-demand cycle for future planning."""
        observed_at = observed_at or dt_util.utcnow()
        self.demand_history.add(observed_at, energy_kwh)
        await self._async_save_demand_state()
        if self.data is not None:
            self.async_update_listeners()

    def _create_demand_sampler(self) -> DemandCycleSampler | None:
        """Create a sampler only when both commissioned window times are valid."""
        start = self.runtime_config.windows.free_charge_start
        end = self.runtime_config.windows.free_charge_end
        if start is None or end is None:
            return None
        return DemandCycleSampler(start, end)

    def _create_heater_sampler(self) -> DailyDemandCycleSampler | None:
        """Create the separate daily heater sampler only when explicitly mapped."""
        if not self.runtime_config.house.heater_power_entity:
            return None
        start = self.runtime_config.windows.free_charge_start
        if start is None:
            return None
        return DailyDemandCycleSampler(start)

    def _configured_time(self, key: str, default: str) -> time:
        """Parse a local-time setting, falling back only for legacy entries."""
        return self.runtime_config.windows.time_for_legacy_key(key, default)

    @property
    def occupancy_result(self) -> OccupancyResult:
        """Return the canonical conservative occupancy classification."""
        people = capture_occupancy_people(self.hass)
        house = self.runtime_config.house
        confirmation = house.away_confirmation_hours
        if confirmation is not None:
            return classify_energy_occupancy(
                house.occupancy_mode_input,
                people,
                dt_util.now(),
                confirmation,
            )
        return classify_energy_occupancy("home", people, dt_util.now(), 0)

    @property
    def base_learning_result(self) -> DemandLearningResult:
        """Return the independent mapped base/whole-house P80 stream."""
        fallback = self.runtime_config.house.learning_fallback_kwh
        if fallback is None:
            fallback = DEFAULT_HOUSE_LEARNING_FALLBACK_KWH
        if not isfinite(fallback) or fallback < 0:
            fallback = DEFAULT_HOUSE_LEARNING_FALLBACK_KWH
        return self.demand_history.select(fallback)

    @property
    def heater_learning_result(self) -> DemandLearningResult | None:
        """Return the optional separate heater P80 stream."""
        if self.heater_sampler is None:
            return None
        return self.heater_history.select(0.0)

    @property
    def learning_result(self) -> HouseBudgetResult:
        """Return the one occupancy-aware protected-house budget."""
        house = self.runtime_config.house
        occupied_fallback = house.learning_fallback_kwh
        away_fallback = house.away_fallback_kwh
        if occupied_fallback is None or away_fallback is None:
            occupied_fallback = DEFAULT_HOUSE_LEARNING_FALLBACK_KWH
            away_fallback = DEFAULT_HOUSE_AWAY_FALLBACK_KWH
        if not isfinite(occupied_fallback) or occupied_fallback < 0:
            occupied_fallback = DEFAULT_HOUSE_LEARNING_FALLBACK_KWH
        if not isfinite(away_fallback) or away_fallback < 0:
            away_fallback = DEFAULT_HOUSE_AWAY_FALLBACK_KWH
        return select_house_cycle_budget(
            [sample.energy_kwh for sample in self.demand_history.samples],
            (
                [sample.energy_kwh for sample in self.heater_history.samples]
                if self.heater_sampler is not None
                else None
            ),
            occupied_fallback,
            away_fallback,
            self.occupancy_result.state,
        )

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

    def _free_window_hours_remaining(self, now: datetime) -> float:
        """Return remaining hours in today's configured free-charge window."""
        start = self._configured_time(CONF_FREE_CHARGE_START, DEFAULT_FREE_CHARGE_START)
        end = self._configured_time(CONF_FREE_CHARGE_END, DEFAULT_FREE_CHARGE_END)
        return window_hours_remaining(now, start, end)

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
        return read_finite_number(self.hass, entity_id)

    def _configured_float(self, key: str) -> float:
        """Retain required-number failure behavior during typed migration."""
        values = {
            CONF_BATTERY_CAPACITY: self.runtime_config.battery.configured_capacity_kwh,
            CONF_BATTERY_FLOOR: self.runtime_config.battery.configured_floor_percent,
            CONF_RESERVE: self.runtime_config.battery.configured_reserve_kwh,
            CONF_EV_MIN_CURRENT: self.runtime_config.ev_connection.configured_min_current_a,
            CONF_EV_MAX_CURRENT: self.runtime_config.ev_connection.configured_max_current_a,
            CONF_EV_VOLTAGE: self.runtime_config.ev_connection.configured_voltage_v,
        }
        value = values.get(key)
        if value is None or not isfinite(value):
            raise ValueError(f"{key} must be finite")
        return value

    def _configured_phase_count(self) -> int:
        """Read the explicitly commissioned EV phase count."""
        connection = self.runtime_config.ev_connection
        if not connection.phase_count_valid:
            raise ValueError(f"{CONF_EV_PHASE_COUNT} must be a positive integer")
        value = connection.phase_count
        if not isfinite(value) or value < 1 or not value.is_integer():
            raise ValueError(f"{CONF_EV_PHASE_COUNT} must be a positive integer")
        return int(value)

    def _configured_site_phase_count(self) -> int:
        """Read the commissioned supply topology without inferring it from power."""
        value = self.runtime_config.site.phase_count
        if value is None:
            raise ValueError(f"{CONF_SITE_PHASE_COUNT} must be a positive integer")
        if not isfinite(value) or value < 1 or not value.is_integer():
            raise ValueError(f"{CONF_SITE_PHASE_COUNT} must be a positive integer")
        return int(value)

    def _configured_nonnegative(self, key: str, default: float) -> float:
        """Read an optional physical limit; zero means not commissioned."""
        configured = self.runtime_config.nonnegative
        values = {
            CONF_ZERO_IMPORT_THRESHOLD_KW: configured.zero_import_threshold_kw,
            CONF_DAILY_FREE_ALLOWANCE_KWH: configured.daily_free_allowance_kwh,
            CONF_ZERO_IMPORT_CONFIRM_MINUTES: configured.zero_import_confirmation_minutes,
            CONF_ZEROHERO_DAILY_CREDIT: configured.zerohero_daily_credit,
            CONF_PEAK_RATE: configured.peak_rate_per_kwh,
            CONF_OFFPEAK_RATE: configured.offpeak_rate_per_kwh,
            CONF_OFFPEAK_BALANCE_RATE: configured.offpeak_balance_rate_per_kwh,
            CONF_SHOULDER_RATE: configured.shoulder_rate_per_kwh,
            CONF_DAILY_CHARGE: configured.daily_charge,
            CONF_EXPORT_ALLOWANCE_KWH: configured.export_allowance_kwh,
            CONF_EXPORT_RATE: configured.export_rate_per_kwh,
            CONF_OFFPEAK_EXPORT_RATE: configured.offpeak_export_rate_per_kwh,
            CONF_SUPER_EXPORT_RATE: configured.super_export_rate_per_kwh,
            CONF_SERVICE_IMPORT_LIMIT_A: configured.service_import_limit_a,
            CONF_EXPORT_LIMIT_KW: configured.export_limit_kw,
            CONF_INVERTER_CHARGE_LIMIT_KW: configured.inverter_charge_limit_kw,
            CONF_INVERTER_DISCHARGE_LIMIT_KW: configured.inverter_discharge_limit_kw,
        }
        value = values.get(key, default)
        if value is None or not isfinite(value) or value < 0:
            raise ValueError(f"{key} must be finite and non-negative")
        return value

    def _bonus_window_active(self, now: datetime) -> bool:
        """Evaluate the configured local-time bonus window, including overnight windows."""
        return window_active(
            now,
            self.runtime_config.windows.bonus_start,
            self.runtime_config.windows.bonus_end,
        )

    def _bonus_window_elapsed_hours(self, now: datetime) -> float:
        """Return elapsed local time in the active ZEROHERO window."""
        start = self._configured_time(CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START)
        end = self._configured_time(CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END)
        return window_elapsed_hours(now, start, end)

    def _zerohero_credit_window_state(self, now: datetime) -> tuple[bool, int]:
        """Return completion and clock-hour count for today's credit window."""
        start = self._configured_time(CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START)
        end = self._configured_time(CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END)
        return window_credit_state(now, start, end)

    def _zero_import_duration_minutes(self, grid_import_kw: float | None, now: datetime) -> float:
        """Track only continuous qualified zero-import time for the bonus guard."""
        threshold = self._configured_nonnegative(
            CONF_ZERO_IMPORT_THRESHOLD_KW, DEFAULT_ZERO_IMPORT_THRESHOLD_KW
        )
        return self._zero_import_tracker.observe(
            grid_import_kw,
            observed_at=now,
            threshold_kw=threshold,
        )

    def _apply_tariff_guard(self, ledger: EnergyLedger) -> EnergyLedger:
        """Add read-only tariff evidence using external or internal daily import."""
        configured_daily_import = self._energy(
            self.runtime_config.accounting.daily_import_entity
        )
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
        daily_export = self.daily_export.imported_kwh if self.daily_export.last_at else None
        standard_export = (
            self.standard_rate_export.imported_kwh
            if self.standard_rate_export.last_at
            else None
        )
        boosted_export = (
            self.zerohero_export.imported_kwh if self.zerohero_export.last_at else None
        )
        meters = AccountingMeterSnapshot(
            daily_import_kwh=daily_import,
            daily_import_source=daily_source,
            free_window_import_kwh=free_import,
            peak_import_kwh=self.peak_import.imported_kwh,
            daily_export_kwh=daily_export,
            standard_window_export_kwh=standard_export,
            boosted_window_export_kwh=boosted_export,
        )
        if daily_import is None or free_import is None:
            return project_daily_accounting(
                AccountingProjectionInputs(
                    ledger=ledger,
                    meters=meters,
                    tariff=None,
                    zerohero=None,
                )
            )
        try:
            now = dt_util.now()
            window_complete, expected_hours = self._zerohero_credit_window_state(now)
            return project_daily_accounting(
                AccountingProjectionInputs(
                    ledger=ledger,
                    meters=meters,
                    tariff=TariffConfiguration(
                        daily_free_allowance_kwh=self._configured_nonnegative(
                            CONF_DAILY_FREE_ALLOWANCE_KWH,
                            DEFAULT_DAILY_FREE_ALLOWANCE_KWH,
                        ),
                        zero_import_threshold_kw=self._configured_nonnegative(
                            CONF_ZERO_IMPORT_THRESHOLD_KW,
                            DEFAULT_ZERO_IMPORT_THRESHOLD_KW,
                        ),
                        minimum_zero_import_minutes=self._configured_nonnegative(
                            CONF_ZERO_IMPORT_CONFIRM_MINUTES,
                            DEFAULT_ZERO_IMPORT_CONFIRM_MINUTES,
                        ),
                        zerohero_daily_credit=self._configured_nonnegative(
                            CONF_ZEROHERO_DAILY_CREDIT,
                            DEFAULT_ZEROHERO_DAILY_CREDIT,
                        ),
                        peak_rate=self._configured_nonnegative(
                            CONF_PEAK_RATE, DEFAULT_PEAK_RATE
                        ),
                        offpeak_rate=self._configured_nonnegative(
                            CONF_OFFPEAK_RATE, DEFAULT_OFFPEAK_RATE
                        ),
                        offpeak_balance_rate=self._configured_nonnegative(
                            CONF_OFFPEAK_BALANCE_RATE,
                            DEFAULT_OFFPEAK_BALANCE_RATE,
                        ),
                        shoulder_rate=self._configured_nonnegative(
                            CONF_SHOULDER_RATE, DEFAULT_SHOULDER_RATE
                        ),
                        daily_charge=self._configured_nonnegative(
                            CONF_DAILY_CHARGE, DEFAULT_DAILY_CHARGE
                        ),
                        boosted_export_allowance_kwh=self._configured_nonnegative(
                            CONF_EXPORT_ALLOWANCE_KWH,
                            DEFAULT_EXPORT_ALLOWANCE_KWH,
                        ),
                        export_rate=self._configured_nonnegative(
                            CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE
                        ),
                        offpeak_export_rate=self._configured_nonnegative(
                            CONF_OFFPEAK_EXPORT_RATE,
                            DEFAULT_OFFPEAK_EXPORT_RATE,
                        ),
                        boosted_export_rate=self._configured_nonnegative(
                            CONF_SUPER_EXPORT_RATE, DEFAULT_SUPER_EXPORT_RATE
                        ),
                    ),
                    zerohero=ZeroHeroWindowEvidence(
                        active=self._bonus_window_active(now),
                        zero_import_minutes=self._zero_import_duration_minutes(
                            ledger.grid_import_kw, now
                        ),
                        hourly_import_kwh=tuple(
                            self.zerohero_import.hourly_import_kwh.values()
                        ),
                        elapsed_hours=self._bonus_window_elapsed_hours(now),
                        complete=window_complete,
                        expected_hour_count=expected_hours,
                    ),
                )
            )
        except (TypeError, ValueError):
            return replace(ledger, tariff_reason="tariff_configuration_invalid")

    async def async_update_forecast(self, now: datetime | None = None) -> None:
        """Update the read-only optimistic forecast and retailer scorecard."""
        now = now or dt_util.now()
        rolled = self.forecast_feedback.roll_to(now.date())
        controller = self.active_controller
        export_plan = (
            controller.export_plan
            if controller is not None
            and controller.export_effective_enabled
            and controller.export_plan is not None
            else None
        )
        realised = max(float(self.zerohero_export.imported_kwh), 0.0)
        planned_remaining = (
            max(float(export_plan.planned_export_energy_kwh), 0.0)
            if export_plan is not None
            else 0.0
        )
        self.forecast_feedback.observe_export(
            planned_total_kwh=realised + planned_remaining,
            realised_kwh=realised,
        )
        self.optimistic_forecast = self._calculate_optimistic_forecast(
            planned_remaining, now
        )
        if self.optimistic_forecast is not None:
            freeze_at = datetime.combine(
                now.date(),
                self._configured_time(CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START),
                tzinfo=now.tzinfo,
            )
            if now >= freeze_at:
                self.forecast_feedback.freeze(self.optimistic_forecast)
        self._match_retailer_scorecard()
        # The storage signature below already coalesces normal plan/export movement.
        # Only a day rollover must bypass it; otherwise a 30-second controller tick
        # could turn a small amount of telemetry noise into needless disk writes.
        await self._async_save_forecast_feedback(force=rolled)

    def _calculate_optimistic_forecast(
        self, planned_remaining_kwh: float, now: datetime
    ) -> OptimisticCostForecast | None:
        """Apply the existing tariff engine to 75%-initial planned export."""
        ledger = self.data
        required = (
            ledger.daily_import_kwh,
            ledger.free_window_import_kwh,
            ledger.daily_export_kwh,
            ledger.standard_window_export_kwh,
            ledger.boosted_window_export_kwh,
            ledger.estimated_energy_cost,
            ledger.estimated_export_revenue,
        )
        if any(value is None for value in required):
            return None
        fraction = self.forecast_feedback.export_realisation_fraction
        standard_fraction = self._forecast_standard_rate_fraction(now)
        try:
            return calculate_tariffed_optimistic_forecast(
                ForecastFinancialInputs(
                    total_import_kwh=float(ledger.daily_import_kwh),
                    free_window_import_kwh=float(ledger.free_window_import_kwh),
                    peak_import_kwh=float(self.peak_import.imported_kwh),
                    free_allowance_kwh=self._configured_nonnegative(
                        CONF_DAILY_FREE_ALLOWANCE_KWH,
                        DEFAULT_DAILY_FREE_ALLOWANCE_KWH,
                    ),
                    peak_rate=self._configured_nonnegative(
                        CONF_PEAK_RATE, DEFAULT_PEAK_RATE
                    ),
                    offpeak_rate=self._configured_nonnegative(
                        CONF_OFFPEAK_RATE, DEFAULT_OFFPEAK_RATE
                    ),
                    offpeak_balance_rate=self._configured_nonnegative(
                        CONF_OFFPEAK_BALANCE_RATE, DEFAULT_OFFPEAK_BALANCE_RATE
                    ),
                    shoulder_rate=self._configured_nonnegative(
                        CONF_SHOULDER_RATE, DEFAULT_SHOULDER_RATE
                    ),
                    daily_charge=self._configured_nonnegative(
                        CONF_DAILY_CHARGE, DEFAULT_DAILY_CHARGE
                    ),
                    total_export_kwh=float(ledger.daily_export_kwh),
                    standard_window_export_kwh=float(
                        ledger.standard_window_export_kwh
                    ),
                    boosted_window_export_kwh=float(
                        ledger.boosted_window_export_kwh
                    ),
                    boosted_export_allowance_kwh=self._configured_nonnegative(
                        CONF_EXPORT_ALLOWANCE_KWH, DEFAULT_EXPORT_ALLOWANCE_KWH
                    ),
                    export_rate=self._configured_nonnegative(
                        CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE
                    ),
                    offpeak_export_rate=self._configured_nonnegative(
                        CONF_OFFPEAK_EXPORT_RATE, DEFAULT_OFFPEAK_EXPORT_RATE
                    ),
                    boosted_export_rate=self._configured_nonnegative(
                        CONF_SUPER_EXPORT_RATE, DEFAULT_SUPER_EXPORT_RATE
                    ),
                    measured_gross_cost=float(ledger.estimated_energy_cost),
                    measured_export_revenue=float(
                        ledger.estimated_export_revenue
                    ),
                    assumed_zerohero_credit=self._configured_nonnegative(
                        CONF_ZEROHERO_DAILY_CREDIT, DEFAULT_ZEROHERO_DAILY_CREDIT
                    ),
                    planned_remaining_export_kwh=planned_remaining_kwh,
                    export_realisation_fraction=fraction,
                    standard_rate_fraction=standard_fraction,
                    learned_cost_bias=self.forecast_feedback.learned_cost_bias,
                )
            )
        except (TypeError, ValueError):
            return None

    def _forecast_standard_rate_fraction(self, now: datetime) -> float:
        """Allocate forecast export across the configured base-rate window."""
        controller = self.active_controller
        if (
            controller is not None
            and controller.export_plan is not None
            and controller.export_planned_start is not None
            and controller.export_plan.planned_duration_h > 0
        ):
            start = controller.export_planned_start
            finish = start + timedelta(hours=controller.export_plan.planned_duration_h)
        else:
            start_time = self._configured_time(
                CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START
            )
            end_time = self._configured_time(
                CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END
            )
            start = datetime.combine(now.date(), start_time, tzinfo=now.tzinfo)
            finish = datetime.combine(now.date(), end_time, tzinfo=now.tzinfo)
            if end_time <= start_time:
                finish += timedelta(days=1)
        return window_overlap_fraction(
            start,
            finish,
            self._configured_time(
                CONF_EXPORT_RATE_WINDOW_START, DEFAULT_EXPORT_RATE_WINDOW_START
            ),
            self._configured_time(
                CONF_EXPORT_RATE_WINDOW_END, DEFAULT_EXPORT_RATE_WINDOW_END
            ),
        )

    def _match_retailer_scorecard(self) -> bool:
        """Match only complete, same-date GloBird results to retained forecasts."""
        accounting = self.runtime_config.accounting
        result = match_retailer_scorecard(
            self.forecast_feedback,
            capture_retailer_scorecard(
                self.hass,
                cost_entity=accounting.retailer_daily_cost_entity,
                status_entity=accounting.retailer_zerohero_status_entity,
            ),
        )
        self.forecast_scorecard_status = result.status
        self.forecast_scorecard_date = result.result_date
        return result.changed

    async def _async_save_forecast_feedback(self, *, force: bool = False) -> None:
        """Checkpoint forecast evidence without writing on every 30-second tick."""
        current = self.forecast_feedback.current
        latest = (
            self.forecast_feedback.history[-1]
            if self.forecast_feedback.history
            else None
        )
        signature = (
            current.local_date,
            current.frozen_forecast_cost,
            round(current.planned_export_kwh, 1),
            round(current.realised_export_kwh, 1),
            self.forecast_feedback.export_realisation_fraction,
            self.forecast_feedback.learned_cost_bias,
            None if latest is None else latest.to_payload().__repr__(),
        )
        if not force and signature == self._forecast_last_saved_signature:
            return
        await self._forecast_repository.async_save(self.forecast_feedback)
        self._forecast_last_saved_signature = signature

    def _power(self, entity_id: str | None) -> float | None:
        return read_power_kw(self.hass, entity_id)

    def _max_telemetry_age(self) -> float:
        return self.runtime_config.telemetry.max_age_seconds

    def _source(self, entity_id: object) -> TelemetrySource | None:
        """Retain the characterized source-capture compatibility seam."""
        return capture_telemetry_source(
            self.hass,
            entity_id,
            reported_at=self._state_reported_at,
        )

    def _normalized_telemetry(self, now: datetime) -> NormalizedTelemetry:
        """Build the single canonical signed telemetry surface."""
        power_sources = self.runtime_config.power_sources
        battery = self.runtime_config.battery
        site = self.runtime_config.site
        electrical = self.runtime_config.electrical
        sources = capture_site_telemetry(
            self.hass,
            TelemetryEntityIds(
                grid_power=power_sources.grid_entity,
                signed_battery_power=power_sources.battery_entity,
                battery_charge_power=battery.charge_power_entity,
                battery_discharge_power=battery.discharge_power_entity,
                solar_power=(
                    power_sources.solar_entity if site.solar_configured else None
                ),
                house_load=power_sources.house_load_entity,
                site_grid_current=site.grid_current_entity,
                phase_grid_power=site.phase_power_entities,
                phase_grid_voltage=site.phase_voltage_entities,
            ),
        )
        return normalize_site_telemetry(
            sources,
            TelemetryNormalizationConfiguration(
                max_age_seconds=self._max_telemetry_age(),
                grid_power_direction=electrical.effective_grid_power_direction,
                battery_power_direction=(
                    electrical.battery_power_positive_direction
                ),
                solar_configured=site.solar_configured,
                solar_generation_direction=(
                    electrical.effective_solar_generation_direction
                ),
                site_grid_current_direction=(
                    electrical.effective_site_grid_current_direction
                ),
                site_phase_count=site.phase_count,
                voltage_v=self.runtime_config.ev_connection.configured_voltage_v,
            ),
            now=now,
        )

    def _energy(self, entity_id: str | None) -> float | None:
        return read_energy_kwh(self.hass, entity_id)

    async def _async_update_data(self) -> EnergyLedger:
        battery_soc = self._number(self.runtime_config.battery.soc_entity)
        if battery_soc is not None:
            try:
                battery_soc = percent(battery_soc)
            except ValueError:
                battery_soc = None
        now = dt_util.now()
        if self.forecast_feedback.roll_to(now.date()):
            await self._async_save_forecast_feedback(force=True)
        self.telemetry = self._normalized_telemetry(now)
        grid = self.telemetry.grid_power.value
        export_kw = None if grid is None else max(-grid, 0.0)
        await advance_accounting_meters(
            AccountingMeterSet(
                daily_import=self.daily_import,
                daily_export=self.daily_export,
                standard_rate_export=self.standard_rate_export,
                free_window_import=self.free_window_import,
                peak_import=self.peak_import,
                zerohero_import=self.zerohero_import,
                zerohero_export=self.zerohero_export,
            ),
            grid_power_kw=grid,
            export_power_kw=export_kw,
            observed_at=now,
            checkpoints=MeterCheckpointState(
                daily_import=self._daily_import_last_saved,
                daily_export=self._daily_export_last_saved,
                standard_rate_export=self._standard_rate_export_last_saved,
                free_window_import=self._free_import_last_saved,
                peak_import=self._peak_import_last_saved,
                zerohero_import=self._zerohero_import_last_saved,
                zerohero_export=self._zerohero_export_last_saved,
            ),
            checkpoint=self._async_checkpoint_accounting_meter,
        )
        try:
            measured_capacity = self._energy(
                self.runtime_config.battery.capacity_entity
            )
            effective_capacity = (
                measured_capacity if measured_capacity is not None and measured_capacity > 0
                else self._configured_float(CONF_BATTERY_CAPACITY)
            )
            self.snapshot = SiteSnapshot(
                battery_soc=battery_soc,
                battery_capacity_kwh=effective_capacity,
                battery_floor_percent=self._configured_float(CONF_BATTERY_FLOOR),
                reserve_kwh=self._configured_float(CONF_RESERVE),
                grid_power_kw=grid,
                house_load_kw=self.telemetry.house_load.value,
                ev_soc=self._number(self.runtime_config.ev_telemetry.soc_entity),
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

    async def _async_checkpoint_accounting_meter(
        self, checkpoint: MeterCheckpointRequest
    ) -> None:
        """Persist one ordered meter checkpoint requested by the domain cycle."""
        if checkpoint.name == DAILY_IMPORT:
            await self._daily_import_repository.async_save(self.daily_import)
            self._daily_import_last_saved = checkpoint.total_kwh
        elif checkpoint.name == DAILY_EXPORT:
            await self._daily_export_repository.async_save(self.daily_export)
            self._daily_export_last_saved = checkpoint.total_kwh
        elif checkpoint.name == STANDARD_RATE_EXPORT:
            await self._standard_rate_export_repository.async_save(
                self.standard_rate_export
            )
            self._standard_rate_export_last_saved = checkpoint.total_kwh
        elif checkpoint.name == FREE_WINDOW_IMPORT:
            await self._free_import_repository.async_save(self.free_window_import)
            self._free_import_last_saved = checkpoint.total_kwh
        elif checkpoint.name == PEAK_IMPORT:
            await self._peak_import_repository.async_save(self.peak_import)
            self._peak_import_last_saved = checkpoint.total_kwh
        elif checkpoint.name == ZEROHERO_IMPORT:
            await self._zerohero_import_repository.async_save(self.zerohero_import)
            self._zerohero_import_last_saved = checkpoint.total_kwh
        elif checkpoint.name == ZEROHERO_EXPORT:
            await self._zerohero_export_repository.async_save(self.zerohero_export)
            self._zerohero_export_last_saved = checkpoint.total_kwh

    async def _async_sample_house_load(self) -> None:
        """Feed qualified house-load readings into the rolling sampler."""
        if self.demand_sampler is None or self.snapshot is None:
            return
        now = dt_util.now()
        house_load_kw = self._protected_house_learning_power_kw(now)
        if house_load_kw is None:
            return
        # Window boundaries are configured in Home Assistant's local site time.
        # Using UTC would silently learn a different interval at most sites.
        heater_power_kw = (
            self._power(self.runtime_config.house.heater_power_entity)
            if self.heater_sampler is not None
            else None
        )
        result = advance_house_learning(
            demand_sampler=self.demand_sampler,
            heater_sampler=self.heater_sampler,
            demand_history=self.demand_history,
            heater_history=self.heater_history,
            observation=HouseLearningObservation(
                observed_at=now,
                base_house_power_kw=house_load_kw,
                heater_power_kw=heater_power_kw,
            ),
            last_saved_at=self._demand_sampler_last_saved_at,
        )
        if result.save_required:
            await self._async_save_demand_state()
            self._demand_sampler_last_saved_at = now

    def _protected_house_learning_power_kw(self, now: datetime) -> float | None:
        """Return the pilot-compatible base-house power used by the learner."""
        if self.snapshot is None or self.snapshot.house_load_kw is None:
            return None
        house = self.runtime_config.house
        includes_ev = house.load_includes_ev
        ev_power_kw = self._state_qualified_ev_power_kw(now) if includes_ev else None
        heater_mapped = bool(house.heater_power_entity)
        heater_power_kw = (
            self._fresh_power(house.heater_power_entity, now)
            if heater_mapped
            else None
        )
        return protected_base_house_power_kw(
            self.snapshot.house_load_kw,
            ev_power_kw=ev_power_kw,
            heater_power_kw=heater_power_kw,
            house_includes_ev=includes_ev,
            heater_is_mapped=heater_mapped,
        )

    def _state_qualified_ev_power_kw(self, now: datetime) -> float | None:
        """Port the pilot's charging-state-qualified EV power calculation."""
        ev_telemetry = self.runtime_config.ev_telemetry
        charging_entity = ev_telemetry.charging_state_entity
        charging_state = capture_telemetry_source(self.hass, charging_entity)
        if charging_state is None or charging_state.updated_at is None:
            return None
        age_seconds = (now - charging_state.updated_at).total_seconds()
        if age_seconds < 0 or age_seconds > self._max_telemetry_age():
            return None
        if str(charging_state.raw_value).lower() != "charging":
            return 0.0
        current_entity = ev_telemetry.actual_current_entity
        current_state = capture_telemetry_source(self.hass, current_entity)
        if current_state is None or current_state.updated_at is None:
            return None
        current_age_seconds = (now - current_state.updated_at).total_seconds()
        if current_age_seconds < 0 or current_age_seconds > self._max_telemetry_age():
            return None
        try:
            current_a = current_to_a(
                float(current_state.raw_value),
                current_state.raw_unit,
            )
            voltage_v = self._configured_float(CONF_EV_VOLTAGE)
            phase_count = self._configured_phase_count()
        except (TypeError, ValueError):
            return None
        if current_a < 0 or voltage_v <= 0:
            return None
        return current_a * voltage_v * phase_count / 1000

    def _fresh_power(self, entity_id: object, now: datetime) -> float | None:
        """Read a mapped power component only while its state is fresh."""
        return read_fresh_power_kw(
            self.hass,
            entity_id,
            now=now,
            max_age_seconds=self._max_telemetry_age(),
        )

    @staticmethod
    def _state_reported_at(state: State) -> datetime:
        """Use Home Assistant's report time so stable polled values stay fresh."""
        return state_reported_at(state)

    async def _async_save_demand_state(self) -> None:
        """Persist completed history and the current partial cycle together."""
        state = DemandPersistenceState.capture(
            self.demand_history,
            self.heater_history,
            self.demand_sampler,
            self.heater_sampler,
        )
        await self._demand_repository.async_save(state)
