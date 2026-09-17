"""Typed codec for the established composite EV controller Store payload."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite

from .ev import (
    DIRECT_EVSE_MAX_ATTEMPTS,
    DIRECT_EVSE_RECONCILIATION_PHASES,
    DirectEvseReconciliationState,
    SmartSocketRecoveryState,
)
from .ev_learning import DrivingSnapshotState
from .ev_outside_window import PreFreeSessionState
from .learning import DemandHistory


@dataclass(frozen=True, slots=True)
class DailyBackfillPersistenceState:
    """Restart-safe daily EV backfill state."""

    cycle_ready_at: datetime | None = None
    delivered_kwh: float = 0.0
    active: bool = False
    session_target_kwh: float = 0.0
    session_start_delivered_kwh: float = 0.0
    frozen_start: datetime | None = None
    stop_pending: bool = False
    stop_attempts: int = 0
    last_stop_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EvPersistenceState:
    """Typed representation of the existing EV controller payload."""

    restored_at: datetime
    grid_average_payload: object = None
    ev_average_payload: object = None
    driving_history: DemandHistory = field(default_factory=lambda: DemandHistory([]))
    driving_snapshot: DrivingSnapshotState = field(default_factory=DrivingSnapshotState)
    daily_driving_energy_kwh: float | None = None
    reconciliation: DirectEvseReconciliationState = field(
        default_factory=DirectEvseReconciliationState
    )
    pre_free_session: PreFreeSessionState = field(default_factory=PreFreeSessionState)
    daily_backfill: DailyBackfillPersistenceState = field(
        default_factory=DailyBackfillPersistenceState
    )
    charge_to_full_started_at: datetime | None = None
    outside_control_active: bool = False
    smart_recovery: SmartSocketRecoveryState = field(
        default_factory=SmartSocketRecoveryState
    )

    @classmethod
    def from_payload(
        cls, payload: dict[str, object] | None, now: datetime
    ) -> EvPersistenceState:
        """Decode valid evidence while retaining the controller's fallback groups."""
        mapping = payload or {}
        driving_history = DemandHistory.from_payload(mapping.get("driving_history"), now)
        driving_snapshot = DrivingSnapshotState()
        daily_driving: float | None = None
        snapshot = mapping.get("driving_snapshot")
        if isinstance(snapshot, dict):
            try:
                date_raw = snapshot.get("snapshot_date")
                snapshot_date = (
                    datetime.fromisoformat(str(date_raw)).date() if date_raw else None
                )
                lifetime_raw = snapshot.get("lifetime_energy_kwh")
                lifetime = float(lifetime_raw) if lifetime_raw is not None else None
                if (
                    snapshot_date is not None
                    and snapshot_date > now.date()
                    or lifetime is not None
                    and (not isfinite(lifetime) or lifetime < 0)
                ):
                    raise ValueError
                driving_snapshot = DrivingSnapshotState(snapshot_date, lifetime)
                daily_raw = mapping.get("daily_driving_energy_kwh")
                daily_driving = float(daily_raw) if daily_raw is not None else None
                if daily_driving is not None and (
                    not isfinite(daily_driving) or daily_driving < 0
                ):
                    raise ValueError
            except (TypeError, ValueError):
                driving_snapshot = DrivingSnapshotState()
                daily_driving = None

        reconciliation = DirectEvseReconciliationState()
        pre_free_session = PreFreeSessionState()
        daily_backfill = DailyBackfillPersistenceState()
        charge_to_full_started_at = None
        outside_control_active = False
        smart_recovery = SmartSocketRecoveryState()
        try:
            reconciliation = _reconciliation(mapping.get("reconciliation"), now)
            pre_free_session = _pre_free(mapping.get("pre_free_session"), now)
            daily_backfill = _daily_backfill(mapping.get("daily_backfill"), now)
            charge_raw = mapping.get("charge_to_full_started_at")
            charge_to_full_started_at = (
                datetime.fromisoformat(str(charge_raw)) if charge_raw else None
            )
            if charge_to_full_started_at is not None and (
                charge_to_full_started_at.tzinfo is None
                or charge_to_full_started_at > now
            ):
                raise ValueError
            outside_control_active = bool(mapping.get("outside_control_active", False))
            smart_recovery = _smart_recovery(mapping.get("smart_recovery"), now)
        except (KeyError, TypeError, ValueError):
            reconciliation = DirectEvseReconciliationState()
            pre_free_session = PreFreeSessionState()
            daily_backfill = DailyBackfillPersistenceState()
            charge_to_full_started_at = None
            outside_control_active = False
            smart_recovery = SmartSocketRecoveryState()

        return cls(
            restored_at=now,
            grid_average_payload=mapping.get("grid_average"),
            ev_average_payload=mapping.get("ev_average"),
            driving_history=driving_history,
            driving_snapshot=driving_snapshot,
            daily_driving_energy_kwh=daily_driving,
            reconciliation=reconciliation,
            pre_free_session=pre_free_session,
            daily_backfill=daily_backfill,
            charge_to_full_started_at=charge_to_full_started_at,
            outside_control_active=outside_control_active,
            smart_recovery=smart_recovery,
        )

    def to_payload(self) -> dict[str, object]:
        """Return the unchanged composite Store payload."""
        reconciliation = self.reconciliation
        daily = self.daily_backfill
        recovery = self.smart_recovery
        return {
            "grid_average": self.grid_average_payload,
            "ev_average": self.ev_average_payload,
            "driving_history": self.driving_history.to_payload(),
            "driving_snapshot": {
                "snapshot_date": (
                    self.driving_snapshot.snapshot_date.isoformat()
                    if self.driving_snapshot.snapshot_date is not None
                    else None
                ),
                "lifetime_energy_kwh": self.driving_snapshot.lifetime_energy_kwh,
            },
            "daily_driving_energy_kwh": self.daily_driving_energy_kwh,
            "reconciliation": {
                "target_current_a": reconciliation.target_current_a,
                "target_limit_percent": reconciliation.target_limit_percent,
                "attempts": reconciliation.attempts,
                "last_command_at": (
                    reconciliation.last_command_at.isoformat()
                    if reconciliation.last_command_at is not None
                    else None
                ),
                "phase": reconciliation.phase,
            },
            "pre_free_session": {
                "active": self.pre_free_session.active,
                "frozen_start": (
                    self.pre_free_session.frozen_start.isoformat()
                    if self.pre_free_session.frozen_start is not None
                    else None
                ),
            },
            "daily_backfill": {
                "cycle_ready_at": (
                    daily.cycle_ready_at.isoformat()
                    if daily.cycle_ready_at is not None
                    else None
                ),
                "delivered_kwh": round(daily.delivered_kwh, 6),
                "active": daily.active,
                "session_target_kwh": daily.session_target_kwh,
                "session_start_delivered_kwh": daily.session_start_delivered_kwh,
                "frozen_start": (
                    daily.frozen_start.isoformat() if daily.frozen_start is not None else None
                ),
                "stop_pending": daily.stop_pending,
                "stop_attempts": daily.stop_attempts,
                "last_stop_at": (
                    daily.last_stop_at.isoformat() if daily.last_stop_at is not None else None
                ),
            },
            "charge_to_full_started_at": (
                self.charge_to_full_started_at.isoformat()
                if self.charge_to_full_started_at is not None
                else None
            ),
            "outside_control_active": self.outside_control_active,
            "smart_recovery": {
                "attempted": recovery.attempted,
                "phase": recovery.phase,
                "phase_started_at": (
                    recovery.phase_started_at.isoformat()
                    if recovery.phase_started_at is not None
                    else None
                ),
                "recovery_current_a": recovery.recovery_current_a,
            },
        }


