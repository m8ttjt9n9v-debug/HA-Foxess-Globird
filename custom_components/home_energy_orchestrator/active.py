"""Explicitly opt-in FoxESS reconciliation for the commissioned path.

The observer remains the default. This controller only starts when the config
entry enables automatic control and disables rehearsal mode, and it requires a
complete FoxESS actuator mapping. The companion EV controller uses the same
gates and only adjusts an explicitly mapped Tessie/Tessy current setpoint while
the free window and local feedback are valid.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .active_ev import ActiveEvController
from .const import (
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_EXPORT_LIMIT_KW,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_REHEARSAL_MODE,
    DEFAULT_EXPORT_LIMIT_KW,
    DEFAULT_INVERTER_CHARGE_LIMIT_KW,
    DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
)
from .coordinator import EnergyCoordinator
from .foxess_adapter import FoxessEntityMap, FoxessServiceAdapter
from .normalise import power_to_kw
from .planner.control import ControlInputs, decide_control
from .planner.foxess import FoxessCommandPlan, FoxessObservation, plan_foxess_commands
from .planner.reconciliation import reconcile_foxess_plan

_LOGGER = logging.getLogger(__name__)


class ActiveFoxessController:
    """Run only the commissioned, opt-in FoxESS free-charge loop."""

    def __init__(self, hass: HomeAssistant, coordinator: EnergyCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._unsub_interval: CALLBACK_TYPE | None = None
        self._adapter: FoxessServiceAdapter | None = None
        self.writes_performed = 0
        self.last_reason = "automatic_control_disabled"
        self.last_actions: tuple[str, ...] = ()
        self._attempts = 0
        self._last_attempt_at = None
        self._last_plan_reason: str | None = None
        self.ev_controller = ActiveEvController(hass, coordinator)

    @property
    def gate_status(self) -> str:
        """Return a human-readable commissioning gate state."""
        if not self.coordinator.config.get(CONF_AUTOMATIC_CONTROL_ENABLED, False):
            return "disabled"
        if self.coordinator.config.get(CONF_REHEARSAL_MODE, True):
            return "rehearsal"
        mapping = (
            self.coordinator.config.get(CONF_FOXESS_WORK_MODE),
            self.coordinator.config.get(CONF_FOXESS_FORCE_CHARGE_POWER),
            self.coordinator.config.get(CONF_FOXESS_FORCE_DISCHARGE_POWER),
        )
        return "ready" if all(mapping) else "blocked_incomplete_mapping"

    async def async_start(self) -> None:
        """Start the bounded reconciliation timer and perform one evaluation."""
        if self._unsub_interval is None:
            self._unsub_interval = async_track_time_interval(
                self.hass, self._async_tick, timedelta(seconds=30)
            )
        await self.async_reconcile()
        await self.ev_controller.async_reconcile()

    async def async_stop(self) -> None:
        """Stop the timer without changing inverter state."""
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None

    async def _async_tick(self, _now) -> None:
        await self.coordinator.async_request_refresh()
        await self.async_reconcile()
        await self.ev_controller.async_reconcile()

    async def async_reconcile(self) -> None:
        """Evaluate and, only after every gate passes, execute one plan."""
        if not self.coordinator.config.get(CONF_AUTOMATIC_CONTROL_ENABLED, False):
            self.last_reason = "automatic_control_disabled"
            return
        if self.coordinator.config.get(CONF_REHEARSAL_MODE, True):
            self.last_reason = "rehearsal_mode"
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
        plan = self.coordinator.free_charge_plan
        if plan is None:
            self.last_reason = "free_charge_inputs_unavailable"
            return
        mode = self._state(str(mapping[0]))
        charge_power = self._power_state(str(mapping[1]))
        discharge_power = self._power_state(str(mapping[2]))
        soc = self.coordinator.snapshot.battery_soc
        grid_import = self.coordinator.data.grid_import_kw
        if mode is None or charge_power is None or discharge_power is None:
            self.last_reason = "foxess_feedback_unavailable"
            return
        if soc is None or grid_import is None:
            self.last_reason = "telemetry_unavailable"
            return
        completion = self.coordinator.free_charge_completion
        free_window_active = self.coordinator._free_window_hours_remaining(  # noqa: SLF001
            dt_util.now()
        ) > 0
        restore_mode = (
            "Backup"
            if free_window_active and completion and completion.action == "backup"
            else "Self Use"
        )
        control = decide_control(
            ControlInputs(
                rehearsal=False,
                ready=True,
                automatic_charge=free_window_active and plan.target_charge_power_kw > 0,
                automatic_export=False,
                free_window_active=free_window_active,
                export_window_active=False,
                current_mode=mode,
                battery_soc=soc,
                charge_target_soc=100.0,
                requested_charge_power_kw=plan.target_charge_power_kw,
                charge_power_max_kw=self._configured(
                    CONF_INVERTER_CHARGE_LIMIT_KW, DEFAULT_INVERTER_CHARGE_LIMIT_KW
                ),
                planned_export_energy_kwh=0.0,
                grid_import_kw=max(grid_import, 0.0),
                export_import_limit_kw=self._configured(
                    CONF_EXPORT_LIMIT_KW, DEFAULT_EXPORT_LIMIT_KW
                ),
                minimum_grid_soc=self.coordinator.snapshot.battery_floor_percent,
                configured_export_rate_c_kwh=0.0,
                minimum_export_rate_c_kwh=0.0,
                requested_discharge_power_kw=0.0,
                discharge_power_max_kw=self._configured(
                    CONF_INVERTER_DISCHARGE_LIMIT_KW, DEFAULT_INVERTER_DISCHARGE_LIMIT_KW
                ),
                restore_mode=restore_mode,
            )
        )
        if control.action == "force_charge" and control.power_kw <= 0:
            self.last_reason = "inverter_charge_limit_unavailable"
            _LOGGER.warning("Automatic control held: inverter charge limit is not commissioned")
            return
        foxess_plan = plan_foxess_commands(
            control,
            FoxessObservation(mode, charge_power, discharge_power),
            charge_power_max_kw=self._configured(
                CONF_INVERTER_CHARGE_LIMIT_KW, DEFAULT_INVERTER_CHARGE_LIMIT_KW
            ),
            discharge_power_max_kw=self._configured(
                CONF_INVERTER_DISCHARGE_LIMIT_KW, DEFAULT_INVERTER_DISCHARGE_LIMIT_KW
            ),
        )
        if foxess_plan.reason != self._last_plan_reason:
            self._attempts = 0
            self._last_attempt_at = None
            self._last_plan_reason = foxess_plan.reason
        reconciliation = reconcile_foxess_plan(
            foxess_plan,
            control,
            FoxessObservation(mode, charge_power, discharge_power),
            attempts=self._attempts,
            last_attempt_at=self._last_attempt_at,
            now=dt_util.now(),
        )
        if reconciliation.status == "satisfied":
            self._attempts = 0
            self._last_attempt_at = None
            self.last_reason = reconciliation.reason
            self.last_actions = ()
            return
        if reconciliation.status != "issue":
            self.last_reason = reconciliation.reason
            self.last_actions = ()
            return
        if self._adapter is None:
            self._adapter = FoxessServiceAdapter(
                self.hass,
                FoxessEntityMap(str(mapping[0]), str(mapping[1]), str(mapping[2])),
                allow_writes=True,
            )
        executed = await self._adapter.async_execute(
            FoxessCommandPlan(reconciliation.commands, reconciliation.reason)
        )
        self._attempts = reconciliation.attempts
        self._last_attempt_at = dt_util.now()
        self.last_reason = reconciliation.reason
        self.last_actions = executed
        self.writes_performed += len(executed)
        if executed:
            _LOGGER.info("FoxESS automatic plan executed: %s", executed)

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
