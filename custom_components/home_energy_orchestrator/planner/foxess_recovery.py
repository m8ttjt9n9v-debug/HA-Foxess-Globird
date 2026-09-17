"""Pure recovery planning when FoxESS actuator feedback is unavailable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .charge_session import ChargeSessionState
from .export_session import ExportSessionState

_CHARGE_RECOVERY_PHASES = frozenset(
    {"starting", "active", "stopping", "recovering"}
)


@dataclass(frozen=True, slots=True)
class FoxessSourceUnavailableResult:
    """Next retained sessions and their exact persistence obligations."""

    charge_session: ChargeSessionState
    export_session: ExportSessionState
    save_charge: bool
    save_export: bool


def mark_foxess_source_unavailable(
    charge_session: ChargeSessionState,
    export_session: ExportSessionState,
    now: datetime,
) -> FoxessSourceUnavailableResult:
    """Return the legacy recovery states without performing storage effects."""
    save_charge = charge_session.phase in _CHARGE_RECOVERY_PHASES
    next_charge = (
        ChargeSessionState(
            "recovering",
            charge_session.requested_power_kw,
            charge_session.attempts,
            charge_session.last_command_at or now,
        )
        if save_charge
        else charge_session
    )
    save_export = export_session.phase != "idle"
    next_export = (
        ExportSessionState(
            "recovering",
            export_session.requested_power_kw,
            export_session.attempts,
            export_session.last_command_at or now,
        )
        if save_export
        else export_session
    )
    return FoxessSourceUnavailableResult(
        next_charge,
        next_export,
        save_charge,
        save_export,
    )
