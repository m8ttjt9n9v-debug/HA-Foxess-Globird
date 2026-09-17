"""Read-only Home Assistant boundary for mapped EV entity feedback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from homeassistant.core import HomeAssistant, State

from .configuration import RuntimeConfiguration
from .normalise import current_to_a, energy_to_kwh
from .planner.ev import DirectEvseObservation

UNKNOWN_STATES = frozenset({"unknown", "unavailable", ""})


@dataclass(frozen=True, slots=True)
class EvEntityFeedback:
    """One immutable read of a mapped Home Assistant entity."""

    entity_id: str | None
    present: bool
    reported_state: str | None
    available_state: str | None
    raw_number: float | None
    number: float | None
    current_a: float | None
    energy_kwh: float | None
    minimum: float | None
    maximum: float | None
    step: float | None
    unit: str | None
    last_changed: datetime | None
    last_updated: datetime | None


@dataclass(frozen=True, slots=True)
class EvObservationEntityMap:
    """Every mapped entity read by EV policy and diagnostics in one cycle."""

    at_home_entity: str | None = None
    cable_connected_entity: str | None = None
    charging_state_entity: str | None = None
    actual_current_entity: str | None = None
    soc_entity: str | None = None
    stored_energy_entity: str | None = None
    lifetime_energy_entity: str | None = None
    current_limit_entity: str | None = None
    charge_limit_entity: str | None = None
    charge_switch_entity: str | None = None
    smart_socket_entity: str | None = None
    legacy_charge_to_full_entity: str | None = None
    battery_soc_entity: str | None = None


@dataclass(frozen=True, slots=True)
class EvFeedbackSnapshot:
    """One coherent read of every explicitly mapped EV-related entity."""

    at_home: EvEntityFeedback
    cable_connected: EvEntityFeedback
    charging_state: EvEntityFeedback
    actual_current: EvEntityFeedback
    soc: EvEntityFeedback
    stored_energy: EvEntityFeedback
    lifetime_energy: EvEntityFeedback
    current_limit: EvEntityFeedback
    charge_limit: EvEntityFeedback
    charge_switch: EvEntityFeedback
    smart_socket: EvEntityFeedback
    legacy_charge_to_full: EvEntityFeedback
    battery_soc: EvEntityFeedback

    def for_entity(self, entity_id: str | None) -> EvEntityFeedback | None:
        """Return captured feedback for an explicitly mapped entity ID."""
        if entity_id is None:
            return None
        for feedback in (
            self.at_home,
            self.cable_connected,
            self.charging_state,
            self.actual_current,
            self.soc,
            self.stored_energy,
            self.lifetime_energy,
            self.current_limit,
            self.charge_limit,
            self.charge_switch,
            self.smart_socket,
            self.legacy_charge_to_full,
            self.battery_soc,
        ):
            if feedback.entity_id == entity_id:
                return feedback
        return None

    @property
    def actual_current_result(self) -> tuple[float, bool]:
        """Return the retained state-qualified actual-current observation."""
        charging = self.charging_state.available_state
        if charging is None:
            return 0.0, False
        if charging != "charging":
            return 0.0, True
        value = self.actual_current.current_a
        if value is None or value < 0:
            return 0.0, False
        return value, True

    @property
    def direct_observation(self) -> DirectEvseObservation | None:
        """Return the retained direct-EVSE actuator view when complete."""
        current = self.current_limit
        limit = self.charge_limit
        switch = self.charge_switch.available_state
        required = (
            current.raw_number,
            limit.raw_number,
            current.minimum,
            current.maximum,
            current.step,
            limit.minimum,
            limit.maximum,
            limit.step,
        )
        if switch is None or any(value is None for value in required):
            return None
        return DirectEvseObservation(
            requested_current_a=current.raw_number,  # type: ignore[arg-type]
            charge_limit_percent=limit.raw_number,  # type: ignore[arg-type]
            charge_switch_on=switch == "on",
            current_minimum_a=current.minimum,
            current_maximum_a=current.maximum,
            current_step_a=current.step,
            limit_minimum_percent=limit.minimum,
            limit_maximum_percent=limit.maximum,
            limit_step_percent=limit.step,
        )


def capture_ev_entity_feedback(
    hass: HomeAssistant,
    entity_id: str | None,
) -> EvEntityFeedback:
    """Capture one mapped entity without policy, mutation or service effects."""
    state = hass.states.get(entity_id) if entity_id else None
    reported = state.state if state is not None else None
    available = (
        reported.lower()
        if reported is not None and reported.lower() not in UNKNOWN_STATES
        else None
    )
    raw_number = _raw_number(state)
    number = _finite_number(state)
    current = _current_a(state)
    energy = _energy_kwh(state)
    return EvEntityFeedback(
        entity_id=entity_id,
        present=state is not None,
        reported_state=reported,
        available_state=available,
        raw_number=raw_number,
        number=number,
        current_a=current,
        energy_kwh=energy,
        minimum=_attribute_number(state, "min"),
        maximum=_attribute_number(state, "max"),
        step=_attribute_number(state, "step"),
        unit=(
            state.attributes.get("unit_of_measurement")
            if state is not None
            and isinstance(state.attributes.get("unit_of_measurement"), str)
            else None
        ),
        last_changed=state.last_changed if state is not None else None,
        last_updated=state.last_updated if state is not None else None,
    )


def capture_ev_feedback(
    hass: HomeAssistant,
    entities: EvObservationEntityMap,
) -> EvFeedbackSnapshot:
    """Capture all mapped EV feedback once per unique entity ID."""
    cache: dict[str | None, EvEntityFeedback] = {}

    def capture(entity_id: str | None) -> EvEntityFeedback:
        if entity_id not in cache:
            cache[entity_id] = capture_ev_entity_feedback(hass, entity_id)
        return cache[entity_id]

    return EvFeedbackSnapshot(
        at_home=capture(entities.at_home_entity),
        cable_connected=capture(entities.cable_connected_entity),
        charging_state=capture(entities.charging_state_entity),
        actual_current=capture(entities.actual_current_entity),
        soc=capture(entities.soc_entity),
        stored_energy=capture(entities.stored_energy_entity),
        lifetime_energy=capture(entities.lifetime_energy_entity),
        current_limit=capture(entities.current_limit_entity),
        charge_limit=capture(entities.charge_limit_entity),
        charge_switch=capture(entities.charge_switch_entity),
        smart_socket=capture(entities.smart_socket_entity),
        legacy_charge_to_full=capture(entities.legacy_charge_to_full_entity),
        battery_soc=capture(entities.battery_soc_entity),
    )


def ev_observation_entity_map(
    runtime: RuntimeConfiguration,
) -> EvObservationEntityMap:
    """Build the complete explicit EV observation map from typed runtime config."""
    return EvObservationEntityMap(
        at_home_entity=runtime.ev_connection.at_home_entity,
        cable_connected_entity=runtime.ev_connection.cable_connected_entity,
        charging_state_entity=runtime.ev_telemetry.charging_state_entity,
        actual_current_entity=runtime.ev_telemetry.actual_current_entity,
        soc_entity=runtime.ev_telemetry.soc_entity,
        stored_energy_entity=runtime.ev_telemetry.stored_energy_entity,
        lifetime_energy_entity=runtime.ev_telemetry.lifetime_energy_entity,
        current_limit_entity=runtime.ev_actuators.current_limit_entity,
        charge_limit_entity=runtime.ev_actuators.charge_limit_entity,
        charge_switch_entity=runtime.ev_actuators.charge_switch_entity,
        smart_socket_entity=runtime.ev_actuators.smart_socket_entity,
        legacy_charge_to_full_entity=(
            runtime.ev_preferences.legacy_charge_to_full_entity
        ),
        battery_soc_entity=runtime.battery.soc_entity,
    )


def _raw_number(state: State | None) -> float | None:
    if state is None:
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def _finite_number(state: State | None) -> float | None:
    value = _raw_number(state)
    return value if value is not None and isfinite(value) else None


def _current_a(state: State | None) -> float | None:
    if state is None:
        return None
    try:
        return current_to_a(
            float(state.state),
            state.attributes.get("unit_of_measurement"),
        )
    except (TypeError, ValueError):
        return None


def _energy_kwh(state: State | None) -> float | None:
    if state is None:
        return None
    try:
        value = energy_to_kwh(
            float(state.state),
            state.attributes.get("unit_of_measurement"),
        )
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) and value >= 0 else None


def _attribute_number(state: State | None, key: str) -> float | None:
    if state is None:
        return None
    try:
        return float(state.attributes[key])
    except (KeyError, TypeError, ValueError):
        return None
