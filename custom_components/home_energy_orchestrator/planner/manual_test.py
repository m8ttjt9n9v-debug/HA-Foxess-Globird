"""Preview calculations for the explicit FoxESS commissioning test surface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class ManualTestEstimate:
    """Energy and money estimate shown before a test command is submitted."""

    energy_kwh: float
    amount: float
    rate_per_kwh: float
    direction: str


@dataclass(frozen=True, slots=True)
class ManualTestPersistenceState:
    """Typed representation of one retained manual-test obligation."""

    active_kind: str | None = None
    phase: str = "idle"
    started_at: datetime | None = None
    ends_at: datetime | None = None
    restore_attempts: int = 0
    last_restore_at: datetime | None = None

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, object] | None,
        *,
        maximum_restore_attempts: int,
    ) -> ManualTestPersistenceState:
        """Decode the established Store payload, raising on malformed evidence."""
        if payload is None:
            return cls()
        if payload.get("active_kind") is None:
            if payload.get("phase", "idle") != "idle":
                raise ValueError("inactive manual test must be idle")
            return cls()
        kind = str(payload["active_kind"])
        phase = str(payload["phase"])
        started_at = datetime.fromisoformat(str(payload["started_at"]))
        ends_at = datetime.fromisoformat(str(payload["ends_at"]))
        attempts = int(payload.get("restore_attempts", 0))
        last_raw = payload.get("last_restore_at")
        last_restore_at = datetime.fromisoformat(str(last_raw)) if last_raw else None
        if (
            kind not in {"charge", "discharge"}
            or phase not in {"starting", "running", "stopping", "restore_failed"}
            or started_at.tzinfo is None
            or ends_at.tzinfo is None
            or ends_at < started_at
            or attempts < 0
            or attempts > maximum_restore_attempts
            or last_restore_at is not None
            and last_restore_at.tzinfo is None
        ):
            raise ValueError("invalid manual test state")
        return cls(kind, phase, started_at, ends_at, attempts, last_restore_at)

    def to_payload(self) -> dict[str, object]:
        """Return the unchanged Store payload."""
        return {
            "active_kind": self.active_kind,
            "phase": self.phase,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ends_at": self.ends_at.isoformat() if self.ends_at else None,
            "restore_attempts": self.restore_attempts,
            "last_restore_at": (
                self.last_restore_at.isoformat() if self.last_restore_at else None
            ),
        }


def estimate_charge(
    power_kw: float,
    duration_minutes: float,
    *,
    free_window_active: bool,
    free_energy_remaining_kwh: float,
    offpeak_rate: float,
    offpeak_balance_rate: float,
    current_rate: float,
) -> ManualTestEstimate:
    """Estimate import cost, applying the remaining free-window allowance."""
    energy = _energy(power_kw, duration_minutes)
    _validate_nonnegative(
        free_energy_remaining_kwh,
        offpeak_rate,
        offpeak_balance_rate,
        current_rate,
    )
    if free_window_active:
        free = min(energy, free_energy_remaining_kwh)
        chargeable = max(energy - free, 0.0)
        amount = free * offpeak_rate + chargeable * offpeak_balance_rate
        rate = amount / energy if energy else 0.0
    else:
        amount = energy * current_rate
        rate = current_rate
    return ManualTestEstimate(round(energy, 3), round(amount, 2), round(rate, 4), "cost")


def estimate_discharge(
    power_kw: float,
    duration_minutes: float,
    *,
    export_rate: float,
) -> ManualTestEstimate:
    """Estimate export earnings using the explicitly entered test rate."""
    energy = _energy(power_kw, duration_minutes)
    _validate_nonnegative(export_rate)
    return ManualTestEstimate(
        round(energy, 3), round(energy * export_rate, 2), round(export_rate, 4), "earning"
    )


def _energy(power_kw: float, duration_minutes: float) -> float:
    _validate_nonnegative(power_kw, duration_minutes)
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")
    return power_kw * duration_minutes / 60


def _validate_nonnegative(*values: float) -> None:
    if not all(isfinite(value) for value in values) or any(value < 0 for value in values):
        raise ValueError("manual test values must be finite and non-negative")