def _reconciliation(payload: object, now: datetime) -> DirectEvseReconciliationState:
    if not isinstance(payload, dict):
        raise ValueError
    last_raw = payload.get("last_command_at")
    last_at = datetime.fromisoformat(str(last_raw)) if last_raw else None
    attempts = int(payload.get("attempts", 0))
    target_current = (
        float(payload["target_current_a"])
        if payload.get("target_current_a") is not None
        else None
    )
    target_limit = (
        float(payload["target_limit_percent"])
        if payload.get("target_limit_percent") is not None
        else None
    )
    phase = str(payload.get("phase", "idle"))
    if (
        attempts < 0
        or attempts > DIRECT_EVSE_MAX_ATTEMPTS
        or last_at is not None
        and last_at > now
        or target_current is not None
        and (not isfinite(target_current) or target_current < 0)
        or target_limit is not None
        and (not isfinite(target_limit) or target_limit < 0)
        or phase not in DIRECT_EVSE_RECONCILIATION_PHASES
    ):
        raise ValueError
    return DirectEvseReconciliationState(
        target_current_a=target_current,
        target_limit_percent=target_limit,
        attempts=attempts,
        last_command_at=last_at,
        phase=phase,
    )


def _pre_free(payload: object, now: datetime) -> PreFreeSessionState:
    if not isinstance(payload, dict):
        raise ValueError
    frozen_raw = payload.get("frozen_start")
    frozen = datetime.fromisoformat(str(frozen_raw)) if frozen_raw else None
    active = bool(payload.get("active", False))
    if frozen is not None and (frozen.tzinfo is None or frozen > now):
        raise ValueError
    if active != (frozen is not None):
        raise ValueError
    return PreFreeSessionState(active=active, frozen_start=frozen)


