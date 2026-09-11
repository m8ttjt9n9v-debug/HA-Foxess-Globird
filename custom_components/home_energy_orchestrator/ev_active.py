"""Commissioned EV runtime for the ported pilot-site charging policy."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from math import isfinite

from homeassistant.components import persistent_notification
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_CHARGE_EFFICIENCY,
    CONF_BATTERY_FREE_WINDOW_TARGET,
    CONF_BATTERY_SOC,
    CONF_BONUS_WINDOW_END,
    CONF_BONUS_WINDOW_START,
    CONF_DAILY_FREE_ALLOWANCE_KWH,
    CONF_DISCHARGE_EFFICIENCY_PERCENT,
    CONF_EV_ACTUAL_CURRENT,
    CONF_EV_ALLOWANCE_GUARD_ENABLED,
    CONF_EV_ALLOWANCE_SAFETY_MARGIN,
    CONF_EV_ARRIVAL_RESERVE_SOC,
    CONF_EV_AT_HOME,
    CONF_EV_BACKFILL_BUFFER_MINUTES,
    CONF_EV_CABLE_CONNECTED,
    CONF_EV_CHARGE_EFFICIENCY,
    CONF_EV_CHARGE_LIMIT,
    CONF_EV_CHARGE_PATH,
    CONF_EV_CHARGE_SWITCH,
    CONF_EV_CHARGE_TO_FULL,
    CONF_EV_CHARGE_TO_FULL_ENABLED,
    CONF_EV_CHARGE_TO_FULL_MAX_HOURS,
    CONF_EV_CHARGING_STATE,
    CONF_EV_CURRENT_LIMIT,
    CONF_EV_DAILY_BACKFILL_ENERGY,
    CONF_EV_DAILY_READY_TIME,
    CONF_EV_DIRECT_LIMIT_HEADROOM,
    CONF_EV_FREE_WINDOW_CHARGE_LIMIT,
    CONF_EV_FREE_WINDOW_MINIMUM_CURRENT,
    CONF_EV_FREE_WINDOW_PRIORITY,
    CONF_EV_FREE_WINDOW_SETTLE_MINUTES,
    CONF_EV_LEARNING_MINIMUM_SAMPLES,
    CONF_EV_LIFETIME_ENERGY,
    CONF_EV_LOCATION_MODE,
    CONF_EV_MAX_CURRENT,
    CONF_EV_OUTSIDE_INVERTER_PERCENT,
    CONF_EV_PHASE_COUNT,
    CONF_EV_PRE_FREE_ENABLED,
    CONF_EV_PROTECTED_BASELINE_A,
    CONF_EV_SMART_RECOVERY_CHARGING_CONFIRM_SECONDS,
    CONF_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS,
    CONF_EV_SMART_RECOVERY_IDLE_CURRENT_A,
    CONF_EV_SMART_RECOVERY_NO_POWER_SECONDS,
    CONF_EV_SMART_RECOVERY_POST_POWER_SECONDS,
    CONF_EV_SMART_RECOVERY_POWER_OFF_SECONDS,
    CONF_EV_SMART_RECOVERY_REARM_SECONDS,
    CONF_EV_SMART_RECOVERY_SOCKET_CONFIRM_SECONDS,
    CONF_EV_SMART_SOCKET,
    CONF_EV_SMART_SOCKET_CURRENT_LIMIT,
    CONF_EV_SMART_SOCKET_POWER_SWITCHING,
    CONF_EV_SMART_SOCKET_RETRY_SECONDS,
    CONF_EV_SMART_SOCKET_SETTLE_SECONDS,
    CONF_EV_SOC,
    CONF_EV_SOLAR_SPILL_BATTERY_SOC,
    CONF_EV_SOLAR_SPILL_ENABLED,
    CONF_EV_STORED_ENERGY,
    CONF_EV_TELEMETRY_MAX_AGE_SECONDS,
    CONF_EV_TELEMETRY_MAX_SKEW_SECONDS,
    CONF_EV_VOLTAGE,
    CONF_FORCE_DISCHARGE_FINISH,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FREE_CHARGE_END,
    CONF_FREE_CHARGE_START,
    CONF_HOUSE_LOAD_INCLUDES_EV,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_SERVICE_IMPORT_LIMIT_A,
    CONF_SITE_GRID_HEADROOM_CURRENT,
    CONF_SITE_PHASE_COUNT,
    DEFAULT_BATTERY_CHARGE_EFFICIENCY,
    DEFAULT_BATTERY_FREE_WINDOW_TARGET,
    DEFAULT_BONUS_WINDOW_END,
    DEFAULT_BONUS_WINDOW_START,
    DEFAULT_DAILY_FREE_ALLOWANCE_KWH,
    DEFAULT_DISCHARGE_EFFICIENCY_PERCENT,
    DEFAULT_EV_ALLOWANCE_GUARD_ENABLED,
    DEFAULT_EV_ALLOWANCE_SAFETY_MARGIN,
    DEFAULT_EV_ARRIVAL_RESERVE_SOC,
    DEFAULT_EV_BACKFILL_BUFFER_MINUTES,
    DEFAULT_EV_CHARGE_EFFICIENCY,
    DEFAULT_EV_CHARGE_PATH,
    DEFAULT_EV_CHARGE_TO_FULL_ENABLED,
    DEFAULT_EV_CHARGE_TO_FULL_MAX_HOURS,
    DEFAULT_EV_DAILY_BACKFILL_ENERGY,
    DEFAULT_EV_DAILY_READY_TIME,
    DEFAULT_EV_DIRECT_LIMIT_HEADROOM,
    DEFAULT_EV_FREE_WINDOW_CHARGE_LIMIT,
    DEFAULT_EV_FREE_WINDOW_MINIMUM_CURRENT,
    DEFAULT_EV_FREE_WINDOW_PRIORITY,
    DEFAULT_EV_FREE_WINDOW_SETTLE_MINUTES,
    DEFAULT_EV_LEARNING_MINIMUM_SAMPLES,
    DEFAULT_EV_LOCATION_MODE,
    DEFAULT_EV_OUTSIDE_INVERTER_PERCENT,
    DEFAULT_EV_PHASE_COUNT,
    DEFAULT_EV_PRE_FREE_ENABLED,
    DEFAULT_EV_PROTECTED_BASELINE_A,
    DEFAULT_EV_SMART_RECOVERY_CHARGING_CONFIRM_SECONDS,
    DEFAULT_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS,
    DEFAULT_EV_SMART_RECOVERY_IDLE_CURRENT_A,
    DEFAULT_EV_SMART_RECOVERY_NO_POWER_SECONDS,
    DEFAULT_EV_SMART_RECOVERY_POST_POWER_SECONDS,
    DEFAULT_EV_SMART_RECOVERY_POWER_OFF_SECONDS,
    DEFAULT_EV_SMART_RECOVERY_REARM_SECONDS,
    DEFAULT_EV_SMART_RECOVERY_SOCKET_CONFIRM_SECONDS,
    DEFAULT_EV_SMART_SOCKET_CURRENT_LIMIT,
    DEFAULT_EV_SMART_SOCKET_POWER_SWITCHING,
    DEFAULT_EV_SMART_SOCKET_RETRY_SECONDS,
    DEFAULT_EV_SMART_SOCKET_SETTLE_SECONDS,
    DEFAULT_EV_SOLAR_SPILL_BATTERY_SOC,
    DEFAULT_EV_SOLAR_SPILL_ENABLED,
    DEFAULT_EV_TELEMETRY_MAX_AGE_SECONDS,
    DEFAULT_EV_TELEMETRY_MAX_SKEW_SECONDS,
    DEFAULT_EV_VOLTAGE,
    DEFAULT_FORCE_DISCHARGE_FINISH,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DEFAULT_FREE_CHARGE_END,
    DEFAULT_FREE_CHARGE_START,
    DEFAULT_HOUSE_LOAD_INCLUDES_EV,
    DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
    DEFAULT_SERVICE_IMPORT_LIMIT_A,
    DEFAULT_SITE_GRID_HEADROOM_CURRENT,
    DEFAULT_SITE_PHASE_COUNT,
    EV_CHARGE_PATH_SMART_SOCKET,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from .coordinator import EnergyCoordinator
from .ev_adapter import EvEntityMap, EvServiceAdapter, EvWriteBlocked, ev_control_gate_status
from .normalise import current_to_a, energy_to_kwh
from .planner.ev import (
    DIRECT_EVSE_MAX_ATTEMPTS,
    AllowanceCeilingInputs,
    ChargeLimitInputs,
    DirectEvseObservation,
    DirectEvseReconciliationState,
    EvCommand,
    EvCommandPlan,
    EvCurrentDecision,
    FreeWindowCurrentInputs,
    SmartSocketObservation,
    SmartSocketRecoveryObservation,
    SmartSocketRecoveryState,
    apply_daily_allowance_ceiling,
    estimate_other_free_window_import_kwh,
    estimate_vehicle_energy_to_target_kwh,
    house_load_excluding_ev_kw,
    plan_charge_limit_target,
    plan_direct_evse_commands,
    plan_free_window_current,
    plan_smart_socket_commands,
    reconcile_direct_evse,
    reconcile_smart_socket_recovery,
)
from .planner.ev_daily_backfill import (
    DailyBackfillInputs,
    DailyBackfillPlan,
    calculate_daily_backfill_plan,
)
from .planner.ev_learning import (
    DrivingSnapshotState,
    LearnedChargeLimitDecision,
    estimate_free_window_soc_gain_percent,
    estimate_usable_ev_capacity_kwh,
    plan_learned_general_charge_limit,
    snapshot_daily_driving_energy,
)
from .planner.ev_outside_window import (
    PreFreeCurrentInputs,
    PreFreePlan,
    PreFreePlanInputs,
    PreFreeSessionState,
    SolarSpillDecision,
    SolarSpillInputs,
    advance_pre_free_session,
    calculate_pre_free_plan,
    plan_pre_free_current,
    plan_solar_spill_current,
    select_outside_window_current,
)
from .planner.learning import DemandHistory
from .planner.timed_average import TimedAverageWindow

_LOGGER = logging.getLogger(__name__)
_UNKNOWN_STATES = {"unknown", "unavailable", ""}


class ActiveEvController:
    """Run the selected commissioned Tessie supply path; never write FoxESS."""

    def __init__(self, hass: HomeAssistant, coordinator: EnergyCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._unsub_interval: CALLBACK_TYPE | None = None
        self._unsub_driving_snapshot: CALLBACK_TYPE | None = None
        self._lock = asyncio.Lock()
        self._adapter: EvServiceAdapter | None = self._create_adapter()
        self._store: Store[dict[str, object]] = Store(
            hass,
            1,
            f"home_energy_orchestrator.{coordinator.entry_id}.ev_control",
            private=True,
        )
        self.grid_average = TimedAverageWindow(timedelta(minutes=3))
        self.ev_average = TimedAverageWindow(timedelta(minutes=3))
        self.reconciliation = DirectEvseReconciliationState()
        self.smart_recovery = SmartSocketRecoveryState()
        self.smart_stage_target_a: float | None = None
        self.smart_stage_started_at: datetime | None = None
        self.pre_free_session = PreFreeSessionState()
        self.pre_free_plan: PreFreePlan | None = None
        self.pre_free_phase = "disabled"
        self.solar_spill = SolarSpillDecision(0.0, 0.0, "disabled")
        self.driving_history = DemandHistory([])
        self.driving_snapshot = DrivingSnapshotState()
        self.daily_driving_energy_kwh: float | None = None
        self.learned_charge_limit: LearnedChargeLimitDecision | None = None
        self.pre_free_current_a: float | None = None
        self.daily_backfill_plan: DailyBackfillPlan | None = None
        self.daily_backfill_cycle_ready_at: datetime | None = None
        self.daily_backfill_delivered_kwh = 0.0
        self.daily_backfill_active = False
        self.daily_backfill_session_target_kwh = 0.0
        self.daily_backfill_session_start_delivered_kwh = 0.0
        self.daily_backfill_frozen_start: datetime | None = None
        self.daily_backfill_last_sample_at: datetime | None = None
        self.daily_backfill_last_actual_current_a: float | None = None
        self.daily_backfill_stop_pending = False
        self.daily_backfill_stop_attempts = 0
        self.daily_backfill_last_stop_at: datetime | None = None
        self.charge_to_full_started_at: datetime | None = None
        self.outside_control_active = False
        self.outside_target_active = False
        self.outside_stop_requested = False
        self.last_decision_at: datetime | None = None
        self._decision_fingerprint: tuple[object, ...] | None = None
        self._general_limit_write_fingerprint: tuple[float, float] | None = None
        self.last_saved_at: datetime | None = None
        self.target_current_a: float | None = None
        self.target_limit_percent: float | None = None
        self.requested_current_a: float | None = None
        self.applied_limit_percent: float | None = None
        self.charge_switch_on: bool | None = None
        self.actual_current_a: float | None = None
        self.decision_phase = "inactive"
        self.allowance_phase = "not_evaluated"
        self.allowance_house_load_kw: float | None = None
        self.allowance_ev_power_kw: float | None = None
        self.last_reason = "automatic_ev_control_disabled"
        self.last_actions: tuple[str, ...] = ()
        self.last_write_at: datetime | None = None
        self.writes_performed = 0

    @property
    def gate_status(self) -> str:
        return ev_control_gate_status(
            self.coordinator.config, adapter_connected=self._adapter is not None
        )

    async def async_start(self) -> None:
        await self._async_restore()
        if self._unsub_interval is None:
            self._unsub_interval = async_track_time_interval(
                self.hass, self._async_tick, timedelta(seconds=30)
            )
        if self._unsub_driving_snapshot is None:
            start = self.coordinator._configured_time(  # noqa: SLF001
                CONF_FREE_CHARGE_START, DEFAULT_FREE_CHARGE_START
            )
            self._unsub_driving_snapshot = async_track_time_change(
                self.hass,
                self._async_driving_boundary,
                hour=start.hour,
                minute=start.minute,
                second=start.second,
            )
        await self.async_reconcile()

    async def async_stop(self) -> None:
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None
        if self._unsub_driving_snapshot is not None:
            self._unsub_driving_snapshot()
            self._unsub_driving_snapshot = None
        await self._async_save()

    async def _async_tick(self, _now) -> None:
        await self.async_reconcile()
        self.coordinator.async_update_listeners()

    async def _async_driving_boundary(self, now: datetime) -> None:
        """Take the pilot's cumulative Tessie snapshot at the free-window start."""
        async with self._lock:
            await self._async_snapshot_driving(now)
        self.coordinator.async_update_listeners()

    async def _async_snapshot_driving(self, now: datetime) -> None:
        lifetime = self._entity_energy(CONF_EV_LIFETIME_ENERGY)
        if lifetime is None or self.driving_snapshot.snapshot_date == now.date():
            return
        transition = snapshot_daily_driving_energy(
            self.driving_snapshot,
            now=now,
            lifetime_energy_kwh=lifetime,
        )
        self.driving_snapshot = transition.state
        self.daily_driving_energy_kwh = transition.sample_kwh
        if transition.sample_kwh is not None:
            self.driving_history.add(now, transition.sample_kwh)
        await self._async_save(now)

    async def async_reconcile(self, now: datetime | None = None) -> None:
        """Sample feedback, make a three-minute decision, then reconcile safely."""
        async with self._lock:
            now = now or dt_util.now()
            self.last_actions = ()
            grid_current, grid_valid = self._grid_current_a()
            ev_current, ev_valid = self._actual_ev_current_a()
            self.actual_current_a = ev_current if ev_valid else None
            observation = self._observation()
            if observation is None:
                self.requested_current_a = None
                self.applied_limit_percent = None
                self.charge_switch_on = None
            else:
                self.requested_current_a = observation.requested_current_a
                self.applied_limit_percent = observation.charge_limit_percent
                self.charge_switch_on = observation.charge_switch_on
            self.grid_average.observe(now, grid_current, source_valid=grid_valid)
            self.ev_average.observe(now, ev_current, source_valid=ev_valid)
            self._update_daily_backfill_energy(
                now,
                ev_current if ev_valid else None,
            )
            if self.last_saved_at is None or now - self.last_saved_at >= timedelta(minutes=1):
                await self._async_save(now)

            gate = self.gate_status
            if gate not in {"ready", "safety_locked"}:
                self.last_reason = gate
                return
            charge_path = self.coordinator.config.get(CONF_EV_CHARGE_PATH, DEFAULT_EV_CHARGE_PATH)
            smart_path = charge_path == EV_CHARGE_PATH_SMART_SOCKET
            if not smart_path and (
                self.smart_recovery != SmartSocketRecoveryState()
                or self.smart_stage_target_a is not None
                or self.smart_stage_started_at is not None
            ):
                # Faithful port of the pilot latch-reset automation: changing
                # to Direct / EVSE ends the smart-socket fault episode even if
                # Tessie connection telemetry is currently unavailable.
                self.smart_recovery = SmartSocketRecoveryState()
                self.smart_stage_target_a = None
                self.smart_stage_started_at = None
                await self._async_save(now)
            if self._float(CONF_SITE_PHASE_COUNT, DEFAULT_SITE_PHASE_COUNT) > 1 and not grid_valid:
                self.last_reason = "multiphase_current_feedback_unavailable"
                return
            connected, connection_reason = self._connected_at_home()
            in_window, elapsed_minutes, remaining_hours = self._free_window(now)
            if not connected:
                if self.charge_to_full_started_at is not None:
                    await self._async_clear_charge_to_full()
                    self.charge_to_full_started_at = None
                self.daily_backfill_active = False
                self.daily_backfill_session_target_kwh = 0.0
                self.daily_backfill_session_start_delivered_kwh = 0.0
                self.daily_backfill_frozen_start = None
                self.daily_backfill_stop_pending = False
                self.daily_backfill_stop_attempts = 0
                self.daily_backfill_last_stop_at = None
                self.pre_free_session = PreFreeSessionState()
                self.pre_free_phase = "not_eligible"
                self.outside_control_active = False
                self.outside_target_active = False
                if smart_path and observation is not None and self._home_control_active():
                    await self._async_reconcile_disconnected_smart_socket(
                        now,
                        observation,
                        in_window=in_window,
                        gate=gate,
                    )
                    if self.last_actions or self.last_reason.startswith(
                        ("smart_socket_", "rehearsal_smart_socket_")
                    ):
                        return
                self.last_reason = connection_reason
                return
            if observation is None:
                self.last_reason = "ev_actuator_feedback_unavailable"
                return
            vehicle_soc = self._entity_number(CONF_EV_SOC)
            if vehicle_soc is not None:
                self._learned_general_limit(observation, vehicle_soc=vehicle_soc)
            if self._charge_to_full_requested():
                if self.charge_to_full_started_at is None:
                    self.charge_to_full_started_at = now
                maximum = observation.limit_maximum_percent or 100.0
                timed_out = now - self.charge_to_full_started_at >= timedelta(
                    hours=self._float(
                        CONF_EV_CHARGE_TO_FULL_MAX_HOURS,
                        DEFAULT_EV_CHARGE_TO_FULL_MAX_HOURS,
                    )
                )
                if (vehicle_soc is not None and vehicle_soc >= maximum) or timed_out:
                    await self._async_clear_charge_to_full()
                    self.charge_to_full_started_at = None
                    if (
                        self._float(
                            CONF_EV_PROTECTED_BASELINE_A,
                            DEFAULT_EV_PROTECTED_BASELINE_A,
                        )
                        <= 0
                    ):
                        self.daily_backfill_stop_pending = True
                        self.daily_backfill_stop_attempts = 0
                        self.daily_backfill_last_stop_at = None
            else:
                if (
                    self.charge_to_full_started_at is not None
                    and self._float(
                        CONF_EV_PROTECTED_BASELINE_A,
                        DEFAULT_EV_PROTECTED_BASELINE_A,
                    )
                    <= 0
                ):
                    self.daily_backfill_stop_pending = True
                    self.daily_backfill_stop_attempts = 0
                    self.daily_backfill_last_stop_at = None
                self.charge_to_full_started_at = None

            outside_enabled = bool(
                self._daily_backfill_enabled()
                or self._charge_to_full_requested()
                or self.daily_backfill_stop_pending
                or (
                    self.coordinator.config.get(
                        CONF_FOXESS_CONTROL_OWNER,
                        DEFAULT_FOXESS_CONTROL_OWNER,
                    )
                    == FOXESS_CONTROL_OWNER_MODBUS
                    and (
                        self.coordinator.config.get(
                            CONF_EV_SOLAR_SPILL_ENABLED, DEFAULT_EV_SOLAR_SPILL_ENABLED
                        )
                        or self.coordinator.config.get(
                            CONF_EV_PRE_FREE_ENABLED, DEFAULT_EV_PRE_FREE_ENABLED
                        )
                    )
                )
            )
            if not in_window and not outside_enabled and not self.outside_control_active:
                await self._async_reconcile_general_limit_only(
                    now,
                    observation,
                    vehicle_soc=vehicle_soc,
                    gate=gate,
                )
                return
            if not in_window and outside_enabled:
                # An opted-in outside-window policy owns the direct current even
                # when its discretionary target is zero. This preserves the
                # pilot's protected baseline after reconnects and restarts.
                self.outside_control_active = True

            charge_to_full_requested = self._charge_to_full_requested()
            decision_fingerprint = (
                vehicle_soc,
                charge_to_full_requested,
                self.coordinator.config.get(
                    CONF_EV_FREE_WINDOW_PRIORITY, DEFAULT_EV_FREE_WINDOW_PRIORITY
                ),
                observation.current_minimum_a,
                observation.current_maximum_a,
                observation.current_step_a,
                observation.limit_minimum_percent,
                observation.limit_maximum_percent,
                observation.limit_step_percent,
            )
            decision_interval_elapsed = (
                self.last_decision_at is not None
                and now - self.last_decision_at >= timedelta(minutes=3)
            )
            fingerprint_changed = decision_fingerprint != self._decision_fingerprint
            only_vehicle_soc_changed = (
                self._decision_fingerprint is not None
                and decision_fingerprint[0] != self._decision_fingerprint[0]
                and decision_fingerprint[1:] == self._decision_fingerprint[1:]
            )
            try:
                previous_vehicle_soc = float(self._decision_fingerprint[0])
            except (TypeError, ValueError):
                previous_vehicle_soc = None
            policy_limit = (
                100.0
                if charge_to_full_requested
                else self._float(
                    CONF_EV_FREE_WINDOW_CHARGE_LIMIT,
                    DEFAULT_EV_FREE_WINDOW_CHARGE_LIMIT,
                )
            )
            soc_remains_below_policy = (
                previous_vehicle_soc is not None
                and previous_vehicle_soc < policy_limit
                and vehicle_soc < policy_limit
            )
            current_transition_pending = (
                in_window
                and bool(
                    self.coordinator.config.get(
                        CONF_EV_ALLOWANCE_GUARD_ENABLED,
                        DEFAULT_EV_ALLOWANCE_GUARD_ENABLED,
                    )
                )
                and bool(
                    self.coordinator.config.get(
                        CONF_HOUSE_LOAD_INCLUDES_EV,
                        DEFAULT_HOUSE_LOAD_INCLUDES_EV,
                    )
                )
                and ev_valid
                and observation.current_step_a is not None
                and abs(observation.requested_current_a - ev_current)
                > observation.current_step_a / 2
            )
            service_limit = self._float(
                CONF_SERVICE_IMPORT_LIMIT_A, DEFAULT_SERVICE_IMPORT_LIMIT_A
            )
            service_overrun = grid_valid and service_limit > 0 and grid_current > service_limit
            defer_soc_redecision = (
                only_vehicle_soc_changed
                and soc_remains_below_policy
                and current_transition_pending
                and not service_overrun
                and not decision_interval_elapsed
            )
            should_decide = not in_window or (
                self.target_current_a is None
                or self.last_decision_at is None
                or decision_interval_elapsed
                or (fingerprint_changed and not defer_soc_redecision)
            )
            if defer_soc_redecision:
                self.decision_phase = "ev_current_transition_hold"
                self.allowance_phase = "transition_hold"
            if in_window and self.pre_free_session.active:
                self.pre_free_session = PreFreeSessionState()
                self.outside_control_active = False
                self.outside_target_active = False
            if should_decide:
                try:
                    calculated = (
                        self._calculate_target(
                            now,
                            observation,
                            elapsed_minutes=elapsed_minutes,
                            remaining_hours=remaining_hours,
                        )
                        if in_window
                        else self._calculate_outside_target(now, observation)
                    )
                except ValueError:
                    self.last_reason = "ev_planning_inputs_invalid"
                    return
                if not calculated:
                    return
                self.last_decision_at = now
                self._decision_fingerprint = decision_fingerprint

            if self.target_current_a is None or self.target_limit_percent is None:
                self.last_reason = "ev_target_unavailable"
                return
            if smart_path:
                await self._async_reconcile_smart_socket(
                    now,
                    observation,
                    in_window=in_window,
                    connected_for_planning=connected,
                    gate=gate,
                )
                return
            if self.outside_stop_requested:
                if not observation.charge_switch_on:
                    self.daily_backfill_stop_pending = False
                    self.daily_backfill_stop_attempts = 0
                    self.daily_backfill_last_stop_at = None
                    self.outside_control_active = False
                    self.last_reason = "daily_backfill_stopped"
                    await self._async_save(now)
                    return
                if self.daily_backfill_stop_attempts >= DIRECT_EVSE_MAX_ATTEMPTS:
                    self.last_reason = "daily_backfill_stop_fault_maximum_attempts"
                    return
                if (
                    self.daily_backfill_last_stop_at is not None
                    and now - self.daily_backfill_last_stop_at < timedelta(seconds=30)
                ):
                    self.last_reason = "daily_backfill_stop_awaiting_feedback"
                    return
                commands = (EvCommand("stop_charging"),)
                plan = EvCommandPlan(commands, "daily_backfill_complete")
                if gate == "safety_locked":
                    self.last_actions = tuple(
                        f"would_{command.action}" for command in plan.commands
                    )
                    self.last_reason = "rehearsal_daily_backfill_complete"
                    return
                if plan.commands:
                    await self._async_execute_ev_plan(plan, now)
                    if self.last_actions == ("stop_charging",):
                        self.daily_backfill_stop_attempts += 1
                        self.daily_backfill_last_stop_at = now
                        await self._async_save(now)
                return
            if gate == "safety_locked":
                rehearsal_plan = plan_direct_evse_commands(
                    observation,
                    target_current_a=self.target_current_a,
                    target_limit_percent=self.target_limit_percent,
                    physical_ceiling_a=self._float(CONF_EV_MAX_CURRENT, 0.0),
                    start_allowed=True,
                )
                self.last_actions = tuple(
                    f"would_{command.action}" for command in rehearsal_plan.commands
                )
                self.last_reason = (
                    "rehearsal_feedback_confirmed"
                    if not rehearsal_plan.commands
                    else f"rehearsal_{rehearsal_plan.reason}"
                )
                return
            transition = reconcile_direct_evse(
                self.reconciliation,
                observation,
                target_current_a=self.target_current_a,
                target_limit_percent=self.target_limit_percent,
                physical_ceiling_a=self._float(CONF_EV_MAX_CURRENT, 0.0),
                now=now,
            )
            self.reconciliation = transition.state
            self.last_reason = transition.plan.reason
            await self._async_save(now)

            if not transition.plan.commands:
                if (
                    not in_window
                    and not outside_enabled
                    and self.outside_control_active
                    and not self.outside_target_active
                    and transition.state.phase == "confirmed"
                ):
                    self.outside_control_active = False
                    await self._async_save(now)
                return
            try:
                self.last_actions = await self._adapter.async_execute(transition.plan)  # type: ignore[union-attr]
            except EvWriteBlocked:
                self.last_actions = self._adapter.last_executed  # type: ignore[union-attr]
                self.writes_performed += len(self.last_actions)
                if self.last_actions:
                    self.last_write_at = now
                self.last_reason = "ev_write_gate_closed"
                await self._async_save(now)
                return
            except Exception:  # service failure is retained for bounded retry diagnostics
                self.last_actions = self._adapter.last_executed  # type: ignore[union-attr]
                self.writes_performed += len(self.last_actions)
                if self.last_actions:
                    self.last_write_at = now
                self.last_reason = "ev_service_call_failed"
                _LOGGER.exception("Direct EVSE reconciliation service call failed")
                await self._async_save(now)
                return
            self.writes_performed += len(self.last_actions)
            self.last_write_at = now
            self.last_reason = "ev_commands_sent_awaiting_feedback"
            await self._async_save(now)

    async def _async_reconcile_general_limit_only(
        self,
        now: datetime,
        observation: DirectEvseObservation,
        *,
        vehicle_soc: float | None,
        gate: str,
    ) -> None:
        """Apply the canonical connected general limit without owning current."""
        if vehicle_soc is None:
            self.last_reason = "ev_soc_unavailable"
            return
        learned = self._learned_general_limit(observation, vehicle_soc=vehicle_soc)
        if learned is None:
            self.last_reason = "ev_learned_limit_unavailable"
            return
        minimum = observation.limit_minimum_percent
        maximum = observation.limit_maximum_percent
        step = observation.limit_step_percent
        if minimum is None or maximum is None or step is None:
            self.last_reason = "ev_charge_limit_metadata_unavailable"
            return
        policy = maximum if self._charge_to_full_requested() else learned.limit_percent
        target = plan_charge_limit_target(
            ChargeLimitInputs(
                connected=True,
                policy_limit_percent=policy,
                current_limit_percent=observation.charge_limit_percent,
                vehicle_soc_percent=vehicle_soc,
                protected_baseline_required=self._float(
                    CONF_EV_PROTECTED_BASELINE_A, DEFAULT_EV_PROTECTED_BASELINE_A
                )
                > 0,
                direct_limit_headroom_percent=self._float(
                    CONF_EV_DIRECT_LIMIT_HEADROOM, DEFAULT_EV_DIRECT_LIMIT_HEADROOM
                ),
                minimum_percent=minimum,
                maximum_percent=maximum,
                step_percent=step,
            )
        )
        self.target_current_a = None
        self.target_limit_percent = target
        if abs(target - observation.charge_limit_percent) < step:
            self._general_limit_write_fingerprint = None
            self.last_reason = "outside_window_general_limit_confirmed"
            return
        fingerprint = (target, observation.charge_limit_percent)
        if fingerprint == self._general_limit_write_fingerprint:
            self.last_reason = "outside_window_general_limit_awaiting_feedback"
            return
        plan = EvCommandPlan((EvCommand("set_charge_limit", target),), "general_limit")
        if gate == "safety_locked":
            self.last_actions = ("would_set_charge_limit",)
            self.last_reason = "rehearsal_general_limit"
            return
        self._general_limit_write_fingerprint = fingerprint
        await self._async_execute_ev_plan(plan, now)

    async def _async_reconcile_disconnected_smart_socket(
        self,
        now: datetime,
        observation: DirectEvseObservation,
        *,
        in_window: bool,
        gate: str,
    ) -> None:
        """Port the pilot's outside-window socket-off rule when unplugged."""
        smart = self._smart_socket_observation(now, observation)
        physical_minimum = self._physical_charging_minimum_a(observation)
        if smart is None or physical_minimum is None:
            self.last_reason = "smart_socket_feedback_unavailable"
            return
        plan = plan_smart_socket_commands(
            smart,
            target_current_a=0.0,
            physical_minimum_a=physical_minimum,
            physical_ceiling_a=self._path_ceiling_a(),
            settle_seconds=self._float(
                CONF_EV_SMART_SOCKET_SETTLE_SECONDS,
                DEFAULT_EV_SMART_SOCKET_SETTLE_SECONDS,
            ),
            charge_allowed=False,
            in_free_window=in_window,
            connected_for_planning=False,
            power_switching_enabled=bool(
                self.coordinator.config.get(
                    CONF_EV_SMART_SOCKET_POWER_SWITCHING,
                    DEFAULT_EV_SMART_SOCKET_POWER_SWITCHING,
                )
            ),
        )
        if gate == "safety_locked":
            self.last_actions = tuple(f"would_{command.action}" for command in plan.commands)
            self.last_reason = f"rehearsal_{plan.reason}"
            return
        if plan.commands:
            await self._async_execute_ev_plan(plan, now)
            return
        self.last_reason = plan.reason

    async def _async_reconcile_smart_socket(
        self,
        now: datetime,
        observation: DirectEvseObservation,
        *,
        in_window: bool,
        connected_for_planning: bool,
        gate: str,
    ) -> None:
        """Run the selected smart-socket path and its one-shot recovery."""
        smart = self._smart_socket_observation(now, observation)
        if smart is None:
            self.last_reason = "smart_socket_feedback_unavailable"
            return
        physical_minimum = self._physical_charging_minimum_a(observation)
        physical_ceiling = self._path_ceiling_a()
        if physical_minimum is None or physical_ceiling < physical_minimum:
            self.last_reason = "smart_socket_physical_limits_invalid"
            return

        recovery_observation = self._smart_recovery_observation(
            now,
            observation,
            smart,
            connected_for_planning=connected_for_planning,
            physical_minimum_a=physical_minimum,
        )
        recovery = reconcile_smart_socket_recovery(
            self.smart_recovery,
            recovery_observation,
            now=now,
            physical_minimum_a=physical_minimum,
            physical_ceiling_a=physical_ceiling,
            current_tolerance_a=observation.current_step_a or physical_minimum,
            idle_current_threshold_a=self._float(
                CONF_EV_SMART_RECOVERY_IDLE_CURRENT_A,
                DEFAULT_EV_SMART_RECOVERY_IDLE_CURRENT_A,
            ),
            no_power_confirm_seconds=self._float(
                CONF_EV_SMART_RECOVERY_NO_POWER_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_NO_POWER_SECONDS,
            ),
            current_confirm_seconds=self._float(
                CONF_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS,
            ),
            socket_confirm_seconds=self._float(
                CONF_EV_SMART_RECOVERY_SOCKET_CONFIRM_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_SOCKET_CONFIRM_SECONDS,
            ),
            power_off_seconds=self._float(
                CONF_EV_SMART_RECOVERY_POWER_OFF_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_POWER_OFF_SECONDS,
            ),
            post_power_settle_seconds=self._float(
                CONF_EV_SMART_RECOVERY_POST_POWER_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_POST_POWER_SECONDS,
            ),
            charging_confirm_seconds=self._float(
                CONF_EV_SMART_RECOVERY_CHARGING_CONFIRM_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_CHARGING_CONFIRM_SECONDS,
            ),
            healthy_rearm_seconds=self._float(
                CONF_EV_SMART_RECOVERY_REARM_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_REARM_SECONDS,
            ),
        )
        recovery_active = recovery.state.phase in {
            "confirming_current",
            "confirming_socket_off",
            "power_off_dwell",
            "confirming_socket_on",
            "post_power_settle",
            "awaiting_actuator",
            "confirming_charging",
        }
        if gate == "safety_locked" and (recovery_active or recovery.plan.commands):
            self.last_actions = tuple(
                f"would_{command.action}" for command in recovery.plan.commands
            )
            self.last_reason = f"rehearsal_{recovery.plan.reason}"
            return
        previous_recovery = self.smart_recovery
        self.smart_recovery = recovery.state
        self._publish_smart_recovery_transition(
            previous_recovery,
            self.smart_recovery,
            recovery.plan.reason,
        )
        if self.smart_recovery != previous_recovery:
            await self._async_save(now)
        if recovery.plan.commands:
            await self._async_execute_ev_plan(recovery.plan, now)
            return
        if recovery_active:
            self.last_reason = recovery.plan.reason
            return

        plan = plan_smart_socket_commands(
            smart,
            target_current_a=self.target_current_a or 0.0,
            physical_minimum_a=physical_minimum,
            physical_ceiling_a=physical_ceiling,
            settle_seconds=self._float(
                CONF_EV_SMART_SOCKET_SETTLE_SECONDS,
                DEFAULT_EV_SMART_SOCKET_SETTLE_SECONDS,
            ),
            charge_allowed=(
                connected_for_planning and (self.target_current_a or 0.0) >= physical_minimum
            ),
            in_free_window=in_window,
            connected_for_planning=connected_for_planning,
            power_switching_enabled=bool(
                self.coordinator.config.get(
                    CONF_EV_SMART_SOCKET_POWER_SWITCHING,
                    DEFAULT_EV_SMART_SOCKET_POWER_SWITCHING,
                )
            ),
        )
        if gate == "safety_locked":
            self.last_actions = tuple(f"would_{command.action}" for command in plan.commands)
            self.last_reason = f"rehearsal_{plan.reason}"
            return
        plan = self._suppress_unconfirmed_smart_stage(plan, smart, now)
        if not plan.commands:
            self.last_reason = plan.reason
            return
        await self._async_execute_ev_plan(plan, now)

    def _publish_smart_recovery_transition(
        self,
        previous: SmartSocketRecoveryState,
        current: SmartSocketRecoveryState,
        reason: str,
    ) -> None:
        """Port the pilot's one notification for a latched recovery outcome."""
        notification_id = f"heo_{self.coordinator.entry_id}_smart_socket_recovery"
        if current.phase == "fault" and previous.phase != "fault":
            persistent_notification.async_create(
                self.hass,
                (
                    "The selected EV smart-socket recovery stopped safely and "
                    f"will not power-cycle again in this fault episode ({reason})."
                ),
                "EV smart-socket recovery failed",
                notification_id,
            )
        elif current.phase == "recovered" and previous.phase != "recovered":
            persistent_notification.async_dismiss(self.hass, notification_id)

    def _smart_socket_observation(
        self, now: datetime, observation: DirectEvseObservation
    ) -> SmartSocketObservation | None:
        socket_entity = self.coordinator.config.get(CONF_EV_SMART_SOCKET)
        socket_state = self.hass.states.get(str(socket_entity)) if socket_entity else None
        if socket_state is None or socket_state.state.lower() not in {"on", "off"}:
            return None
        socket_on = socket_state.state.lower() == "on"
        socket_on_seconds = (
            max((now - socket_state.last_changed).total_seconds(), 0.0) if socket_on else 0.0
        )
        return SmartSocketObservation(
            requested_current_a=observation.requested_current_a,
            charge_switch_on=observation.charge_switch_on,
            socket_on=socket_on,
            socket_on_seconds=socket_on_seconds,
            current_maximum_a=observation.current_maximum_a,
            current_step_a=observation.current_step_a,
        )

    def _smart_recovery_observation(
        self,
        now: datetime,
        observation: DirectEvseObservation,
        smart: SmartSocketObservation,
        *,
        connected_for_planning: bool,
        physical_minimum_a: float,
    ) -> SmartSocketRecoveryObservation:
        charging_entity = self.coordinator.config.get(CONF_EV_CHARGING_STATE)
        charging_state = self.hass.states.get(str(charging_entity)) if charging_entity else None
        charging_value = (
            charging_state.state.lower()
            if charging_state is not None and charging_state.state.lower() not in _UNKNOWN_STATES
            else None
        )
        stable_seconds = self._float(
            CONF_EV_SMART_RECOVERY_NO_POWER_SECONDS,
            DEFAULT_EV_SMART_RECOVERY_NO_POWER_SECONDS,
        )
        at_home_state = self.hass.states.get(str(self.coordinator.config.get(CONF_EV_AT_HOME, "")))
        cable_state = self.hass.states.get(
            str(self.coordinator.config.get(CONF_EV_CABLE_CONNECTED, ""))
        )
        charge_switch_state = self.hass.states.get(
            str(self.coordinator.config.get(CONF_EV_CHARGE_SWITCH, ""))
        )
        evidence_states = (at_home_state, cable_state, charge_switch_state)
        evidence_age_stable = all(
            state is not None
            and state.state.lower() not in _UNKNOWN_STATES
            and 0 <= (now - state.last_changed).total_seconds()
            and (now - state.last_changed).total_seconds() >= stable_seconds
            for state in evidence_states
        )
        cloud_stable = bool(
            evidence_age_stable
            and at_home_state is not None
            and at_home_state.state.lower() in {"home", "on"}
            and cable_state is not None
            and cable_state.state.lower() == "on"
            and charge_switch_state is not None
            and charge_switch_state.state.lower() in {"on", "off"}
        )
        vehicle_soc = self._entity_number(CONF_EV_SOC)
        actual_current, actual_valid = self._actual_ev_current_a()
        return SmartSocketRecoveryObservation(
            charging_state=charging_value,
            charging_state_seconds=(
                max((now - charging_state.last_changed).total_seconds(), 0.0)
                if charging_state is not None
                else 0.0
            ),
            home_control_active=self._home_control_active(),
            cloud_evidence_stable=cloud_stable,
            smart_path_selected=True,
            socket_on=smart.socket_on,
            cable_connected=self._is_on(CONF_EV_CABLE_CONNECTED),
            charge_allowed=(self.target_current_a or 0.0) >= physical_minimum_a,
            actuator_writable=(
                observation.current_maximum_a is not None
                and observation.current_maximum_a > 0
                and observation.charge_switch_on is not None
            ),
            target_current_a=self.target_current_a or 0.0,
            requested_current_a=observation.requested_current_a,
            actual_current_a=actual_current if actual_valid else float("nan"),
            vehicle_soc_percent=vehicle_soc if vehicle_soc is not None else float("nan"),
            charge_limit_percent=observation.charge_limit_percent,
            writable_maximum_a=observation.current_maximum_a,
            charge_switch_on=observation.charge_switch_on,
        )

    def _suppress_unconfirmed_smart_stage(
        self,
        plan: EvCommandPlan,
        observation: SmartSocketObservation,
        now: datetime,
    ) -> EvCommandPlan:
        stage_only = (
            not observation.socket_on
            and len(plan.commands) == 1
            and plan.commands[0].action == "set_charge_current"
        )
        if not stage_only:
            if any(command.action == "turn_on_smart_socket" for command in plan.commands):
                self.smart_stage_target_a = None
                self.smart_stage_started_at = None
            return plan
        target = plan.commands[0].value
        if target != self.smart_stage_target_a or self.smart_stage_started_at is None:
            self.smart_stage_target_a = target
            self.smart_stage_started_at = now
            return plan
        elapsed = (now - self.smart_stage_started_at).total_seconds()
        timeout = self._float(
            CONF_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS,
            DEFAULT_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS,
        )
        retry = self._float(
            CONF_EV_SMART_SOCKET_RETRY_SECONDS,
            DEFAULT_EV_SMART_SOCKET_RETRY_SECONDS,
        )
        if elapsed >= retry:
            # The pilot retries its stopped one-minute wait from a five-minute
            # reconciliation trigger. Preserve that cadence without issuing a
            # current write every 30-second HACS controller tick.
            self.smart_stage_started_at = now
            return plan
        reason = (
            "smart_socket_awaiting_staged_current"
            if elapsed < timeout
            else "smart_socket_staged_current_not_confirmed"
        )
        return EvCommandPlan((), reason)

    async def _async_execute_ev_plan(self, plan: EvCommandPlan, now: datetime) -> None:
        try:
            self.last_actions = await self._adapter.async_execute(plan)  # type: ignore[union-attr]
        except EvWriteBlocked:
            self.last_actions = self._adapter.last_executed  # type: ignore[union-attr]
            self.last_reason = "ev_write_gate_closed"
        except Exception:
            self.last_actions = self._adapter.last_executed  # type: ignore[union-attr]
            self.last_reason = "ev_service_call_failed"
            _LOGGER.exception("Smart-socket EV service call failed")
        else:
            self.last_reason = plan.reason
        self.writes_performed += len(self.last_actions)
        if self.last_actions:
            self.last_write_at = now
        await self._async_save(now)

    def _calculate_target(
        self,
        now: datetime,
        observation: DirectEvseObservation,
        *,
        elapsed_minutes: float,
        remaining_hours: float,
    ) -> bool:
        snapshot = self.coordinator.snapshot
        if snapshot is None:
            self.last_reason = "site_snapshot_unavailable"
            return False
        grid = self.grid_average.result(now)
        ev = self.ev_average.result(now)
        current_minimum = self._physical_charging_minimum_a(observation)
        current_step = observation.current_step_a
        if current_minimum is None or current_step is None:
            self.last_reason = "ev_actuator_metadata_unavailable"
            return False
        # The commissioned connector rating is the planning ceiling. Tessie's
        # transient number maximum is only a transport bound in the command
        # planner, matching the pilot's v1.4.19+ anti-ramp behavior.
        ceiling = self._path_ceiling_a()
        if ceiling <= 0:
            self.last_reason = "ev_physical_ceiling_uncommissioned"
            return False
        baseline = min(
            max(
                self._float(CONF_EV_PROTECTED_BASELINE_A, DEFAULT_EV_PROTECTED_BASELINE_A),
                current_minimum,
                current_step,
            ),
            ceiling,
        )
        effective_minimum = min(
            max(
                self._float(
                    CONF_EV_FREE_WINDOW_MINIMUM_CURRENT,
                    DEFAULT_EV_FREE_WINDOW_MINIMUM_CURRENT,
                ),
                current_minimum,
            ),
            ceiling,
        )
        charge_to_full = self._charge_to_full_requested()
        policy_limit = (
            100.0
            if charge_to_full
            else self._float(
                CONF_EV_FREE_WINDOW_CHARGE_LIMIT,
                DEFAULT_EV_FREE_WINDOW_CHARGE_LIMIT,
            )
        )
        vehicle_soc = self._entity_number(CONF_EV_SOC)
        if vehicle_soc is None:
            self.last_reason = "ev_soc_unavailable"
            return False
        below_policy = vehicle_soc < policy_limit
        base = plan_free_window_current(
            FreeWindowCurrentInputs(
                in_free_window=True,
                connected=True,
                ceiling_a=ceiling,
                effective_minimum_a=effective_minimum,
                protected_baseline_a=baseline,
                requested_a=observation.requested_current_a,
                service_limit_a=self._float(
                    CONF_SERVICE_IMPORT_LIMIT_A, DEFAULT_SERVICE_IMPORT_LIMIT_A
                ),
                service_headroom_a=self._float(
                    CONF_SITE_GRID_HEADROOM_CURRENT,
                    DEFAULT_SITE_GRID_HEADROOM_CURRENT,
                ),
                grid_average_a=grid.value or 0.0,
                grid_average_valid=(
                    grid.value is not None
                    and grid.age_coverage_ratio >= 0.67
                    and grid.source_value_valid
                ),
                actual_ev_current_a=self._actual_ev_current_a()[0],
                ev_average_a=ev.value or 0.0,
                ev_average_source_valid=ev.source_value_valid,
                elapsed_minutes=elapsed_minutes,
                settle_minutes=self._float(
                    CONF_EV_FREE_WINDOW_SETTLE_MINUTES,
                    DEFAULT_EV_FREE_WINDOW_SETTLE_MINUTES,
                ),
                current_step_a=current_step,
                ev_priority=(
                    below_policy
                    and self.coordinator.config.get(
                        CONF_EV_FREE_WINDOW_PRIORITY,
                        DEFAULT_EV_FREE_WINDOW_PRIORITY,
                    )
                    == "ev"
                ),
                charge_to_full=charge_to_full,
            )
        )
        target_current = base.current_a if below_policy or charge_to_full else baseline
        self.decision_phase = (
            base.phase if below_policy or charge_to_full else "policy_limit_reached"
        )
        self.allowance_phase = "disabled"
        self.allowance_house_load_kw = None
        self.allowance_ev_power_kw = None
        if self.coordinator.config.get(
            CONF_EV_ALLOWANCE_GUARD_ENABLED, DEFAULT_EV_ALLOWANCE_GUARD_ENABLED
        ):
            allowance = self._allowance_target(
                target_current,
                baseline,
                current_minimum,
                current_step,
                policy_limit,
                vehicle_soc,
                remaining_hours,
                snapshot,
            )
            if allowance is None:
                target_current = baseline
                self.allowance_phase = "projection_unavailable"
            else:
                target_current = allowance.current_a
                self.allowance_phase = allowance.phase
        limit_min = observation.limit_minimum_percent
        limit_max = observation.limit_maximum_percent
        limit_step = observation.limit_step_percent
        if limit_min is None or limit_max is None or limit_step is None:
            self.last_reason = "ev_charge_limit_metadata_unavailable"
            return False
        self.target_current_a = target_current
        self.target_limit_percent = plan_charge_limit_target(
            ChargeLimitInputs(
                connected=True,
                policy_limit_percent=policy_limit,
                current_limit_percent=observation.charge_limit_percent,
                vehicle_soc_percent=vehicle_soc,
                protected_baseline_required=baseline > 0,
                direct_limit_headroom_percent=self._float(
                    CONF_EV_DIRECT_LIMIT_HEADROOM, DEFAULT_EV_DIRECT_LIMIT_HEADROOM
                ),
                minimum_percent=limit_min,
                maximum_percent=limit_max,
                step_percent=limit_step,
            )
        )
        return True

    def _allowance_target(
        self,
        base_current: float,
        baseline: float,
        minimum: float,
        step: float,
        policy_limit: float,
        vehicle_soc: float | None,
        remaining_hours: float,
        snapshot,
    ):
        stored = self._entity_energy(CONF_EV_STORED_ENERGY)
        imported = (
            self.coordinator.free_window_import.imported_kwh
            if self.coordinator.free_window_import.last_at is not None
            else None
        )
        if (
            stored is None
            or vehicle_soc is None
            or snapshot.battery_soc is None
            or snapshot.house_load_kw is None
        ):
            return None
        try:
            allowance_house_load_kw = snapshot.house_load_kw
            if self.coordinator.config.get(
                CONF_HOUSE_LOAD_INCLUDES_EV, DEFAULT_HOUSE_LOAD_INCLUDES_EV
            ):
                actual_current, actual_current_valid = self._actual_ev_current_a()
                if not actual_current_valid:
                    return None
                voltage = self._float(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE)
                phases = int(self._float(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT))
                allowance_house_load_kw = house_load_excluding_ev_kw(
                    house_load_kw=snapshot.house_load_kw,
                    actual_ev_current_a=actual_current,
                    ev_voltage_v=voltage,
                    ev_phase_count=phases,
                )
                self.allowance_ev_power_kw = round(actual_current * voltage * phases / 1000, 3)
            self.allowance_house_load_kw = allowance_house_load_kw
            ev_need = estimate_vehicle_energy_to_target_kwh(
                stored_energy_kwh=stored,
                current_soc_percent=vehicle_soc,
                target_soc_percent=policy_limit,
                charge_efficiency_percent=self._float(
                    CONF_EV_CHARGE_EFFICIENCY, DEFAULT_EV_CHARGE_EFFICIENCY
                ),
            )
            other = estimate_other_free_window_import_kwh(
                battery_capacity_kwh=snapshot.battery_capacity_kwh,
                battery_soc_percent=snapshot.battery_soc,
                battery_target_percent=self._float(
                    CONF_BATTERY_FREE_WINDOW_TARGET,
                    DEFAULT_BATTERY_FREE_WINDOW_TARGET,
                ),
                battery_charge_efficiency_percent=self._float(
                    CONF_BATTERY_CHARGE_EFFICIENCY,
                    DEFAULT_BATTERY_CHARGE_EFFICIENCY,
                ),
                house_load_kw=allowance_house_load_kw,
                remaining_window_hours=remaining_hours,
            )
            return apply_daily_allowance_ceiling(
                AllowanceCeilingInputs(
                    base_current_a=base_current,
                    protected_baseline_a=min(baseline, base_current),
                    minimum_charge_a=minimum,
                    current_step_a=step,
                    voltage_v=self._float(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE),
                    phase_count=int(self._float(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT)),
                    site_service_limit_a=self._float(
                        CONF_SERVICE_IMPORT_LIMIT_A, DEFAULT_SERVICE_IMPORT_LIMIT_A
                    ),
                    site_voltage_v=self._float(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE),
                    site_phase_count=int(
                        self._float(CONF_SITE_PHASE_COUNT, DEFAULT_SITE_PHASE_COUNT)
                    ),
                    remaining_window_hours=remaining_hours,
                    allowance_kwh=self._float(
                        CONF_DAILY_FREE_ALLOWANCE_KWH,
                        DEFAULT_DAILY_FREE_ALLOWANCE_KWH,
                    ),
                    imported_in_window_kwh=imported,
                    projected_other_import_kwh=other,
                    projected_ev_energy_kwh=ev_need,
                    safety_margin_kwh=self._float(
                        CONF_EV_ALLOWANCE_SAFETY_MARGIN,
                        DEFAULT_EV_ALLOWANCE_SAFETY_MARGIN,
                    ),
                )
            )
        except ValueError:
            return None

    def _calculate_outside_target(self, now: datetime, observation: DirectEvseObservation) -> bool:
        """Port solar spill and latest-start backfill without touching FoxESS."""
        self.outside_stop_requested = False
        snapshot = self.coordinator.snapshot
        current_minimum = self._physical_charging_minimum_a(observation)
        current_step = observation.current_step_a
        if current_minimum is None or current_step is None:
            self.last_reason = "ev_actuator_metadata_unavailable"
            return False
        ceiling = self._path_ceiling_a()
        if ceiling <= 0:
            self.last_reason = "ev_physical_ceiling_uncommissioned"
            return False
        service_ceiling = self._outside_service_ceiling_a(
            ceiling,
            current_step=current_step,
        )
        baseline = min(
            max(
                self._float(CONF_EV_PROTECTED_BASELINE_A, DEFAULT_EV_PROTECTED_BASELINE_A),
                current_minimum,
                current_step,
            ),
            ceiling,
        )
        vehicle_soc = self._entity_number(CONF_EV_SOC)
        if vehicle_soc is None:
            self.last_reason = "ev_soc_unavailable"
            return False
        soft_limit = self._float(
            CONF_EV_FREE_WINDOW_CHARGE_LIMIT, DEFAULT_EV_FREE_WINDOW_CHARGE_LIMIT
        )
        charge_to_full = self._charge_to_full_requested()
        if charge_to_full and service_ceiling < current_minimum:
            self.last_reason = "charge_to_full_service_headroom_unavailable"
            return False

        self.daily_backfill_plan = None
        daily_current_a = 0.0
        if self._daily_backfill_enabled() and not charge_to_full:
            self.daily_backfill_plan = self._calculate_daily_backfill_plan(
                now,
                vehicle_soc=vehicle_soc,
                vehicle_soft_limit=soft_limit,
                charger_minimum_a=current_minimum,
                current_step_a=current_step,
                charger_ceiling_a=service_ceiling,
            )
            plan = self.daily_backfill_plan
            if plan is not None:
                if self.daily_backfill_active:
                    session_delivered = max(
                        self.daily_backfill_delivered_kwh
                        - self.daily_backfill_session_start_delivered_kwh,
                        0.0,
                    )
                    if (
                        session_delivered >= self.daily_backfill_session_target_kwh
                        or plan.phase
                        in {
                            "ready_time_passed",
                            "vehicle_target_reached",
                            "protected_energy_unavailable",
                            "outside_power_ceiling_too_low",
                        }
                    ):
                        self.daily_backfill_active = False
                        self.daily_backfill_session_target_kwh = 0.0
                        self.daily_backfill_session_start_delivered_kwh = 0.0
                        self.daily_backfill_frozen_start = None
                        self.daily_backfill_stop_pending = True
                        self.daily_backfill_stop_attempts = 0
                        self.daily_backfill_last_stop_at = None
                elif plan.phase == "charge_now" and plan.planned_energy_kwh > 0:
                    self.daily_backfill_active = True
                    self.daily_backfill_session_target_kwh = plan.planned_energy_kwh
                    self.daily_backfill_session_start_delivered_kwh = (
                        self.daily_backfill_delivered_kwh
                    )
                    self.daily_backfill_frozen_start = plan.planned_start
                    self.daily_backfill_last_sample_at = now
                    self.daily_backfill_last_actual_current_a = self.actual_current_a
                    self.daily_backfill_stop_pending = False
                    self.daily_backfill_stop_attempts = 0
                    self.daily_backfill_last_stop_at = None
                if self.daily_backfill_active:
                    daily_current_a = plan.current_ceiling_a

        self.solar_spill = SolarSpillDecision(0.0, 0.0, "disabled")
        if self.coordinator.config.get(CONF_EV_SOLAR_SPILL_ENABLED, DEFAULT_EV_SOLAR_SPILL_ENABLED):
            if snapshot is None or snapshot.battery_soc is None:
                self.solar_spill = SolarSpillDecision(0.0, 0.0, "site_snapshot_unavailable")
            else:
                self.solar_spill = self._solar_spill_decision(
                    now,
                    snapshot.battery_soc,
                    vehicle_soc,
                    soft_limit,
                    ceiling,
                    current_minimum,
                    current_step,
                )

        self.pre_free_plan = None
        self.pre_free_current_a = baseline
        if self.coordinator.config.get(CONF_EV_PRE_FREE_ENABLED, DEFAULT_EV_PRE_FREE_ENABLED):
            free_start, in_pre_free, hours_until_free = self._pre_free_window(now)
            active_controller = getattr(self.coordinator, "active_controller", None)
            export_plan = getattr(active_controller, "export_plan", None)
            stored_energy = self._entity_energy(CONF_EV_STORED_ENERGY)
            if export_plan is not None and stored_energy is not None:
                vehicle_room = estimate_vehicle_energy_to_target_kwh(
                    stored_energy_kwh=stored_energy,
                    current_soc_percent=vehicle_soc,
                    target_soc_percent=soft_limit,
                    charge_efficiency_percent=self._float(
                        CONF_EV_CHARGE_EFFICIENCY, DEFAULT_EV_CHARGE_EFFICIENCY
                    ),
                )
                self.pre_free_plan = calculate_pre_free_plan(
                    PreFreePlanInputs(
                        discretionary_ac_kwh=(
                            export_plan.planned_export_energy_kwh if in_pre_free else 0.0
                        ),
                        vehicle_wall_room_kwh=vehicle_room,
                        baseline_a=baseline,
                        current_ceiling_a=ceiling,
                        voltage_v=self._float(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE),
                        phase_count=int(self._float(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT)),
                        free_window_start=free_start,
                    )
                )
            planned_energy = (
                self.pre_free_plan.planned_energy_kwh if self.pre_free_plan is not None else 0.0
            )
            planned_start = (
                self.pre_free_plan.planned_start if self.pre_free_plan is not None else None
            )
            export_active = bool(
                active_controller is not None and active_controller.export_session.phase != "idle"
            )
            transition = advance_pre_free_session(
                self.pre_free_session,
                now=now,
                in_pre_free_window=in_pre_free,
                connected=True,
                export_session_active=export_active,
                planned_energy_kwh=planned_energy,
                vehicle_soc_percent=vehicle_soc,
                vehicle_soft_limit_percent=soft_limit,
                planned_start=planned_start,
            )
            self.pre_free_session = transition.state
            self.pre_free_phase = transition.phase
            if (
                self.pre_free_session.active
                and self.pre_free_session.frozen_start
                and self.pre_free_plan is not None
            ):
                self.pre_free_plan = PreFreePlan(
                    self.pre_free_plan.planned_energy_kwh,
                    self.pre_free_plan.maximum_additional_power_kw,
                    self.pre_free_plan.planned_duration_minutes,
                    self.pre_free_session.frozen_start,
                )
            self.pre_free_current_a = plan_pre_free_current(
                PreFreeCurrentInputs(
                    session_active=self.pre_free_session.active,
                    planned_energy_kwh=planned_energy,
                    hours_until_free=hours_until_free,
                    voltage_v=self._float(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE),
                    phase_count=int(self._float(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT)),
                    current_step_a=current_step,
                    baseline_a=baseline,
                    current_ceiling_a=ceiling,
                    vehicle_soc_percent=vehicle_soc,
                    vehicle_soft_limit_percent=soft_limit,
                )
            ).current_a
        else:
            self.pre_free_session = PreFreeSessionState()
            self.pre_free_phase = "disabled"

        if charge_to_full:
            selected = EvCurrentDecision(
                service_ceiling,
                "charge_to_full_paid_grid_override",
            )
        elif self.daily_backfill_active:
            selected = EvCurrentDecision(daily_current_a, "daily_ready_backfill")
        else:
            selected = select_outside_window_current(
                baseline_a=baseline,
                current_ceiling_a=ceiling,
                charger_minimum_a=current_minimum,
                pre_free_active=self.pre_free_session.active,
                pre_free_current_a=self.pre_free_current_a,
                solar_spill_current_a=self.solar_spill.current_a,
            )
        self.outside_target_active = bool(
            charge_to_full
            or self.daily_backfill_active
            or self.pre_free_session.active
            or self.solar_spill.current_a >= current_minimum
        )
        if self.outside_target_active:
            self.outside_control_active = True
        elif (
            self.daily_backfill_stop_pending
            and self._float(
                CONF_EV_PROTECTED_BASELINE_A,
                DEFAULT_EV_PROTECTED_BASELINE_A,
            )
            <= 0
            and not self.pre_free_session.active
            and self.solar_spill.current_a < current_minimum
        ):
            self.outside_stop_requested = True
            self.outside_control_active = True
        if not self.outside_target_active and not self.outside_control_active:
            self.decision_phase = selected.phase
            self.last_reason = "outside_window_no_active_policy"
            return False
        limit_min = observation.limit_minimum_percent
        limit_max = observation.limit_maximum_percent
        limit_step = observation.limit_step_percent
        if limit_min is None or limit_max is None or limit_step is None:
            self.last_reason = "ev_charge_limit_metadata_unavailable"
            return False
        learned_limit = self._learned_general_limit(
            observation,
            vehicle_soc=vehicle_soc,
        )
        policy_limit = (
            limit_max
            if charge_to_full
            else soft_limit
            if self.outside_target_active or learned_limit is None
            else learned_limit.limit_percent
        )
        self.target_current_a = selected.current_a
        self.target_limit_percent = plan_charge_limit_target(
            ChargeLimitInputs(
                connected=True,
                policy_limit_percent=policy_limit,
                current_limit_percent=observation.charge_limit_percent,
                vehicle_soc_percent=vehicle_soc,
                protected_baseline_required=baseline > 0,
                direct_limit_headroom_percent=self._float(
                    CONF_EV_DIRECT_LIMIT_HEADROOM, DEFAULT_EV_DIRECT_LIMIT_HEADROOM
                ),
                minimum_percent=limit_min,
                maximum_percent=limit_max,
                step_percent=limit_step,
            )
        )
        self.decision_phase = selected.phase
        self.allowance_phase = "outside_free_window"
        return True

    def _calculate_daily_backfill_plan(
        self,
        now: datetime,
        *,
        vehicle_soc: float,
        vehicle_soft_limit: float,
        charger_minimum_a: float,
        current_step_a: float,
        charger_ceiling_a: float,
    ) -> DailyBackfillPlan | None:
        """Apply the approved ready-by extension to current live energy."""
        data = self.coordinator.data
        protected_house = getattr(self.coordinator, "learning_remaining_kwh", None)
        stored_energy = self._entity_energy(CONF_EV_STORED_ENERGY)
        if (
            data is None
            or data.available_after_reserve_kwh is None
            or protected_house is None
            or stored_energy is None
        ):
            self.last_reason = "daily_backfill_energy_inputs_unavailable"
            return None
        ready_at, planning_start, next_free = self._daily_ready_cycle(now)
        self._roll_daily_backfill_cycle(ready_at)
        vehicle_room = estimate_vehicle_energy_to_target_kwh(
            stored_energy_kwh=stored_energy,
            current_soc_percent=vehicle_soc,
            target_soc_percent=vehicle_soft_limit,
            charge_efficiency_percent=self._float(
                CONF_EV_CHARGE_EFFICIENCY,
                DEFAULT_EV_CHARGE_EFFICIENCY,
            ),
        )
        return calculate_daily_backfill_plan(
            DailyBackfillInputs(
                now=now,
                ready_at=ready_at,
                planning_window_start=planning_start,
                next_free_start=next_free,
                available_ac_after_reserve_kwh=max(float(data.available_after_reserve_kwh), 0.0)
                * self._float(
                    CONF_DISCHARGE_EFFICIENCY_PERCENT,
                    DEFAULT_DISCHARGE_EFFICIENCY_PERCENT,
                )
                / 100,
                protected_house_kwh=max(float(protected_house), 0.0),
                protected_ev_allocation_kwh=self._float(
                    CONF_EV_DAILY_BACKFILL_ENERGY,
                    DEFAULT_EV_DAILY_BACKFILL_ENERGY,
                ),
                delivered_this_cycle_kwh=self.daily_backfill_delivered_kwh,
                vehicle_wall_room_kwh=vehicle_room,
                inverter_output_limit_kw=self._float(
                    CONF_INVERTER_DISCHARGE_LIMIT_KW,
                    DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
                ),
                outside_inverter_percent=self._float(
                    CONF_EV_OUTSIDE_INVERTER_PERCENT,
                    DEFAULT_EV_OUTSIDE_INVERTER_PERCENT,
                ),
                voltage_v=self._float(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE),
                phase_count=int(self._float(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT)),
                current_step_a=current_step_a,
                charger_minimum_a=charger_minimum_a,
                charger_maximum_a=charger_ceiling_a,
                planning_buffer_minutes=self._float(
                    CONF_EV_BACKFILL_BUFFER_MINUTES,
                    DEFAULT_EV_BACKFILL_BUFFER_MINUTES,
                ),
            )
        )

    def _daily_backfill_enabled(self) -> bool:
        return (
            self._float(
                CONF_EV_DAILY_BACKFILL_ENERGY,
                DEFAULT_EV_DAILY_BACKFILL_ENERGY,
            )
            > 0
        )

    def _outside_service_ceiling_a(
        self,
        physical_ceiling_a: float,
        *,
        current_step: float,
    ) -> float:
        """Bound outside charging by commissioned per-phase service headroom."""
        service_limit = self._float(
            CONF_SERVICE_IMPORT_LIMIT_A,
            DEFAULT_SERVICE_IMPORT_LIMIT_A,
        )
        if service_limit <= 0:
            return physical_ceiling_a
        grid_current, grid_valid = self._grid_current_a()
        actual_current, actual_valid = self._actual_ev_current_a()
        if not grid_valid or not actual_valid:
            return 0.0
        non_ev_current = max(grid_current - actual_current, 0.0)
        available = max(
            service_limit
            - self._float(
                CONF_SITE_GRID_HEADROOM_CURRENT,
                DEFAULT_SITE_GRID_HEADROOM_CURRENT,
            )
            - non_ev_current,
            0.0,
        )
        stepped = int(available / current_step) * current_step
        return round(min(physical_ceiling_a, stepped), 3)

    def _daily_ready_cycle(self, now: datetime) -> tuple[datetime, datetime, datetime]:
        ready_time = self.coordinator._configured_time(  # noqa: SLF001
            CONF_EV_DAILY_READY_TIME,
            DEFAULT_EV_DAILY_READY_TIME,
        )
        free_time = self.coordinator._configured_time(  # noqa: SLF001
            CONF_FREE_CHARGE_START,
            DEFAULT_FREE_CHARGE_START,
        )
        ready_at = datetime.combine(now.date(), ready_time, tzinfo=now.tzinfo)
        if now >= ready_at:
            ready_at += timedelta(days=1)
        planning_start = datetime.combine(
            ready_at.date(),
            datetime.min.time(),
            tzinfo=now.tzinfo,
        )
        next_free = datetime.combine(ready_at.date(), free_time, tzinfo=now.tzinfo)
        if next_free <= ready_at:
            next_free += timedelta(days=1)
        return ready_at, planning_start, next_free

    def _roll_daily_backfill_cycle(self, ready_at: datetime) -> None:
        if self.daily_backfill_cycle_ready_at == ready_at:
            return
        if self.daily_backfill_active:
            self.daily_backfill_stop_pending = True
            self.daily_backfill_stop_attempts = 0
            self.daily_backfill_last_stop_at = None
        self.daily_backfill_cycle_ready_at = ready_at
        self.daily_backfill_delivered_kwh = 0.0
        self.daily_backfill_active = False
        self.daily_backfill_session_target_kwh = 0.0
        self.daily_backfill_session_start_delivered_kwh = 0.0
        self.daily_backfill_frozen_start = None
        self.daily_backfill_last_sample_at = None
        self.daily_backfill_last_actual_current_a = None

    def _update_daily_backfill_energy(self, now: datetime, actual_current_a: float | None) -> None:
        """Integrate confirmed wall current only while this policy owns charging."""
        if not self._daily_backfill_enabled():
            return
        ready_at, _, _ = self._daily_ready_cycle(now)
        self._roll_daily_backfill_cycle(ready_at)
        previous_at = self.daily_backfill_last_sample_at
        previous_current = self.daily_backfill_last_actual_current_a
        if (
            self.daily_backfill_active
            and actual_current_a is not None
            and previous_at is not None
            and previous_current is not None
            and now >= previous_at
            and now - previous_at
            <= timedelta(
                seconds=self._float(
                    CONF_EV_TELEMETRY_MAX_AGE_SECONDS,
                    DEFAULT_EV_TELEMETRY_MAX_AGE_SECONDS,
                )
            )
        ):
            hours = (now - previous_at).total_seconds() / 3600
            average_current = (previous_current + actual_current_a) / 2
            self.daily_backfill_delivered_kwh += (
                average_current
                * self._float(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE)
                * int(self._float(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT))
                / 1000
                * hours
            )
        self.daily_backfill_last_sample_at = now if self.daily_backfill_active else None
        self.daily_backfill_last_actual_current_a = (
            actual_current_a if self.daily_backfill_active else None
        )

    def daily_backfill_protection_kwh(self, now: datetime) -> float:
        """Energy Local-Modbus export must retain for the next ready deadline."""
        if not self._daily_backfill_enabled():
            return 0.0
        ready_at, _, _ = self._daily_ready_cycle(now)
        delivered = (
            self.daily_backfill_delivered_kwh
            if self.daily_backfill_cycle_ready_at == ready_at
            else 0.0
        )
        return round(
            max(
                self._float(
                    CONF_EV_DAILY_BACKFILL_ENERGY,
                    DEFAULT_EV_DAILY_BACKFILL_ENERGY,
                )
                - delivered,
                0.0,
            ),
            3,
        )

    def _learned_general_limit(
        self,
        observation: DirectEvseObservation,
        *,
        vehicle_soc: float,
    ) -> LearnedChargeLimitDecision | None:
        """Evaluate the source's P85/fallback general Tesla limit."""
        stored = self._entity_energy(CONF_EV_STORED_ENERGY)
        minimum = observation.limit_minimum_percent
        maximum = observation.limit_maximum_percent
        step = observation.limit_step_percent
        if stored is None or minimum is None or maximum is None or step is None:
            self.learned_charge_limit = None
            return None
        try:
            usable = estimate_usable_ev_capacity_kwh(
                stored_energy_kwh=stored,
                soc_percent=vehicle_soc,
            )
            gain = estimate_free_window_soc_gain_percent(
                maximum_current_a=self._path_ceiling_a(),
                voltage_v=self._float(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE),
                phase_count=int(self._float(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT)),
                window_hours=self._free_window_duration_hours(),
                charge_efficiency_percent=self._float(
                    CONF_EV_CHARGE_EFFICIENCY, DEFAULT_EV_CHARGE_EFFICIENCY
                ),
                usable_capacity_kwh=usable,
            )
            self.learned_charge_limit = plan_learned_general_charge_limit(
                [sample.energy_kwh for sample in self.driving_history.samples],
                minimum_samples=int(
                    self._float(
                        CONF_EV_LEARNING_MINIMUM_SAMPLES,
                        DEFAULT_EV_LEARNING_MINIMUM_SAMPLES,
                    )
                ),
                arrival_reserve_percent=self._float(
                    CONF_EV_ARRIVAL_RESERVE_SOC,
                    DEFAULT_EV_ARRIVAL_RESERVE_SOC,
                ),
                free_window_limit_percent=self._float(
                    CONF_EV_FREE_WINDOW_CHARGE_LIMIT,
                    DEFAULT_EV_FREE_WINDOW_CHARGE_LIMIT,
                ),
                free_window_soc_gain_percent=gain,
                usable_capacity_kwh=usable,
                actuator_minimum_percent=minimum,
                actuator_maximum_percent=maximum,
                actuator_step_percent=step,
            )
        except ValueError:
            self.learned_charge_limit = None
        return self.learned_charge_limit

    def _free_window_duration_hours(self) -> float:
        start = self.coordinator._configured_time(  # noqa: SLF001
            CONF_FREE_CHARGE_START, DEFAULT_FREE_CHARGE_START
        )
        end = self.coordinator._configured_time(  # noqa: SLF001
            CONF_FREE_CHARGE_END, DEFAULT_FREE_CHARGE_END
        )
        anchor = dt_util.now().date()
        start_at = datetime.combine(anchor, start)
        end_at = datetime.combine(anchor, end)
        if end_at <= start_at:
            end_at += timedelta(days=1)
        return (end_at - start_at).total_seconds() / 3600

    def _solar_spill_decision(
        self,
        now: datetime,
        battery_soc: float,
        vehicle_soc: float,
        soft_limit: float,
        ceiling: float,
        current_minimum: float,
        current_step: float,
    ) -> SolarSpillDecision:
        telemetry = self.coordinator.telemetry
        grid = None if telemetry is None else telemetry.grid_power
        battery = None if telemetry is None else telemetry.battery_power
        actual_state = self.hass.states.get(
            str(self.coordinator.config.get(CONF_EV_ACTUAL_CURRENT, ""))
        )
        soc_state = self.hass.states.get(str(self.coordinator.config.get(CONF_BATTERY_SOC, "")))
        ev_current, ev_valid = self._actual_ev_current_a()
        timestamps = [
            source.updated_at
            for sample in (grid, battery)
            if sample is not None
            for source in sample.sources
            if source.updated_at is not None
        ]
        timestamps.extend(
            state.last_updated for state in (actual_state, soc_state) if state is not None
        )
        max_age = self._float(
            CONF_EV_TELEMETRY_MAX_AGE_SECONDS,
            DEFAULT_EV_TELEMETRY_MAX_AGE_SECONDS,
        )
        max_skew = self._float(
            CONF_EV_TELEMETRY_MAX_SKEW_SECONDS,
            DEFAULT_EV_TELEMETRY_MAX_SKEW_SECONDS,
        )
        coherent = (
            grid is not None
            and grid.value is not None
            and battery is not None
            and battery.value is not None
            and ev_valid
            and actual_state is not None
            and soc_state is not None
            and all(
                source.updated_at is not None
                for sample in (grid, battery)
                for source in sample.sources
            )
            and all(0 <= (now - timestamp).total_seconds() <= max_age for timestamp in timestamps)
            and (max(timestamps) - min(timestamps)).total_seconds() <= max_skew
        )
        grid_import = grid.value if grid is not None and grid.value is not None else 0.0
        battery_charge = battery.value if battery is not None and battery.value is not None else 0.0
        voltage = self._float(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE)
        phases = int(self._float(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT))
        return plan_solar_spill_current(
            SolarSpillInputs(
                telemetry_valid=coherent,
                battery_soc_percent=battery_soc,
                battery_full_threshold_percent=self._float(
                    CONF_EV_SOLAR_SPILL_BATTERY_SOC,
                    DEFAULT_EV_SOLAR_SPILL_BATTERY_SOC,
                ),
                connected=True,
                vehicle_soc_percent=vehicle_soc,
                vehicle_soft_limit_percent=soft_limit,
                in_boosted_export_window=self._boosted_window_active(now),
                ev_power_kw=ev_current * voltage * phases / 1000,
                grid_export_kw=max(-grid_import, 0.0),
                battery_charge_kw=battery_charge,
                voltage_v=voltage,
                phase_count=phases,
                current_step_a=current_step,
                charger_minimum_a=current_minimum,
                current_ceiling_a=ceiling,
            )
        )

    def _pre_free_window(self, now: datetime) -> tuple[datetime, bool, float]:
        free_time = self.coordinator._configured_time(  # noqa: SLF001
            CONF_FREE_CHARGE_START, DEFAULT_FREE_CHARGE_START
        )
        finish_time = self.coordinator._configured_time(  # noqa: SLF001
            CONF_FORCE_DISCHARGE_FINISH, DEFAULT_FORCE_DISCHARGE_FINISH
        )
        free_start = datetime.combine(now.date(), free_time, tzinfo=now.tzinfo)
        if free_start <= now:
            free_start += timedelta(days=1)
        finish = datetime.combine(free_start.date(), finish_time, tzinfo=now.tzinfo)
        if finish_time >= free_time:
            finish -= timedelta(days=1)
        return (
            free_start,
            finish <= now < free_start,
            max((free_start - now).total_seconds() / 3600, 0.0),
        )

    def _boosted_window_active(self, now: datetime) -> bool:
        start = self.coordinator._configured_time(  # noqa: SLF001
            CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START
        )
        end = self.coordinator._configured_time(  # noqa: SLF001
            CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END
        )
        start_at = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
        end_at = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
        if end > start:
            return start_at <= now < end_at
        if end < start:
            return now >= start_at or now < end_at
        return False

    def _connected_at_home(self) -> tuple[bool, str]:
        mode = str(self.coordinator.config.get(CONF_EV_LOCATION_MODE, DEFAULT_EV_LOCATION_MODE))
        if mode == "away":
            return False, "ev_location_away"
        if not self._home_control_active():
            return False, "ev_location_not_confirmed_home"
        if self._entity_state(CONF_EV_CABLE_CONNECTED) != "on":
            return False, "ev_cable_not_connected"
        charging = self._entity_state(CONF_EV_CHARGING_STATE)
        if charging is None or charging == "disconnected":
            return False, "ev_connection_state_unavailable"
        return True, "ev_connected_at_home"

    def _home_control_active(self) -> bool:
        """Port the pilot's explicit Home/Auto/Away current-write scope."""
        mode = str(self.coordinator.config.get(CONF_EV_LOCATION_MODE, DEFAULT_EV_LOCATION_MODE))
        return mode == "home" or (
            mode == "auto" and self._entity_state(CONF_EV_AT_HOME) in {"home", "on"}
        )

    def _grid_current_a(self) -> tuple[float, bool]:
        telemetry = self.coordinator.telemetry
        if telemetry is None or telemetry.site_grid_current.value is None:
            return 0.0, False
        return telemetry.site_grid_current.value, True

    def _actual_ev_current_a(self) -> tuple[float, bool]:
        charging = self._entity_state(CONF_EV_CHARGING_STATE)
        if charging is None:
            return 0.0, False
        if charging != "charging":
            return 0.0, True
        entity = self.coordinator.config.get(CONF_EV_ACTUAL_CURRENT)
        state = self.hass.states.get(str(entity)) if entity else None
        try:
            value = (
                current_to_a(float(state.state), state.attributes.get("unit_of_measurement"))
                if state is not None
                else None
            )
        except (TypeError, ValueError):
            value = None
        if value is None:
            return 0.0, False
        if value < 0:
            return 0.0, False
        return value, True

    def _observation(self) -> DirectEvseObservation | None:
        current_entity = self.coordinator.config.get(CONF_EV_CURRENT_LIMIT)
        limit_entity = self.coordinator.config.get(CONF_EV_CHARGE_LIMIT)
        if not current_entity or not limit_entity:
            return None
        current_state = self.hass.states.get(str(current_entity))
        limit_state = self.hass.states.get(str(limit_entity))
        switch = self._entity_state(CONF_EV_CHARGE_SWITCH)
        if current_state is None or limit_state is None or switch is None:
            return None
        try:
            return DirectEvseObservation(
                requested_current_a=float(current_state.state),
                charge_limit_percent=float(limit_state.state),
                charge_switch_on=switch == "on",
                current_minimum_a=float(current_state.attributes["min"]),
                current_maximum_a=float(current_state.attributes["max"]),
                current_step_a=float(current_state.attributes["step"]),
                limit_minimum_percent=float(limit_state.attributes["min"]),
                limit_maximum_percent=float(limit_state.attributes["max"]),
                limit_step_percent=float(limit_state.attributes["step"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _physical_charging_minimum_a(
        observation: DirectEvseObservation,
    ) -> float | None:
        """Port the pilot's Tessie min=0 fallback to one actuator step."""
        minimum = observation.current_minimum_a
        step = observation.current_step_a
        if minimum is None or step is None or step <= 0:
            return None
        return minimum if minimum > 0 else step

    def _free_window(self, now: datetime) -> tuple[bool, float, float]:
        start = self.coordinator._configured_time(  # noqa: SLF001
            CONF_FREE_CHARGE_START, DEFAULT_FREE_CHARGE_START
        )
        end = self.coordinator._configured_time(  # noqa: SLF001
            CONF_FREE_CHARGE_END, DEFAULT_FREE_CHARGE_END
        )
        start_at = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
        end_at = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
        if end <= start:
            end_at += timedelta(days=1)
            if now < datetime.combine(now.date(), end, tzinfo=now.tzinfo):
                start_at -= timedelta(days=1)
                end_at -= timedelta(days=1)
        active = start_at <= now < end_at
        return (
            active,
            max((now - start_at).total_seconds() / 60, 0.0) if active else 0.0,
            max((end_at - now).total_seconds() / 3600, 0.0) if active else 0.0,
        )

    def _create_adapter(self) -> EvServiceAdapter | None:
        config = self.coordinator.config
        mapping = (
            config.get(CONF_EV_CURRENT_LIMIT),
            config.get(CONF_EV_CHARGE_LIMIT),
            config.get(CONF_EV_CHARGE_SWITCH),
        )
        if not all(mapping):
            return None
        return EvServiceAdapter(
            self.hass,
            EvEntityMap(
                *(str(value) for value in mapping),
                smart_socket_entity=(
                    str(config[CONF_EV_SMART_SOCKET]) if config.get(CONF_EV_SMART_SOCKET) else None
                ),
            ),
            allow_writes=True,
            write_guard=lambda: self.gate_status == "ready",
        )

    def _entity_state(self, key: str) -> str | None:
        entity = self.coordinator.config.get(key)
        state = self.hass.states.get(str(entity)) if entity else None
        if state is None or state.state.lower() in _UNKNOWN_STATES:
            return None
        return state.state.lower()

    def _entity_number(self, key: str) -> float | None:
        entity = self.coordinator.config.get(key)
        state = self.hass.states.get(str(entity)) if entity else None
        try:
            value = float(state.state) if state is not None else None
        except (TypeError, ValueError):
            return None
        return value if value is not None and isfinite(value) else None

    def _entity_energy(self, key: str) -> float | None:
        entity = self.coordinator.config.get(key)
        state = self.hass.states.get(str(entity)) if entity else None
        if state is None:
            return None
        try:
            value = energy_to_kwh(float(state.state), state.attributes.get("unit_of_measurement"))
        except (TypeError, ValueError):
            return None
        return value if isfinite(value) and value >= 0 else None

    def _is_on(self, key: str) -> bool:
        return self._entity_state(key) == "on"

    def _charge_to_full_requested(self) -> bool:
        """Use HEO's switch, with the old mapped helper as upgrade fallback."""
        if CONF_EV_CHARGE_TO_FULL_ENABLED in self.coordinator.config:
            return bool(
                self.coordinator.config.get(
                    CONF_EV_CHARGE_TO_FULL_ENABLED,
                    DEFAULT_EV_CHARGE_TO_FULL_ENABLED,
                )
            )
        return self._is_on(CONF_EV_CHARGE_TO_FULL)

    async def _async_clear_charge_to_full(self) -> None:
        """Clear the HEO-owned paid-grid override after its bounded session."""
        entry = self.hass.config_entries.async_get_entry(self.coordinator.entry_id)
        if entry is None:
            return
        config = {key: value for key, value in entry.data.items() if key != CONF_EV_CHARGE_TO_FULL}
        config[CONF_EV_CHARGE_TO_FULL_ENABLED] = False
        self.hass.config_entries.async_update_entry(entry, data=config)
        self.coordinator.config.pop(CONF_EV_CHARGE_TO_FULL, None)
        self.coordinator.config[CONF_EV_CHARGE_TO_FULL_ENABLED] = False

    def _float(self, key: str, default: float) -> float:
        try:
            value = float(self.coordinator.config.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if isfinite(value) else default

    def _path_ceiling_a(self) -> float:
        if (
            self.coordinator.config.get(CONF_EV_CHARGE_PATH, DEFAULT_EV_CHARGE_PATH)
            == EV_CHARGE_PATH_SMART_SOCKET
        ):
            return self._float(
                CONF_EV_SMART_SOCKET_CURRENT_LIMIT,
                DEFAULT_EV_SMART_SOCKET_CURRENT_LIMIT,
            )
        return self._float(CONF_EV_MAX_CURRENT, 0.0)

    async def _async_restore(self) -> None:
        payload = await self._store.async_load()
        if not isinstance(payload, dict):
            return
        now = dt_util.now()
        self.grid_average.restore(payload.get("grid_average"), now)
        self.ev_average.restore(payload.get("ev_average"), now)
        self.driving_history = DemandHistory.from_payload(payload.get("driving_history"), now)
        driving_snapshot = payload.get("driving_snapshot")
        if isinstance(driving_snapshot, dict):
            try:
                snapshot_date_raw = driving_snapshot.get("snapshot_date")
                snapshot_date = (
                    datetime.fromisoformat(str(snapshot_date_raw)).date()
                    if snapshot_date_raw
                    else None
                )
                lifetime_raw = driving_snapshot.get("lifetime_energy_kwh")
                lifetime = float(lifetime_raw) if lifetime_raw is not None else None
                if (
                    snapshot_date is not None
                    and snapshot_date > now.date()
                    or lifetime is not None
                    and (not isfinite(lifetime) or lifetime < 0)
                ):
                    raise ValueError
                self.driving_snapshot = DrivingSnapshotState(snapshot_date, lifetime)
                daily_raw = payload.get("daily_driving_energy_kwh")
                daily = float(daily_raw) if daily_raw is not None else None
                if daily is not None and (not isfinite(daily) or daily < 0):
                    raise ValueError
                self.daily_driving_energy_kwh = daily
            except (TypeError, ValueError):
                self.driving_snapshot = DrivingSnapshotState()
                self.daily_driving_energy_kwh = None
        try:
            state = payload.get("reconciliation", {})
            if not isinstance(state, dict):
                raise ValueError
            last_raw = state.get("last_command_at")
            last_at = datetime.fromisoformat(str(last_raw)) if last_raw else None
            attempts = int(state.get("attempts", 0))
            target_current = (
                float(state["target_current_a"])
                if state.get("target_current_a") is not None
                else None
            )
            target_limit = (
                float(state["target_limit_percent"])
                if state.get("target_limit_percent") is not None
                else None
            )
            phase = str(state.get("phase", "idle"))
            if (
                attempts < 0
                or attempts > DIRECT_EVSE_MAX_ATTEMPTS
                or (last_at is not None and last_at > now)
                or (
                    target_current is not None
                    and (not isfinite(target_current) or target_current < 0)
                )
                or (target_limit is not None and (not isfinite(target_limit) or target_limit < 0))
                or phase
                not in {
                    "idle",
                    "target_changed",
                    "awaiting_feedback",
                    "confirmed",
                    "fault_maximum_attempts",
                    "blocked",
                }
            ):
                raise ValueError
            self.reconciliation = DirectEvseReconciliationState(
                target_current_a=target_current,
                target_limit_percent=target_limit,
                attempts=attempts,
                last_command_at=last_at,
                phase=phase,
            )
            self.target_current_a = self.reconciliation.target_current_a
            self.target_limit_percent = self.reconciliation.target_limit_percent
            pre_free = payload.get("pre_free_session", {})
            if not isinstance(pre_free, dict):
                raise ValueError
            frozen_raw = pre_free.get("frozen_start")
            frozen_start = datetime.fromisoformat(str(frozen_raw)) if frozen_raw else None
            pre_free_active = bool(pre_free.get("active", False))
            if frozen_start is not None and (frozen_start.tzinfo is None or frozen_start > now):
                raise ValueError
            if pre_free_active != (frozen_start is not None):
                raise ValueError
            self.pre_free_session = PreFreeSessionState(
                active=pre_free_active,
                frozen_start=frozen_start,
            )
            daily = payload.get("daily_backfill", {})
            if not isinstance(daily, dict):
                raise ValueError
            cycle_raw = daily.get("cycle_ready_at")
            cycle_ready_at = datetime.fromisoformat(str(cycle_raw)) if cycle_raw else None
            frozen_daily_raw = daily.get("frozen_start")
            frozen_daily = (
                datetime.fromisoformat(str(frozen_daily_raw)) if frozen_daily_raw else None
            )
            delivered = float(daily.get("delivered_kwh", 0.0))
            session_target = float(daily.get("session_target_kwh", 0.0))
            session_start = float(daily.get("session_start_delivered_kwh", 0.0))
            daily_active = bool(daily.get("active", False))
            if (
                any(
                    not isfinite(value) or value < 0
                    for value in (delivered, session_target, session_start)
                )
                or cycle_ready_at is not None
                and cycle_ready_at.tzinfo is None
                or frozen_daily is not None
                and frozen_daily.tzinfo is None
                or daily_active != (frozen_daily is not None)
            ):
                raise ValueError
            self.daily_backfill_cycle_ready_at = cycle_ready_at
            self.daily_backfill_delivered_kwh = delivered
            self.daily_backfill_active = daily_active
            self.daily_backfill_session_target_kwh = session_target
            self.daily_backfill_session_start_delivered_kwh = session_start
            self.daily_backfill_frozen_start = frozen_daily
            self.daily_backfill_stop_pending = bool(daily.get("stop_pending", False))
            self.daily_backfill_stop_attempts = int(daily.get("stop_attempts", 0))
            stop_at_raw = daily.get("last_stop_at")
            self.daily_backfill_last_stop_at = (
                datetime.fromisoformat(str(stop_at_raw)) if stop_at_raw else None
            )
            if (
                not 0 <= self.daily_backfill_stop_attempts <= DIRECT_EVSE_MAX_ATTEMPTS
                or self.daily_backfill_last_stop_at is not None
                and (
                    self.daily_backfill_last_stop_at.tzinfo is None
                    or self.daily_backfill_last_stop_at > now
                )
            ):
                raise ValueError
            charge_full_raw = payload.get("charge_to_full_started_at")
            charge_full_started = (
                datetime.fromisoformat(str(charge_full_raw)) if charge_full_raw else None
            )
            if charge_full_started is not None and (
                charge_full_started.tzinfo is None or charge_full_started > now
            ):
                raise ValueError
            self.charge_to_full_started_at = charge_full_started
            self.outside_control_active = bool(payload.get("outside_control_active", False))
            smart_recovery = payload.get("smart_recovery", {})
            if not isinstance(smart_recovery, dict):
                raise ValueError
            recovery_started_raw = smart_recovery.get("phase_started_at")
            recovery_started = (
                datetime.fromisoformat(str(recovery_started_raw)) if recovery_started_raw else None
            )
            recovery_current = (
                float(smart_recovery["recovery_current_a"])
                if smart_recovery.get("recovery_current_a") is not None
                else None
            )
            recovery_phase = str(smart_recovery.get("phase", "idle"))
            if (
                recovery_phase
                not in {
                    "idle",
                    "confirming_current",
                    "confirming_socket_off",
                    "power_off_dwell",
                    "confirming_socket_on",
                    "post_power_settle",
                    "awaiting_actuator",
                    "confirming_charging",
                    "recovered",
                    "fault",
                }
                or (
                    recovery_started is not None
                    and (recovery_started.tzinfo is None or recovery_started > now)
                )
                or (
                    recovery_current is not None
                    and (not isfinite(recovery_current) or recovery_current < 0)
                )
            ):
                raise ValueError
            self.smart_recovery = SmartSocketRecoveryState(
                attempted=bool(smart_recovery.get("attempted", False)),
                phase=recovery_phase,
                phase_started_at=recovery_started,
                recovery_current_a=recovery_current,
            )
        except (KeyError, TypeError, ValueError):
            self.reconciliation = DirectEvseReconciliationState()
            self.pre_free_session = PreFreeSessionState()
            self.daily_backfill_cycle_ready_at = None
            self.daily_backfill_delivered_kwh = 0.0
            self.daily_backfill_active = False
            self.daily_backfill_session_target_kwh = 0.0
            self.daily_backfill_session_start_delivered_kwh = 0.0
            self.daily_backfill_frozen_start = None
            self.daily_backfill_stop_pending = False
            self.daily_backfill_stop_attempts = 0
            self.daily_backfill_last_stop_at = None
            self.charge_to_full_started_at = None
            self.outside_control_active = False
            self.smart_recovery = SmartSocketRecoveryState()

    async def _async_save(self, now: datetime | None = None) -> None:
        state = self.reconciliation
        await self._store.async_save(
            {
                "grid_average": self.grid_average.to_payload(),
                "ev_average": self.ev_average.to_payload(),
                "driving_history": self.driving_history.to_payload(),
                "driving_snapshot": {
                    "snapshot_date": (
                        self.driving_snapshot.snapshot_date.isoformat()
                        if self.driving_snapshot.snapshot_date is not None
                        else None
                    ),
                    "lifetime_energy_kwh": self.driving_snapshot.lifetime_energy_kwh,
                },
                "daily_driving_energy_kwh": self.daily_driving_energy_kwh,
                "reconciliation": {
                    "target_current_a": state.target_current_a,
                    "target_limit_percent": state.target_limit_percent,
                    "attempts": state.attempts,
                    "last_command_at": (
                        state.last_command_at.isoformat()
                        if state.last_command_at is not None
                        else None
                    ),
                    "phase": state.phase,
                },
                "pre_free_session": {
                    "active": self.pre_free_session.active,
                    "frozen_start": (
                        self.pre_free_session.frozen_start.isoformat()
                        if self.pre_free_session.frozen_start is not None
                        else None
                    ),
                },
                "daily_backfill": {
                    "cycle_ready_at": (
                        self.daily_backfill_cycle_ready_at.isoformat()
                        if self.daily_backfill_cycle_ready_at is not None
                        else None
                    ),
                    "delivered_kwh": round(self.daily_backfill_delivered_kwh, 6),
                    "active": self.daily_backfill_active,
                    "session_target_kwh": self.daily_backfill_session_target_kwh,
                    "session_start_delivered_kwh": (
                        self.daily_backfill_session_start_delivered_kwh
                    ),
                    "frozen_start": (
                        self.daily_backfill_frozen_start.isoformat()
                        if self.daily_backfill_frozen_start is not None
                        else None
                    ),
                    "stop_pending": self.daily_backfill_stop_pending,
                    "stop_attempts": self.daily_backfill_stop_attempts,
                    "last_stop_at": (
                        self.daily_backfill_last_stop_at.isoformat()
                        if self.daily_backfill_last_stop_at is not None
                        else None
                    ),
                },
                "charge_to_full_started_at": (
                    self.charge_to_full_started_at.isoformat()
                    if self.charge_to_full_started_at is not None
                    else None
                ),
                "outside_control_active": self.outside_control_active,
                "smart_recovery": {
                    "attempted": self.smart_recovery.attempted,
                    "phase": self.smart_recovery.phase,
                    "phase_started_at": (
                        self.smart_recovery.phase_started_at.isoformat()
                        if self.smart_recovery.phase_started_at is not None
                        else None
                    ),
                    "recovery_current_a": self.smart_recovery.recovery_current_a,
                },
            }
        )
        self.last_saved_at = now or dt_util.now()
