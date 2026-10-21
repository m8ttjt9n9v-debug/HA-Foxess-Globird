"""Latched, bounded FoxESS export-session state machine.

This module only plans transitions. It deliberately has no Home Assistant
service dependency; an active coordinator must persist the returned state and
give the command plan to the fail-closed FoxESS adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite

from .foxess import (
    ControlDecision,
    FoxessCommandPlan,
    FoxessObservation,
    foxess_response_matches,
    plan_foxess_commands,
)


@dataclass(frozen=True, slots=True)
class ExportSessionState:
    """Persistable export-session state."""

    phase: str = "idle"
    requested_power_kw: float = 0.0
    attempts: int = 0
    last_command_at: datetime | None = None
    authority_source: str = "zerohero"
    price_deadline: datetime | None = None
    price_actuator_entities: tuple[str, str, str] | None = None
    price_permission_end: datetime | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, object] | None) -> ExportSessionState:
        """Decode the established Store payload, raising on malformed evidence."""
        if payload is None:
            return cls()
        phase = str(payload["phase"])
        power = float(payload["requested_power_kw"])
        attempts = int(payload["attempts"])
        last_raw = payload.get("last_command_at")
        last_at = datetime.fromisoformat(str(last_raw)) if last_raw else None
        authority = str(payload.get("authority_source", "zerohero"))
        deadline_raw = payload.get("price_deadline")
        deadline = datetime.fromisoformat(str(deadline_raw)) if deadline_raw else None
        mapping = _price_mapping(payload.get("price_actuator_entities"))
        permission_raw = payload.get("price_permission_end")
        permission_end = datetime.fromisoformat(str(permission_raw)) if permission_raw else None
        if phase not in {"idle", "starting", "active", "stopping", "recovering"}:
            raise ValueError("invalid export session phase")
        if power < 0 or attempts < 0:
            raise ValueError("invalid export session counter")
        _validate_authority(authority, deadline, phase=phase)
        if authority == "price" and (not isfinite(power) or power <= 0):
            raise ValueError("price-owned power must be positive and finite")
        if authority == "price" and (
            type(payload["attempts"]) is not int
            or last_at is not None and (last_at.tzinfo is None or last_at.utcoffset() is None)
            or phase in {"starting", "active"} and last_at is not None and last_at > deadline
        ):
            raise ValueError("invalid price command timing or retry counter")
        if authority == "price" and mapping is None:
            raise ValueError("price-owned journal must bind its original actuators")
        if authority == "zerohero" and mapping is not None:
            raise ValueError("ordinary journal cannot inherit price actuators")
        if permission_end is not None and (
            authority != "price" or permission_end.tzinfo is None
            or permission_end.utcoffset() is None or deadline > permission_end
        ):
            raise ValueError("invalid price permission boundary")
        return cls(phase, power, attempts, last_at, authority, deadline, mapping, permission_end)

    def to_payload(self) -> dict[str, object]:
        """Return the unchanged Store payload."""
        payload = {
            "phase": self.phase,
            "requested_power_kw": self.requested_power_kw,
            "attempts": self.attempts,
            "last_command_at": (
                self.last_command_at.isoformat() if self.last_command_at else None
            ),
        }
        if self.authority_source != "zerohero" or self.price_deadline is not None:
            if self.price_actuator_entities is None:
                raise ValueError("price persistence requires original actuator mappings")
            payload["authority_source"] = self.authority_source
            payload["price_deadline"] = (
                self.price_deadline.isoformat() if self.price_deadline else None
            )
            payload["price_actuator_entities"] = list(self.price_actuator_entities)
            if self.price_permission_end is not None:
                payload["price_permission_end"] = self.price_permission_end.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class ExportSessionTransition:
    """The next state and optional adapter-neutral command plan."""

    state: ExportSessionState
    plan: FoxessCommandPlan
    reason: str


def advance_export_session(
    state: ExportSessionState,
    observation: FoxessObservation,
    *,
    now: datetime,
    source_available: bool,
    window_active: bool,
    eligible: bool,
    requested_discharge_power_kw: float,
    discharge_power_max_kw: float,
    finish_requested: bool = False,
    acceptance_timeout: timedelta = timedelta(seconds=30),
    retry_after: timedelta = timedelta(seconds=30),
    max_attempts: int = 3,
    tolerance_kw: float = 0.01,
    authority_source: str = "zerohero",
    price_deadline: datetime | None = None,
    price_permission_end: datetime | None = None,
) -> ExportSessionTransition:
    """Advance a latched session with bounded writes and restart recovery."""
    _validate_inputs(
        state,
        now,
        requested_discharge_power_kw,
        discharge_power_max_kw,
        acceptance_timeout,
        retry_after,
        max_attempts,
    )
    if state.authority_source == "price" or (
        authority_source == "price" and state.phase == "idle"
    ):
        return _advance_price_session(
            state,
            observation,
            now=now,
            source_available=source_available,
            window_active=window_active,
            eligible=eligible,
            requested_discharge_power_kw=requested_discharge_power_kw,
            discharge_power_max_kw=discharge_power_max_kw,
            finish_requested=finish_requested,
            acceptance_timeout=acceptance_timeout,
            retry_after=retry_after,
            max_attempts=max_attempts,
            tolerance_kw=tolerance_kw,
            authority_source=authority_source,
            price_deadline=price_deadline,
            price_permission_end=price_permission_end,
        )
    _validate_authority(authority_source, price_deadline)
    new_session_desired = (
        source_available
        and window_active
        and eligible
        and not finish_requested
        and requested_discharge_power_kw > 0
    )
    requested = round(min(requested_discharge_power_kw, discharge_power_max_kw), 3)
    if not source_available:
        if state.phase in {"starting", "active", "stopping", "recovering"}:
            return ExportSessionTransition(
                replace(state, phase="recovering"),
                FoxessCommandPlan((), "source_unavailable"),
                "source_unavailable",
            )
        return ExportSessionTransition(
            replace(state, phase="idle", attempts=0, last_command_at=None),
            FoxessCommandPlan((), "source_unavailable"),
            "source_unavailable",
        )

    if state.phase == "recovering":
        if window_active and not finish_requested and state.requested_power_kw > 0:
            return _start(
                replace(state, phase="idle", attempts=0, last_command_at=None),
                observation,
                now,
                state.requested_power_kw,
                discharge_power_max_kw,
                tolerance_kw,
            )
        return _stop(state, observation, now, tolerance_kw)

    if state.phase == "idle":
        if not new_session_desired or requested <= 0:
            return _idle("not_eligible")
        return _start(state, observation, now, requested, discharge_power_max_kw, tolerance_kw)

    if state.phase == "starting":
        if not window_active or finish_requested:
            return _stop(state, observation, now, tolerance_kw)
        decision = ControlDecision(
            "force_discharge", state.requested_power_kw, "export_window_ready"
        )
        if foxess_response_matches(decision, observation, tolerance_kw=tolerance_kw):
            return ExportSessionTransition(
                replace(state, phase="active", attempts=0),
                FoxessCommandPlan((), "feedback_matches_plan"),
                "active",
            )
        if _within_retry(state, now, acceptance_timeout):
            return ExportSessionTransition(
                state, FoxessCommandPlan((), "awaiting_feedback"), "awaiting_feedback"
            )
        if state.attempts >= max_attempts:
            return ExportSessionTransition(
                state,
                FoxessCommandPlan((), "max_attempts_exceeded"),
                "max_attempts_exceeded",
            )
        return _start(
            state,
            observation,
            now,
            state.requested_power_kw,
            discharge_power_max_kw,
            tolerance_kw,
        )

    if state.phase == "active":
        if not window_active or finish_requested:
            return _stop(state, observation, now, tolerance_kw)
        decision = ControlDecision(
            "force_discharge", state.requested_power_kw, "export_window_ready"
        )
        if foxess_response_matches(decision, observation, tolerance_kw=tolerance_kw):
            return ExportSessionTransition(state, FoxessCommandPlan((), "latched"), "latched")
        if _within_retry(state, now, retry_after):
            return ExportSessionTransition(
                state, FoxessCommandPlan((), "awaiting_feedback"), "awaiting_feedback"
            )
        if state.attempts >= max_attempts:
            return ExportSessionTransition(
                state,
                FoxessCommandPlan((), "max_attempts_exceeded"),
                "max_attempts_exceeded",
            )
        return _start(
            replace(state, phase="starting"),
            observation,
            now,
            state.requested_power_kw,
            discharge_power_max_kw,
            tolerance_kw,
        )

    if state.phase == "stopping":
        if new_session_desired:
            return _start(
                replace(state, phase="idle", attempts=0),
                observation,
                now,
                requested,
                discharge_power_max_kw,
                tolerance_kw,
            )
        decision = ControlDecision("restore_self_use", 0.0, "no_active_policy")
        if foxess_response_matches(decision, observation, tolerance_kw=tolerance_kw):
            return _idle("restored_self_use")
        if _within_retry(state, now, acceptance_timeout):
            return ExportSessionTransition(
                state, FoxessCommandPlan((), "awaiting_feedback"), "awaiting_feedback"
            )
        if state.attempts >= max_attempts:
            return ExportSessionTransition(
                state,
                FoxessCommandPlan((), "max_attempts_exceeded"),
                "max_attempts_exceeded",
            )
        return _stop(replace(state, attempts=state.attempts), observation, now, tolerance_kw)

    raise ValueError(f"unsupported export session phase: {state.phase}")


def _advance_price_session(state, observation, **kwargs):
    """Apply current price permission around the retained session transitions."""
    now = kwargs["now"]
    authority = kwargs.pop("authority_source")
    proposed_deadline = kwargs.pop("price_deadline")
    permission_end = kwargs.pop("price_permission_end")
    _validate_authority(authority, proposed_deadline)
    latched = state.phase != "idle" and state.authority_source == "price"
    deadline = state.price_deadline if latched else proposed_deadline
    if latched and proposed_deadline is not None:
        renewing = price_permission_can_renew(state, now, permission_end)
        deadline = proposed_deadline if renewing else min(deadline, proposed_deadline)
    plain = replace(
        state, authority_source="zerohero", price_deadline=None, price_actuator_entities=None,
        price_permission_end=None,
    )
    permitted = (
        authority == "price" and deadline is not None and now < deadline
        and kwargs["window_active"] and kwargs["eligible"]
        and not kwargs["finish_requested"]
    )
    if latched and state.last_command_at is not None and now < state.last_command_at:
        permitted = False
    if not kwargs["source_available"]:
        transition = advance_export_session(plain, observation, **kwargs)
    elif latched and (state.phase == "stopping" or not permitted):
        decision = ControlDecision("restore_self_use", 0, "price_export_finished")
        if foxess_response_matches(decision, observation, tolerance_kw=kwargs["tolerance_kw"]):
            return _idle("restored_self_use")
        if state.phase == "stopping":
            interval = timedelta(
                seconds=min(30 * 2 ** min(max(state.attempts - 1, 0), 4), 300)
            )
            if (
                state.last_command_at is not None and now >= state.last_command_at
                and _within_retry(state, now, interval)
            ):
                transition = ExportSessionTransition(
                    plain, FoxessCommandPlan((), "awaiting_feedback"), "awaiting_feedback"
                )
            else:
                transition = _stop(plain, observation, now, kwargs["tolerance_kw"])
        else:
            transition = _stop(
                replace(plain, attempts=0, last_command_at=None),
                observation, now, kwargs["tolerance_kw"],
            )
    elif not latched and not permitted:
        return _idle("not_eligible")
    elif not latched and observation.mode != "Self Use":
        return _idle("price_external_owner")
    else:
        if latched:
            # A commissioned reduction may curtail a price-owned target, but
            # fresh intervals cannot increase its latched inverter power.
            plain = replace(
                plain,
                requested_power_kw=min(
                    state.requested_power_kw,
                    kwargs["requested_discharge_power_kw"],
                    kwargs["discharge_power_max_kw"],
                ),
            )
        transition = advance_export_session(plain, observation, **kwargs)
    if transition.state.phase == "idle":
        return transition
    assert deadline is not None
    return replace(
        transition,
        state=replace(
            transition.state, authority_source="price", price_deadline=deadline,
            price_actuator_entities=state.price_actuator_entities,
            price_permission_end=(
                max(state.price_permission_end, permission_end)
                if state.price_permission_end is not None and permission_end is not None
                else state.price_permission_end or permission_end
            ),
        ),
    )


def price_permission_can_renew(
    state: ExportSessionState, now: datetime, permission_end: datetime | None,
) -> bool:
    """A newer confirmed block can renew only a still-live running session."""
    return (
        state.authority_source == "price" and state.phase in {"starting", "active"}
        and state.price_deadline is not None and now < state.price_deadline
        and state.price_permission_end is not None and permission_end is not None
        and permission_end > state.price_permission_end
    )


def _start(state, observation, now, requested, maximum, tolerance):
    decision = ControlDecision("force_discharge", requested, "export_window_ready")
    if foxess_response_matches(decision, observation, tolerance_kw=tolerance):
        return ExportSessionTransition(
            replace(state, phase="active", requested_power_kw=requested, attempts=0),
            FoxessCommandPlan((), "feedback_matches_plan"),
            "active",
        )
    plan = plan_foxess_commands(
        decision,
        observation,
        charge_power_max_kw=maximum,
        discharge_power_max_kw=maximum,
    )
    return ExportSessionTransition(
        ExportSessionState(
            "starting", requested, state.attempts + 1, now,
            state.authority_source, state.price_deadline,
            state.price_actuator_entities,
        ),
        plan, "start_requested",
    )


def _stop(state, observation, now, tolerance):
    decision = ControlDecision("restore_self_use", 0.0, "no_active_policy")
    if foxess_response_matches(decision, observation, tolerance_kw=tolerance):
        return _idle("restored_self_use")
    plan = plan_foxess_commands(
        decision,
        observation,
        charge_power_max_kw=max(state.requested_power_kw, 0.0),
        discharge_power_max_kw=max(state.requested_power_kw, 0.0),
    )
    return ExportSessionTransition(
        ExportSessionState(
            "stopping", state.requested_power_kw, state.attempts + 1, now,
            state.authority_source, state.price_deadline,
            state.price_actuator_entities,
        ),
        plan,
        "stop_requested",
    )


def _within_retry(state: ExportSessionState, now: datetime, interval: timedelta) -> bool:
    return state.last_command_at is not None and now - state.last_command_at < interval


def _idle(reason: str) -> ExportSessionTransition:
    return ExportSessionTransition(ExportSessionState(), FoxessCommandPlan((), reason), reason)


def _validate_inputs(state, now, requested, maximum, acceptance_timeout, retry_after, max_attempts):
    if state.phase not in {"idle", "starting", "active", "stopping", "recovering"}:
        raise ValueError(f"unsupported export session phase: {state.phase}")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if state.last_command_at is not None and (
        state.last_command_at.tzinfo is None or state.last_command_at.utcoffset() is None
    ):
        raise ValueError("last_command_at must be timezone-aware")
    if requested < 0 or maximum < 0:
        raise ValueError("requested and maximum power must be non-negative")
    if acceptance_timeout < timedelta(0) or retry_after < timedelta(0):
        raise ValueError("timeouts must be non-negative")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    _validate_authority(state.authority_source, state.price_deadline, phase=state.phase)
    if state.authority_source == "price" and (
        not isfinite(state.requested_power_kw) or state.requested_power_kw <= 0
        or not isfinite(requested) or not isfinite(maximum)
    ):
        raise ValueError("invalid price export power")


def _validate_authority(authority, deadline, *, phase=None):
    if authority not in {"zerohero", "price"}:
        raise ValueError("unknown export authority")
    if deadline is not None and (
        deadline.tzinfo is None or deadline.utcoffset() is None
    ):
        raise ValueError("price deadline must be timezone-aware")
    if authority == "zerohero" and deadline is not None:
        raise ValueError("ordinary export cannot inherit a price deadline")
    if authority == "price" and (
        deadline is None or phase == "idle"
    ):
        raise ValueError("price-owned state must retain its deadline until idle")


def _price_mapping(raw):
    if raw is None:
        return None
    if (
        not isinstance(raw, (list, tuple)) or len(raw) != 3
        or any(not isinstance(value, str) or not value.strip() for value in raw)
        or len(set(raw)) != 3
    ):
        raise ValueError("invalid original price actuator mapping")
    return tuple(raw)
