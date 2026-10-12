"""Explicit, time-limited FoxESS commissioning tests.

The test surface is deliberately separate from the automatic coordinator. It
refuses charge tests outside the configured free window, bounds power and
duration, derives the active export tariff from the site configuration, and
always restores Self Use when the timer expires or the integration unloads.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from functools import partial
from math import isfinite

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BONUS_WINDOW_END,
    CONF_BONUS_WINDOW_START,
    CONF_EXPORT_RATE_WINDOW_END,
    CONF_EXPORT_RATE_WINDOW_START,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_PEAK_WINDOW_END,
    CONF_PEAK_WINDOW_START,
    DEFAULT_BONUS_WINDOW_END,
    DEFAULT_BONUS_WINDOW_START,
    DEFAULT_EXPORT_RATE_WINDOW_END,
    DEFAULT_EXPORT_RATE_WINDOW_START,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from .coordinator import EnergyCoordinator
from .foxess_adapter import FoxessEntityMap, FoxessServiceAdapter
from .foxess_observation_adapter import capture_foxess_feedback
from .persistence import TypedValueStoreRepository
from .planner.foxess import (
    ControlDecision,
    FoxessCommand,
    FoxessCommandPlan,
    FoxessObservation,
    plan_foxess_commands,
)
from .planner.manual_test import (
    ManualTestEstimate,
    ManualTestPersistenceState,
    estimate_charge,
    estimate_discharge,
)


class ManualTestError(ValueError):
    """Raised when a commissioning test is not safe to start."""


class ManualTestController:
    """Own one short-lived manual charge or discharge test."""

    MAX_DURATION_MINUTES = 120.0
    MAX_RESTORE_ATTEMPTS = 3
    RESTORE_RETRY_SECONDS = 30.0

    def __init__(self, hass: HomeAssistant, coordinator: EnergyCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.charge_power_kw = 1.0
        self.discharge_power_kw = 1.0
        self.duration_minutes = 5.0
        self.active_kind: str | None = None
        self.phase = "idle"
        self.started_at: datetime | None = None
        self.ends_at: datetime | None = None
        self.restore_attempts = 0
        self.last_restore_at: datetime | None = None
        self.last_reason = "idle"
        self.storage_status = "not_loaded"
        self._cancel_timer = None
        self._cancel_restore = None
        self._adapter: FoxessServiceAdapter | None = None
        self._generation = 0
        self._write_generation: int | None = None
        self._hardware_lock = asyncio.Lock()
        self._save_lock = asyncio.Lock()
        self._store: Store[dict[str, object]] = Store(
            hass,
            1,
            f"home_energy_orchestrator.{coordinator.entry_id}.manual_test",
            private=True,
        )
        self._repository = TypedValueStoreRepository(
            self._store,
            decode=lambda payload: ManualTestPersistenceState.from_payload(
                payload,
                maximum_restore_attempts=self.MAX_RESTORE_ATTEMPTS,
            ),
            encode=ManualTestPersistenceState.to_payload,
        )

    @property
    def is_active(self) -> bool:
        return self.active_kind is not None

    @property
    def status(self) -> str:
        if self.active_kind is None:
            return "idle"
        if self.phase == "running":
            return f"active_{self.active_kind}"
        return f"{self.phase}_{self.active_kind}"

    @property
    def remaining_minutes(self) -> float:
        if self.ends_at is None:
            return 0.0
        return max(0.0, (self.ends_at - dt_util.now()).total_seconds() / 60)

    async def async_startup(self) -> None:
        """Restore an unfinished test and make its cleanup obligation durable."""
        await self._async_load()
        if not self.is_active:
            return
        self.phase = "stopping"
        self.last_reason = "restart_restore_pending"
        await self._async_save()
        try:
            await self._async_reconcile_restore("integration_restarted")
        except Exception:
            # Keep setup available so the visible persisted fault and its
            # scheduled bounded retry are not replaced by an entry setup error.
            return

    async def async_unload(self) -> None:
        """Attempt one restoration and persist any unfinished recovery."""
        self._cancel_callbacks()
        if not self.is_active:
            return
        self.phase = "stopping"
        self.last_reason = "integration_unload_restore_pending"
        await self._async_save()
        try:
            await self._async_reconcile_restore(
                "integration_unloaded", schedule_retry=False
            )
        except Exception:
            # The mapped integration or its services may already be unloading.
            # Persisted state makes the next setup resume restoration.
            return

    def preview_charge(self) -> ManualTestEstimate:
        now = dt_util.now()
        free_remaining = 0.0
        if self.coordinator.data is not None:
            free_remaining = max(self.coordinator.data.free_energy_remaining_kwh or 0.0, 0.0)
        tariff = self.coordinator.runtime_config.tariff
        return estimate_charge(
            self.charge_power_kw,
            self.duration_minutes,
            free_window_active=self._free_window_active(now),
            free_energy_remaining_kwh=free_remaining,
            offpeak_rate=tariff.effective_offpeak_import_rate_per_kwh,
            offpeak_balance_rate=(
                tariff.effective_offpeak_balance_rate_per_kwh
            ),
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
        tariff = self.coordinator.runtime_config.tariff
        standard_rate = (
            tariff.effective_peak_export_rate_per_kwh
            if self._standard_export_window_active(now)
            else tariff.effective_offpeak_export_rate_per_kwh
        )
        if self._bonus_window_active(now):
            return standard_rate + tariff.effective_additional_export_rate_per_kwh
        return standard_rate

    def current_import_rate(self, now: datetime | None = None) -> float:
        """Return the configured import rate at the current local time."""
        now = now or dt_util.now()
        if self._free_window_active(now):
            remaining = (
                0.0
                if self.coordinator.data is None
                else max(self.coordinator.data.free_energy_remaining_kwh or 0.0, 0.0)
            )
            tariff = self.coordinator.runtime_config.tariff
            return (
                tariff.effective_offpeak_import_rate_per_kwh
                if remaining > 0
                else tariff.effective_offpeak_balance_rate_per_kwh
            )
        start = self.coordinator._configured_time(CONF_PEAK_WINDOW_START, "16:00:00")
        end = self.coordinator._configured_time(CONF_PEAK_WINDOW_END, "23:00:00")
        current = now.timetz().replace(tzinfo=None)
        in_peak = (start <= current < end) if start < end else (current >= start or current < end)
        tariff = self.coordinator.runtime_config.tariff
        return (
            tariff.effective_peak_import_rate_per_kwh
            if in_peak
            else tariff.effective_shoulder_import_rate_per_kwh
        )

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
        self._generation += 1
        generation = self._generation
        self.active_kind = kind
        self.phase = "starting"
        self.started_at = now
        self.ends_at = now.replace(microsecond=0) + timedelta(minutes=duration)
        self.restore_attempts = 0
        self.last_restore_at = None
        self.last_reason = f"starting_{kind}"
        try:
            await self._async_save()
            async with self._shared_hardware_lock():
                if generation != self._generation or not self.is_active:
                    return
                self._write_generation = generation
                await adapter.async_execute(plan)
            if generation != self._generation or not self.is_active:
                return
            self.phase = "running"
            self.last_reason = f"started_{kind}"
            await self._async_save()
            if generation != self._generation or not self.is_active:
                return
            self._cancel_timer = async_call_later(
                self.hass,
                duration * 60,
                partial(self._async_expire, generation=generation),
            )
            self.coordinator.async_update_listeners()
        except asyncio.CancelledError:
            await self._async_cancel_start(generation)
            raise
        except Exception:
            if generation != self._generation:
                return
            # Latch the test so the automatic controller cannot race a
            # partially accepted request; the stop action remains available.
            self.last_reason = f"start_{kind}_failed"
            self.coordinator.async_update_listeners()
            raise

    async def _async_cancel_start(self, generation: int) -> None:
        """Retain reducing cleanup after cancellation, without reviving old intent."""
        if generation != self._generation or not self.is_active:
            return
        self._generation += 1
        cleanup_generation = self._generation
        self._cancel_callbacks()
        self.phase = "stopping"
        self.last_reason = "cancelled_start_restore_pending"
        checkpoint = asyncio.create_task(self._async_save())
        while not checkpoint.done():
            try:
                # wait() shields the child from caller cancellation without
                # creating a cancelled shield future that logs a later I/O
                # exception before the cleanup path can consume it.
                await asyncio.wait({checkpoint})
            except asyncio.CancelledError:
                # A repeated cancellation cannot erase the accepted command's
                # cleanup ticket or let a previous snapshot finish after it.
                continue
            except Exception:
                break
        try:
            checkpoint.result()
        except Exception:
            if cleanup_generation == self._generation and self.is_active:
                self.last_reason = "cancelled_start_restore_storage_failed"
        if cleanup_generation != self._generation or not self.is_active:
            return
        self._schedule_restore("cancelled_start", generation=cleanup_generation)
        self.coordinator.async_update_listeners()

    async def async_stop(self, reason: str = "stopped_by_user") -> None:
        """Request a confirmed, bounded Self Use restoration."""
        if not self.is_active:
            self.last_reason = reason
            self.coordinator.async_update_listeners()
            return
        self._generation += 1
        if self.phase == "restore_failed":
            self.restore_attempts = 0
            self.last_restore_at = None
        self.phase = "stopping"
        self.last_reason = f"{reason}_pending"
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None
        await self._async_save()
        await self._async_reconcile_restore(reason)

    async def _async_reconcile_restore(self, reason: str, *, schedule_retry: bool = True) -> None:
        """Confirm restoration or issue one bounded retry."""
        if not self.is_active:
            return
        generation = self._generation
        if blocked_reason := self._restore_gate_reason():
            self.phase = "stopping"
            self.last_reason = blocked_reason
            await self._async_save()
            if generation != self._generation or not self.is_active:
                return
            self.coordinator.async_update_listeners()
            if schedule_retry:
                self._schedule_restore(reason, generation=generation)
            return
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
                charge_power_max_kw=max(
                    self._limit(CONF_INVERTER_CHARGE_LIMIT_KW), 0.0
                ),
                discharge_power_max_kw=max(
                    self._limit(CONF_INVERTER_DISCHARGE_LIMIT_KW), 0.0
                ),
            )
            if not plan.commands:
                if generation == self._generation:
                    await self._async_clear(reason)
                return
        if self.restore_attempts >= self.MAX_RESTORE_ATTEMPTS:
            self.phase = "restore_failed"
            self.last_reason = "restore_max_attempts_exceeded"
            await self._async_save()
            self.coordinator.async_update_listeners()
            return
        self.restore_attempts += 1
        self.last_restore_at = dt_util.now()
        self.phase = "stopping"
        self.last_reason = f"{reason}_attempt_{self.restore_attempts}"
        await self._async_save()
        try:
            async with self._shared_hardware_lock():
                if generation != self._generation or not self.is_active:
                    return
                self._write_generation = generation
                await self._get_adapter().async_execute(plan)
        except Exception:
            if generation != self._generation:
                return
            self.last_reason = f"{reason}_attempt_failed"
            await self._async_save()
            if generation != self._generation or not self.is_active:
                return
            self.coordinator.async_update_listeners()
            if schedule_retry:
                self._schedule_restore(reason, generation=generation)
            raise
        if generation != self._generation:
            return
        self.coordinator.async_update_listeners()
        if schedule_retry:
            self._schedule_restore(reason, generation=generation)

    async def _async_clear(self, reason: str) -> None:
        self._cancel_callbacks()
        self.active_kind = None
        self.phase = "idle"
        self.started_at = None
        self.ends_at = None
        self.restore_attempts = 0
        self.last_restore_at = None
        self.last_reason = reason
        await self._async_save()
        self.coordinator.async_update_listeners()

    def _schedule_restore(self, reason: str, *, generation: int | None = None) -> None:
        generation = self._generation if generation is None else generation
        if generation != self._generation or not self.is_active:
            return
        if self._cancel_restore is not None:
            self._cancel_restore()
        self._cancel_restore = async_call_later(
            self.hass,
            self.RESTORE_RETRY_SECONDS,
            partial(self._async_retry_restore, reason, generation=generation),
        )

    async def _async_retry_restore(
        self, reason: str, _now=None, *, generation: int | None = None
    ) -> None:
        if generation is not None and generation != self._generation:
            return
        self._cancel_restore = None
        try:
            await self._async_reconcile_restore(reason)
        except Exception:  # pragma: no cover - surfaced through persistent status
            return

    def _cancel_callbacks(self) -> None:
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None
        if self._cancel_restore is not None:
            self._cancel_restore()
            self._cancel_restore = None

    async def _async_expire(self, _now, *, generation: int | None = None) -> None:
        if generation is not None and generation != self._generation:
            return
        try:
            await self.async_stop("timer_expired")
        except Exception:  # pragma: no cover - surfaced in HA logs
            self.last_reason = "timer_expiry_stop_failed"
            await self._async_save()
            self.coordinator.async_update_listeners()

    async def _async_load(self) -> None:
        restored = await self._repository.async_load()
        status = self._repository.last_restore_status
        self.storage_status = {
            "restored": "valid",
            "missing": "missing",
            "invalid": "malformed",
        }[status]
        if status != "restored" or restored.active_kind is None:
            return
        self.active_kind = restored.active_kind
        self.phase = restored.phase
        self.started_at = restored.started_at
        self.ends_at = restored.ends_at
        self.restore_attempts = restored.restore_attempts
        self.last_restore_at = restored.last_restore_at

    async def async_checkpoint_safe_idle(self) -> None:
        """Replace degraded evidence only after externally verified Self Use."""
        if self.is_active:
            return
        self.phase = "idle"
        await self._async_save()
        self.storage_status = "valid"

    async def _async_save(self) -> None:
        async with self._save_lock:
            checkpoint = asyncio.create_task(
                self._repository.async_save(
                    ManualTestPersistenceState(
                        active_kind=self.active_kind,
                        phase=self.phase,
                        started_at=self.started_at,
                        ends_at=self.ends_at,
                        restore_attempts=self.restore_attempts,
                        last_restore_at=self.last_restore_at,
                    )
                )
            )
            cancelled = False
            while not checkpoint.done():
                try:
                    # wait() never propagates waiter cancellation into the
                    # underlying Store task; keep the lock until it finishes.
                    await asyncio.wait({checkpoint})
                except asyncio.CancelledError:
                    # Keep serialization until the underlying storage write
                    # finishes; a cleanup/handoff must be the later snapshot.
                    cancelled = True
            try:
                checkpoint.result()
            except Exception as error:
                if cancelled:
                    raise asyncio.CancelledError from error
                raise
            if cancelled:
                raise asyncio.CancelledError

    def _shared_hardware_lock(self):
        automatic = getattr(self.coordinator, "active_controller", None)
        return getattr(automatic, "_reconcile_lock", self._hardware_lock)

    async def async_relinquish_for_manual(self) -> None:
        """Cancel diagnostic intent under an operator hold, without any restore write."""
        self._generation += 1
        self._cancel_callbacks()
        self.active_kind = None
        self.phase = "idle"
        self.started_at = self.ends_at = self.last_restore_at = None
        self.restore_attempts = 0
        self.last_reason = "manual_inverter_handoff"
        await self._async_save()

    def _require_gate(self) -> None:
        runtime = self.coordinator.runtime_config
        if runtime.automation.control_owner != FOXESS_CONTROL_OWNER_MODBUS:
            raise ManualTestError(
                "select Local Modbus as the FoxESS control owner before a diagnostic test"
            )
        if runtime.automation.safety_lock:
            raise ManualTestError("disable Rehearsal mode before running a diagnostic test")
        if not runtime.inverter.actuator_mapping_complete:
            raise ManualTestError("complete the three FoxESS actuator mappings first")
        if self.coordinator.snapshot is None or self.coordinator.data is None:
            raise ManualTestError("live telemetry is unavailable")
        automatic = getattr(self.coordinator, "active_controller", None)
        handoff = getattr(automatic, "manual", None)
        if handoff is not None and handoff.is_active:
            raise ManualTestError("resume automatic battery control before a diagnostic test")
        if automatic is not None and any(
            session.phase != "idle"
            for session in (automatic.charge_session, automatic.export_session)
        ):
            raise ManualTestError(
                "stop the active automatic FoxESS session before a diagnostic test"
            )

    def _restore_gate_reason(self) -> str | None:
        """Return the no-write reason for a persisted restoration obligation."""
        runtime = self.coordinator.runtime_config
        automatic = getattr(self.coordinator, "active_controller", None)
        handoff = getattr(automatic, "manual", None)
        if handoff is not None and handoff.is_active:
            return "restore_blocked_manual_inverter_hold"
        if runtime.automation.control_owner != FOXESS_CONTROL_OWNER_MODBUS:
            return "restore_blocked_control_owner"
        if runtime.automation.safety_lock:
            return "restore_blocked_safety_lock"
        if not runtime.inverter.actuator_mapping_complete:
            return "restore_blocked_incomplete_mapping"
        return None

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
            inverter = self.coordinator.runtime_config.inverter
            if not inverter.actuator_mapping_complete:
                raise ManualTestError("complete the three FoxESS actuator mappings first")
            assert inverter.work_mode_entity is not None
            assert inverter.force_charge_power_entity is not None
            assert inverter.force_discharge_power_entity is not None
            self._adapter = FoxessServiceAdapter(
                self.hass,
                FoxessEntityMap(
                    inverter.work_mode_entity,
                    inverter.force_charge_power_entity,
                    inverter.force_discharge_power_entity,
                ),
                allow_writes=True,
                write_guard=self._diagnostic_write_authorized,
            )
        return self._adapter

    def _diagnostic_write_authorized(self) -> bool:
        if not self.is_active or self._write_generation != self._generation:
            return False
        if self._restore_gate_reason() is not None:
            return False
        inverter = self.coordinator.runtime_config.inverter
        return self._adapter is not None and self._adapter.entities == FoxessEntityMap(
            str(inverter.work_mode_entity),
            str(inverter.force_charge_power_entity),
            str(inverter.force_discharge_power_entity),
        )

    def _observation(self) -> FoxessObservation:
        inverter = self.coordinator.runtime_config.inverter
        mode_id = inverter.work_mode_entity
        charge_id = inverter.force_charge_power_entity
        discharge_id = inverter.force_discharge_power_entity
        feedback = capture_foxess_feedback(
            self.hass,
            FoxessEntityMap(str(mode_id), str(charge_id), str(discharge_id)),
        )
        if not feedback.mapped_entities_available:
            raise ManualTestError("FoxESS actuator feedback is unavailable")
        if feedback.manual_observation is None:
            raise ManualTestError("FoxESS power feedback is unavailable")
        return feedback.manual_observation

    def _limit(self, key: str) -> float:
        inverter = self.coordinator.runtime_config.inverter
        value = (
            inverter.charge_limit_kw
            if key == CONF_INVERTER_CHARGE_LIMIT_KW
            else inverter.discharge_limit_kw
            if key == CONF_INVERTER_DISCHARGE_LIMIT_KW
            else 0.0
        )
        return value if isfinite(value) and value >= 0 else 0.0

    def _free_window_active(self, now: datetime) -> bool:
        return self.coordinator._free_window_hours_remaining(now) > 0

    def _bonus_window_active(self, now: datetime) -> bool:
        """Evaluate the configured local-time ZEROHERO export window."""
        checker = getattr(self.coordinator, "_bonus_window_active", None)
        if checker is not None:
            return bool(checker(now))
        start = self.coordinator._configured_time(
            CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START
        )
        end = self.coordinator._configured_time(
            CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END
        )
        current = now.timetz().replace(tzinfo=None)
        return (start <= current < end) if start < end else (current >= start or current < end)

    def _standard_export_window_active(self, now: datetime) -> bool:
        """Evaluate the configured standard feed-in tariff window."""
        start = self.coordinator._configured_time(
            CONF_EXPORT_RATE_WINDOW_START, DEFAULT_EXPORT_RATE_WINDOW_START
        )
        end = self.coordinator._configured_time(
            CONF_EXPORT_RATE_WINDOW_END, DEFAULT_EXPORT_RATE_WINDOW_END
        )
        current = now.timetz().replace(tzinfo=None)
        return (start <= current < end) if start < end else (current >= start or current < end)
