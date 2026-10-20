"""Explicitly opt-in Local Modbus battery controller.

The observer remains the default. This controller only starts when the config
entry selects Local Modbus ownership, enables automatic control and one of its
independent charge/export policies, disables rehearsal mode, and provides a
complete FoxESS actuator mapping.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, time, timedelta
from math import ceil, isfinite

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_time_interval
from homeassistant.util import dt as dt_util

from .aemo_monitor import PRICE_PUBLICATION_GRACE
from .const import (
    FOXESS_CONTROL_OWNER_CLOUD,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from .coordinator import EnergyCoordinator
from .ev_observation_adapter import (
    capture_ev_entity_feedback,
    capture_ev_feedback,
    ev_observation_entity_map,
)
from .foxess_adapter import FoxessEntityMap, FoxessServiceAdapter, FoxessWriteBlocked
from .foxess_observation_adapter import (
    FoxessFeedbackSnapshot,
    capture_foxess_feedback,
)
from .maintenance_barrier import maintenance_writes_blocked
from .manual_inverter import ManualInverterController
from .models import SiteSnapshot
from .persistence import create_typed_value_repository
from .planner.charge_session import ChargeSessionState, advance_charge_session
from .planner.control_windows import (
    control_window_bounds,
    daily_windows_overlap,
    derive_force_discharge_finish,
    hours_until_next_window,
)
from .planner.ev_before_export import (
    EvBeforeExportDecision,
    calculate_protected_keepalive_energy_kwh,
    compose_protected_ev_energy_kwh,
    protected_keepalive_requires_evidence,
)
from .planner.ev_outside_window import protected_baseline_current_a
from .planner.export import ExportPlan
from .planner.export_session import ExportSessionState, advance_export_session
from .planner.foxess import (
    ControlDecision,
    FoxessCommand,
    FoxessCommandPlan,
    FoxessObservation,
    apply_force_mode_command_delays,
    plan_foxess_commands,
)
from .planner.foxess_charge_policy import (
    FoxessChargePolicyContext,
    evaluate_foxess_charge_policy,
)
from .planner.foxess_export_policy import (
    FoxessExportPolicyContext,
    evaluate_foxess_export_policy,
)
from .planner.foxess_gate import FoxessGateContext, evaluate_foxess_gate
from .planner.foxess_ownership import (
    FoxessOwnershipContext,
    evaluate_foxess_ownership,
)
from .planner.foxess_recovery import mark_foxess_source_unavailable
from .planner.ledger import calculate_ledger
from .telemetry import CLOUD_SOLAR_BALANCE_MAX_AGE_SECONDS
from .telemetry_adapter import capture_telemetry_source

_LOGGER = logging.getLogger(__name__)


class ActiveFoxessController:
    """Run commissioned, independently opted-in Local Modbus policies."""

    def __init__(self, hass: HomeAssistant, coordinator: EnergyCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._unsub_interval: CALLBACK_TYPE | None = None
        self._adapter: FoxessServiceAdapter | None = None
        self._reconcile_lock = asyncio.Lock()
        self._reconcile_stopped = False
        self._price_unsub = None
        self._price_task = None
        self._price_reconcile_requested = False
        self._price_deadline_unsub = None
        self._price_deadline_token = 0
        self._price_write_deadline = None
        self._price_write_signature = None
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
        self._export_repository = create_typed_value_repository(
            hass,
            storage_version=1,
            storage_key=(
                "home_energy_orchestrator."
                f"{getattr(coordinator, 'entry_id', 'runtime')}.export_session"
            ),
            decode=ExportSessionState.from_payload,
            encode=ExportSessionState.to_payload,
        )
        self._charge_repository = create_typed_value_repository(
            hass,
            storage_version=1,
            storage_key=(
                "home_energy_orchestrator."
                f"{getattr(coordinator, 'entry_id', 'runtime')}.charge_session"
            ),
            decode=ChargeSessionState.from_payload,
            encode=ChargeSessionState.to_payload,
        )
        self.manual = ManualInverterController(hass, coordinator, self)

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

    def _writes_still_authorized(self) -> bool:
        """Recheck the live interlock between commands in a delayed plan."""
        manual_test = getattr(self.coordinator, "manual_test", None)
        if self._reconcile_stopped:
            return False
        runtime = self.coordinator.runtime_config
        if not self._price_mapping_matches():
            return False
        if isinstance(
            self._adapter, FoxessServiceAdapter
        ) and self._adapter.entities != FoxessEntityMap(
            runtime.inverter.work_mode_entity,
            runtime.inverter.force_charge_power_entity,
            runtime.inverter.force_discharge_power_entity,
        ):
            return False
        allowed = (
            self.gate_status == "ready"
            and not bool(manual_test is not None and manual_test.is_active)
            and not self.manual.is_active
        )
        if not allowed:
            return False
        if self.export_session.phase in {
            "starting",
            "active",
        } and not self._ev_before_export_handoff_ready(dt_util.now()):
            return False
        if self._price_write_deadline is None:
            return True
        now = dt_util.now()
        if now >= self._price_write_deadline:
            return False
        window = self._price_window(now)
        if window is None or self._price_signature(window) != self._price_write_signature:
            return False
        feedback = capture_foxess_feedback(self.hass, self._adapter.entities)
        try:
            current = evaluate_foxess_export_policy(self._export_context(feedback, now))
        except (TypeError, ValueError):
            return False
        return (
            current.eligible
            and not current.finish_requested
            and current.price_deadline is not None
            and self._price_write_deadline <= current.price_deadline
            and self.export_session.requested_power_kw <= current.discharge_max_kw
        )

    def _price_mapping_matches(self) -> bool:
        if self.export_session.authority_source != "price" or self.export_session.phase == "idle":
            return True
        inverter = self.coordinator.runtime_config.inverter
        return self.export_session.price_actuator_entities == (
            inverter.work_mode_entity,
            inverter.force_charge_power_entity,
            inverter.force_discharge_power_entity,
        )

    def _price_physical_feedback_fresh(self, now: datetime) -> bool:
        telemetry = getattr(self.coordinator, "telemetry", None)
        for name in ("grid_power", "battery_power"):
            sample = getattr(telemetry, name, None)
            at = getattr(sample, "updated_at", None)
            if (
                sample is None
                or not sample.valid
                or not sample.fresh
                or at is None
                or not 0
                <= (now - at).total_seconds()
                <= self.coordinator.runtime_config.telemetry.max_age_seconds
            ):
                return False
        return True

    def _price_cleanup_capable(self, feedback: FoxessFeedbackSnapshot) -> bool:
        return (
            "Self Use" in feedback.mode_options
            and self._price_mapping_matches()
            and feedback.zero_power_writable
        )

    async def async_start(self) -> None:
        """Start the bounded reconciliation timer and perform one evaluation."""
        self._reconcile_stopped = False
        await self.manual.async_restore_handoff()
        await self._async_load_charge_session()
        await self._async_load_export_session()
        monitor = getattr(self.coordinator, "market_monitor", None)
        if monitor is not None and self._price_unsub is None:
            self._price_unsub = monitor.async_add_listener(self._price_changed)
        if self._unsub_interval is None:
            self._unsub_interval = async_track_time_interval(
                self.hass, self._async_tick, timedelta(seconds=30)
            )
        await self.async_reconcile()
        await self.coordinator.async_update_forecast()
        self.coordinator.async_update_listeners()

    async def async_stop(self) -> None:
        """Stop the timer without changing inverter state."""
        self._reconcile_stopped = True
        if self._price_unsub is not None:
            self._price_unsub()
            self._price_unsub = None
        self._cancel_price_deadline()
        await self.manual.async_unload()
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None
        async with self._reconcile_lock:
            pass
        if self._price_task is not None and not self._price_task.done():
            self._price_task.cancel()

    async def _async_tick(self, _now) -> None:
        await self.coordinator.async_request_refresh()
        await self.async_reconcile()
        await self.coordinator.async_update_forecast()
        self.coordinator.async_update_listeners()

    def _price_changed(self) -> None:
        """Ask the same controller to reconcile; the observer never writes."""
        if self._reconcile_stopped:
            return
        if not self.coordinator.runtime_config.export.price_triggered_enabled and (
            self.export_session.authority_source != "price" or self.export_session.phase == "idle"
        ):
            return
        self._price_reconcile_requested = True
        if self._price_task is None or self._price_task.done():
            self._price_task = self.hass.async_create_background_task(
                self._async_price_reconcile(), "HEO price export reconciliation"
            )

    async def _async_price_reconcile(self) -> None:
        blocked_followup_used = False
        while self._price_reconcile_requested and not self._reconcile_stopped:
            self._price_reconcile_requested = False
            await self.coordinator.async_request_refresh()
            try:
                await self.async_reconcile()
            except FoxessWriteBlocked:
                # A price can expire during command staging. The persisted
                # export session retains cleanup; never retry a positive plan.
                # A persistent gate block must yield to the ordinary timer,
                # rather than spin a second controller loop.
                if blocked_followup_used:
                    break
                blocked_followup_used = True
                self._price_reconcile_requested = True
            self.coordinator.async_update_listeners()

    def _cancel_price_deadline(self) -> None:
        self._price_deadline_token += 1
        if self._price_deadline_unsub is not None:
            self._price_deadline_unsub()
            self._price_deadline_unsub = None

    def _schedule_price_deadline(self) -> None:
        self._cancel_price_deadline()
        deadline = self.export_session.price_deadline
        if (
            self.export_session.authority_source != "price"
            or self.export_session.phase in {"idle", "stopping"}
            or deadline is None
            or deadline <= dt_util.now()
        ):
            return
        token = self._price_deadline_token

        async def expire(_now):
            if token == self._price_deadline_token and not self._reconcile_stopped:
                self._price_deadline_unsub = None
                self._price_changed()

        self._price_deadline_unsub = async_track_point_in_utc_time(self.hass, expire, deadline)

    def _price_window(self, now: datetime) -> tuple[datetime, datetime] | None:
        runtime = self.coordinator.runtime_config
        monitor = getattr(self.coordinator, "market_monitor", None)
        if not runtime.export.price_triggered_enabled or monitor is None:
            return None
        config = runtime.aemo_monitor
        result = monitor.export_result
        if (
            not config.enabled
            or result is None
            or result.region != config.region
            or result.price_per_kwh is None
            or not result.price_per_kwh >= config.export_threshold_per_kwh
            or result.interval_start is None
            or result.interval_end is None
            or not result.interval_start <= now < result.interval_end + PRICE_PUBLICATION_GRACE
        ):
            return None
        # Price export cannot replace ordinary free charging or a paid trip.
        if self.coordinator._free_window_hours_remaining(now) > 0:
            return None
        ev = getattr(self.coordinator, "ev_controller", None)
        preference = runtime.ev_preferences
        legacy = (
            capture_ev_entity_feedback(self.hass, preference.legacy_charge_to_full_entity)
            if (
                preference.legacy_charge_to_full_entity and not preference.charge_to_full_configured
            )
            else None
        )
        if (
            preference.charge_to_full_enabled
            or (ev is not None and getattr(ev, "charge_to_full_started_at", None) is not None)
            or (legacy is not None and legacy.available_state == "on")
        ):
            return None
        feedback = capture_foxess_feedback(
            self.hass,
            FoxessEntityMap(
                runtime.inverter.work_mode_entity,
                runtime.inverter.force_charge_power_entity,
                runtime.inverter.force_discharge_power_entity,
            ),
        )
        if feedback.native_power_units != ("kW", "kW"):
            return None
        next_free = now + timedelta(
            hours=hours_until_next_window(now, start=runtime.windows.effective_free_charge_start)
        )
        return result.interval_start, min(result.interval_end + PRICE_PUBLICATION_GRACE, next_free)

    def _price_signature(self, window) -> tuple[object, ...]:
        runtime = self.coordinator.runtime_config
        return (
            *window,
            runtime.aemo_monitor.region,
            runtime.aemo_monitor.export_threshold_per_kwh,
            runtime.export.price_triggered_enabled,
        )

    def _price_available_energy(self, now: datetime, maximum_kw: float) -> float | None:
        """Use the same ledger with current evidence and an execution margin."""
        runtime = self.coordinator.runtime_config
        telemetry = getattr(self.coordinator, "telemetry", None)
        snapshot, ledger = self.coordinator.snapshot, self.coordinator.data
        if snapshot is None or ledger is None or telemetry is None or maximum_kw <= 0:
            return None
        ages = []
        for name in ("grid_power", "battery_power", "house_load"):
            sample = getattr(telemetry, name, None)
            if sample is None or not sample.valid or not sample.fresh or sample.value is None:
                return None
            at = sample.updated_at
            if at is None or not isfinite(sample.value):
                return None
            age = (now - at).total_seconds()
            maximum_age = runtime.telemetry.max_age_seconds
            if (
                name == "house_load"
                and runtime.power_sources.house_load_source == "power_balance_cloud_solar"
            ):
                maximum_age = CLOUD_SOLAR_BALANCE_MAX_AGE_SECONDS
            if not 0 <= age <= maximum_age:
                return None
            ages.append(age)
        source = capture_telemetry_source(self.hass, runtime.battery.soc_entity)
        if source is None or source.updated_at is None:
            return None
        age = (now - source.updated_at).total_seconds()
        if not 0 <= age <= runtime.telemetry.max_age_seconds:
            return None
        ages.append(age)
        try:
            soc = float(source.raw_value)
            if not isfinite(soc) or not 0 <= soc <= 100:
                return None
            fresh = calculate_ledger(
                SiteSnapshot(
                    battery_soc=soc,
                    battery_capacity_kwh=snapshot.battery_capacity_kwh,
                    battery_floor_percent=snapshot.battery_floor_percent,
                    reserve_kwh=snapshot.reserve_kwh,
                    grid_power_kw=telemetry.grid_power.value,
                    house_load_kw=telemetry.house_load.value,
                )
            ).available_after_reserve_kwh
            cached = ledger.available_after_reserve_kwh
            if fresh is None or cached is None or not isfinite(cached):
                return None
            return max(min(fresh, cached) - maximum_kw * (max(ages) + 5) / 3600, 0)
        except (TypeError, ValueError):
            return None

    def _export_context(self, feedback, now: datetime) -> FoxessExportPolicyContext:
        """One protected export calculation for ordinary and price admission."""
        runtime = self.coordinator.runtime_config
        start_at, finish_at = self._export_bounds(now)
        window = self._price_window(now)
        price_owned = (
            self.export_session.authority_source == "price" and self.export_session.phase != "idle"
        )
        if not feedback.export_source_available:
            window = None
        protected_ev = self._protected_keepalive_energy_kwh(self._hours_until_next_free(now))
        ev = getattr(self.coordinator, "ev_controller", None)
        protected_ev = compose_protected_ev_energy_kwh(
            keepalive_kwh=protected_ev,
            daily_backfill_kwh=ev.daily_backfill_protection_kwh(now)
            if protected_ev is not None and ev
            else None,
        )
        ledger = self.coordinator.data
        available = getattr(ledger, "available_after_reserve_kwh", None)
        # The existing all-day meter counts earlier spikes as well as normal
        # exports. It is not reset by a new price interval or switch toggle.
        exported = getattr(ledger, "daily_export_kwh", None)
        if exported is None and window is None and self.export_session.authority_source != "price":
            exported = getattr(
                getattr(self.coordinator, "zerohero_export", None), "imported_kwh", None
            )
        price_path = self.export_session.authority_source == "price" or (
            window is not None and self.export_session.phase == "idle"
        )
        if price_path:
            available = self._price_available_energy(
                now, min(runtime.inverter.discharge_limit_kw, feedback.discharge_power_max_kw)
            )
        return FoxessExportPolicyContext(
            requested_enabled=runtime.automation.battery_export_enabled,
            before_export_enabled=runtime.ev_preferences.before_export_enabled,
            ev_soc_percent=getattr(self.coordinator.snapshot, "ev_soc", None),
            before_export_target_percent=runtime.ev_preferences.before_export_soc_target,
            now=now,
            start_at=start_at,
            finish_at=finish_at,
            source_capability_available=(
                self._price_cleanup_capable(feedback)
                if price_owned and (window is None or available is None)
                else feedback.export_source_available
            ),
            configured_max_kw=runtime.inverter.discharge_limit_kw,
            observed_max_kw=feedback.discharge_power_max_kw,
            exported_kwh=exported,
            automatic_limit_kwh=runtime.export.automatic_limit_kwh,
            protected_house_kwh=getattr(self.coordinator, "learning_remaining_kwh", None),
            protected_ev_kwh=protected_ev,
            available_after_reserve_kwh=available,
            discharge_efficiency_percent=runtime.export.discharge_efficiency_percent,
            session=self.export_session,
            previous_automatic_remaining_kwh=self.automatic_export_remaining_kwh,
            previous_protected_ev_kwh=self.export_protected_ev_kwh,
            price_export_enabled=runtime.export.price_triggered_enabled,
            price_interval_start=window[0] if window else None,
            price_interval_end=window[1] if window else None,
        )

    def _ev_before_export_handoff_ready(self, now: datetime) -> bool:
        """Confirm the EV is no longer spending surplus before export takes it.

        This uses physical feedback, not the EV controller's callback order or
        remembered target. A positively disconnected car may retain requested
        and raw current; only the shared complete disconnected-idle proof
        permits disregarding those values.
        """
        runtime = self.coordinator.runtime_config
        connection = runtime.ev_connection
        if (
            not runtime.ev_preferences.before_export_enabled
            or not connection.configured
            or not connection.control_commissioned
        ):
            return True
        feedback = capture_ev_feedback(self.hass, ev_observation_entity_map(runtime))
        maximum_age = runtime.telemetry.max_age_seconds
        physical = feedback.physical_observation(now=now, max_age_seconds=maximum_age)
        if not physical.available:
            return False
        if physical.disconnected_idle:
            return True
        if feedback.cable_connected.available_state not in {"on", "connected"}:
            return False
        # An off, non-charging connected car needs no reduced-current command.
        # Positive connected raw current remains contradictory, not stopped
        # proof merely because the state-qualified projection reports zero.
        if not physical.charge_switch_on and not physical.charging_activity:
            return True
        current = feedback.current_limit
        values = (
            current.current_a,
            current.minimum,
            current.maximum,
            current.step,
            connection.configured_max_current_a,
            connection.protected_baseline_a,
            feedback.actual_current.current_a,
        )
        if not current.fresh(now, maximum_age) or any(
            value is None or not isfinite(value) for value in values
        ):
            return False
        requested, minimum, maximum, step, ceiling, configured, actual = values
        assert all(value is not None for value in values)
        if minimum < 0 or step <= 0 or maximum < minimum or ceiling <= 0:
            return False
        ceiling = min(ceiling, maximum)
        baseline = protected_baseline_current_a(
            configured_baseline_a=configured,
            physical_minimum_a=minimum if minimum > 0 else step,
            current_step_a=step,
            physical_ceiling_a=ceiling,
        )
        baseline = ceil(baseline / step) * step
        return (
            physical.charge_switch_on
            and baseline > 0
            and minimum <= baseline
            and baseline <= ceiling
            and minimum <= requested <= baseline
            and 0 <= actual <= baseline
        )

    async def async_reconcile(self) -> None:
        """Evaluate and, only after every gate passes, execute one plan."""
        await self.manual.async_restore_handoff()
        async with self._reconcile_lock:
            await self._async_reconcile_locked()

    async def _async_reconcile_locked(self) -> None:
        if maintenance_writes_blocked(self.hass):
            return
        if self._reconcile_stopped:
            return
        if await self.manual.async_reconcile_locked():
            self.last_reason = self.manual.status
            self.last_actions = ()
            self.export_effective_enabled = False
            return
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
                    (self.coordinator.snapshot is not None and self.coordinator.data is not None)
                    or (
                        self.export_session.authority_source == "price"
                        and self.export_session.phase != "idle"
                    )
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
        if not self._price_mapping_matches():
            self.last_reason = "export_price_mapping_changed"
            self.last_actions = ()
            return
        assert runtime.inverter.work_mode_entity is not None
        assert runtime.inverter.force_charge_power_entity is not None
        assert runtime.inverter.force_discharge_power_entity is not None
        entities = FoxessEntityMap(
            runtime.inverter.work_mode_entity,
            runtime.inverter.force_charge_power_entity,
            runtime.inverter.force_discharge_power_entity,
        )
        feedback = capture_foxess_feedback(self.hass, entities)
        now = dt_util.now()
        if feedback.observation is None:
            if (
                self.export_session.authority_source == "price"
                and self.export_session.phase != "idle"
            ):
                await self._async_price_unknown_feedback_cleanup(entities, feedback, now)
                return
            await self._async_mark_sessions_source_unavailable(now)
            self.last_reason = "foxess_feedback_unavailable"
            return
        observation = feedback.observation
        if await self._async_hold_unverified_ownership(observation):
            return
        if self.export_session.authority_source == "price" and self.export_session.phase != "idle":
            await self._async_reconcile_export(observation, entities, feedback, now)
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

    async def async_supervisory_repair(self, expected_mode: str) -> None:
        """Re-arm one proven HEO intent after a persistent feedback mismatch."""
        await self.manual.async_restore_handoff()
        async with self._reconcile_lock:
            if self.manual.is_active:
                await self._async_reconcile_locked()
                return
            await self._async_supervisory_repair_locked(expected_mode)

    async def async_relinquish_for_manual(self, entities: FoxessEntityMap) -> None:
        """Transfer HEO obligations under the common lock without a restore write."""
        if self._adapter is not None and self._adapter.entities != entities:
            raise FoxessWriteBlocked("resolve changed automatic actuator mapping before handoff")
        if not self._price_mapping_matches():
            raise FoxessWriteBlocked("restore the owned price-export mapping before manual handoff")
        self._cancel_price_deadline()
        manual_test = getattr(self.coordinator, "manual_test", None)
        if manual_test is not None:
            await manual_test.async_relinquish_for_manual()
        self.charge_session = ChargeSessionState()
        self.export_session = ExportSessionState()
        self.charge_power_target_kw = None
        self.export_plan = None
        self.export_planned_start = None
        self.export_effective_enabled = False
        self.last_actions = ()
        await self._charge_repository.async_save(self.charge_session)
        await self._export_repository.async_save(self.export_session)
        self._charge_storage_status = self._export_storage_status = "valid"

    async def _async_supervisory_repair_locked(self, expected_mode: str) -> None:
        if self.gate_status != "ready":
            return
        runtime = self.coordinator.runtime_config
        entities = FoxessEntityMap(
            str(runtime.inverter.work_mode_entity),
            str(runtime.inverter.force_charge_power_entity),
            str(runtime.inverter.force_discharge_power_entity),
        )
        feedback = capture_foxess_feedback(self.hass, entities)
        if feedback.observation is None:
            return
        if expected_mode == "Force Charge" and self.charge_session.phase in {
            "starting",
            "active",
            "recovering",
        }:
            self.charge_session = replace(
                self.charge_session,
                phase="recovering",
                attempts=0,
                last_command_at=None,
            )
            await self._charge_repository.async_save(self.charge_session)
            await self._async_reconcile_locked()
            return
        if expected_mode == "Force Discharge" and self.export_session.phase in {
            "starting",
            "active",
            "recovering",
        }:
            self.export_session = replace(
                self.export_session,
                phase="recovering",
                attempts=0,
                last_command_at=None,
            )
            await self._export_repository.async_save(self.export_session)
            await self._async_reconcile_locked()
            return
        if expected_mode != "Self Use":
            return
        plan = plan_foxess_commands(
            ControlDecision(
                "restore_self_use", 0.0, "supervisor_restore_self_use"
            ),
            feedback.observation,
            charge_power_max_kw=max(feedback.charge_power_max_kw or 0.0, 0.0),
            discharge_power_max_kw=max(
                feedback.discharge_power_max_kw or 0.0, 0.0
            ),
        )
        if not plan.commands:
            return
        if self._adapter is None:
            self._adapter = FoxessServiceAdapter(
                self.hass,
                entities,
                allow_writes=True,
                write_guard=self._writes_still_authorized,
            )
        executed = await self._adapter.async_execute(plan)
        self.last_actions = executed
        self.writes_performed += len(executed)
        self.last_reason = "supervisor_restore_self_use"

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
                    write_guard=self._writes_still_authorized,
                )
            plan = apply_force_mode_command_delays(transition.plan)
            try:
                executed = await self._adapter.async_execute(plan)
            except Exception:
                executed = self._adapter.last_executed
                self.last_actions = executed
                self.writes_performed += len(executed)
                raise
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
        """Apply either permission through the same protected export session."""
        context = self._export_context(feedback, now)
        policy = evaluate_foxess_export_policy(context)
        if (
            policy.before_export_decision.export_allowed
            and not self._ev_before_export_handoff_ready(now)
        ):
            # Preserve the reducer and its persisted cleanup duty. Admission is
            # withheld until actual/requested EV current has handed energy back;
            # reaching the SoC target alone cannot start overlapping export.
            policy = replace(
                policy,
                before_export_decision=EvBeforeExportDecision(False, "ev_handoff_pending"),
                effective_enabled=False,
                eligible=False,
                should_advance=policy.latched,
                session_window_active=False,
                finish_requested=True,
            )
        self.ev_before_export_decision = policy.before_export_decision
        self.export_effective_enabled = policy.effective_enabled
        self.automatic_export_remaining_kwh = policy.automatic_remaining_kwh
        self.export_protected_ev_kwh = policy.protected_ev_kwh
        self.export_plan = policy.export_plan
        self.export_planned_start = policy.planned_start
        if not policy.should_advance:
            if self.export_session.phase == "idle":
                self._cancel_price_deadline()
            return False
        previous = self.export_session
        transition = advance_export_session(
            previous,
            observation,
            now=now,
            source_available=policy.source_available,
            window_active=policy.session_window_active,
            eligible=policy.eligible,
            requested_discharge_power_kw=policy.requested_power_kw,
            discharge_power_max_kw=policy.discharge_max_kw,
            finish_requested=policy.finish_requested,
            authority_source=policy.authority_source,
            price_deadline=policy.price_deadline,
            price_permission_end=context.price_interval_end if policy.authority_source == "price"
            else None,
        )
        if transition.state.authority_source == "price" and previous.phase == "idle":
            transition = replace(
                transition,
                state=replace(
                    transition.state,
                    price_actuator_entities=(
                        entities.work_mode_entity,
                        entities.force_charge_power_entity,
                        entities.force_discharge_power_entity,
                    ),
                ),
            )
        if (
            previous.authority_source == "price"
            and previous.phase != "idle"
            and transition.state.phase == "idle"
            and not self._price_physical_feedback_fresh(now)
        ):
            transition = replace(
                transition,
                state=replace(previous, phase="stopping"),
                reason="price_cleanup_feedback_unconfirmed",
            )
        positive = any(
            command.action == "select_mode"
            and command.value == "Force Discharge"
            or command.action == "set_discharge_power"
            and float(command.value) > 0
            for command in transition.plan.commands
        )
        self.export_session = transition.state
        if self.export_session != previous:
            try:
                await self._export_repository.async_save(self.export_session)
            except (OSError, ValueError):
                if previous.authority_source != "price" or previous.phase == "idle" or positive:
                    self.export_session = previous
                    raise
                if transition.state.phase == "idle":
                    self.export_session = previous
            else:
                self._export_storage_status = "valid"
        self._schedule_price_deadline()
        self.last_reason = f"export_{transition.reason}"
        self.last_actions = ()
        if transition.plan.commands:
            if positive and transition.state.authority_source == "price":
                self._price_write_deadline = transition.state.price_deadline
                window = self._price_window(now)
                self._price_write_signature = self._price_signature(window) if window else None
            try:
                await self._async_execute_export_plan(transition.plan, entities)
            finally:
                self._price_write_deadline = self._price_write_signature = None
        return True

    async def _async_execute_export_plan(self, plan, entities) -> None:
        if self._adapter is None:
            self._adapter = FoxessServiceAdapter(
                self.hass,
                entities,
                allow_writes=True,
                write_guard=self._writes_still_authorized,
            )
        try:
            executed = await self._adapter.async_execute(apply_force_mode_command_delays(plan))
        except Exception:
            self.last_actions = self._adapter.last_executed
            self.writes_performed += len(self.last_actions)
            raise
        self.last_actions = executed
        self.writes_performed += len(executed)
        if executed:
            _LOGGER.info(
                "FoxESS %s export plan executed: %s",
                "price" if self.export_session.authority_source == "price" else "ZEROHERO",
                executed,
            )

    async def _async_price_unknown_feedback_cleanup(self, entities, feedback, now) -> None:
        """An owned journal permits only reducing cleanup with valid metadata."""
        state = self.export_session
        self.export_effective_enabled = False
        self.export_plan = None
        self.export_planned_start = None
        self.last_actions = ()
        self.last_reason = "export_price_cleanup_feedback_unavailable"
        if not self._price_cleanup_capable(feedback):
            return
        delay = min(30 * 2 ** min(max(state.attempts - 1, 0), 4), 300)
        if (
            state.phase == "stopping"
            and state.last_command_at is not None
            and state.last_command_at <= now
            and (now - state.last_command_at).total_seconds() < delay
        ):
            return
        self.export_session = replace(
            state, phase="stopping", attempts=state.attempts + 1, last_command_at=now
        )
        try:
            await self._export_repository.async_save(self.export_session)
        except (OSError, ValueError):
            pass  # Previous durable ownership still authorises only reducing cleanup.
        self._cancel_price_deadline()
        await self._async_execute_export_plan(
            FoxessCommandPlan(
                (
                    FoxessCommand("select_mode", "Self Use"),
                    FoxessCommand("set_charge_power", 0),
                    FoxessCommand("set_discharge_power", 0),
                ),
                "price_feedback_unavailable",
            ),
            entities,
        )

    async def _async_mark_sessions_source_unavailable(self, now: datetime) -> None:
        recovery = mark_foxess_source_unavailable(
            self.charge_session,
            self.export_session,
            now,
        )
        self.charge_session = recovery.charge_session
        self.export_session = recovery.export_session
        if recovery.save_charge:
            await self._charge_repository.async_save(self.charge_session)
        if recovery.save_export:
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
        result = evaluate_foxess_ownership(
            FoxessOwnershipContext(
                mode=observation.mode,
                charge_phase=self.charge_session.phase,
                export_phase=self.export_session.phase,
                charge_storage_status=self._charge_storage_status,
                export_storage_status=self._export_storage_status,
                manual_present=manual is not None,
                manual_active=bool(
                    manual is not None and getattr(manual, "is_active", False)
                ),
                manual_kind=(
                    getattr(manual, "active_kind", None)
                    if manual is not None
                    else None
                ),
                manual_storage_status=manual_status,
            )
        )
        if result.reset_sessions:
            self.charge_session = ChargeSessionState()
            self.export_session = ExportSessionState()
            await self._charge_repository.async_save(self.charge_session)
            await self._export_repository.async_save(self.export_session)
            self._charge_storage_status = "valid"
            self._export_storage_status = "valid"
        if result.checkpoint_manual_idle:
            assert manual is not None
            await manual.async_checkpoint_safe_idle()
        self.ownership_status = result.status
        if result.reason is not None:
            self.last_reason = result.reason
        if result.clear_actions:
            self.last_actions = ()
        return result.hold

    def _export_state_payload(self) -> dict[str, object]:
        return self.export_session.to_payload()

    def _export_bounds(self, now: datetime) -> tuple[datetime, datetime]:
        start = self.coordinator.runtime_config.windows.effective_bonus_start
        finish = self._force_discharge_finish_time()
        return control_window_bounds(now, start=start, finish=finish)

    def _force_discharge_finish_time(self) -> time:
        """Derive finish from ZEROHERO end, retaining pre-v5 compatibility."""
        runtime = self.coordinator.runtime_config
        return derive_force_discharge_finish(
            bonus_end=runtime.windows.effective_bonus_end,
            offset_configured=runtime.export.force_discharge_offset_configured,
            offset_minutes=runtime.export.force_discharge_offset_minutes,
            legacy_finish=runtime.windows.effective_legacy_force_discharge_finish,
        )

    def _hours_until_next_free(self, now: datetime) -> float:
        free_start = self.coordinator.runtime_config.windows.effective_free_charge_start
        return hours_until_next_window(now, start=free_start)

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

        return daily_windows_overlap(
            charge_start,
            charge_end,
            export_start,
            export_end,
        )

    def _protected_keepalive_energy_kwh(self, hours_until_free: float) -> float | None:
        """Port the pilot site's mandatory connected-EV keepalive reservation.

        Presence and cable state are explicitly mapped. Missing evidence blocks
        a new export whenever a non-zero baseline is commissioned.
        """
        ev = self.coordinator.runtime_config.ev_connection
        home_entity = ev.at_home_entity
        cable_entity = ev.cable_connected_entity
        evidence_required = protected_keepalive_requires_evidence(
            ev_configured=ev.configured,
            control_commissioned=ev.control_commissioned,
            protected_baseline_a=ev.protected_baseline_a,
        )
        home = (
            self._state(str(home_entity))
            if evidence_required and home_entity
            else None
        )
        cable = (
            self._state(str(cable_entity))
            if evidence_required and cable_entity
            else None
        )
        return calculate_protected_keepalive_energy_kwh(
            ev_configured=ev.configured,
            control_commissioned=ev.control_commissioned,
            protected_baseline_a=ev.protected_baseline_a,
            home_state=home,
            cable_state=cable,
            hours_until_free=hours_until_free,
            voltage_v=ev.voltage_v,
            phase_count=ev.phase_count,
        )

    def _state(self, entity_id: str) -> str | None:
        reported = capture_ev_entity_feedback(self.hass, entity_id).reported_state
        if reported is None or reported in {"unknown", "unavailable"}:
            return None
        return reported