def _daily_backfill(payload: object, now: datetime) -> DailyBackfillPersistenceState:
    if not isinstance(payload, dict):
        raise ValueError
    cycle_raw = payload.get("cycle_ready_at")
    cycle_ready_at = datetime.fromisoformat(str(cycle_raw)) if cycle_raw else None
    frozen_raw = payload.get("frozen_start")
    frozen = datetime.fromisoformat(str(frozen_raw)) if frozen_raw else None
    delivered = float(payload.get("delivered_kwh", 0.0))
    target = float(payload.get("session_target_kwh", 0.0))
    session_start = float(payload.get("session_start_delivered_kwh", 0.0))
    active = bool(payload.get("active", False))
    attempts = int(payload.get("stop_attempts", 0))
    last_raw = payload.get("last_stop_at")
    last_stop = datetime.fromisoformat(str(last_raw)) if last_raw else None
    if (
        any(not isfinite(value) or value < 0 for value in (delivered, target, session_start))
        or cycle_ready_at is not None
        and cycle_ready_at.tzinfo is None
        or frozen is not None
        and frozen.tzinfo is None
        or active != (frozen is not None)
        or not 0 <= attempts <= DIRECT_EVSE_MAX_ATTEMPTS
        or last_stop is not None
        and (last_stop.tzinfo is None or last_stop > now)
    ):
        raise ValueError
    return DailyBackfillPersistenceState(
        cycle_ready_at=cycle_ready_at,
        delivered_kwh=delivered,
        active=active,
        session_target_kwh=target,
        session_start_delivered_kwh=session_start,
        frozen_start=frozen,
        stop_pending=bool(payload.get("stop_pending", False)),
        stop_attempts=attempts,
        last_stop_at=last_stop,
    )


def _smart_recovery(payload: object, now: datetime) -> SmartSocketRecoveryState:
    if not isinstance(payload, dict):
        raise ValueError
    started_raw = payload.get("phase_started_at")
    started = datetime.fromisoformat(str(started_raw)) if started_raw else None
    current = (
        float(payload["recovery_current_a"])
        if payload.get("recovery_current_a") is not None
        else None
    )
    phase = str(payload.get("phase", "idle"))
    if (
        phase
        not in {
            "idle",
            "confirming_current",
            "confirming_socket_off",
            "power_off_dwell",
            "confirming_socket_on",
            "post_power_settle",
            "awaiting_actuator",
            "confirming_charging",
            "recovered",
            "fault",
        }
        or started is not None
        and (started.tzinfo is None or started > now)
        or current is not None
        and (not isfinite(current) or current < 0)
    ):
        raise ValueError
    return SmartSocketRecoveryState(
        attempted=bool(payload.get("attempted", False)),
        phase=phase,
        phase_started_at=started,
        recovery_current_a=current,
    )
