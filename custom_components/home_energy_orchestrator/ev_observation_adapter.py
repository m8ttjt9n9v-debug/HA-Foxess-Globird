"""Read-only Home Assistant boundary for mapped EV entity feedback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from homeassistant.core import HomeAssistant, State

from .normalise import current_to_a, energy_to_kwh

UNKNOWN_STATES = frozenset({"unknown", "unavailable"})


@dataclass(frozen=True, slots=True)
class EvEntityFeedback:
    """One immutable read of a mapped Home Assistant entity."""

    entity_id: str | None
    present: bool
    reported_state: str | None
    available_state: str | None
    number: float | None
    current_a: float | None
    energy_kwh: float | None
    minimum: float | None
    maximum: float | None
    step: float | None
    unit: str | None
    last_changed: datetime | None
    last_updated: datetime | None


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
    number = _finite_number(state)
    current = _current_a(state)
    energy = _energy_kwh(state)
    return EvEntityFeedback(
        entity_id=entity_id,
        present=state is not None,
        reported_state=reported,
        available_state=available,
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


def _finite_number(state: State | None) -> float | None:
    if state is None:
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


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
