"""Explicitly opt-in EV current control for a mapped Tessie-compatible entity."""

from __future__ import annotations

import logging
from math import isfinite

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_BONUS_LOAD_FOLLOWING_PERCENT,
    CONF_EV_CHARGE_SWITCH,
    CONF_EV_CURRENT_LIMIT,
    CONF_EV_MAX_CURRENT,
    CONF_EV_MIN_CURRENT,
    CONF_EV_PHASE_COUNT,
    CONF_EV_VOLTAGE,
    CONF_INVERTER_CAPACITY,
    CONF_LOAD_FOLLOWING_OVERRIDE,
    CONF_NON_FREE_LOAD_FOLLOWING_PERCENT,
    CONF_REHEARSAL_MODE,
    CONF_SERVICE_IMPORT_LIMIT_A,
    DEFAULT_BONUS_LOAD_FOLLOWING_PERCENT,
    DEFAULT_EV_MAX_CURRENT,
    DEFAULT_EV_MIN_CURRENT,
    DEFAULT_EV_PHASE_COUNT,
    DEFAULT_EV_VOLTAGE,
    DEFAULT_INVERTER_CAPACITY_KW,
    DEFAULT_LOAD_FOLLOWING_OVERRIDE,
    DEFAULT_NON_FREE_LOAD_FOLLOWING_PERCENT,
    DEFAULT_SERVICE_IMPORT_LIMIT_A,
)
from .coordinator import EnergyCoordinator
from .ev_adapter import EvEntityMap, EvServiceAdapter
from .planner.ev import EvCommand, EvCommandPlan, EvCurrentInputs, plan_ev_current_target

_LOGGER = logging.getLogger(__name__)


