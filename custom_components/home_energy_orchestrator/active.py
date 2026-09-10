"""Explicitly opt-in Local Modbus battery controller.

The observer remains the default. This controller only starts when the config
entry selects Local Modbus ownership, enables automatic control and one of its
independent charge/export policies, disables rehearsal mode, and provides a
complete FoxESS actuator mapping.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_BATTERY_FREE_WINDOW_TARGET,
    CONF_BONUS_WINDOW_START,
    CONF_DISCHARGE_EFFICIENCY_PERCENT,
    CONF_EV_AT_HOME,
    CONF_EV_BEFORE_EXPORT_ENABLED,
    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
    CONF_EV_CABLE_CONNECTED,
    CONF_EV_PHASE_COUNT,
    CONF_EV_PROTECTED_BASELINE_A,
    CONF_EV_VOLTAGE,
    CONF_EXPORT_ALLOWANCE_KWH,
    CONF_EXPORT_DISCHARGE_POWER_KW,
    CONF_FORCE_DISCHARGE_FINISH,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_FREE_CHARGE_END,
    CONF_FREE_CHARGE_SCHEDULE_CONFIRMED,
    CONF_FREE_CHARGE_START,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_REHEARSAL_MODE,
    CONF_SIGN_CONVENTIONS_VERIFIED,
    DEFAULT_AUTOMATIC_CHARGE_ENABLED,
    DEFAULT_AUTOMATIC_EXPORT_ENABLED,
    DEFAULT_BATTERY_FREE_WINDOW_TARGET,
    DEFAULT_BONUS_WINDOW_START,
    DEFAULT_DISCHARGE_EFFICIENCY_PERCENT,
    DEFAULT_EV_BEFORE_EXPORT_ENABLED,
    DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
    DEFAULT_EV_PHASE_COUNT,
    DEFAULT_EV_PROTECTED_BASELINE_A,
    DEFAULT_EV_VOLTAGE,
    DEFAULT_EXPORT_ALLOWANCE_KWH,
    DEFAULT_EXPORT_DISCHARGE_POWER_KW,
    DEFAULT_FORCE_DISCHARGE_FINISH,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DEFAULT_FREE_CHARGE_END,
    DEFAULT_FREE_CHARGE_START,
    DEFAULT_INVERTER_CHARGE_LIMIT_KW,
    DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
    DEFAULT_SIGN_CONVENTIONS_VERIFIED,
    FOXESS_CONTROL_OWNER_CLOUD,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from .coordinator import EnergyCoordinator
from .foxess_adapter import FoxessEntityMap, FoxessServiceAdapter
from .normalise import power_to_kw
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
        self.export_allowance_remaining_kwh: float | None = None
        self.export_protected_ev_kwh: float | None = None
        self.ev_before_export_decision = EvBeforeExportDecision(True, "disabled")
        self.export_effective_enabled = False
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

    @property
    def gate_status(self) -> str:
        """Return a human-readable commissioning gate state."""
        owner = self.coordinator.config.get(
            CONF_FOXESS_CONTROL_OWNER, DEFAULT_FOXESS_CONTROL_OWNER
        )
        if owner == FOXESS_CONTROL_OWNER_CLOUD:
            return "foxcloud_scheduler_owner"
        if owner != FOXESS_CONTROL_OWNER_MODBUS:
            return "observer_owner"
        if not self.coordinator.config.get(CONF_AUTOMATIC_CONTROL_ENABLED, False):
            return "disabled"
        if self.coordinator.config.get(CONF_REHEARSAL_MODE, True):
            return "rehearsal"
        if not self.coordinator.config.get(
            CONF_SIGN_CONVENTIONS_VERIFIED,
            DEFAULT_SIGN_CONVENTIONS_VERIFIED,
        ):
            return "sign_conventions_unverified"
        mapping = (
            self.coordinator.config.get(CONF_FOXESS_WORK_MODE),
            self.coordinator.config.get(CONF_FOXESS_FORCE_CHARGE_POWER),
            self.coordinator.config.get(CONF_FOXESS_FORCE_DISCHARGE_POWER),
        )
        return "ready" if all(mapping) else "blocked_incomplete_mapping"

    async def async_start(self) -> None:
        """Start the bounded reconciliation timer and perform one evaluation."""
        await self._async_load_charge_session()
        await self._async_load_export_session()
        if self._unsub_interval is None:
            self._unsub_interval = async_track_time_interval(
                self.hass, self._async_tick, timedelta(seconds=30)
            )
        await self.async_reconcile()

    async def async_stop(self) -> None:
        """Stop the timer without changing inverter state."""
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None

    async def _async_tick(self, _now) -> None:
        await self.coordinator.async_request_refresh()
        await self.async_reconcile()
        self.coordinator.async_update_listeners()

    async def async_reconcile(self) -> None:
        """Evaluate and, only after every gate passes, execute one plan."""
        manual_test = getattr(self.coordinator, "manual_test", None)
        if manual_test is not None and manual_test.is_active:
            self.last_reason = "manual_test_active"
            self.last_actions = ()
            return
        owner = self.coordinator.config.get(
            CONF_FOXESS_CONTROL_OWNER, DEFAULT_FOXESS_CONTROL_OWNER
        )
        if owner == FOXESS_CONTROL_OWNER_CLOUD:
            self.last_reason = "foxcloud_scheduler_owns_inverter"
            self.last_actions = ()
            return
        if owner != FOXESS_CONTROL_OWNER_MODBUS:
            self.last_reason = "foxess_observer_owner"
            self.last_actions = ()
            return
        if not self.coordinator.config.get(CONF_AUTOMATIC_CONTROL_ENABLED, False):
            self.last_reason = "automatic_control_disabled"
            return
        if self.coordinator.config.get(CONF_REHEARSAL_MODE, True):
            self.last_reason = "rehearsal_mode"
            return
        if not self.coordinator.config.get(
            CONF_SIGN_CONVENTIONS_VERIFIED,
            DEFAULT_SIGN_CONVENTIONS_VERIFIED,
        ):
            self.last_reason = "sign_conventions_unverified"
            return
        mapping = (
            self.coordinator.config.get(CONF_FOXESS_WORK_MODE),
            self.coordinator.config.get(CONF_FOXESS_FORCE_CHARGE_POWER),
            self.coordinator.config.get(CONF_FOXESS_FORCE_DISCHARGE_POWER),
        )
        if not all(mapping):
            self.last_reason = "incomplete_foxess_mapping"
            _LOGGER.warning("Automatic control held: FoxESS mapping is incomplete")
            return
        if self.coordinator.snapshot is None or self.coordinator.data is None:
            self.last_reason = "telemetry_unavailable"
            return
        mode = self._state(str(mapping[0]))
        charge_power = self._power_state(str(mapping[1]))
        discharge_power = self._power_state(str(mapping[2]))
        now = dt_util.now()
        if mode is None or charge_power is None or discharge_power is None:
            await self._async_mark_sessions_source_unavailable(now)
            self.last_reason = "foxess_feedback_unavailable"
            return
        observation = FoxessObservation(mode, charge_power, discharge_power)
        # Finish a latched policy before considering another direction. With
        # ordinary non-overlapping windows this also guarantees that Self Use
        # feedback is confirmed before the next session may start.
        if self.charge_session.phase != "idle":
            if await self._async_reconcile_charge(observation, mapping, now):
                return
        if self.export_session.phase != "idle":
            if await self._async_reconcile_export(observation, mapping, now):
                return
        if self._enabled_control_windows_overlap():
            self.last_reason = "configured_control_windows_overlap"
            self.last_actions = ()
            return
        if await self._async_reconcile_charge(observation, mapping, now):
            return
        if await self._async_reconcile_export(observation, mapping, now):
            return
        self.last_reason = "no_automatic_foxess_policy_active"
        self.last_actions = ()

    async def _async_reconcile_charge(
        self,
        observation: FoxessObservation,
        mapping: tuple[object, object, object],
        now: datetime,
    ) -> bool:
        """Run the default-off fixed-power free-window charge extension."""
        requested_enabled = bool(
            self.coordinator.config.get(
                CONF_AUTOMATIC_CHARGE_ENABLED,
                DEFAULT_AUTOMATIC_CHARGE_ENABLED,
            )
        )
        schedule_confirmed = bool(
            self.coordinator.config.get(CONF_FREE_CHARGE_SCHEDULE_CONFIRMED, False)
        )
        enabled = requested_enabled and schedule_confirmed
        window_active = self.coordinator._free_window_hours_remaining(now) > 0  # noqa: SLF001
        configured_max = self._configured(
            CONF_INVERTER_CHARGE_LIMIT_KW,
            DEFAULT_INVERTER_CHARGE_LIMIT_KW,
        )
        charge_max = min(configured_max, self._entity_power_max(str(mapping[1])))
        source_available = (
            self._charge_source_available(str(mapping[0])) and charge_max > 0
        )
        self.charge_power_target_kw = (
            self.charge_session.requested_power_kw
            if source_available and self.charge_session.phase != "idle"
            else (0.0 if source_available else None)
        )
        soc = getattr(self.coordinator.snapshot, "battery_soc", None)
        target_soc = self._configured(
            CONF_BATTERY_FREE_WINDOW_TARGET,
            DEFAULT_BATTERY_FREE_WINDOW_TARGET,
        )
        eligible_to_start = (
            soc is not None
            and 0 <= float(soc) < target_soc
            and charge_max > 0
        )
        latched = self.charge_session.phase != "idle"
        if requested_enabled and not schedule_confirmed and not latched:
            self.last_reason = "charge_schedule_unconfirmed"
            self.last_actions = ()
            return True
        if (
            not latched
            and enabled
            and window_active
            and eligible_to_start
            and observation.mode != "Self Use"
        ):
            self.last_reason = "charge_start_mode_not_self_use"
            self.last_actions = ()
            return True
        if not latched and not (enabled and window_active and eligible_to_start):
            return False
        previous_state = self.charge_session
        transition = advance_charge_session(
            previous_state,
            observation,
            now=now,
            source_available=source_available,
            window_active=enabled and window_active,
            eligible_to_start=eligible_to_start,
            requested_charge_power_kw=charge_max,
            charge_power_max_kw=charge_max,
            finish_requested=not enabled or not window_active,
        )
        self.charge_session = transition.state
        self.charge_power_target_kw = (
            self.charge_session.requested_power_kw
            if self.charge_session.phase != "idle"
            else 0.0
        )
        if self.charge_session != previous_state:
            await self._charge_store.async_save(self._charge_state_payload())
        self.last_reason = f"charge_{transition.reason}"
        self.last_actions = ()
        if transition.plan.commands:
            if self._adapter is None:
                self._adapter = FoxessServiceAdapter(
                    self.hass,
                    FoxessEntityMap(str(mapping[0]), str(mapping[1]), str(mapping[2])),
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
        mapping: tuple[object, object, object],
        now: datetime,
    ) -> bool:
        """Run the ported pilot-site ZEROHERO session, when it owns this tick."""
        enabled = bool(
            self.coordinator.config.get(
                CONF_AUTOMATIC_EXPORT_ENABLED, DEFAULT_AUTOMATIC_EXPORT_ENABLED
            )
        )
        self.ev_before_export_decision = decide_ev_before_export(
            enabled=bool(
                self.coordinator.config.get(
                    CONF_EV_BEFORE_EXPORT_ENABLED,
                    DEFAULT_EV_BEFORE_EXPORT_ENABLED,
                )
            ),
            ev_soc_percent=getattr(self.coordinator.snapshot, "ev_soc", None),
            target_soc_percent=self._configured(
                CONF_EV_BEFORE_EXPORT_SOC_TARGET,
                DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
            ),
        )
        self.export_effective_enabled = (
            enabled and self.ev_before_export_decision.export_allowed
        )
        start_at, finish_at = self._export_bounds(now)
        within_session_window = start_at <= now < finish_at
        source_available = self._export_source_available(str(mapping[0]))
        discharge_max = min(
            self._configured(
                CONF_INVERTER_DISCHARGE_LIMIT_KW,
                DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
            ),
            self._entity_power_max(str(mapping[2])),
        )
        requested = min(
            self._configured(
                CONF_EXPORT_DISCHARGE_POWER_KW, DEFAULT_EXPORT_DISCHARGE_POWER_KW
            ),
            discharge_max,
        )
        eligible = False
        self.export_plan = None
        self.export_planned_start = None
        exported = getattr(
            getattr(self.coordinator, "zerohero_export", None), "imported_kwh", None
        )
        try:
            allowance = self._configured(
                CONF_EXPORT_ALLOWANCE_KWH, DEFAULT_EXPORT_ALLOWANCE_KWH
            )
            self.export_allowance_remaining_kwh = (
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
                and self.export_allowance_remaining_kwh is not None
                and discharge_max > 0
            ):
                efficiency = self._configured(
                    CONF_DISCHARGE_EFFICIENCY_PERCENT,
                    DEFAULT_DISCHARGE_EFFICIENCY_PERCENT,
                ) / 100
                window_hours = (finish_at - start_at).total_seconds() / 3600
                self.export_plan = calculate_export_plan(
                    max(float(available), 0.0) * efficiency,
                    protected_house,
                    protected_ev,
                    self.export_allowance_remaining_kwh,
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
            await self._export_store.async_save(self._export_state_payload())
        self.last_reason = f"export_{transition.reason}"
        self.last_actions = ()
        if transition.plan.commands:
            if self._adapter is None:
                self._adapter = FoxessServiceAdapter(
                    self.hass,
                    FoxessEntityMap(str(mapping[0]), str(mapping[1]), str(mapping[2])),
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
        if self.charge_session.phase != "idle":
            self.charge_session = ChargeSessionState(
                "recovering",
                self.charge_session.requested_power_kw,
                self.charge_session.attempts,
                self.charge_session.last_command_at or now,
            )
            await self._charge_store.async_save(self._charge_state_payload())
        if self.export_session.phase != "idle":
            self.export_session = ExportSessionState(
                "recovering",
                self.export_session.requested_power_kw,
                self.export_session.attempts,
                self.export_session.last_command_at or now,
            )
            await self._export_store.async_save(self._export_state_payload())

    async def _async_load_charge_session(self) -> None:
        payload = await self._charge_store.async_load()
        if not isinstance(payload, dict):
            return
        try:
            phase = str(payload["phase"])
            power = float(payload["requested_power_kw"])
            attempts = int(payload["attempts"])
            last_raw = payload.get("last_command_at")
            last_at = datetime.fromisoformat(str(last_raw)) if last_raw else None
            restored = ChargeSessionState(phase, power, attempts, last_at)
            if phase not in {"idle", "starting", "active", "stopping", "recovering"}:
                raise ValueError
            if power < 0 or attempts < 0:
                raise ValueError
            self.charge_session = restored
        except (KeyError, TypeError, ValueError):
            self.charge_session = ChargeSessionState()

    def _charge_state_payload(self) -> dict[str, object]:
        return {
            "phase": self.charge_session.phase,
            "requested_power_kw": self.charge_session.requested_power_kw,
            "attempts": self.charge_session.attempts,
            "last_command_at": (
                self.charge_session.last_command_at.isoformat()
                if self.charge_session.last_command_at
                else None
            ),
        }

    async def _async_load_export_session(self) -> None:
        payload = await self._export_store.async_load()
        if not isinstance(payload, dict):
            return
        try:
            phase = str(payload["phase"])
            power = float(payload["requested_power_kw"])
            attempts = int(payload["attempts"])
            last_raw = payload.get("last_command_at")
            last_at = datetime.fromisoformat(str(last_raw)) if last_raw else None
            restored = ExportSessionState(phase, power, attempts, last_at)
            if phase not in {"idle", "starting", "active", "stopping", "recovering"}:
                raise ValueError
            if power < 0 or attempts < 0:
                raise ValueError
            self.export_session = restored
        except (KeyError, TypeError, ValueError):
            self.export_session = ExportSessionState()

    def _export_state_payload(self) -> dict[str, object]:
        return {
            "phase": self.export_session.phase,
            "requested_power_kw": self.export_session.requested_power_kw,
            "attempts": self.export_session.attempts,
            "last_command_at": (
                self.export_session.last_command_at.isoformat()
                if self.export_session.last_command_at
                else None
            ),
        }

    def _export_bounds(self, now: datetime) -> tuple[datetime, datetime]:
        start = self.coordinator._configured_time(  # noqa: SLF001
            CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START
        )
        finish = self.coordinator._configured_time(  # noqa: SLF001
            CONF_FORCE_DISCHARGE_FINISH, DEFAULT_FORCE_DISCHARGE_FINISH
        )
        start_at = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
        finish_at = datetime.combine(now.date(), finish, tzinfo=now.tzinfo)
        if finish <= start:
            finish_at += timedelta(days=1)
            if now < datetime.combine(now.date(), finish, tzinfo=now.tzinfo):
                start_at -= timedelta(days=1)
                finish_at -= timedelta(days=1)
        return start_at, finish_at

    def _hours_until_next_free(self, now: datetime) -> float:
        free_start = self.coordinator._configured_time(  # noqa: SLF001
            CONF_FREE_CHARGE_START, DEFAULT_FREE_CHARGE_START
        )
        target = datetime.combine(now.date(), free_start, tzinfo=now.tzinfo)
        if target <= now:
            target += timedelta(days=1)
        return max((target - now).total_seconds() / 3600, 0.0)

    def _enabled_control_windows_overlap(self) -> bool:
        if not (
            self.coordinator.config.get(
                CONF_AUTOMATIC_CHARGE_ENABLED,
                DEFAULT_AUTOMATIC_CHARGE_ENABLED,
            )
            and self.coordinator.config.get(
                CONF_AUTOMATIC_EXPORT_ENABLED,
                DEFAULT_AUTOMATIC_EXPORT_ENABLED,
            )
        ):
            return False
        charge_start = self.coordinator._configured_time(  # noqa: SLF001
            CONF_FREE_CHARGE_START, DEFAULT_FREE_CHARGE_START
        )
        charge_end = self.coordinator._configured_time(  # noqa: SLF001
            CONF_FREE_CHARGE_END, DEFAULT_FREE_CHARGE_END
        )
        export_start = self.coordinator._configured_time(  # noqa: SLF001
            CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START
        )
        export_end = self.coordinator._configured_time(  # noqa: SLF001
            CONF_FORCE_DISCHARGE_FINISH, DEFAULT_FORCE_DISCHARGE_FINISH
        )

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
        baseline_a = self._configured(
            CONF_EV_PROTECTED_BASELINE_A, DEFAULT_EV_PROTECTED_BASELINE_A
        )
        if baseline_a <= 0:
            return 0.0
        home_entity = self.coordinator.config.get(CONF_EV_AT_HOME)
        cable_entity = self.coordinator.config.get(CONF_EV_CABLE_CONNECTED)
        if not home_entity or not cable_entity:
            return None
        home = self._state(str(home_entity))
        cable = self._state(str(cable_entity))
        if home is None or cable is None:
            return None
        if home not in {"home", "on"} or cable != "on":
            return 0.0
        voltage = self._configured(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE)
        phases = self._configured(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT)
        return round(max(hours_until_free, 0.0) * baseline_a * voltage * phases / 1000, 3)

    def _export_source_available(self, mode_entity: str) -> bool:
        state = self.hass.states.get(mode_entity)
        if state is None:
            return False
        options = state.attributes.get("options")
        return isinstance(options, (list, tuple)) and {
            "Force Discharge",
            "Self Use",
        }.issubset(options)

    def _charge_source_available(self, mode_entity: str) -> bool:
        state = self.hass.states.get(mode_entity)
        if state is None:
            return False
        options = state.attributes.get("options")
        return isinstance(options, (list, tuple)) and {
            "Force Charge",
            "Self Use",
        }.issubset(options)

    def _entity_power_max(self, entity_id: str) -> float:
        state = self.hass.states.get(entity_id)
        if state is None:
            return 0.0
        try:
            return power_to_kw(
                float(state.attributes.get("max", 0.0)),
                state.attributes.get("unit_of_measurement"),
            )
        except (TypeError, ValueError):
            return 0.0

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

    def _power_state(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        try:
            value = float(state.state)
            return power_to_kw(value, state.attributes.get("unit_of_measurement"))
        except (TypeError, ValueError):
            return None

    def _configured(self, key: str, default: float) -> float:
        try:
            value = float(self.coordinator.config.get(key, default))
        except (TypeError, ValueError):
            return default
        return max(value, 0.0)
