"""Read-only Home Assistant boundary for commissioned FoxESS feedback."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from homeassistant.core import HomeAssistant, State

from .foxess_adapter import FoxessEntityMap
from .normalise import power_to_kw
from .planner.foxess import FoxessObservation

INVALID_STATES = frozenset({"unknown", "unavailable"})


@dataclass(frozen=True, slots=True)
class FoxessFeedbackSnapshot:
    """One coherent read of mapped inverter mode and force-power feedback."""

    observation: FoxessObservation | None
    reported_mode: str | None
    mode: str | None
    charge_power_kw: float | None
    discharge_power_kw: float | None
    mode_options: tuple[str, ...]
    charge_power_max_kw: float
    discharge_power_max_kw: float
    mapped_entities_available: bool

    @property
    def manual_observation(self) -> FoxessObservation | None:
        """Return legacy diagnostic feedback without automatic-mode filtering."""
        if (
            not self.mapped_entities_available
            or self.reported_mode is None
            or self.charge_power_kw is None
            or self.discharge_power_kw is None
        ):
            return None
        return FoxessObservation(
            self.reported_mode,
            self.charge_power_kw,
            self.discharge_power_kw,
        )

    @property
    def charge_source_available(self) -> bool:
        """Return whether the mapped mode supports bounded charge control."""
        return {"Self Use", "Force Charge"}.issubset(self.mode_options)

    @property
    def export_source_available(self) -> bool:
        """Return whether the mapped mode supports bounded discharge control."""
        return {"Self Use", "Force Discharge"}.issubset(self.mode_options)


def capture_foxess_feedback(
    hass: HomeAssistant,
    entities: FoxessEntityMap,
) -> FoxessFeedbackSnapshot:
    """Capture mapped FoxESS feedback without policy or service side effects."""
    mode_state = hass.states.get(entities.work_mode_entity)
    charge_state = hass.states.get(entities.force_charge_power_entity)
    discharge_state = hass.states.get(entities.force_discharge_power_entity)
    mode = _available_state(mode_state)
    charge_power_kw = _power_state_kw(charge_state)
    discharge_power_kw = _power_state_kw(discharge_state)
    observation = (
        FoxessObservation(mode, charge_power_kw, discharge_power_kw)
        if mode is not None
        and charge_power_kw is not None
        and discharge_power_kw is not None
        else None
    )
    return FoxessFeedbackSnapshot(
        observation=observation,
        reported_mode=mode_state.state if mode_state is not None else None,
        mode=mode,
        charge_power_kw=charge_power_kw,
        discharge_power_kw=discharge_power_kw,
        mode_options=_mode_options(mode_state),
        charge_power_max_kw=_power_max_kw(charge_state),
        discharge_power_max_kw=_power_max_kw(discharge_state),
        mapped_entities_available=all(
            state is not None for state in (mode_state, charge_state, discharge_state)
        ),
    )


def _available_state(state: State | None) -> str | None:
    if state is None or state.state in INVALID_STATES:
        return None
    return state.state


def _mode_options(state: State | None) -> tuple[str, ...]:
    if state is None:
        return ()
    options = state.attributes.get("options")
    if not isinstance(options, (list, tuple)):
        return ()
    return tuple(option for option in options if isinstance(option, str))


def _power_state_kw(state: State | None) -> float | None:
    if state is None or state.state in INVALID_STATES:
        return None
    try:
        value = power_to_kw(
            float(state.state),
            state.attributes.get("unit_of_measurement"),
        )
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) and value >= 0 else None


def _power_max_kw(state: State | None) -> float:
    if state is None:
        return 0.0
    try:
        value = power_to_kw(
            float(state.attributes.get("max", 0.0)),
            state.attributes.get("unit_of_measurement"),
        )
    except (TypeError, ValueError):
        return 0.0
    return value if isfinite(value) and value >= 0 else 0.0
