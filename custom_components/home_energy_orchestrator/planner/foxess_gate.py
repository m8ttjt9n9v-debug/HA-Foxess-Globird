"""Pure absolute-gate evaluation for automatic FoxESS control."""

from __future__ import annotations

from dataclasses import dataclass

from ..const import FOXESS_CONTROL_OWNER_CLOUD, FOXESS_CONTROL_OWNER_MODBUS


@dataclass(frozen=True, slots=True)
class FoxessGateContext:
    """Inputs evaluated before automatic control may observe or command hardware."""

    manual_test_active: bool
    control_owner: str
    master_enabled: bool
    safety_lock: bool
    electrical_verified: bool
    actuator_mapping_complete: bool
    telemetry_available: bool


@dataclass(frozen=True, slots=True)
class FoxessGateResult:
    """Legacy-compatible outcome of the absolute automatic-control gates."""

    reason: str | None = None
    clear_actions: bool = False
    warn_incomplete_mapping: bool = False

    @property
    def blocked(self) -> bool:
        """Return whether reconciliation must stop at this gate."""
        return self.reason is not None


def evaluate_foxess_gate(context: FoxessGateContext) -> FoxessGateResult:
    """Evaluate absolute gates in their established precedence order."""
    if context.manual_test_active:
        return FoxessGateResult("manual_test_active", clear_actions=True)
    if context.control_owner == FOXESS_CONTROL_OWNER_CLOUD:
        return FoxessGateResult(
            "foxcloud_scheduler_owns_inverter",
            clear_actions=True,
        )
    if context.control_owner != FOXESS_CONTROL_OWNER_MODBUS:
        return FoxessGateResult("foxess_observer_owner", clear_actions=True)
    if not context.master_enabled:
        return FoxessGateResult("automatic_control_disabled")
    if context.safety_lock:
        return FoxessGateResult("rehearsal_mode")
    if not context.electrical_verified:
        return FoxessGateResult("sign_conventions_unverified")
    if not context.actuator_mapping_complete:
        return FoxessGateResult(
            "incomplete_foxess_mapping",
            warn_incomplete_mapping=True,
        )
    if not context.telemetry_available:
        return FoxessGateResult("telemetry_unavailable")
    return FoxessGateResult()
