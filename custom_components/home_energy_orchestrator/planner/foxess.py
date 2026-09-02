"""Pure FoxESS actuator planning and response verification.

The planner describes an ordered command sequence but never calls a Home
Assistant service. The eventual adapter is responsible for mapping each
command to explicitly commissioned entity IDs and for reporting failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose, isfinite

from .control import ControlDecision


@dataclass(frozen=True, slots=True)
class FoxessObservation:
    """Current FoxESS mode and force-power feedback."""

    mode: str
    charge_power_kw: float
    discharge_power_kw: float


@dataclass(frozen=True, slots=True)
class FoxessCommand:
    """One ordered, adapter-neutral FoxESS command."""

    action: str
    value: float | str | None = None
    wait_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class FoxessCommandPlan:
    """An idempotent command sequence with an auditable reason."""

    commands: tuple[FoxessCommand, ...]
    reason: str


def plan_foxess_commands(
    decision: ControlDecision,
    observation: FoxessObservation,
    *,
    rehearsal: bool = False,
    charge_power_max_kw: float,
    discharge_power_max_kw: float,
    response_tolerance_kw: float = 0.01,
) -> FoxessCommandPlan:
    """Translate one guarded decision into bounded, ordered commands."""
    _validate_observation(observation)
    _validate_limit(charge_power_max_kw, "charge_power_max_kw")
    _validate_limit(discharge_power_max_kw, "discharge_power_max_kw")
    _validate_limit(response_tolerance_kw, "response_tolerance_kw")

    # Rehearsal is an absolute no-write interlock. This remains true even when
    # the decision asks for recovery from a forced mode.
    if rehearsal or decision.reason == "rehearsal_mode":
        return FoxessCommandPlan((), "rehearsal_mode")

    if decision.action == "hold":
        return FoxessCommandPlan((), decision.reason)
    if decision.action == "force_charge":
        power = _bounded(decision.power_kw, charge_power_max_kw)
        commands: list[FoxessCommand] = []
        if not _same_power(observation.discharge_power_kw, 0.0, response_tolerance_kw):
            commands.append(FoxessCommand("set_discharge_power", 0.0))
        if not _same_power(observation.charge_power_kw, power, response_tolerance_kw):
            commands.append(FoxessCommand("set_charge_power", power))
        if observation.mode != "Force Charge":
            commands.append(FoxessCommand("select_mode", "Force Charge"))
        return FoxessCommandPlan(tuple(commands), decision.reason)
    if decision.action == "force_discharge":
        power = _bounded(decision.power_kw, discharge_power_max_kw)
        commands = []
        if not _same_power(observation.charge_power_kw, 0.0, response_tolerance_kw):
            commands.append(FoxessCommand("set_charge_power", 0.0))
        if not _same_power(observation.discharge_power_kw, power, response_tolerance_kw):
            commands.append(FoxessCommand("set_discharge_power", power))
        if observation.mode != "Force Discharge":
            commands.append(FoxessCommand("select_mode", "Force Discharge"))
        return FoxessCommandPlan(tuple(commands), decision.reason)
    if decision.action == "restore_self_use":
        commands = []
        if observation.mode != "Self Use":
            commands.append(FoxessCommand("select_mode", "Self Use", wait_seconds=5.0))
        if not _same_power(observation.charge_power_kw, 0.0, response_tolerance_kw):
            commands.append(FoxessCommand("set_charge_power", 0.0))
        if not _same_power(observation.discharge_power_kw, 0.0, response_tolerance_kw):
            commands.append(FoxessCommand("set_discharge_power", 0.0))
        return FoxessCommandPlan(tuple(commands), decision.reason)
    raise ValueError(f"unsupported FoxESS action: {decision.action}")


def foxess_response_matches(
    decision: ControlDecision,
    observation: FoxessObservation,
    *,
    tolerance_kw: float = 0.01,
) -> bool:
    """Return whether measured feedback matches a requested intent."""
    _validate_observation(observation)
    _validate_limit(tolerance_kw, "tolerance_kw")
    if decision.action == "force_charge":
        return (
            observation.mode == "Force Charge"
            and _same_power(observation.charge_power_kw, decision.power_kw, tolerance_kw)
            and _same_power(observation.discharge_power_kw, 0.0, tolerance_kw)
        )
    if decision.action == "force_discharge":
        return (
            observation.mode == "Force Discharge"
            and _same_power(observation.discharge_power_kw, decision.power_kw, tolerance_kw)
            and _same_power(observation.charge_power_kw, 0.0, tolerance_kw)
        )
    if decision.action == "restore_self_use":
        return (
            observation.mode == "Self Use"
            and _same_power(observation.charge_power_kw, 0.0, tolerance_kw)
            and _same_power(observation.discharge_power_kw, 0.0, tolerance_kw)
        )
    return decision.action == "hold"


def _validate_observation(observation: FoxessObservation) -> None:
    if not observation.mode:
        raise ValueError("mode must be non-empty")
    if not isfinite(observation.charge_power_kw) or observation.charge_power_kw < 0:
        raise ValueError("charge_power_kw must be finite and non-negative")
    if not isfinite(observation.discharge_power_kw) or observation.discharge_power_kw < 0:
        raise ValueError("discharge_power_kw must be finite and non-negative")


def _validate_limit(value: float, name: str) -> None:
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")


def _bounded(requested: float, maximum: float) -> float:
    if not isfinite(requested) or requested < 0:
        raise ValueError("requested power must be finite and non-negative")
    return round(min(requested, maximum), 3)


def _same_power(actual: float, expected: float, tolerance: float) -> bool:
    return isclose(actual, expected, abs_tol=tolerance, rel_tol=0.0)
