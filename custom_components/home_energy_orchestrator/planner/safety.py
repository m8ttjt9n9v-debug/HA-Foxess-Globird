"""Pure runtime safety-state evaluation for the actuator coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RuntimeState(StrEnum):
    """States visible to operators and used as write interlocks."""

    DISABLED = "disabled"
    OBSERVE = "observe"
    COMMISSIONING = "commissioning"
    READY = "ready"
    AUTOMATIC = "automatic"
    HELD = "held"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    FAULT = "fault"


@dataclass(frozen=True, slots=True)
class SafetyInputs:
    """Evidence required to select a runtime state."""

    automatic_enabled: bool
    commissioning: bool
    telemetry_valid: bool
    external_conflict: bool = False
    recovering: bool = False
    command_failed: bool = False


def evaluate_runtime_state(inputs: SafetyInputs) -> tuple[RuntimeState, str]:
    """Return the highest-priority state and an auditable reason."""
    if inputs.command_failed:
        return RuntimeState.FAULT, "command_failed"
    if inputs.recovering:
        return RuntimeState.RECOVERING, "reconciliation_in_progress"
    if inputs.external_conflict:
        return RuntimeState.HELD, "external_actuator_conflict"
    if inputs.commissioning:
        return RuntimeState.COMMISSIONING, "commissioning_not_complete"
    if not inputs.automatic_enabled:
        return RuntimeState.OBSERVE, "automatic_mode_disabled"
    if not inputs.telemetry_valid:
        return RuntimeState.DEGRADED, "required_telemetry_invalid"
    return RuntimeState.AUTOMATIC, "automatic_inputs_valid"
