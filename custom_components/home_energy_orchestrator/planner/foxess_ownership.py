"""Pure retained-ownership evaluation for FoxESS forced modes."""

from __future__ import annotations

from dataclasses import dataclass

_OWNED_PHASES = frozenset({"starting", "active", "stopping", "recovering"})
_DEGRADED_STORAGE = frozenset({"missing", "malformed", "not_loaded"})


@dataclass(frozen=True, slots=True)
class FoxessOwnershipContext:
    """Evidence used to decide whether a forced inverter mode is trustworthy."""

    mode: str
    charge_phase: str
    export_phase: str
    charge_storage_status: str
    export_storage_status: str
    manual_present: bool
    manual_active: bool
    manual_kind: str | None
    manual_storage_status: str


@dataclass(frozen=True, slots=True)
class FoxessOwnershipResult:
    """Ownership decision plus explicit facade obligations."""

    status: str
    hold: bool = False
    reset_sessions: bool = False
    checkpoint_manual_idle: bool = False
    reason: str | None = None
    clear_actions: bool = False


def evaluate_foxess_ownership(
    context: FoxessOwnershipContext,
) -> FoxessOwnershipResult:
    """Evaluate the retained controller's ownership rules exactly."""
    degraded = any(
        status in _DEGRADED_STORAGE
        for status in (
            context.charge_storage_status,
            context.export_storage_status,
            context.manual_storage_status,
        )
    )
    charge_owned = context.charge_phase in _OWNED_PHASES
    export_owned = context.export_phase in _OWNED_PHASES
    manual_kind_for_mode = {
        "Force Charge": "charge",
        "Force Discharge": "discharge",
    }.get(context.mode)
    manual_owned = (
        context.manual_present
        and context.manual_active
        and context.manual_kind == manual_kind_for_mode
    )
    matching_owner = (
        context.mode == "Force Charge"
        and charge_owned
        or context.mode == "Force Discharge"
        and export_owned
        or manual_owned
    )
    if matching_owner:
        return FoxessOwnershipResult("verified_session")
    if context.mode == "Self Use" and (
        charge_owned or export_owned or manual_owned
    ):
        return FoxessOwnershipResult("verified_session")
    if context.mode == "Self Use":
        if degraded:
            return FoxessOwnershipResult(
                "verified_safe_mode",
                reset_sessions=True,
                checkpoint_manual_idle=context.manual_present,
                reason="ownership_reestablished_self_use",
                clear_actions=True,
            )
        return FoxessOwnershipResult("verified")
    if degraded:
        return FoxessOwnershipResult(
            "ownership_unknown",
            hold=True,
            reason="ownership_unknown",
            clear_actions=True,
        )
    return FoxessOwnershipResult(
        "verified_external_owner",
        hold=True,
        reason="external_forced_mode",
        clear_actions=True,
    )
