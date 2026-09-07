"""Commissioned direct-EVSE runtime for the ported pilot-site free-window policy."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from math import isfinite

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_CHARGE_EFFICIENCY,
    CONF_BATTERY_CHARGE_POSITIVE,
    CONF_BATTERY_FREE_WINDOW_TARGET,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BONUS_WINDOW_END,
    CONF_BONUS_WINDOW_START,
    CONF_DAILY_FREE_ALLOWANCE_KWH,
    CONF_EV_ACTUAL_CURRENT,
    CONF_EV_ALLOWANCE_GUARD_ENABLED,
    CONF_EV_ALLOWANCE_SAFETY_MARGIN,
    CONF_EV_AT_HOME,
    CONF_EV_CABLE_CONNECTED,
    CONF_EV_CHARGE_EFFICIENCY,
    CONF_EV_CHARGE_LIMIT,
    CONF_EV_CHARGE_PATH,
    CONF_EV_CHARGE_SWITCH,
    CONF_EV_CHARGE_TO_FULL,
    CONF_EV_CHARGING_STATE,
    CONF_EV_CURRENT_LIMIT,
    CONF_EV_DIRECT_LIMIT_HEADROOM,
    CONF_EV_FREE_WINDOW_CHARGE_LIMIT,
    CONF_EV_FREE_WINDOW_MINIMUM_CURRENT,
    CONF_EV_FREE_WINDOW_PRIORITY,
    CONF_EV_FREE_WINDOW_SETTLE_MINUTES,
    CONF_EV_LOCATION_MODE,
    CONF_EV_MAX_CURRENT,
    CONF_EV_PHASE_COUNT,
    CONF_EV_PRE_FREE_ENABLED,
    CONF_EV_PROTECTED_BASELINE_A,
    CONF_EV_SMART_SOCKET,
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
    CONF_GRID_IMPORT_POSITIVE,
    CONF_GRID_POWER,
    CONF_SERVICE_IMPORT_LIMIT_A,
    CONF_SITE_GRID_CURRENT,
    CONF_SITE_GRID_HEADROOM_CURRENT,
    CONF_SITE_PHASE_COUNT,
    DEFAULT_BATTERY_CHARGE_EFFICIENCY,
    DEFAULT_BATTERY_CHARGE_POSITIVE,
    DEFAULT_BATTERY_FREE_WINDOW_TARGET,
    DEFAULT_BONUS_WINDOW_END,
    DEFAULT_BONUS_WINDOW_START,
    DEFAULT_DAILY_FREE_ALLOWANCE_KWH,
    DEFAULT_EV_ALLOWANCE_GUARD_ENABLED,
    DEFAULT_EV_ALLOWANCE_SAFETY_MARGIN,
    DEFAULT_EV_CHARGE_EFFICIENCY,
    DEFAULT_EV_CHARGE_PATH,
    DEFAULT_EV_DIRECT_LIMIT_HEADROOM,
    DEFAULT_EV_FREE_WINDOW_CHARGE_LIMIT,
    DEFAULT_EV_FREE_WINDOW_MINIMUM_CURRENT,
    DEFAULT_EV_FREE_WINDOW_PRIORITY,
    DEFAULT_EV_FREE_WINDOW_SETTLE_MINUTES,
    DEFAULT_EV_LOCATION_MODE,
    DEFAULT_EV_PHASE_COUNT,
    DEFAULT_EV_PRE_FREE_ENABLED,
    DEFAULT_EV_PROTECTED_BASELINE_A,
    DEFAULT_EV_SOLAR_SPILL_BATTERY_SOC,
    DEFAULT_EV_SOLAR_SPILL_ENABLED,
    DEFAULT_EV_TELEMETRY_MAX_AGE_SECONDS,
    DEFAULT_EV_TELEMETRY_MAX_SKEW_SECONDS,
    DEFAULT_EV_VOLTAGE,
    DEFAULT_FORCE_DISCHARGE_FINISH,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DEFAULT_FREE_CHARGE_END,
    DEFAULT_FREE_CHARGE_START,
    DEFAULT_SERVICE_IMPORT_LIMIT_A,
    DEFAULT_SITE_GRID_HEADROOM_CURRENT,
    DEFAULT_SITE_PHASE_COUNT,
    EV_CHARGE_PATH_DIRECT,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from .coordinator import EnergyCoordinator
from .ev_adapter import EvEntityMap, EvServiceAdapter, EvWriteBlocked, ev_control_gate_status
from .normalise import current_to_a, power_to_kw, signed_grid_power_to_import_kw
from .planner.ev import (
    DIRECT_EVSE_MAX_ATTEMPTS,
    AllowanceCeilingInputs,
    ChargeLimitInputs,
    DirectEvseObservation,
    DirectEvseReconciliationState,
    FreeWindowCurrentInputs,
    apply_daily_allowance_ceiling,
    estimate_other_free_window_import_kwh,
    estimate_vehicle_energy_to_target_kwh,
    plan_charge_limit_target,
    plan_direct_evse_commands,
    plan_free_window_current,
    reconcile_direct_evse,
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
from .planner.timed_average import TimedAverageWindow

_LOGGER = logging.getLogger(__name__)
_UNKNOWN_STATES = {"unknown", "unavailable", ""}


class ActiveEvController:
    """Run only the commissioned direct Tessie path; never write FoxESS."""

    def __init__(self, hass: HomeAssistant, coordinator: EnergyCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._unsub_interval: CALLBACK_TYPE | None = None
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
        self.pre_free_session = PreFreeSessionState()
        self.pre_free_plan: PreFreePlan | None = None
        self.solar_spill = SolarSpillDecision(0.0, 0.0, "disabled")
        self.pre_free_current_a: float | None = None
        self.outside_control_active = False
        self.outside_target_active = False
        self.last_decision_at: datetime | None = None
        self._decision_fingerprint: tuple[object, ...] | None = None
        self.last_saved_at: datetime | None = None
        self.target_current_a: float | None = None
        self.target_limit_percent: float | None = None
        self.requested_current_a: float | None = None
        self.applied_limit_percent: float | None = None
        self.charge_switch_on: bool | None = None
        self.actual_current_a: float | None = None
        self.decision_phase = "inactive"
        self.allowance_phase = "not_evaluated"
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
        await self.async_reconcile()

    async def async_stop(self) -> None:
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None
        await self._async_save()

    async def _async_tick(self, _now) -> None:
        await self.async_reconcile()
        self.coordinator.async_update_listeners()

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
            if self.last_saved_at is None or now - self.last_saved_at >= timedelta(minutes=1):
                await self._async_save(now)

            gate = self.gate_status
            if gate not in {"ready", "safety_locked"}:
                self.last_reason = gate
                return
            if (
                self.coordinator.config.get(CONF_EV_CHARGE_PATH, DEFAULT_EV_CHARGE_PATH)
                != EV_CHARGE_PATH_DIRECT
            ):
                self.last_reason = "smart_socket_runtime_not_connected"
                return
            if self._float(CONF_SITE_PHASE_COUNT, DEFAULT_SITE_PHASE_COUNT) > 1 and not grid_valid:
                self.last_reason = "multiphase_current_feedback_unavailable"
                return
            connected, connection_reason = self._connected_at_home()
            in_window, elapsed_minutes, remaining_hours = self._free_window(now)
            if not connected:
                self.pre_free_session = PreFreeSessionState()
                self.outside_control_active = False
                self.outside_target_active = False
                self.last_reason = connection_reason
                return
            if observation is None:
                self.last_reason = "ev_actuator_feedback_unavailable"
                return

            outside_enabled = bool(
                self.coordinator.config.get(CONF_FOXESS_CONTROL_OWNER, DEFAULT_FOXESS_CONTROL_OWNER)
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
            if not in_window and not outside_enabled and not self.outside_control_active:
                self.last_reason = "outside_free_window_no_direct_write"
                return
            if not in_window and outside_enabled:
                # An opted-in outside-window policy owns the direct current even
                # when its discretionary target is zero. This preserves the
                # pilot's protected baseline after reconnects and restarts.
                self.outside_control_active = True

            vehicle_soc = self._entity_number(CONF_EV_SOC)
            decision_fingerprint = (
                vehicle_soc,
                self._is_on(CONF_EV_CHARGE_TO_FULL),
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
            should_decide = not in_window or (
                self.target_current_a is None
                or self.last_decision_at is None
                or now - self.last_decision_at >= timedelta(minutes=3)
                or decision_fingerprint != self._decision_fingerprint
            )
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
        current_minimum = observation.current_minimum_a
        current_step = observation.current_step_a
        if current_minimum is None or current_step is None:
            self.last_reason = "ev_actuator_metadata_unavailable"
            return False
        # The commissioned connector rating is the planning ceiling. Tessie's
        # transient number maximum is only a transport bound in the command
        # planner, matching the pilot's v1.4.19+ anti-ramp behavior.
        ceiling = self._float(CONF_EV_MAX_CURRENT, 0.0)
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
        charge_to_full = self._is_on(CONF_EV_CHARGE_TO_FULL)
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
        stored = self._entity_number(CONF_EV_STORED_ENERGY)
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
                house_load_kw=snapshot.house_load_kw,
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
        snapshot = self.coordinator.snapshot
        if snapshot is None or snapshot.battery_soc is None:
            self.last_reason = "site_snapshot_unavailable"
            return False
        current_minimum = observation.current_minimum_a
        current_step = observation.current_step_a
        if current_minimum is None or current_step is None:
            self.last_reason = "ev_actuator_metadata_unavailable"
            return False
        ceiling = self._float(CONF_EV_MAX_CURRENT, 0.0)
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
        vehicle_soc = self._entity_number(CONF_EV_SOC)
        if vehicle_soc is None:
            self.last_reason = "ev_soc_unavailable"
            return False
        soft_limit = self._float(
            CONF_EV_FREE_WINDOW_CHARGE_LIMIT, DEFAULT_EV_FREE_WINDOW_CHARGE_LIMIT
        )

        self.solar_spill = SolarSpillDecision(0.0, 0.0, "disabled")
        if self.coordinator.config.get(CONF_EV_SOLAR_SPILL_ENABLED, DEFAULT_EV_SOLAR_SPILL_ENABLED):
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
            stored_energy = self._entity_number(CONF_EV_STORED_ENERGY)
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

        selected = select_outside_window_current(
            baseline_a=baseline,
            current_ceiling_a=ceiling,
            charger_minimum_a=current_minimum,
            pre_free_active=self.pre_free_session.active,
            pre_free_current_a=self.pre_free_current_a,
            solar_spill_current_a=self.solar_spill.current_a,
        )
        self.outside_target_active = bool(
            self.pre_free_session.active or self.solar_spill.current_a >= current_minimum
        )
        if self.outside_target_active:
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
        self.target_current_a = selected.current_a
        self.target_limit_percent = plan_charge_limit_target(
            ChargeLimitInputs(
                connected=True,
                policy_limit_percent=soft_limit,
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
        grid = self._power_sample(CONF_GRID_POWER)
        battery = self._power_sample(CONF_BATTERY_POWER)
        actual_state = self.hass.states.get(
            str(self.coordinator.config.get(CONF_EV_ACTUAL_CURRENT, ""))
        )
        soc_state = self.hass.states.get(str(self.coordinator.config.get(CONF_BATTERY_SOC, "")))
        ev_current, ev_valid = self._actual_ev_current_a()
        timestamps = [
            state.last_updated
            for state in (grid[1], battery[1], actual_state, soc_state)
            if state is not None
        ]
        max_age = self._float(
            CONF_EV_TELEMETRY_MAX_AGE_SECONDS,
            DEFAULT_EV_TELEMETRY_MAX_AGE_SECONDS,
        )
        max_skew = self._float(
            CONF_EV_TELEMETRY_MAX_SKEW_SECONDS,
            DEFAULT_EV_TELEMETRY_MAX_SKEW_SECONDS,
        )
        coherent = (
            grid[0] is not None
            and battery[0] is not None
            and ev_valid
            and len(timestamps) == 4
            and all(0 <= (now - timestamp).total_seconds() <= max_age for timestamp in timestamps)
            and (max(timestamps) - min(timestamps)).total_seconds() <= max_skew
        )
        grid_import = (
            signed_grid_power_to_import_kw(
                grid[0], bool(self.coordinator.config.get(CONF_GRID_IMPORT_POSITIVE, True))
            )
            if grid[0] is not None
            else 0.0
        )
        battery_charge = (
            (
                battery[0]
                if self.coordinator.config.get(
                    CONF_BATTERY_CHARGE_POSITIVE, DEFAULT_BATTERY_CHARGE_POSITIVE
                )
                else -battery[0]
            )
            if battery[0] is not None
            else 0.0
        )
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

    def _power_sample(self, key: str):
        entity = self.coordinator.config.get(key)
        state = self.hass.states.get(str(entity)) if entity else None
        if state is None or state.state in _UNKNOWN_STATES:
            return None, state
        try:
            value = power_to_kw(float(state.state), state.attributes.get("unit_of_measurement"))
        except (TypeError, ValueError):
            return None, state
        return (value if isfinite(value) else None), state

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
        if mode == "auto" and self._entity_state(CONF_EV_AT_HOME) not in {"home", "on"}:
            return False, "ev_location_not_confirmed_home"
        if self._entity_state(CONF_EV_CABLE_CONNECTED) != "on":
            return False, "ev_cable_not_connected"
        charging = self._entity_state(CONF_EV_CHARGING_STATE)
        if charging is None or charging == "disconnected":
            return False, "ev_connection_state_unavailable"
        return True, "ev_connected_at_home"

    def _grid_current_a(self) -> tuple[float, bool]:
        mapped = self.coordinator.config.get(CONF_SITE_GRID_CURRENT)
        if mapped:
            state = self.hass.states.get(str(mapped))
            if state is None or state.state in _UNKNOWN_STATES:
                return 0.0, False
            try:
                result = current_to_a(
                    float(state.state), state.attributes.get("unit_of_measurement")
                )
                return (result, True) if isfinite(result) else (0.0, False)
            except (TypeError, ValueError):
                return 0.0, False
        phases = int(self._float(CONF_SITE_PHASE_COUNT, DEFAULT_SITE_PHASE_COUNT))
        snapshot = self.coordinator.snapshot
        if phases != 1 or snapshot is None or snapshot.grid_power_kw is None:
            return 0.0, False
        voltage = self._float(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE)
        return snapshot.grid_power_kw * 1000 / voltage, voltage > 0

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

    def _is_on(self, key: str) -> bool:
        return self._entity_state(key) == "on"

    def _float(self, key: str, default: float) -> float:
        try:
            value = float(self.coordinator.config.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if isfinite(value) else default

    async def _async_restore(self) -> None:
        payload = await self._store.async_load()
        if not isinstance(payload, dict):
            return
        now = dt_util.now()
        self.grid_average.restore(payload.get("grid_average"), now)
        self.ev_average.restore(payload.get("ev_average"), now)
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
            self.outside_control_active = bool(payload.get("outside_control_active", False))
        except (KeyError, TypeError, ValueError):
            self.reconciliation = DirectEvseReconciliationState()
            self.pre_free_session = PreFreeSessionState()
            self.outside_control_active = False

    async def _async_save(self, now: datetime | None = None) -> None:
        state = self.reconciliation
        await self._store.async_save(
            {
                "grid_average": self.grid_average.to_payload(),
                "ev_average": self.ev_average.to_payload(),
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
                "outside_control_active": self.outside_control_active,
            }
        )
        self.last_saved_at = now or dt_util.now()