class ActiveEvController:
    """Adjust an already-connected EV's Tessie current setpoint safely.

    This first active EV milestone intentionally does not start/stop charging
    or change the vehicle's SoC limit. It only writes the explicitly mapped
    current setpoint while the configured free window is active, and only when
    local cable/current feedback can be found. That keeps cloud schedules and
    charge-to-target behaviour outside this commissioning surface.
    """

    def __init__(self, hass: HomeAssistant, coordinator: EnergyCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._adapter: EvServiceAdapter | None = None
        self.writes_performed = 0
        self.last_reason = "automatic_control_disabled"
        self.last_actions: tuple[str, ...] = ()

    @property
    def gate_status(self) -> str:
        """Return the current EV commissioning gate."""
        if not self.coordinator.config.get(CONF_AUTOMATIC_CONTROL_ENABLED, False):
            return "disabled"
        if self.coordinator.config.get(CONF_REHEARSAL_MODE, True):
            return "rehearsal"
        mapping = (
            self.coordinator.config.get(CONF_EV_CURRENT_LIMIT),
            self.coordinator.config.get(CONF_EV_CHARGE_SWITCH),
        )
        if not all(mapping):
            return "blocked_incomplete_ev_mapping"
        if not self._feedback_entities():
            return "blocked_ev_feedback_unavailable"
        return "ready"

    async def async_reconcile(self) -> None:
        """Evaluate one bounded current adjustment; otherwise perform no write."""
        if not self.coordinator.config.get(CONF_AUTOMATIC_CONTROL_ENABLED, False):
            self.last_reason = "automatic_control_disabled"
            self.last_actions = ()
            return
        if self.coordinator.config.get(CONF_REHEARSAL_MODE, True):
            self.last_reason = "rehearsal_mode"
            self.last_actions = ()
            return
        current_entity = self.coordinator.config.get(CONF_EV_CURRENT_LIMIT)
        switch_entity = self.coordinator.config.get(CONF_EV_CHARGE_SWITCH)
        if not current_entity or not switch_entity:
            self.last_reason = "incomplete_ev_mapping"
            self.last_actions = ()
            return
        if self.coordinator.snapshot is None:
            self.last_reason = "telemetry_unavailable"
            self.last_actions = ()
            return
        feedback = self._feedback_entities()
        if feedback is None:
            self.last_reason = "ev_feedback_unavailable"
            self.last_actions = ()
            return
        current_sensor, cable_sensor = feedback
        cable_connected = cable_sensor.state == "on"
        now = dt_util.now()
        hours_remaining = self.coordinator._free_window_hours_remaining(now)  # noqa: SLF001
        free_window_active = hours_remaining > 0
        if not free_window_active or not cable_connected:
            self.last_reason = "outside_free_window" if not free_window_active else "disconnected"
            self.last_actions = ()
            return

        current_state = self.hass.states.get(str(current_entity))
        if current_state is None:
            self.last_reason = "ev_current_setpoint_unavailable"
            self.last_actions = ()
            return
        current_value = _finite_number(current_state.state)
        if current_value is None:
            self.last_reason = "ev_current_setpoint_unavailable"
            self.last_actions = ()
            return
        minimum = _attribute_number(current_state, "min", 0.0)
        maximum = _attribute_number(
            current_state,
            "max",
            _configured(self.coordinator.config, CONF_EV_MAX_CURRENT, DEFAULT_EV_MAX_CURRENT),
        )
        step = _attribute_number(current_state, "step", 1.0)
        voltage = _configured(self.coordinator.config, CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE)
        phase_count = int(
            _configured(self.coordinator.config, CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT)
        )
        grid_power_kw = getattr(self.coordinator.snapshot, "grid_power_kw", None)
        grid_average_a = None
        if grid_power_kw is not None and isfinite(grid_power_kw):
            grid_average_a = max(grid_power_kw, 0.0) * 1000 / (voltage * phase_count)
        measured_current = _finite_number(current_sensor.state)
        try:
            decision = plan_ev_current_target(
                EvCurrentInputs(
                    free_window_active=True,
                    cable_connected=True,
                    ceiling_a=max(maximum, 0.0),
                    protected_baseline_a=min(
                        _configured(
                            self.coordinator.config, CONF_EV_MIN_CURRENT, DEFAULT_EV_MIN_CURRENT
                        ),
                        max(maximum, 0.0),
                    ),
                    effective_minimum_a=max(
                        minimum,
                        _configured(
                            self.coordinator.config, CONF_EV_MIN_CURRENT, DEFAULT_EV_MIN_CURRENT
                        ),
                    ),
                    requested_current_a=current_value,
                    service_current_a=_configured(
                        self.coordinator.config,
                        CONF_SERVICE_IMPORT_LIMIT_A,
                        DEFAULT_SERVICE_IMPORT_LIMIT_A,
                    ),
                    headroom_a=1.0,
                    grid_average_a=grid_average_a,
                    grid_coverage_ratio=1.0 if grid_average_a is not None else 0.0,
                    ev_average_a=measured_current,
                    ev_current_now_a=measured_current,
                    ev_feedback_source_valid=measured_current is not None,
                    elapsed_free_window_minutes=max(0.0, 180.0 - hours_remaining * 60),
                    settle_minutes=5.0,
                    priority_ev=False,
                    load_following_active=True,
                    bonus_window_active=(
                        self.coordinator._bonus_window_active(now)  # noqa: SLF001
                        if hasattr(self.coordinator, "_bonus_window_active")
                        else False
                    ),
                    inverter_capacity_kw=_configured(
                        self.coordinator.config,
                        CONF_INVERTER_CAPACITY,
                        DEFAULT_INVERTER_CAPACITY_KW,
                    ),
                    bonus_load_following_percent=_configured(
                        self.coordinator.config,
                        CONF_BONUS_LOAD_FOLLOWING_PERCENT,
                        DEFAULT_BONUS_LOAD_FOLLOWING_PERCENT,
                    ),
                    non_free_load_following_percent=_configured(
                        self.coordinator.config,
                        CONF_NON_FREE_LOAD_FOLLOWING_PERCENT,
                        DEFAULT_NON_FREE_LOAD_FOLLOWING_PERCENT,
                    ),
                    load_following_override=bool(
                        self.coordinator.config.get(
                            CONF_LOAD_FOLLOWING_OVERRIDE, DEFAULT_LOAD_FOLLOWING_OVERRIDE
                        )
                    ),
                    ev_voltage_v=voltage,
                    ev_phase_count=phase_count,
                    step_a=max(step, 0.1),
                )
            )
        except (TypeError, ValueError):
            self.last_reason = "ev_inputs_invalid"
            self.last_actions = ()
            return
        target = decision.target_current_a
        if abs(target - current_value) < max(step, 0.1):
            self.last_reason = decision.reason
            self.last_actions = ()
            return
        if self._adapter is None:
            self._adapter = EvServiceAdapter(
                self.hass,
                EvEntityMap(current_limit_entity=str(current_entity)),
                allow_writes=True,
            )
        actions = await self._adapter.async_execute(
            EvCommandPlan((EvCommand("set_current", target),), decision.reason)
        )
        self.last_reason = decision.reason
        self.last_actions = actions
        self.writes_performed += len(actions)
        if actions:
            _LOGGER.info("EV automatic current plan executed: %s", actions)

    def _feedback_entities(self):
        """Find one local Tessie/Tessy current sensor and cable sensor."""
        current = _find_state(self.hass, "sensor", ("charger_current", "charging_current"))
        cable = _find_state(self.hass, "binary_sensor", ("charge_cable", "cable_connected"))
        if current is None or cable is None:
            return None
        return current, cable


def _find_state(hass: HomeAssistant, domain: str, tokens: tuple[str, ...]):
    matches = []
    for state in hass.states.async_all(domain):
        combined = (
            f"{state.entity_id} {state.attributes.get('friendly_name', '')}"
        ).casefold()
        if not any(marker in combined for marker in ("tessie", "tessy")):
            continue
        if not any(token in combined for token in tokens):
            continue
        if state.state in {"unknown", "unavailable"}:
            continue
        matches.append(state)
    if len(matches) == 1:
        return matches[0]
    for state in matches:
        if state.entity_id.casefold() in {
            "sensor.tessie_charger_current",
            "sensor.tessy_charger_current",
            "binary_sensor.tessie_charge_cable",
            "binary_sensor.tessy_charge_cable",
        }:
            return state
    return None


def _finite_number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _attribute_number(state, key: str, default: float) -> float:
    value = _finite_number(state.attributes.get(key))
    return default if value is None else value


def _configured(config: dict[str, object], key: str, default: float) -> float:
    value = _finite_number(config.get(key, default))
    return default if value is None or value < 0 else value
