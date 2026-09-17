"""Read configured entities and calculate a safe observer-by-default ledger."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from math import isfinite

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .configuration import RuntimeConfiguration
from .const import (
    BATTERY_POSITIVE_CHARGE,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_CHARGE_POWER,
    CONF_BATTERY_DISCHARGE_POWER,
    CONF_BATTERY_FLOOR,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BONUS_WINDOW_END,
    CONF_BONUS_WINDOW_START,
    CONF_DAILY_CHARGE,
    CONF_DAILY_FREE_ALLOWANCE_KWH,
    CONF_DAILY_IMPORT_ENTITY,
    CONF_EV_ACTUAL_CURRENT,
    CONF_EV_CHARGING_STATE,
    CONF_EV_MAX_CURRENT,
    CONF_EV_MIN_CURRENT,
    CONF_EV_PHASE_COUNT,
    CONF_EV_SOC,
    CONF_EV_VOLTAGE,
    CONF_EXPORT_ALLOWANCE_KWH,
    CONF_EXPORT_LIMIT_KW,
    CONF_EXPORT_RATE,
    CONF_EXPORT_RATE_WINDOW_END,
    CONF_EXPORT_RATE_WINDOW_START,
    CONF_FREE_CHARGE_END,
    CONF_FREE_CHARGE_START,
    CONF_GLOBIRD_LATEST_DAILY_COST,
    CONF_GLOBIRD_ZEROHERO_STATUS,
    CONF_GRID_POWER,
    CONF_GRID_POWER_DIRECTION,
    CONF_HEATER_POWER,
    CONF_HOUSE_LOAD,
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
    CONF_SITE_GRID_CURRENT,
    CONF_SITE_GRID_CURRENT_DIRECTION,
    CONF_SITE_PHASE_COUNT,
    CONF_SOLAR_POWER,
    CONF_SOLAR_POWER_DIRECTION,
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
    DEFAULT_SITE_GRID_CURRENT_DIRECTION,
    DEFAULT_SOLAR_POWER_DIRECTION,
    DEFAULT_SUPER_EXPORT_RATE,
    DEFAULT_ZERO_IMPORT_CONFIRM_MINUTES,
    DEFAULT_ZERO_IMPORT_THRESHOLD_KW,
    DEFAULT_ZEROHERO_DAILY_CREDIT,
    DOMAIN,
    GRID_POSITIVE_EXPORT,
    GRID_POSITIVE_IMPORT,
    REASON_INVALID_CONFIGURATION,
    SOLAR_GENERATION_POSITIVE,
)
from .models import EnergyLedger, SiteSnapshot
from .normalise import current_to_a, energy_to_kwh, percent, power_to_kw
from .planner.daily_meter import (
    DailyImportAccumulator,
    HourlyWindowImportAccumulator,
    WindowImportAccumulator,
)
from .planner.forecast import (
    ForecastFeedbackState,
    OptimisticCostForecast,
    calculate_optimistic_cost_forecast,
    window_overlap_fraction,
)
from .planner.learning import (
    DailyDemandCycleSampler,
    DemandCycleSampler,
    DemandHistory,
    DemandLearningResult,
    HouseBudgetResult,
    OccupancyPerson,
    OccupancyResult,
    classify_energy_occupancy,
    protected_base_house_power_kw,
    remaining_protected_cycle_budget_kwh,
    select_house_cycle_budget,
)
from .planner.ledger import calculate_ledger
from .planner.tariff import (
    calculate_daily_financials,
    calculate_tariff_guard,
    calculate_zerohero_credit,
)
from .telemetry import (
    NormalizedSample,
    NormalizedTelemetry,
    TelemetrySource,
    battery_power_from_magnitudes_or_signed,
    normalize_current_sample,
    normalize_power_sample,
    unavailable_sample,
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
        self._zero_import_since: datetime | None = None
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
        self._daily_import_last_saved: float | None = None
        self._daily_export_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.daily_export", private=True
        )
        self._daily_export_last_saved: float | None = None
        self._standard_rate_export_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.standard_rate_export", private=True
        )
        self._standard_rate_export_last_saved: float | None = None
        self._free_import_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.free_window_import", private=True
        )
        self._peak_import_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.peak_import", private=True
        )
        self._zerohero_import_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.zerohero_hourly_import", private=True
        )
        self._zerohero_export_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.zerohero_export", private=True
        )
        self._free_import_last_saved: float | None = None
        self._peak_import_last_saved: float | None = None
        self._zerohero_import_last_saved: float | None = None
        self._zerohero_export_last_saved: float | None = None
        self._demand_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.demand_history", private=True
        )
        self._forecast_store: Store[dict[str, object]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}.forecast_feedback", private=True
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
                for key in (
                    CONF_BATTERY_SOC,
                    CONF_BATTERY_CAPACITY_ENTITY,
                    CONF_BATTERY_POWER,
                    CONF_BATTERY_CHARGE_POWER,
                    CONF_BATTERY_DISCHARGE_POWER,
                    CONF_GRID_POWER,
                    CONF_DAILY_IMPORT_ENTITY,
                    CONF_GLOBIRD_LATEST_DAILY_COST,
                    CONF_GLOBIRD_ZEROHERO_STATUS,
                    CONF_HOUSE_LOAD,
                    CONF_HEATER_POWER,
                    CONF_SOLAR_POWER,
                    CONF_SITE_GRID_CURRENT,
                    CONF_EV_SOC,
                    CONF_EV_CHARGING_STATE,
                    CONF_EV_ACTUAL_CURRENT,
                )
                if (entity_id := config.get(key))
            ),
            self._async_source_changed,
        )

    def update_config_value(self, key: str, value: object) -> None:
        """Update the live config mirror through one future typed-config boundary."""
        self.config[key] = value
        self.runtime_config = RuntimeConfiguration.from_mapping(self.config)

    async def async_load_demand_history(self) -> None:
        """Load and validate the rolling learner history from HA storage."""
        payload = await self._demand_store.async_load()
        self.demand_history = DemandHistory.from_payload(payload, dt_util.utcnow())
        if isinstance(payload, dict):
            self.heater_history = DemandHistory.from_payload(
                payload.get("heater_history"), dt_util.utcnow()
            )
            if self.demand_sampler is not None:
                self.demand_sampler.restore(payload.get("in_progress_cycle"), dt_util.now())
            if self.heater_sampler is not None:
                self.heater_sampler.restore(
                    payload.get("heater_in_progress_cycle"), dt_util.now()
                )

    async def async_load_daily_import(self) -> None:
        """Load the persisted same-day tariff accumulators."""
        self.daily_import.restore(await self._daily_import_store.async_load(), dt_util.now())
        now = dt_util.now()
        self.daily_export.restore(await self._daily_export_store.async_load(), now)
        self.standard_rate_export.restore(
            await self._standard_rate_export_store.async_load(), now
        )
        self.free_window_import.restore(await self._free_import_store.async_load(), now)
        self.peak_import.restore(await self._peak_import_store.async_load(), now)
        self.zerohero_import.restore(await self._zerohero_import_store.async_load(), now)
        self.zerohero_export.restore(await self._zerohero_export_store.async_load(), now)

    async def async_load_forecast_feedback(self) -> None:
        """Load forecast-only calibration and comparison history."""
        self.forecast_feedback = ForecastFeedbackState.restore(
            await self._forecast_store.async_load(),
            today=dt_util.now().date(),
            default_fraction=DEFAULT_FORECAST_EXPORT_REALISATION,
        )
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
        try:
            return time.fromisoformat(str(self.config.get(key, default)))
        except (TypeError, ValueError):
            return time.fromisoformat(default)

    @property
    def occupancy_result(self) -> OccupancyResult:
        """Return the canonical conservative occupancy classification."""
        people = [
            OccupancyPerson(state.state, state.last_changed)
            for state in self.hass.states.async_all("person")
        ]
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

    def _zerohero_credit_window_state(self, now: datetime) -> tuple[bool, int]:
        """Return completion and clock-hour count for today's credit window."""
        start = self._configured_time(CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START)
        end = self._configured_time(CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END)
        if start == end:
            return False, 0
        current = now.timetz().replace(tzinfo=None)
        start_at = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
        end_at = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
        if end <= start:
            if current < end:
                start_at -= timedelta(days=1)
            else:
                end_at += timedelta(days=1)
            if end <= current < start:
                start_at -= timedelta(days=1)
                end_at -= timedelta(days=1)
        cursor = start_at.replace(minute=0, second=0, microsecond=0)
        expected_hours = 0
        while cursor < end_at:
            expected_hours += 1
            cursor += timedelta(hours=1)
        return now >= end_at, expected_hours

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
        daily_export = self.daily_export.imported_kwh if self.daily_export.last_at else None
        standard_export = (
            self.standard_rate_export.imported_kwh
            if self.standard_rate_export.last_at
            else None
        )
        boosted_export = (
            self.zerohero_export.imported_kwh if self.zerohero_export.last_at else None
        )
        export_accounting_available = (
            daily_export is not None
            and standard_export is not None
            and boosted_export is not None
        )
        if daily_import is None or free_import is None:
            return replace(
                ledger,
                tariff_reason="daily_import_meter_unavailable",
                daily_import_kwh=daily_import,
                daily_import_source=daily_source if daily_import is not None else "unavailable",
                free_window_import_kwh=free_import,
                daily_export_kwh=daily_export,
                standard_window_export_kwh=standard_export,
                boosted_window_export_kwh=boosted_export,
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
            window_complete, expected_hours = self._zerohero_credit_window_state(now)
            credit = calculate_zerohero_credit(
                hourly_import_kwh=tuple(self.zerohero_import.hourly_import_kwh.values()),
                expected_hour_count=expected_hours,
                threshold_kwh_per_hour=self._configured_nonnegative(
                    CONF_ZERO_IMPORT_THRESHOLD_KW, DEFAULT_ZERO_IMPORT_THRESHOLD_KW
                ),
                configured_credit=self._configured_nonnegative(
                    CONF_ZEROHERO_DAILY_CREDIT, DEFAULT_ZEROHERO_DAILY_CREDIT
                ),
                window_complete=window_complete,
            )
            financials = calculate_daily_financials(
                total_import_kwh=daily_import,
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
                daily_charge=self._configured_nonnegative(
                    CONF_DAILY_CHARGE, DEFAULT_DAILY_CHARGE
                ),
                total_export_kwh=daily_export if daily_export is not None else 0.0,
                standard_window_export_kwh=(
                    standard_export if standard_export is not None else 0.0
                ),
                boosted_window_export_kwh=(
                    boosted_export if boosted_export is not None else 0.0
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
                zerohero_credit=credit.credit,
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
            daily_export_kwh=daily_export,
            standard_window_export_kwh=standard_export,
            boosted_window_export_kwh=boosted_export,
            standard_rate_export_kwh=(
                financials.standard_export_kwh if export_accounting_available else None
            ),
            offpeak_rate_export_kwh=(
                financials.offpeak_export_kwh if export_accounting_available else None
            ),
            boosted_rate_export_kwh=(
                financials.boosted_export_kwh if export_accounting_available else None
            ),
            estimated_energy_cost=financials.gross_cost,
            estimated_import_energy_cost=financials.import_energy_cost,
            daily_supply_charge=financials.supply_charge,
            estimated_export_revenue=(
                financials.export_revenue if export_accounting_available else None
            ),
            zerohero_credit=credit.credit,
            zerohero_credit_status=credit.status,
            estimated_net_cost=financials.net_cost if export_accounting_available else None,
        )

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
        additional_export = planned_remaining_kwh * fraction
        standard_fraction = self._forecast_standard_rate_fraction(now)
        try:
            hypothetical = calculate_daily_financials(
                total_import_kwh=float(ledger.daily_import_kwh),
                free_window_import_kwh=float(ledger.free_window_import_kwh),
                peak_import_kwh=float(self.peak_import.imported_kwh),
                free_allowance_kwh=self._configured_nonnegative(
                    CONF_DAILY_FREE_ALLOWANCE_KWH, DEFAULT_DAILY_FREE_ALLOWANCE_KWH
                ),
                peak_rate=self._configured_nonnegative(CONF_PEAK_RATE, DEFAULT_PEAK_RATE),
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
                total_export_kwh=float(ledger.daily_export_kwh) + additional_export,
                standard_window_export_kwh=(
                    float(ledger.standard_window_export_kwh)
                    + additional_export * standard_fraction
                ),
                boosted_window_export_kwh=(
                    float(ledger.boosted_window_export_kwh) + additional_export
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
                zerohero_credit=self._configured_nonnegative(
                    CONF_ZEROHERO_DAILY_CREDIT, DEFAULT_ZEROHERO_DAILY_CREDIT
                ),
            )
            additional_revenue = max(
                hypothetical.export_revenue - float(ledger.estimated_export_revenue),
                0.0,
            )
            return calculate_optimistic_cost_forecast(
                measured_gross_cost=float(ledger.estimated_energy_cost),
                measured_export_revenue=float(ledger.estimated_export_revenue),
                assumed_zerohero_credit=self._configured_nonnegative(
                    CONF_ZEROHERO_DAILY_CREDIT, DEFAULT_ZEROHERO_DAILY_CREDIT
                ),
                planned_remaining_export_kwh=planned_remaining_kwh,
                export_realisation_fraction=fraction,
                forecast_additional_export_revenue=additional_revenue,
                learned_cost_bias=self.forecast_feedback.learned_cost_bias,
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
        cost_entity = self.config.get(CONF_GLOBIRD_LATEST_DAILY_COST)
        status_entity = self.config.get(CONF_GLOBIRD_ZEROHERO_STATUS)
        self.forecast_scorecard_date = None
        if not cost_entity and not status_entity:
            self.forecast_scorecard_status = "not_configured"
            return False
        if not cost_entity or not status_entity:
            self.forecast_scorecard_status = "incomplete_mapping"
            return False
        cost_state = self.hass.states.get(str(cost_entity))
        status_state = self.hass.states.get(str(status_entity))
        if cost_state is None or status_state is None:
            self.forecast_scorecard_status = "retailer_data_unavailable"
            return False
        cost_complete = bool(
            cost_state.attributes.get("latest_available_day_complete", False)
        )
        status_complete = bool(
            status_state.attributes.get("latest_available_day_complete", False)
        )
        if not cost_complete or not status_complete:
            self.forecast_scorecard_status = "retailer_day_incomplete"
            return False
        cost_date = self._retailer_result_date(cost_state)
        status_date = self._retailer_result_date(status_state)
        if cost_date is None or status_date is None or cost_date != status_date:
            self.forecast_scorecard_status = "retailer_date_mismatch"
            return False
        try:
            actual_cost = float(cost_state.state)
        except (TypeError, ValueError):
            self.forecast_scorecard_status = "retailer_cost_invalid"
            return False
        zerohero_status = {
            "achieved": "achieved",
            "missed": "not_achieved",
            # Retain compatibility with scorecard fixtures and any older
            # GloBird integration version that exposed this spelling.
            "not_achieved": "not_achieved",
        }.get(str(status_state.state).casefold())
        if zerohero_status is None:
            self.forecast_scorecard_status = "retailer_status_unrecognized"
            return False
        previous = self.forecast_feedback.record_for(cost_date)
        previous_payload = previous.to_payload() if previous is not None else None
        previous_bias = self.forecast_feedback.learned_cost_bias
        self.forecast_scorecard_status = self.forecast_feedback.match_retailer(
            result_date=cost_date,
            actual_cost=actual_cost,
            zerohero_status=zerohero_status,
        )
        self.forecast_scorecard_date = cost_date
        current = self.forecast_feedback.record_for(cost_date)
        return (
            previous_payload != (current.to_payload() if current is not None else None)
            or previous_bias != self.forecast_feedback.learned_cost_bias
        )

    @staticmethod
    def _retailer_result_date(state: State) -> date | None:
        value = state.attributes.get("latest_available_day") or state.attributes.get(
            "latest_day"
        )
        if not value:
            return None
        try:
            return date.fromisoformat(str(value).replace("/", "-"))
        except ValueError:
            return None

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
        await self._forecast_store.async_save(self.forecast_feedback.to_payload())
        self._forecast_last_saved_signature = signature

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

    def _source(self, entity_id: object) -> TelemetrySource | None:
        """Capture raw state and timestamp without interpreting sign or unit."""
        if not isinstance(entity_id, str) or not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return TelemetrySource(entity_id, None, None, None)
        return TelemetrySource(
            entity_id=entity_id,
            raw_value=state.state,
            raw_unit=state.attributes.get("unit_of_measurement"),
            # Home Assistant keeps ``last_updated`` unchanged when an
            # integration reports the same value again.  ``last_reported`` is
            # the freshness timestamp: a steady zero/current/SoC is still
            # healthy telemetry when its source continues to report it.
            updated_at=self._state_reported_at(state),
        )

    def _max_telemetry_age(self) -> float:
        return self.runtime_config.telemetry.max_age_seconds

    def _direction(self, key: str, default: str) -> str:
        value = self.config.get(key, default)
        return str(value) if value else default

    def _power_sample(
        self,
        entity_key: str,
        *,
        now: datetime,
        direction: str,
        positive_direction: str,
    ) -> NormalizedSample:
        source = self._source(self.config.get(entity_key))
        if source is None:
            return unavailable_sample(
                unit="kW",
                positive_direction=positive_direction,
                reason="not_configured",
            )
        return normalize_power_sample(
            source,
            now=now,
            max_age_seconds=self._max_telemetry_age(),
            multiplier=1.0 if direction == positive_direction else -1.0,
            positive_direction=positive_direction,
        )

    def _normalized_telemetry(self, now: datetime) -> NormalizedTelemetry:
        """Build the single canonical signed telemetry surface."""
        grid_direction = self._direction(
            CONF_GRID_POWER_DIRECTION,
            (
                GRID_POSITIVE_IMPORT
                if bool(self.config.get("grid_import_positive", True))
                else GRID_POSITIVE_EXPORT
            ),
        )
        grid = self._power_sample(
            CONF_GRID_POWER,
            now=now,
            direction=grid_direction,
            positive_direction=GRID_POSITIVE_IMPORT,
        )

        battery_direction = (
            self.runtime_config.electrical.battery_power_positive_direction
        )
        signed_battery = self._power_sample(
            CONF_BATTERY_POWER,
            now=now,
            direction=battery_direction,
            positive_direction=BATTERY_POSITIVE_CHARGE,
        )

        charge_source = self._source(self.runtime_config.battery.charge_power_entity)
        discharge_source = self._source(
            self.runtime_config.battery.discharge_power_entity
        )
        if charge_source is not None or discharge_source is not None:
            charge = (
                normalize_power_sample(
                    charge_source,
                    now=now,
                    max_age_seconds=self._max_telemetry_age(),
                    multiplier=1.0,
                    positive_direction="positive_magnitude",
                )
                if charge_source is not None
                else unavailable_sample(
                    unit="kW", positive_direction="positive_magnitude", reason="not_configured"
                )
            )
            discharge = (
                normalize_power_sample(
                    discharge_source,
                    now=now,
                    max_age_seconds=self._max_telemetry_age(),
                    multiplier=1.0,
                    positive_direction="positive_magnitude",
                )
                if discharge_source is not None
                else unavailable_sample(
                    unit="kW", positive_direction="positive_magnitude", reason="not_configured"
                )
            )
            battery = battery_power_from_magnitudes_or_signed(
                charge, discharge, signed_battery
            )
        else:
            battery = signed_battery

        # Missing is a pre-capability entry and retains its historical sensor
        # behavior. Only an explicit choice means deliberate absence.
        solar_configured = self.runtime_config.site.solar_configured
        if solar_configured:
            solar_direction = self._direction(
                CONF_SOLAR_POWER_DIRECTION, DEFAULT_SOLAR_POWER_DIRECTION
            )
            solar = self._power_sample(
                CONF_SOLAR_POWER,
                now=now,
                direction=solar_direction,
                positive_direction=SOLAR_GENERATION_POSITIVE,
            )
        else:
            solar = NormalizedSample(
                value=0.0,
                unit="kW",
                sources=(),
                positive_direction=SOLAR_GENERATION_POSITIVE,
                valid=True,
                fresh=True,
                reason="configured_absent",
            )
        house = self._power_sample(
            CONF_HOUSE_LOAD,
            now=now,
            direction="positive_consumption",
            positive_direction="positive_consumption",
        )

        current_source = self._source(self.runtime_config.site.grid_current_entity)
        current = None
        if current_source is not None:
            current_direction = self._direction(
                CONF_SITE_GRID_CURRENT_DIRECTION,
                DEFAULT_SITE_GRID_CURRENT_DIRECTION,
            )
            current = normalize_current_sample(
                current_source,
                now=now,
                max_age_seconds=self._max_telemetry_age(),
                multiplier=1.0 if current_direction == GRID_POSITIVE_IMPORT else -1.0,
                positive_direction=GRID_POSITIVE_IMPORT,
            )
        if (
            (current is None or current.value is None)
            and self._configured_site_phase_count() == 1
            and grid.value is not None
        ):
            voltage = self._configured_float(CONF_EV_VOLTAGE)
            current = (
                NormalizedSample(
                    value=grid.value * 1000 / voltage,
                    unit="A",
                    sources=(
                        *(current.sources if current is not None else ()),
                        *grid.sources,
                    ),
                    positive_direction=GRID_POSITIVE_IMPORT,
                    valid=grid.valid,
                    fresh=grid.fresh,
                    reason=(
                        "derived_from_grid_power"
                        if current_source is None
                        else "derived_from_grid_power_current_fallback"
                    ),
                )
                if voltage > 0
                else unavailable_sample(
                    unit="A",
                    positive_direction=GRID_POSITIVE_IMPORT,
                    reason="invalid_voltage",
                    sources=grid.sources,
                )
            )
        if current is None:
            current = unavailable_sample(
                unit="A",
                positive_direction=GRID_POSITIVE_IMPORT,
                reason="multiphase_mapping_required",
            )
        return NormalizedTelemetry(grid, battery, solar, house, current)

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
        if self.daily_import.observe(grid, now):
            # Persist at useful increments rather than writing HA storage on
            # every 30-second coordinator refresh.
            if (
                self._daily_import_last_saved is None
                or self.daily_import.imported_kwh < self._daily_import_last_saved
                or self.daily_import.imported_kwh - self._daily_import_last_saved >= 0.05
                or self.daily_import.checkpoint_required
            ):
                await self._daily_import_store.async_save(self.daily_import.to_payload())
                self._daily_import_last_saved = self.daily_import.imported_kwh
        if self.daily_export.observe(export_kw, now):
            if (
                self._daily_export_last_saved is None
                or self.daily_export.imported_kwh < self._daily_export_last_saved
                or self.daily_export.imported_kwh - self._daily_export_last_saved >= 0.05
                or self.daily_export.checkpoint_required
            ):
                await self._daily_export_store.async_save(self.daily_export.to_payload())
                self._daily_export_last_saved = self.daily_export.imported_kwh
        if self.standard_rate_export.observe(export_kw, now):
            standard_exported = self.standard_rate_export.imported_kwh
            if (
                self._standard_rate_export_last_saved is None
                or standard_exported < self._standard_rate_export_last_saved
                or standard_exported - self._standard_rate_export_last_saved >= 0.01
                or self.standard_rate_export.checkpoint_required
            ):
                await self._standard_rate_export_store.async_save(
                    self.standard_rate_export.to_payload()
                )
                self._standard_rate_export_last_saved = standard_exported
        if self.free_window_import.observe(grid, now):
            if (
                self._free_import_last_saved is None
                or self.free_window_import.imported_kwh < self._free_import_last_saved
                or self.free_window_import.imported_kwh - self._free_import_last_saved >= 0.05
                or self.free_window_import.checkpoint_required
            ):
                await self._free_import_store.async_save(self.free_window_import.to_payload())
                self._free_import_last_saved = self.free_window_import.imported_kwh
        if self.peak_import.observe(grid, now):
            if (
                self._peak_import_last_saved is None
                or self.peak_import.imported_kwh < self._peak_import_last_saved
                or self.peak_import.imported_kwh - self._peak_import_last_saved >= 0.05
                or self.peak_import.checkpoint_required
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
                or self.zerohero_import.checkpoint_required
            ):
                await self._zerohero_import_store.async_save(self.zerohero_import.to_payload())
                self._zerohero_import_last_saved = zerohero_total
        if self.zerohero_export.observe(export_kw, now):
            exported = self.zerohero_export.imported_kwh
            if (
                self._zerohero_export_last_saved is None
                or exported < self._zerohero_export_last_saved
                or exported - self._zerohero_export_last_saved >= 0.01
                or self.zerohero_export.checkpoint_required
            ):
                await self._zerohero_export_store.async_save(
                    self.zerohero_export.to_payload()
                )
                self._zerohero_export_last_saved = exported
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
        sample = self.demand_sampler.observe(now, house_load_kw)
        heater_sample = None
        if self.heater_sampler is not None:
            heater_power_kw = self._power(
                self.runtime_config.house.heater_power_entity
            )
            if heater_power_kw is not None:
                heater_sample = self.heater_sampler.observe(now, heater_power_kw)
        if sample is not None:
            self.demand_history.add(sample.observed_at, sample.energy_kwh)
        if heater_sample is not None:
            self.heater_history.add(heater_sample.observed_at, heater_sample.energy_kwh)
        save_interval = self.demand_sampler.max_gap / 2
        if (
            sample is not None
            or heater_sample is not None
            or self._demand_sampler_last_saved_at is None
            or now - self._demand_sampler_last_saved_at >= save_interval
        ):
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
        charging_state = self.hass.states.get(charging_entity) if charging_entity else None
        if charging_state is None:
            return None
        age_seconds = (now - self._state_reported_at(charging_state)).total_seconds()
        if age_seconds < 0 or age_seconds > self._max_telemetry_age():
            return None
        if charging_state.state.lower() != "charging":
            return 0.0
        current_entity = ev_telemetry.actual_current_entity
        current_state = self.hass.states.get(current_entity) if current_entity else None
        if current_state is None:
            return None
        current_age_seconds = (now - self._state_reported_at(current_state)).total_seconds()
        if current_age_seconds < 0 or current_age_seconds > self._max_telemetry_age():
            return None
        try:
            current_a = current_to_a(
                float(current_state.state),
                current_state.attributes.get("unit_of_measurement"),
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
        if not isinstance(entity_id, str) or not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        age_seconds = (now - self._state_reported_at(state)).total_seconds()
        if age_seconds < 0 or age_seconds > self._max_telemetry_age():
            return None
        return self._power(entity_id)

    @staticmethod
    def _state_reported_at(state: State) -> datetime:
        """Use Home Assistant's report time so stable polled values stay fresh."""
        return getattr(state, "last_reported", state.last_updated)

    async def _async_save_demand_state(self) -> None:
        """Persist completed history and the current partial cycle together."""
        payload: dict[str, object] = self.demand_history.to_payload()
        payload["heater_history"] = self.heater_history.to_payload()
        if self.demand_sampler is not None:
            payload["in_progress_cycle"] = self.demand_sampler.to_payload()
        if self.heater_sampler is not None:
            payload["heater_in_progress_cycle"] = self.heater_sampler.to_payload()
        await self._demand_store.async_save(payload)
