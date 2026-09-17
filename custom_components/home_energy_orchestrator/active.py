"""Explicitly opt-in Local Modbus battery controller.

The observer remains the default. This controller only starts when the config
entry selects Local Modbus ownership, enables automatic control and one of its
independent charge/export policies, disables rehearsal mode, and provides a
complete FoxESS actuator mapping.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    FOXESS_CONTROL_OWNER_CLOUD,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from .coordinator import EnergyCoordinator
from .foxess_adapter import FoxessEntityMap, FoxessServiceAdapter
from .foxess_observation_adapter import (
    FoxessFeedbackSnapshot,
    capture_foxess_feedback,
)
from .persistence import TypedValueStoreRepository
from .planner.charge_session import ChargeSessionState, advance_charge_session
from .planner.ev_before_export import (
    EvBeforeExportDecision,
    decide_ev_before_export,
)
from .planner.export import ExportPlan, calculate_export_plan, calculate_export_start
from .planner.export_session import ExportSessionState, advance_export_session
from .planner.foxess import (
    FoxessCommand,
    FoxessCommandPlan,
    FoxessObservation,
)
from .planner.foxess_charge_policy import (
    FoxessChargePolicyContext,
    evaluate_foxess_charge_policy,
)
from .planner.foxess_gate import FoxessGateContext, evaluate_foxess_gate

_LOGGER = logging.getLogger(__name__)


class ActiveFoxessController:
    """Run commissioned, independently opted-in Local Modbus policies."""

    def __init__(self, hass: HomeAssistant, coordinator: EnergyCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._unsub_interval: CALLBACK_TYPE | None = None
        self._adapter: FoxessServiceAdapter | None = None
        self.writes_performed = 0
        self.last_reason = "automatic_control_disabled"
        self.last_actions: tuple[str, ...] = ()
        self.charge_session = ChargeSessionState()
        self.charge_power_target_kw: float | None = None
        self.export_session = ExportSessionState()
        self.export_plan: ExportPlan | None = None
        self.export_planned_start: datetime | None = None
        self.automatic_export_remaining_kwh: float | None = None
        self.export_protected_ev_kwh: float | None = None
        self.ev_before_export_decision = EvBeforeExportDecision(True, "disabled")
        self.export_effective_enabled = False
        self.ownership_status = "not_evaluated"
        self._charge_storage_status = "not_loaded"
        self._export_storage_status = "not_loaded"
        self._export_store: Store[dict[str, object]] = Store(
            hass,
            1,
            "home_energy_orchestrator."
            f"{getattr(coordinator, 'entry_id', 'runtime')}.export_session",
            private=True,
        )
        self._charge_store: Store[dict[str, object]] = Store(
            hass,
            1,
            "home_energy_orchestrator."
            f"{getattr(coordinator, 'entry_id', 'runtime')}.charge_session",
            private=True,
        )
        self._export_repository = TypedValueStoreRepository(
            self._export_store,
            decode=ExportSessionState.from_payload,
            encode=ExportSessionState.to_payload,
        )
        self._charge_repository = TypedValueStoreRepository(
            self._charge_store,
            decode=ChargeSessionState.from_payload,
            encode=ChargeSessionState.to_payload,
        )

    @property
    def gate_status(self) -> str:
        """Return a human-readable commissioning gate state."""
        runtime = self.coordinator.runtime_config
        owner = runtime.automation.control_owner
        if owner == FOXESS_CONTROL_OWNER_CLOUD:
            return "foxcloud_scheduler_owner"
        if owner != FOXESS_CONTROL_OWNER_MODBUS:
            return "observer_owner"
        if not runtime.automation.master_enabled:
            return "disabled"
        if runtime.automation.safety_lock:
            return "rehearsal"
        if not runtime.electrical.verified:
            return "sign_conventions_unverified"
        return (
            "ready"
            if runtime.inverter.actuator_mapping_complete
            else "blocked_incomplete_mapping"
        )

    async def async_start(self) -> None:
        """Start the bounded reconciliation timer and perform one evaluation."""
        await self._async_load_charge_session()
        await self._async_load_export_session()
        if self._unsub_interval is None:
            self._unsub_interval = async_track_time_interval(
                self.hass, self._async_tick, timedelta(seconds=30)
            )
        await self.async_reconcile()
        await self.coordinator.async_update_forecast()
        self.coordinator.async_update_listeners()

    async def async_stop(self) -> None:
        """Stop the timer without changing inverter state."""
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None

    async def _async_tick(self, _now) -> None:
        await self.coordinator.async_request_refresh()
        await self.async_reconcile()
        await self.coordinator.async_update_forecast()
        self.coordinator.async_update_listeners()

    async def async_reconcile(self) -> None:
        """Evaluate and, only after every gate passes, execute one plan."""
        manual_test = getattr(self.coordinator, "manual_test", None)
        runtime = self.coordinator.runtime_config
        gate = evaluate_foxess_gate(
            FoxessGateContext(
                manual_test_active=bool(
                    manual_test is not None and manual_test.is_active
                ),
                control_owner=runtime.automation.control_owner,
                master_enabled=runtime.automation.master_enabled,
                safety_lock=runtime.automation.safety_lock,
                electrical_verified=runtime.electrical.verified,
                actuator_mapping_complete=runtime.inverter.actuator_mapping_complete,
                telemetry_available=(
                    self.coordinator.snapshot is not None
                    and self.coordinator.data is not None
                ),
            )
        )
        if gate.blocked:
            assert gate.reason is not None
            self.last_reason = gate.reason
            if gate.clear_actions:
                self.last_actions = ()
            if gate.warn_incomplete_mapping:
                _LOGGER.warning("Automatic control held: FoxESS mapping is incomplete")
            return
        assert runtime.inverter.work_mode_entity is not None
        assert runtime.inverter.force_charge_power_entity is not None
        assert runtime.inverter.force_discharge_power_entity is not None
        entities = FoxessEntityMap(
            runtime.inverter.work_mode_entity,
            runtime.inverter.force_charge_power_entity,
            runtime.inverter.force_discharge_power_entity,
        )
        assert self.coordinator.snapshot is not None
        assert self.coordinator.data is not None
        feedback = capture_foxess_feedback(self.hass, entities)
        now = dt_util.now()
        if feedback.observation is None:
            await self._async_mark_sessions_source_unavailable(now)
            self.last_reason = "foxess_feedback_unavailable"
            return
        observation = feedback.observation
        if await self._async_hold_unverified_ownership(observation):
            return
        # Finish a latched policy before considering another direction. With
        # ordinary non-overlapping windows this also guarantees that Self Use
        # feedback is confirmed before the next session may start.
        if self.charge_session.phase != "idle":
            if await self._async_reconcile_charge(
                observation, entities, feedback, now
            ):
                return
        if self.export_session.phase != "idle":
            if await self._async_reconcile_export(
                observation, entities, feedback, now
            ):
                return
        if self._enabled_control_windows_overlap():
            self.last_reason = "configured_control_windows_overlap"
            self.last_actions = ()
            return
        if await self._async_reconcile_charge(observation, entities, feedback, now):
            return
        if await self._async_reconcile_export(observation, entities, feedback, now):
            return
        self.last_reason = "no_automatic_foxess_policy_active"
        self.last_actions = ()

    async def _async_reconcile_charge(
        self,
        observation: FoxessObservation,
        entities: FoxessEntityMap,
        feedback: FoxessFeedbackSnapshot,
        now: datetime,
    ) -> bool:
        """Run the default-off fixed-power free-window charge extension."""
        automation = self.coordinator.runtime_config.automation
        window_active = self.coordinator._free_window_hours_remaining(now) > 0  # noqa: SLF001
        soc = getattr(self.coordinator.snapshot, "battery_soc", None)
        target_soc = self.coordinator.runtime_config.battery.free_window_target_percent
        free_energy_remaining = getattr(
            self.coordinator.data, "free_energy_remaining_kwh", None
        )
        policy = evaluate_foxess_charge_policy(
            FoxessChargePolicyContext(
                requested_enabled=automation.battery_charge_enabled,
                schedule_confirmed=automation.free_charge_schedule_confirmed,
                window_active=window_active,
                configured_max_kw=(
                    self.coordinator.runtime_config.inverter.charge_limit_kw
                ),
                observed_max_kw=feedback.charge_power_max_kw,
                source_capability_available=feedback.charge_source_available,
                mode=observation.mode,
                battery_soc=soc,
                target_soc_percent=target_soc,
                free_energy_remaining_kwh=free_energy_remaining,
                session=self.charge_session,
            )
        )
        self.charge_power_target_kw = policy.charge_power_target_kw
        if policy.terminal_reason is not None:
            self.last_reason = policy.terminal_reason
            self.last_actions = ()
            return True
        if not policy.should_advance:
            return False
        previous_state = self.charge_session
        transition = advance_charge_session(
            previous_state,
            observation,
            now=now,
            source_available=policy.source_available,
            window_active=policy.session_window_active,
            eligible_to_start=policy.eligible_to_start,
            requested_charge_power_kw=policy.charge_max_kw,
            charge_power_max_kw=policy.charge_max_kw,
            finish_requested=policy.finish_requested,
        )
        self.charge_session = transition.state
        self.charge_power_target_kw = (
            self.charge_session.requested_power_kw
            if self.charge_session.phase
            in {"starting", "active", "recovering", "stopping"}
            else 0.0
        )
        if self.charge_session != previous_state:
            await self._charge_repository.async_save(self.charge_session)
        self.last_reason = f"charge_{transition.reason}"
        self.last_actions = ()
        if transition.plan.commands:
            if self._adapter is None:
                self._adapter = FoxessServiceAdapter(
                    self.hass,
                    entities,
                    allow_writes=True,
                )
            plan = self._force_mode_command_delays(transition.plan)
            executed = await self._adapter.async_execute(plan)
            self.last_actions = executed
            self.writes_performed += len(executed)
            if executed:
                _LOGGER.info("FoxESS free-window charge plan executed: %s", executed)
        return True

    async def _async_reconcile_export(
        self,
        observation: FoxessObservation,
        entities: FoxessEntityMap,
        feedback: FoxessFeedbackSnapshot,
        now: datetime,
    ) -> bool:
        """Run the ported pilot-site ZEROHERO session, when it owns this tick."""
        runtime = self.coordinator.runtime_config
        enabled = runtime.automation.battery_export_enabled
        self.ev_before_export_decision = decide_ev_before_export(
            enabled=runtime.ev_preferences.before_export_enabled,
            ev_soc_percent=getattr(self.coordinator.snapshot, "ev_soc", None),
            target_soc_percent=runtime.ev_preferences.before_export_soc_target,
        )
        self.export_effective_enabled = (
            enabled and self.ev_before_export_decision.export_allowed
        )
        start_at, finish_at = self._export_bounds(now)
        within_session_window = start_at <= now < finish_at
        source_available = feedback.export_source_available
        discharge_max = min(
            max(
                self.coordinator.runtime_config.inverter.discharge_limit_kw,
                0.0,
            ),
            feedback.discharge_power_max_kw,
        )
        # Energy and time limits govern how long the session runs.  Requesting
        # the maximum available inverter discharge preserves headroom for
        # simultaneous house load and minimises the risk of a brief grid import
        # invalidating the ZEROHERO credit. The inverter enforces its own grid
        # export limit; that limit must not reduce this battery-side request.
        requested = discharge_max
        eligible = False
        self.export_plan = None
        self.export_planned_start = None
        exported = getattr(
            getattr(self.coordinator, "zerohero_export", None), "imported_kwh", None
        )
        try:
            allowance = runtime.export.automatic_limit_kwh
            self.automatic_export_remaining_kwh = (
                max(allowance - float(exported), 0.0) if exported is not None else None
            )
            protected_house = getattr(
                self.coordinator, "learning_remaining_kwh", None
            )
            protected_ev = self._protected_keepalive_energy_kwh(
                self._hours_until_next_free(now)
            )
            ev_controller = getattr(self.coordinator, "ev_controller", None)
            if protected_ev is not None and ev_controller is not None:
                protected_ev += ev_controller.daily_backfill_protection_kwh(now)
            self.export_protected_ev_kwh = protected_ev
            available = self.coordinator.data.available_after_reserve_kwh
            if (
                available is not None
                and protected_house is not None
                and protected_ev is not None
                and self.automatic_export_remaining_kwh is not None
                and discharge_max > 0
            ):
                efficiency = runtime.export.discharge_efficiency_percent / 100
                window_hours = (finish_at - start_at).total_seconds() / 3600
                self.export_plan = calculate_export_plan(
                    max(float(available), 0.0) * efficiency,
                    protected_house,
                    protected_ev,
                    self.automatic_export_remaining_kwh,
                    requested,
                    window_hours,
                )
                self.export_planned_start = calculate_export_start(
                    start_at, finish_at, self.export_plan.planned_duration_h
                )
                eligible = (
                    self.export_planned_start is not None
                    and now >= self.export_planned_start
                    and within_session_window
                )
        except (TypeError, ValueError):
            self.export_plan = None

        latched = self.export_session.phase != "idle"
        if not latched and not (self.export_effective_enabled and eligible):
            return False
        previous_state = self.export_session
        transition = advance_export_session(
            previous_state,
            observation,
            now=now,
            source_available=source_available,
            window_active=self.export_effective_enabled and within_session_window,
            eligible=eligible,
            requested_discharge_power_kw=requested,
            discharge_power_max_kw=discharge_max,
            finish_requested=not self.export_effective_enabled or now >= finish_at,
        )
        self.export_session = transition.state
        if self.export_session != previous_state:
            await self._export_repository.async_save(self.export_session)
        self.last_reason = f"export_{transition.reason}"
        self.last_actions = ()
        if transition.plan.commands:
            if self._adapter is None:
                self._adapter = FoxessServiceAdapter(
                    self.hass,
                    entities,
                    allow_writes=True,
                )
            plan = self._force_mode_command_delays(transition.plan)
            executed = await self._adapter.async_execute(plan)
            self.last_actions = executed
            self.writes_performed += len(executed)
            if executed:
                _LOGGER.info("FoxESS ZEROHERO export plan executed: %s", executed)
        return True

    async def _async_mark_sessions_source_unavailable(self, now: datetime) -> None:
        if self.charge_session.phase in {
            "starting",
            "active",
            "stopping",
            "recovering",
        }:
            self.charge_session = ChargeSessionState(
                "recovering",
                self.charge_session.requested_power_kw,
                self.charge_session.attempts,
                self.charge_session.last_command_at or now,
            )
            await self._charge_repository.async_save(self.charge_session)
        if self.export_session.phase != "idle":
            self.export_session = ExportSessionState(
                "recovering",
                self.export_session.requested_power_kw,
                self.export_session.attempts,
                self.export_session.last_command_at or now,
            )
            await self._export_repository.async_save(self.export_session)

    async def _async_load_charge_session(self) -> None:
        restored = await self._charge_repository.async_load()
        status = self._charge_repository.last_restore_status
        self._charge_storage_status = {
            "restored": "valid",
            "missing": "missing",
            "invalid": "malformed",
        }[status]
        if status != "missing":
            self.charge_session = restored

    def _charge_state_payload(self) -> dict[str, object]:
        return self.charge_session.to_payload()

    async def _async_load_export_session(self) -> None:
        restored = await self._export_repository.async_load()
        status = self._export_repository.last_restore_status
        self._export_storage_status = {
            "restored": "valid",
            "missing": "missing",
            "invalid": "malformed",
        }[status]
        if status != "missing":
            self.export_session = restored

    async def _async_hold_unverified_ownership(
        self, observation: FoxessObservation
    ) -> bool:
        """Refuse hardware writes until forced-mode ownership is trustworthy."""
        manual = getattr(self.coordinator, "manual_test", None)
        manual_status = getattr(manual, "storage_status", "missing")
        degraded = any(
            status in {"missing", "malformed", "not_loaded"}
            for status in (
                self._charge_storage_status,
                self._export_storage_status,
                manual_status,
            )
        )
        charge_owned = self.charge_session.phase in {
            "starting",
            "active",
            "stopping",
            "recovering",
        }
        export_owned = self.export_session.phase in {
            "starting",
            "active",
            "stopping",
            "recovering",
        }
        manual_kind_for_mode = {
            "Force Charge": "charge",
            "Force Discharge": "discharge",
        }.get(observation.mode)
        manual_owned = bool(
            manual is not None
            and manual.is_active
            and manual.active_kind == manual_kind_for_mode
        )
        matching_owner = (
            observation.mode == "Force Charge" and charge_owned
            or observation.mode == "Force Discharge" and export_owned
            or manual_owned
        )
        if matching_owner:
            self.ownership_status = "verified_session"
            return False
        if observation.mode == "Self Use" and (
            charge_owned or export_owned or manual_owned
        ):
            # A valid retained obligation may observe Self Use while it resumes
            # or confirms restoration. Missing evidence from an unrelated
            # family must not erase that trustworthy obligation.
            self.ownership_status = "verified_session"
            return False
        if observation.mode == "Self Use":
            if degraded:
                self.charge_session = ChargeSessionState()
                self.export_session = ExportSessionState()
                await self._charge_repository.async_save(self.charge_session)
                await self._export_repository.async_save(self.export_session)
                self._charge_storage_status = "valid"
                self._export_storage_status = "valid"
                if manual is not None:
                    await manual.async_checkpoint_safe_idle()
                self.ownership_status = "verified_safe_mode"
                self.last_reason = "ownership_reestablished_self_use"
                self.last_actions = ()
                # The observed Self Use state itself establishes the safe
                # boundary. Continue normal evaluation from that verified
                # baseline; no extra reconciliation interval is required.
                return False
            self.ownership_status = "verified"
            return False
        self.last_actions = ()
        if degraded:
            self.ownership_status = "ownership_unknown"
            self.last_reason = "ownership_unknown"
        else:
            self.ownership_status = "verified_external_owner"
            self.last_reason = "external_forced_mode"
        return True

    def _export_state_payload(self) -> dict[str, object]:
        return self.export_session.to_payload()

    def _export_bounds(self, now: datetime) -> tuple[datetime, datetime]:
        start = self.coordinator.runtime_config.windows.effective_bonus_start
        start_at = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
        finish = self._force_discharge_finish_time()
        finish_at = datetime.combine(now.date(), finish, tzinfo=now.tzinfo)
        if finish <= start:
            finish_at += timedelta(days=1)
            if now < datetime.combine(now.date(), finish, tzinfo=now.tzinfo):
                start_at -= timedelta(days=1)
                finish_at -= timedelta(days=1)
        return start_at, finish_at

    def _force_discharge_finish_time(self) -> time:
        """Derive finish from ZEROHERO end, retaining pre-v5 compatibility."""
        runtime = self.coordinator.runtime_config
        if not runtime.export.force_discharge_offset_configured:
            return runtime.windows.effective_legacy_force_discharge_finish
        bonus_end = runtime.windows.effective_bonus_end
        anchor = datetime.combine(datetime.min.date(), bonus_end)
        derived = anchor + timedelta(
            minutes=runtime.export.force_discharge_offset_minutes
        )
        return derived.time()

    def _hours_until_next_free(self, now: datetime) -> float:
        free_start = self.coordinator.runtime_config.windows.effective_free_charge_start
        target = datetime.combine(now.date(), free_start, tzinfo=now.tzinfo)
        if target <= now:
            target += timedelta(days=1)
        return max((target - now).total_seconds() / 3600, 0.0)

    def _enabled_control_windows_overlap(self) -> bool:
        automation = self.coordinator.runtime_config.automation
        if not (
            automation.battery_charge_enabled
            and automation.battery_export_enabled
        ):
            return False
        windows = self.coordinator.runtime_config.windows
        charge_start = windows.effective_free_charge_start
        charge_end = windows.effective_free_charge_end
        export_start = windows.effective_bonus_start
        export_end = self._force_discharge_finish_time()

        def segments(start, end):
            start_s = start.hour * 3600 + start.minute * 60 + start.second
            end_s = end.hour * 3600 + end.minute * 60 + end.second
            if start_s < end_s:
                return ((start_s, end_s),)
            return ((start_s, 86400), (0, end_s))

        return any(
            max(charge_left, export_left) < min(charge_right, export_right)
            for charge_left, charge_right in segments(charge_start, charge_end)
            for export_left, export_right in segments(export_start, export_end)
        )

    def _protected_keepalive_energy_kwh(self, hours_until_free: float) -> float | None:
        """Port the pilot site's mandatory connected-EV keepalive reservation.

        Presence and cable state are explicitly mapped. Missing evidence blocks
        a new export whenever a non-zero baseline is commissioned.
        """
        ev = self.coordinator.runtime_config.ev_connection
        if not ev.configured or not ev.control_commissioned:
            # A battery-only installation has no EV demand to protect.  Do not
            # let retained/default EV fields turn an otherwise valid export
            # plan into ``unknown``.
            return 0.0
        baseline_a = ev.protected_baseline_a
        if baseline_a <= 0:
            return 0.0
        home_entity = ev.at_home_entity
        cable_entity = ev.cable_connected_entity
        if not home_entity or not cable_entity:
            return None
        home = self._state(str(home_entity))
        cable = self._state(str(cable_entity))
        if home is None or cable is None:
            return None
        if home not in {"home", "on"} or cable != "on":
            return 0.0
        voltage = ev.voltage_v
        phases = ev.phase_count
        return round(max(hours_until_free, 0.0) * baseline_a * voltage * phases / 1000, 3)

    @staticmethod
    def _force_mode_command_delays(plan: FoxessCommandPlan) -> FoxessCommandPlan:
        commands = list(plan.commands)
        for index, command in enumerate(commands[:-1]):
            next_action = commands[index + 1].action
            if command.action in {
                "set_charge_power",
                "set_discharge_power",
            } and next_action == "select_mode":
                commands[index] = FoxessCommand(command.action, command.value, 5.0)
        return FoxessCommandPlan(tuple(commands), plan.reason)

    def _state(self, entity_id: str) -> str | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in {"unknown", "unavailable"}:
            return None
        return state.state
