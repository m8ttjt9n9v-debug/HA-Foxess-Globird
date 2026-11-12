"""Typed codec for the established composite EV controller Store payload."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from math import isfinite

from .ev import (
    DIRECT_EVSE_FEEDBACK_SETTLE_INTERVAL,
    DIRECT_EVSE_RECONCILIATION_PHASES,
    DirectEvseCurrentProof,
    DirectEvseReconciliationState,
    DirectEvseRetryState,
    SmartSocketRecoveryState,
)
from .ev_before_export import EvBeforeExportImport, EvBeforeExportRecovery
from .ev_learning import DrivingSnapshotState
from .ev_outside_window import MeasuredSolarAdjustmentState, PreFreeSessionState
from .learning import DemandHistory

_MAX_RESERVATION_BINDING_PARTS = 8
_MAX_RESERVATION_BINDING_PART_LENGTH = 256


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
class EvReservationSocRecord:
    """The last verified SoC and original measurement time for one vehicle."""

    value_percent: float
    observed_at: datetime
    binding: tuple[str, ...]

    def valid_at(self, now: datetime) -> bool:
        """Validate the journal record without granting live telemetry authority."""
        if not (
            type(self.value_percent) in (int, float)
            and 0 <= self.value_percent <= 100
            and isinstance(self.observed_at, datetime)
            and self.observed_at.utcoffset() is not None
            and now.utcoffset() is not None
            and isinstance(self.binding, tuple)
            and 0 < len(self.binding) <= _MAX_RESERVATION_BINDING_PARTS
            and all(
                isinstance(part, str) and len(part) <= _MAX_RESERVATION_BINDING_PART_LENGTH
                and part.strip()
                for part in self.binding
            )
        ):
            return False
        try:
            return self.observed_at.astimezone(UTC) <= now.astimezone(UTC)
        except (OverflowError, ValueError):
            return False


@dataclass(frozen=True, slots=True)
class EvPersistenceState:
    """Typed representation of the existing EV controller payload."""

    restored_at: datetime
    grid_average_payload: object = None
    ev_average_payload: object = None
    solar_soak_average_payload: object = None
    driving_history: DemandHistory = field(default_factory=lambda: DemandHistory([]))
    driving_snapshot: DrivingSnapshotState = field(default_factory=DrivingSnapshotState)
    daily_driving_energy_kwh: float | None = None
    reconciliation: DirectEvseReconciliationState = field(
        default_factory=DirectEvseReconciliationState
    )
    pre_free_session: PreFreeSessionState = field(default_factory=PreFreeSessionState)
    measured_solar_adjustment: MeasuredSolarAdjustmentState = field(
        default_factory=MeasuredSolarAdjustmentState
    )
    daily_backfill: DailyBackfillPersistenceState = field(
        default_factory=DailyBackfillPersistenceState
    )
    charge_to_full_started_at: datetime | None = None
    outside_control_active: bool = False
    when_connected_owned: bool = False
    before_export_recovery: EvBeforeExportRecovery = field(default_factory=EvBeforeExportRecovery)
    before_export_import: EvBeforeExportImport = field(default_factory=EvBeforeExportImport)
    smart_recovery: SmartSocketRecoveryState = field(
        default_factory=SmartSocketRecoveryState
    )
    reservation_soc: EvReservationSocRecord | None = None

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
        measured_solar_adjustment = MeasuredSolarAdjustmentState()
        daily_backfill = DailyBackfillPersistenceState()
        charge_to_full_started_at = None
        outside_control_active = False
        smart_recovery = SmartSocketRecoveryState()
        try:
            reconciliation = _reconciliation(mapping.get("reconciliation"), now)
            pre_free_session = _pre_free(mapping.get("pre_free_session"), now)
            measured_solar_adjustment = _measured_solar_adjustment(
                mapping.get("measured_solar_adjustment"), now
            )
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
            measured_solar_adjustment = MeasuredSolarAdjustmentState()
            daily_backfill = DailyBackfillPersistenceState()
            charge_to_full_started_at = None
            outside_control_active = False
            smart_recovery = SmartSocketRecoveryState()

        return cls(
            restored_at=now,
            grid_average_payload=mapping.get("grid_average"),
            ev_average_payload=mapping.get("ev_average"),
            solar_soak_average_payload=mapping.get("solar_soak_average"),
            driving_history=driving_history,
            driving_snapshot=driving_snapshot,
            daily_driving_energy_kwh=daily_driving,
            reconciliation=reconciliation,
            pre_free_session=pre_free_session,
            measured_solar_adjustment=measured_solar_adjustment,
            daily_backfill=daily_backfill,
            charge_to_full_started_at=charge_to_full_started_at,
            outside_control_active=outside_control_active,
            # An invalid optional owner must retain cleanup, never prove it
            # completed. Earlier releases simply ignore this additive field.
            when_connected_owned=(mapping.get("when_connected_owned", False) is not False),
            before_export_recovery=(
                _before_export_recovery(mapping['before_export_recovery'])
                if 'before_export_recovery' in mapping else EvBeforeExportRecovery()
            ),
            smart_recovery=smart_recovery,
            before_export_import=_before_export_import(mapping.get("before_export_import"), now),
            reservation_soc=_reservation_soc(mapping.get("reservation_soc"), now),
        )

    def to_payload(self) -> dict[str, object]:
        """Retain the composite Store and append only qualified optional evidence."""
        reconciliation = self.reconciliation
        daily = self.daily_backfill
        recovery = self.smart_recovery
        reservation_soc = self.reservation_soc
        return {
            "grid_average": self.grid_average_payload,
            "ev_average": self.ev_average_payload,
            **({"solar_soak_average": self.solar_soak_average_payload}
               if self.solar_soak_average_payload is not None else {}),
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
                **_retry_channels_payload(reconciliation),
            },
            "pre_free_session": {
                "active": self.pre_free_session.active,
                "frozen_start": (
                    self.pre_free_session.frozen_start.isoformat()
                    if self.pre_free_session.frozen_start is not None
                    else None
                ),
            },
            "measured_solar_adjustment": {
                "phase": self.measured_solar_adjustment.phase,
                "target_current_a": self.measured_solar_adjustment.target_current_a,
                "changed_at": (
                    self.measured_solar_adjustment.changed_at.isoformat()
                    if self.measured_solar_adjustment.changed_at is not None
                    else None
                ),
                "pending_current_a": (
                    self.measured_solar_adjustment.pending_current_a
                ),
                "pending_since": (
                    self.measured_solar_adjustment.pending_since.isoformat()
                    if self.measured_solar_adjustment.pending_since is not None
                    else None
                ),
                **(
                    {"battery_current_a": self.measured_solar_adjustment.battery_current_a}
                    if self.measured_solar_adjustment.battery_current_a is not None
                    else {}
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
            **({"when_connected_owned": True} if self.when_connected_owned else {}),
            **({"before_export_import": {
                "since": self.before_export_import.since.isoformat()
                if self.before_export_import.since else None,
                "binding": list(self.before_export_import.binding),
                "valid": self.before_export_import.valid,
            }} if self.before_export_import != EvBeforeExportImport() else {}),
            **({"before_export_recovery": {
                "pending": self.before_export_recovery.pending,
                "binding": list(self.before_export_recovery.binding),
                "valid": self.before_export_recovery.valid,
            }} if self.before_export_recovery != EvBeforeExportRecovery() else {}),
            **({"reservation_soc": {
                "value_percent": reservation_soc.value_percent,
                "observed_at": reservation_soc.observed_at.isoformat(),
                "binding": list(reservation_soc.binding),
            }} if isinstance(reservation_soc, EvReservationSocRecord)
                and reservation_soc.valid_at(self.restored_at) else {}),
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

    def validated_for_storage(self) -> EvPersistenceState:
        """Apply the established grouped fallbacks before writing a snapshot."""
        return type(self).from_payload(self.to_payload(), self.restored_at)


def _reservation_soc(payload: object, now: datetime) -> EvReservationSocRecord | None:
    """Discard malformed reservation evidence independently of control state."""
    if not isinstance(payload, dict):
        return None
    raw_stamp = payload.get("observed_at")
    binding = payload.get("binding")
    if (
        not isinstance(raw_stamp, str) or not isinstance(binding, list)
        or not 0 < len(binding) <= _MAX_RESERVATION_BINDING_PARTS
    ):
        return None
    try:
        observed_at = datetime.fromisoformat(raw_stamp)
    except ValueError:
        return None
    record = EvReservationSocRecord(payload.get("value_percent"), observed_at, tuple(binding))
    return record if record.valid_at(now) else None


def _before_export_import(payload: object, now: datetime) -> EvBeforeExportImport:
    if payload is None:
        return EvBeforeExportImport()
    try:
        if not isinstance(payload, dict) or type(payload.get("valid")) is not bool:
            raise ValueError
        binding = payload["binding"]
        if (not isinstance(binding, list) or len(binding) > 40
                or any(not isinstance(v, str) or len(v) > 256 for v in binding)):
            raise ValueError
        since_raw = payload["since"]
        if since_raw is not None and not isinstance(since_raw, str):
            raise ValueError
        since = datetime.fromisoformat(since_raw) if since_raw is not None else None
        if since is not None and (since.tzinfo is None or since > now or not binding):
            raise ValueError
        return EvBeforeExportImport(since, tuple(binding), payload["valid"])
    except (KeyError, TypeError, ValueError):
        return EvBeforeExportImport(valid=False)


def _before_export_recovery(payload: object) -> EvBeforeExportRecovery:
    if (
        not isinstance(payload, dict) or type(payload.get('pending')) is not bool
        or type(payload.get('valid', True)) is not bool
        or not isinstance(payload.get('binding'), list)
        or len(payload['binding']) > 32
        or any(not isinstance(v, str) or len(v) > 256 for v in payload['binding'])
        or payload['pending'] and not payload['binding']
    ):
        return EvBeforeExportRecovery(valid=False)
    return EvBeforeExportRecovery(
        payload['pending'], tuple(payload['binding']), payload.get('valid', True),
    )


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
        or last_at is not None
        and last_at > now
        or target_current is not None
        and (not isfinite(target_current) or target_current < 0)
        or target_limit is not None
        and (not isfinite(target_limit) or target_limit < 0)
        or phase not in DIRECT_EVSE_RECONCILIATION_PHASES | {"fault_maximum_attempts"}
    ):
        raise ValueError
    # Retain the timing and attempt count from pre-backoff versions, but
    # migrate their terminal latch into an ordinary feedback wait.
    if phase == "fault_maximum_attempts":
        phase = "awaiting_feedback"
    state = DirectEvseReconciliationState(
        target_current_a=target_current,
        target_limit_percent=target_limit,
        attempts=attempts,
        last_command_at=last_at,
        phase=phase,
    )
    return _retry_channels(payload.get("retry_channels"), state, now)


def _retry_channels_payload(state: DirectEvseReconciliationState) -> dict[str, object]:
    """Append only; old readers retain the conservative aggregate retry clock."""
    channels = (state.current_retry, state.limit_retry, state.start_retry)
    if all(channel is None for channel in channels):
        return {}

    def clock(value):
        return value.isoformat() if value is not None else None

    def channel(value):
        if value is None:
            return None
        return {"target": value.target, "attempts": value.attempts,
                "last_command_at": clock(value.last_command_at)}

    proof = state.current_proof
    return {"retry_channels": {
        "version": 1,
        "current": channel(state.current_retry), "limit": channel(state.limit_retry),
        "start": channel(state.start_retry),
        "current_signature": list(state.current_signature) if state.current_signature else None,
        "current_proof": {
            "binding": proof.binding, "completed_at": clock(proof.completed_at),
            "stable_since": clock(proof.stable_since), "stable_last": clock(proof.stable_last),
            "acknowledged_at": clock(proof.acknowledged_at), "seen_at": clock(proof.seen_at),
            "acknowledged_since": clock(proof.acknowledged_since),
            "armed": proof.armed,
        },
    }}


def _retry_channels(payload, legacy, now):
    """Malformed optional state cannot erase existing stop/ownership journals."""
    if payload is None:
        return legacy
    try:
        if not isinstance(payload, dict) or type(payload.get("version")) is not int or (
            payload["version"] != 1
        ):
            raise ValueError
        channels = tuple(_retry_channel(payload[key], now) for key in ("current", "limit", "start"))
        signature = payload.get("current_signature")
        if not isinstance(signature, list) or len(signature) != 3 or any(
            type(value) not in (int, float) or not isfinite(value) or value < 0
            for value in signature
        ) or signature[2] <= 0 or channels[0].target != signature[0]:
            raise ValueError
        if channels[1].target > 100 or channels[2].target != 1:
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        # Legacy aggregate attempts/time intentionally overprotect every
        # unknown channel. A corrupt extension is not a fresh episode.
        return legacy
    proof = _current_proof(payload.get("current_proof"), now)
    if proof.completed_at is not None and (
        channels[0].last_command_at is None
        or proof.completed_at < channels[0].last_command_at
    ):
        proof = DirectEvseCurrentProof()
    return replace(
        legacy, current_retry=channels[0], limit_retry=channels[1], start_retry=channels[2],
        current_signature=tuple(signature),
        current_proof=proof,
    )


def _retry_clock(value, now):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None or stamp > now:
        raise ValueError
    return stamp


def _retry_channel(payload, now):
    if not isinstance(payload, dict):
        raise ValueError
    target, attempts = payload.get("target"), payload.get("attempts")
    last = _retry_clock(payload.get("last_command_at"), now)
    if type(target) not in (int, float) or not isfinite(target) or target < 0 or (
        type(attempts) is not int or attempts < 0
    ) or (attempts > 0) != (last is not None):
        raise ValueError
    return DirectEvseRetryState(float(target), attempts, last)


def _current_proof(payload, now):
    try:
        if not isinstance(payload, dict) or type(payload.get("armed")) is not bool:
            raise ValueError
        binding = payload.get("binding")
        if binding is not None and (not isinstance(binding, str) or not 0 < len(binding) <= 256):
            raise ValueError
        clocks = {key: _retry_clock(payload.get(key), now) for key in (
            "completed_at", "stable_since", "stable_last", "acknowledged_at", "seen_at",
            "acknowledged_since",
        )}
        completed, since, last, acknowledged, seen, acknowledged_since = clocks.values()
        if (binding is None) != (completed is None) or (
            any(value is not None for value in (since, last, acknowledged, acknowledged_since))
            and completed is None
        ) or (since is None) != (last is None) or (
            since is not None and (since <= completed or last < since)
        ) or (last is not None and (seen is None or last > seen)) or (
            (acknowledged is None) != (acknowledged_since is None)
        ) or (acknowledged is not None and (
            acknowledged <= completed or seen is None or acknowledged > seen
            or acknowledged_since <= completed
            or acknowledged - acknowledged_since < DIRECT_EVSE_FEEDBACK_SETTLE_INTERVAL
        )) or (payload["armed"] and acknowledged is None):
            raise ValueError
        return DirectEvseCurrentProof(binding=binding, **clocks, armed=payload["armed"])
    except (TypeError, ValueError, OverflowError):
        return DirectEvseCurrentProof()


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


def _measured_solar_adjustment(
    payload: object,
    now: datetime,
) -> MeasuredSolarAdjustmentState:
    """Decode the optional rate-limit state without blocking old EV stores."""
    if payload is None:
        return MeasuredSolarAdjustmentState()
    if not isinstance(payload, dict):
        raise ValueError
    phase = payload.get("phase")
    target_raw = payload.get("target_current_a")
    changed_raw = payload.get("changed_at")
    pending_raw = payload.get("pending_current_a")
    pending_since_raw = payload.get("pending_since")
    battery_raw = payload.get("battery_current_a")
    if phase is None and all(
        value is None
        for value in (target_raw, changed_raw, pending_raw, pending_since_raw, battery_raw)
    ):
        return MeasuredSolarAdjustmentState()
    if isinstance(battery_raw, bool):
        raise ValueError
    target = float(target_raw) if target_raw is not None else None
    changed_at = datetime.fromisoformat(str(changed_raw)) if changed_raw else None
    pending = float(pending_raw) if pending_raw is not None else None
    pending_since = (
        datetime.fromisoformat(str(pending_since_raw)) if pending_since_raw else None
    )
    try:
        battery_current = float(battery_raw) if battery_raw is not None else None
    except OverflowError as error:
        raise ValueError from error
    if (
        phase not in {"solar_spill", "morning_solar"}
        or target is None
        or changed_at is None
        or not isfinite(target)
        or target <= 0
        or changed_at.tzinfo is None
        or changed_at > now
        or (pending is None) != (pending_since is None)
        or pending is not None
        and (not isfinite(pending) or pending <= 0)
        or pending_since is not None
        and (pending_since.tzinfo is None or pending_since > now or pending_since < changed_at)
        or battery_current is not None
        and (not isfinite(battery_current) or battery_current < 0)
    ):
        raise ValueError
    return MeasuredSolarAdjustmentState(
        phase=phase,
        target_current_a=target,
        changed_at=changed_at,
        pending_current_a=pending,
        pending_since=pending_since,
        battery_current_a=battery_current,
    )


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
        or not 0 <= attempts <= 1_000_000
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
