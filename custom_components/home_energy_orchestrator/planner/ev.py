"""Pure EV charge-to-target planning primitives.

The planner contains no Home Assistant calls. An eventual integration adapter
must map the returned commands to the explicitly commissioned EV number and
switch entities, then verify the resulting state.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class EvObservation:
    """Current vehicle connection, SoC, and charge-limit bounds."""

    soc_percent: float | None
    cable_connected: bool
    limit_min_percent: float | None
    limit_max_percent: float | None


@dataclass(frozen=True, slots=True)
class EvCommand:
    """One adapter-neutral EV command."""

    action: str
    value: float | None = None


@dataclass(frozen=True, slots=True)
class EvCommandPlan:
    """An ordered EV command sequence with an auditable reason."""

    commands: tuple[EvCommand, ...]
    reason: str


def plan_ev_start(target_soc_percent: float, observation: EvObservation) -> EvCommandPlan:
    """Plan a guarded charge-to-target start.

    A disconnected vehicle, unknown SoC, malformed limits, or a target above
    the mapped entity's maximum produces a no-op. The number limit is written
    before the charge switch is turned on. A target below the entity minimum
    is allowed: the independent stop-at-target guard still enforces the
    requested target (for example, a 40% target with a 50% Tessie minimum).
    """

    _validate_target(target_soc_percent)
    soc = _finite_percent(observation.soc_percent, "soc_percent")
    minimum = _finite_percent(observation.limit_min_percent, "limit_min_percent")
    maximum = _finite_percent(observation.limit_max_percent, "limit_max_percent")
    if minimum is None or maximum is None:
        return EvCommandPlan((), "charge_limit_bounds_unknown")
    if minimum > maximum:
        return EvCommandPlan((), "charge_limit_bounds_invalid")
    if not observation.cable_connected:
        return EvCommandPlan((), "disconnected")
    if soc is None:
        return EvCommandPlan((), "soc_unknown")
    if soc >= target_soc_percent:
        return EvCommandPlan((), "target_reached")
    if target_soc_percent > maximum:
        return EvCommandPlan((), "target_exceeds_charge_limit")

    effective_limit = max(target_soc_percent, minimum)
    return EvCommandPlan(
        (
            EvCommand("set_charge_limit", round(effective_limit, 3)),
            EvCommand("turn_on_charge"),
        ),
        "ready",
    )


def plan_ev_stop(observation: EvObservation, *, reason: str = "manual_stop") -> EvCommandPlan:
    """Plan a safe stop; stopping remains valid even if the cable is removed."""

    _finite_percent(observation.soc_percent, "soc_percent")
    _finite_percent(observation.limit_min_percent, "limit_min_percent")
    _finite_percent(observation.limit_max_percent, "limit_max_percent")
    return EvCommandPlan((EvCommand("turn_off_charge"),), reason)


def ev_charge_should_stop(
    target_soc_percent: float,
    *,
    soc_percent: float | None,
    cable_connected: bool,
    armed: bool,
) -> bool:
    """Return whether an armed session must be stopped now."""

    _validate_target(target_soc_percent)
    if not armed or not cable_connected:
        return bool(armed and not cable_connected)
    soc = _finite_percent(soc_percent, "soc_percent")
    return soc is not None and soc >= target_soc_percent


def _validate_target(value: float) -> None:
    if not isfinite(value) or not 0 <= value <= 100:
        raise ValueError("target_soc_percent must be finite and between 0 and 100")


def _finite_percent(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    if not isfinite(value) or not 0 <= value <= 100:
        raise ValueError(f"{name} must be finite and between 0 and 100")
    return value
