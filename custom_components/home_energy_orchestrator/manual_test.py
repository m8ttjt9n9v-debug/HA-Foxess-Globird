"""Explicit, time-limited FoxESS commissioning tests.

The test surface is deliberately separate from the automatic coordinator. It
refuses charge tests outside the configured free window, bounds power and
duration, derives the active export tariff from the site configuration, and
always restores Self Use when the timer expires or the integration unloads.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EXPORT_RATE,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_OFFPEAK_BALANCE_RATE,
    CONF_OFFPEAK_RATE,
    CONF_PEAK_RATE,
    CONF_PEAK_WINDOW_END,
    CONF_PEAK_WINDOW_START,
    CONF_REHEARSAL_MODE,
    CONF_SHOULDER_RATE,
    CONF_SUPER_EXPORT_RATE,
    DEFAULT_EXPORT_RATE,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DEFAULT_SUPER_EXPORT_RATE,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from .coordinator import EnergyCoordinator
from .foxess_adapter import FoxessEntityMap, FoxessServiceAdapter
from .normalise import power_to_kw
from .planner.control import ControlDecision
from .planner.foxess import (
    FoxessCommand,
    FoxessCommandPlan,
    FoxessObservation,
    plan_foxess_commands,
)
from .planner.manual_test import ManualTestEstimate, estimate_charge, estimate_discharge


class ManualTestError(ValueError):
    """Raised when a commissioning test is not safe to start."""


class ManualTestController:
    """Own one short-lived manual charge or discharge test."""

    MAX_DURATION_MINUTES = 120.0

    def __init__(self, hass: HomeAssistant, coordinator: EnergyCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.charge_power_kw = 1.0
        self.discharge_power_kw = 1.0
        self.duration_minutes = 5.0
        self.active_kind: str | None = None
        self.started_at: datetime | None = None
        self.ends_at: datetime | None = None
        self.last_reason = "idle"
        self._cancel_timer = None
        self._adapter: FoxessServiceAdapter | None = None

    @property
    def is_active(self) -> bool:
        return self.active_kind is not None

    @property
    def status(self) -> str:
        return "idle" if self.active_kind is None else f"active_{self.active_kind}"

    @property
    def remaining_minutes(self) -> float:
        if self.ends_at is None:
            return 0.0
        return max(0.0, (self.ends_at - dt_util.now()).total_seconds() / 60)

    def preview_charge(self) -> ManualTestEstimate:
        now = dt_util.now()
        free_remaining = 0.0
        if self.coordinator.data is not None:
            free_remaining = max(self.coordinator.data.free_energy_remaining_kwh or 0.0, 0.0)
        return estimate_charge(
            self.charge_power_kw,
            self.duration_minutes,
            free_window_active=self._free_window_active(now),
            free_energy_remaining_kwh=free_remaining,
            offpeak_rate=self._rate(CONF_OFFPEAK_RATE, 0.0),
            offpeak_balance_rate=self._rate(CONF_OFFPEAK_BALANCE_RATE, 0.0),
            current_rate=self.current_import_rate(now),
        )

    def preview_discharge(self) -> ManualTestEstimate:
        now = dt_util.now()
        return estimate_discharge(
            self.discharge_power_kw,
            self.duration_minutes,
            export_rate=self.current_export_rate(now),
        )

    def current_export_rate(self, now: datetime | None = None) -> float:
        """Return the configured export rate for the current local time."""
        now = now or dt_util.now()
        if self._bonus_window_active(now):
            return self._rate(CONF_SUPER_EXPORT_RATE, DEFAULT_SUPER_EXPORT_RATE)
        return self._rate(CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE)

    def current_import_rate(self, now: datetime | None = None) -> float:
        """Return the configured import rate at the current local time."""
        now = now or dt_util.now()
        if self._free_window_active(now):
            remaining = (
                0.0
                if self.coordinator.data is None
                else max(self.coordinator.data.free_energy_remaining_kwh or 0.0, 0.0)
            )
            return self._rate(
                CONF_OFFPEAK_RATE if remaining > 0 else CONF_OFFPEAK_BALANCE_RATE,
                0.0,
            )
        start = self.coordinator._configured_time(CONF_PEAK_WINDOW_START, "16:00:00")
        end = self.coordinator._configured_time(CONF_PEAK_WINDOW_END, "23:00:00")
        current = now.timetz().replace(tzinfo=None)
        in_peak = (start <= current < end) if start < end else (current >= start or current < end)
        return self._rate(CONF_PEAK_RATE if in_peak else CONF_SHOULDER_RATE, 0.0)

    async def async_start(self, kind: str, power_kw: float, duration_minutes: float) -> None:
        """Start a bounded test after all commissioning gates pass."""
        self._require_gate()
        if self.is_active:
            raise ManualTestError("a manual FoxESS test is already active")
        if kind not in {"charge", "discharge"}:
            raise ManualTestError("kind must be charge or discharge")
        power = self._validate_power(kind, power_kw)
        duration = self._validate_duration(duration_minutes)
        now = dt_util.now()
        if kind == "charge" and not self._free_window_active(now):
            raise ManualTestError("force-charge tests are blocked outside the free window")
        soc = self.coordinator.snapshot.battery_soc if self.coordinator.snapshot else None
        if soc is None:
            raise ManualTestError("battery SOC telemetry is unavailable")
        if kind == "charge" and soc >= 100.0:
            raise ManualTestError("battery is already at 100% SOC")
        if kind == "discharge" and soc <= self.coordinator.snapshot.battery_floor_percent:
            raise ManualTestError("battery is at or below its configured floor")
        observation = self._observation()
        decision = ControlDecision(
            "force_charge" if kind == "charge" else "force_discharge",
            power,
            f"manual_test_{kind}",
        )
        adapter = self._get_adapter()
        plan = plan_foxess_commands(
            decision,
            observation,
            charge_power_max_kw=self._limit(CONF_INVERTER_CHARGE_LIMIT_KW),
            discharge_power_max_kw=self._limit(CONF_INVERTER_DISCHARGE_LIMIT_KW),
        )
        self.active_kind = kind
        self.started_at = now
        self.ends_at = now.replace(microsecond=0) + timedelta(minutes=duration)
        self.last_reason = f"starting_{kind}"
        try:
            await adapter.async_execute(plan)
        except Exception:
            # Latch the test so the automatic controller cannot race a
            # partially accepted request; the stop action remains available.
            self.last_reason = f"start_{kind}_failed"
            self.coordinator.async_update_listeners()
            raise
        self.last_reason = f"started_{kind}"
        self._cancel_timer = async_call_later(
            self.hass, duration * 60, self._async_expire
        )
        self.coordinator.async_update_listeners()

    async def async_stop(self, reason: str = "stopped_by_user") -> None:
        """Restore Self Use and clear a running test."""
        if not self.is_active:
            self.last_reason = reason
            self.coordinator.async_update_listeners()
            return
        adapter = self._get_adapter()
        try:
            observation = self._observation()
        except ManualTestError:
            # Feedback can disappear during a test.  Clear both targets and
            # select Self Use so the stop path remains fail-safe.
            plan = FoxessCommandPlan(
                (
                    FoxessCommand("select_mode", "Self Use"),
                    FoxessCommand("set_charge_power", 0.0),
                    FoxessCommand("set_discharge_power", 0.0),
                ),
                reason,
            )
        else:
            decision = ControlDecision("restore_self_use", 0.0, reason)
            plan = plan_foxess_commands(
                decision,
                observation,
                charge_power_max_kw=max(self._limit(CONF_INVERTER_CHARGE_LIMIT_KW), 0.0),
                discharge_power_max_kw=max(self._limit(CONF_INVERTER_DISCHARGE_LIMIT_KW), 0.0),
            )
        await adapter.async_execute(plan)
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None
        self.active_kind = None
        self.started_at = None
        self.ends_at = None
        self.last_reason = reason
        self.coordinator.async_update_listeners()

    async def _async_expire(self, _now) -> None:
        try:
            await self.async_stop("timer_expired")
        except Exception:  # pragma: no cover - surfaced in HA logs
            self.last_reason = "timer_expiry_stop_failed"
            self.coordinator.async_update_listeners()

    def _require_gate(self) -> None:
        owner = self.coordinator.config.get(
            CONF_FOXESS_CONTROL_OWNER, DEFAULT_FOXESS_CONTROL_OWNER
        )
        if owner != FOXESS_CONTROL_OWNER_MODBUS:
            raise ManualTestError(
                "select Local Modbus as the FoxESS control owner before a diagnostic test"
            )
        if self.coordinator.config.get(CONF_REHEARSAL_MODE, True):
            raise ManualTestError("disable Rehearsal mode before running a diagnostic test")
        if not all(
            self.coordinator.config.get(key)
            for key in (
                CONF_FOXESS_WORK_MODE,
                CONF_FOXESS_FORCE_CHARGE_POWER,
                CONF_FOXESS_FORCE_DISCHARGE_POWER,
            )
        ):
            raise ManualTestError("complete the three FoxESS actuator mappings first")
        if self.coordinator.snapshot is None or self.coordinator.data is None:
            raise ManualTestError("live telemetry is unavailable")

    def _validate_power(self, kind: str, value: float) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError) as err:
            raise ManualTestError("test power must be numeric") from err
        maximum = self._limit(
            CONF_INVERTER_CHARGE_LIMIT_KW
            if kind == "charge"
            else CONF_INVERTER_DISCHARGE_LIMIT_KW
        )
        if not isfinite(value) or value <= 0 or maximum <= 0 or value > maximum:
            raise ManualTestError(f"test power must be between 0 and {maximum:g} kW")
        return round(value, 3)

    def _validate_duration(self, value: float) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError) as err:
            raise ManualTestError("test duration must be numeric") from err
        if not isfinite(value) or value <= 0 or value > self.MAX_DURATION_MINUTES:
            raise ManualTestError(
                f"test duration must be between 0 and {self.MAX_DURATION_MINUTES:g} minutes"
            )
        return round(value, 2)

    def _get_adapter(self) -> FoxessServiceAdapter:
        if self._adapter is None:
            self._adapter = FoxessServiceAdapter(
                self.hass,
                FoxessEntityMap(
                    str(self.coordinator.config[CONF_FOXESS_WORK_MODE]),
                    str(self.coordinator.config[CONF_FOXESS_FORCE_CHARGE_POWER]),
                    str(self.coordinator.config[CONF_FOXESS_FORCE_DISCHARGE_POWER]),
                ),
                allow_writes=True,
            )
        return self._adapter

    def _observation(self) -> FoxessObservation:
        mode_id = self.coordinator.config.get(CONF_FOXESS_WORK_MODE)
        charge_id = self.coordinator.config.get(CONF_FOXESS_FORCE_CHARGE_POWER)
        discharge_id = self.coordinator.config.get(CONF_FOXESS_FORCE_DISCHARGE_POWER)
        mode_state = self.hass.states.get(str(mode_id))
        charge_state = self.hass.states.get(str(charge_id))
        discharge_state = self.hass.states.get(str(discharge_id))
        if not mode_state or not charge_state or not discharge_state:
            raise ManualTestError("FoxESS actuator feedback is unavailable")
        try:
            charge = power_to_kw(
                float(charge_state.state), charge_state.attributes.get("unit_of_measurement")
            )
            discharge = power_to_kw(
                float(discharge_state.state), discharge_state.attributes.get("unit_of_measurement")
            )
        except (TypeError, ValueError):
            raise ManualTestError("FoxESS power feedback is unavailable") from None
        return FoxessObservation(mode_state.state, charge, discharge)

    def _limit(self, key: str) -> float:
        try:
            value = float(self.coordinator.config.get(key, 0.0))
        except (TypeError, ValueError):
            return 0.0
        return value if isfinite(value) and value >= 0 else 0.0

    def _rate(self, key: str, default: float) -> float:
        try:
            value = float(self.coordinator.config.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if isfinite(value) and value >= 0 else default

    def _free_window_active(self, now: datetime) -> bool:
        return self.coordinator._free_window_hours_remaining(now) > 0

    def _bonus_window_active(self, now: datetime) -> bool:
        """Evaluate the configured local-time ZEROHERO export window."""
        checker = getattr(self.coordinator, "_bonus_window_active", None)
        if checker is not None:
            return bool(checker(now))
        start = self.coordinator._configured_time("bonus_window_start", "18:00:00")
        end = self.coordinator._configured_time("bonus_window_end", "21:00:00")
        current = now.timetz().replace(tzinfo=None)
        return (start <= current < end) if start < end else (current >= start or current < end)
