"""Explicitly opt-in EV current control for a mapped Tessie-compatible entity."""

from __future__ import annotations

import logging
from datetime import datetime
from math import isfinite

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_BONUS_LOAD_FOLLOWING_PERCENT,
    CONF_EV_CHARGE_LIMIT,
    CONF_EV_CHARGE_SWITCH,
    CONF_EV_CURRENT_LIMIT,
    CONF_EV_MAX_CURRENT,
    CONF_EV_MIN_CURRENT,
    CONF_EV_PHASE_COUNT,
    CONF_EV_VOLTAGE,
    CONF_FREE_CHARGE_START,
    CONF_INVERTER_CAPACITY,
    CONF_LOAD_FOLLOWING_OVERRIDE,
    CONF_NON_FREE_LOAD_FOLLOWING_PERCENT,
    CONF_REHEARSAL_MODE,
    CONF_SERVICE_IMPORT_LIMIT_A,
    CONF_SOLAR_POWER,
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

    This controller intentionally does not start/stop charging or change the
    vehicle's SoC limit. It only writes the explicitly mapped current setpoint
    for an at-home, connected vehicle, and only when local cable/current
    feedback can be found. Cloud schedules and charge-to-target behaviour stay
    outside this commissioning surface.
    """

    def __init__(self, hass: HomeAssistant, coordinator: EnergyCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._adapter: EvServiceAdapter | None = None
        self.writes_performed = 0
        self.last_reason = "automatic_control_disabled"
        self.last_actions: tuple[str, ...] = ()
        self._session_started = False

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
        switch_state = self.hass.states.get(str(switch_entity))
        if switch_state is None or switch_state.state not in {"on", "off"}:
            self.last_reason = "ev_charge_switch_unavailable"
            self.last_actions = ()
            return
        now = dt_util.now()
        hours_remaining = self.coordinator._free_window_hours_remaining(now)  # noqa: SLF001
        free_window_active = hours_remaining > 0
        at_home = self._at_home()
        if at_home is None:
            self.last_reason = "home_presence_unavailable"
            self.last_actions = ()
            return
        if at_home is False:
            # Away/supercharger operation belongs to Tessie.  Do not push a
            # zero or baseline current to a vehicle that has left the site.
            self.last_reason = "away"
            self.last_actions = ()
            return
        if not cable_connected:
            self.last_reason = "disconnected"
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
        ev_soc = self.coordinator.snapshot.ev_soc
        charge_limit = 100.0
        limit_state = self.hass.states.get(
            str(self.coordinator.config.get(CONF_EV_CHARGE_LIMIT, ""))
        )
        if limit_state is not None:
            charge_limit = _finite_number(limit_state.state) or charge_limit
        solar_kw = self.coordinator._power(  # noqa: SLF001
            self.coordinator.config.get(CONF_SOLAR_POWER)
        )
        house_kw = self.coordinator.snapshot.house_load_kw
        solar_surplus_kw = (
            max(solar_kw - max(house_kw, 0.0), 0.0)
            if solar_kw is not None and house_kw is not None
            else None
        )
        solar_spill_active = (
            not free_window_active
            and solar_surplus_kw is not None
            and solar_surplus_kw > 0.1
            and ev_soc is not None
            and ev_soc < charge_limit
            and self.coordinator.snapshot.battery_soc is not None
            and self.coordinator.snapshot.battery_soc >= 99.0
        )
        pre_free_current = self._pre_free_backfill_current(
            now, free_window_active, cable_connected, at_home, charge_limit
        )
        session_window_active = (
            free_window_active or solar_spill_active or pre_free_current is not None
        )
        target_reached = ev_soc is not None and ev_soc >= charge_limit
        session_intent = session_window_active and not target_reached
        if session_window_active and switch_state.state == "off" and ev_soc is None:
            self.last_reason = "ev_soc_unavailable"
            self.last_actions = ()
            return
        stop_reason = "target_reached" if target_reached else "charging_window_finished"
        if (
            self._session_started
            and not session_intent
            and switch_state.state == "on"
        ):
            if self._adapter is None:
                self._adapter = EvServiceAdapter(
                    self.hass,
                    EvEntityMap(
                        current_limit_entity=str(current_entity),
                        charge_switch_entity=str(switch_entity),
                    ),
                    allow_writes=True,
                )
            actions = await self._adapter.async_execute(
                EvCommandPlan((EvCommand("turn_off_charge"),), stop_reason)
            )
            self._session_started = False
            self.last_reason = stop_reason
            self.last_actions = actions
            self.writes_performed += len(actions)
            return
        try:
            decision = plan_ev_current_target(
                EvCurrentInputs(
                    free_window_active=free_window_active,
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
                    # Free-window charging is budget-controlled; the slower
                    # load-following percentage cap is for non-free sessions.
                    load_following_active=False,
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
                    home_presence_known=True,
                    at_home=at_home,
                    solar_spill_active=solar_spill_active,
                    solar_surplus_kw=solar_surplus_kw,
                    battery_soc_percent=self.coordinator.snapshot.battery_soc,
                    pre_free_backfill_active=pre_free_current is not None,
                    pre_free_backfill_current_a=pre_free_current,
                )
            )
        except (TypeError, ValueError):
            self.last_reason = "ev_inputs_invalid"
            self.last_actions = ()
            return
        target = decision.target_current_a
        start_session = session_intent and switch_state.state == "off"
        if abs(target - current_value) < max(step, 0.1) and not start_session:
            self.last_reason = decision.reason
            self.last_actions = ()
            return
        commands = [EvCommand("set_current", target)]
        if start_session:
            commands.append(EvCommand("turn_on_charge"))
        if self._adapter is None:
            self._adapter = EvServiceAdapter(
                self.hass,
                EvEntityMap(
                    current_limit_entity=str(current_entity),
                    charge_switch_entity=str(switch_entity),
                ),
                allow_writes=True,
            )
        actions = await self._adapter.async_execute(
            EvCommandPlan(tuple(commands), decision.reason)
        )
        if start_session and "turn_on_charge" in actions:
            self._session_started = True
        self.last_reason = decision.reason
        self.last_actions = actions
        self.writes_performed += len(actions)
        if actions:
            _LOGGER.info("EV automatic current plan executed: %s", actions)

    def _at_home(self) -> bool | None:
        """Read a Tessie/Tessy location tracker; unknown presence fails closed."""
        candidates = []
        for state in self.hass.states.async_all("device_tracker"):
            combined = f"{state.entity_id} {state.attributes.get('friendly_name', '')}".casefold()
            if any(marker in combined for marker in ("tessie", "tessy")):
                candidates.append(state)
        if not candidates:
            return None
        exact = next(
            (state for state in candidates if state.entity_id.casefold() in {
                "device_tracker.tessie_location", "device_tracker.tessy_location"
            }),
            candidates[0],
        )
        if exact.state == "home":
            return True
        if exact.state in {"not_home", "away"}:
            return False
        return None

    def _pre_free_backfill_current(
        self,
        now,
        free_window_active: bool,
        cable_connected: bool,
        at_home: bool,
        charge_limit: float,
    ) -> float | None:
        """Return a modest battery-funded backfill target before free power."""
        if free_window_active or not cable_connected or not at_home:
            return None
        if (
            self.coordinator.snapshot.ev_soc is None
            or self.coordinator.snapshot.ev_soc >= charge_limit
        ):
            return None
        if (
            self.coordinator.snapshot.grid_power_kw is None
            or self.coordinator.snapshot.grid_power_kw > 0
        ):
            return None
        available = getattr(self.coordinator.data, "available_after_reserve_kwh", None)
        if available is None or available <= 0.5:
            return None
        start = self.coordinator._configured_time(  # noqa: SLF001
            CONF_FREE_CHARGE_START, "12:01:00"
        )
        current = now.timetz().replace(tzinfo=None)
        if current >= start:
            return None
        hours_until = max(
            0.0,
            (
                datetime.combine(now.date(), start)
                - datetime.combine(now.date(), current)
            ).total_seconds()
            / 3600,
        )
        if hours_until <= 0 or hours_until > 6:
            return None
        voltage = _configured(
            self.coordinator.config, CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE
        )
        phase_count = int(
            _configured(
                self.coordinator.config, CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT
            )
        )
        return max(0.0, min(6.0, available * 1000 / (hours_until * voltage * phase_count)))

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
