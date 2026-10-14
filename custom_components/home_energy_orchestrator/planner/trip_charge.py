"""Pure one-off trip settings, durable Full lease and retained latest-start math."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite

TRIP_STATUSES = (
    "not_scheduled",
    "waiting_for_start",
    "already_at_target",
    "waiting_for_car",
    "waiting_for_data",
    "control_unavailable",
    "external_override",
    "override_active",
    "completed",
    "cancelled",
    "interrupted",
    "expired",
    "charging_late",
    "legacy_conflict",
    "storage_unavailable",
    "invalid_storage",
)


def _date(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("trip timestamp must be aware ISO8601")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("trip timestamp must be aware")
    return result.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class TripChargeState:
    """One journal owns settings and the request-specific logical Full lease."""

    departure: datetime | None = None
    target_soc: int = 100
    extra_minutes: float = 0.0
    armed: bool = False
    status: str = "not_scheduled"
    generation: int = 0
    full_generation: int = 0
    full_owner: str | None = None
    full_enabled: bool = False
    owner_token: str | None = None
    owned_generation: int | None = None
    captured_departure: datetime | None = None
    captured_target: int | None = None
    cleanup_pending: bool = False

    @property
    def owns_full(self) -> bool:
        return (
            self.owner_token is not None
            and self.full_owner == self.owner_token
            and self.owned_generation == self.full_generation
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": 1,
            "departure": self.departure.isoformat() if self.departure else None,
            "target_soc": self.target_soc,
            "extra_minutes": self.extra_minutes,
            "armed": self.armed,
            "status": self.status,
            "generation": self.generation,
            "full_generation": self.full_generation,
            "full_owner": self.full_owner,
            "full_enabled": self.full_enabled,
            "owner_token": self.owner_token,
            "owned_generation": self.owned_generation,
            "captured_departure": (
                self.captured_departure.isoformat() if self.captured_departure else None
            ),
            "captured_target": self.captured_target,
            "cleanup_pending": self.cleanup_pending,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object] | None) -> TripChargeState:
        if payload is None:
            return cls()
        if type(payload.get("schema")) is not int or payload.get("schema") != 1:
            raise ValueError("unknown trip journal")
        state = cls(
            departure=_date(payload.get("departure")),
            target_soc=payload["target_soc"],
            extra_minutes=payload["extra_minutes"],
            armed=payload["armed"],
            status=payload["status"],
            generation=payload["generation"],
            full_generation=payload["full_generation"],
            full_owner=payload["full_owner"],
            full_enabled=payload["full_enabled"],
            owner_token=payload["owner_token"],
            owned_generation=payload["owned_generation"],
            captured_departure=_date(payload.get("captured_departure")),
            captured_target=payload["captured_target"],
            cleanup_pending=payload["cleanup_pending"],
        )
        if (
            type(state.target_soc) is not int
            or not 1 <= state.target_soc <= 100
            or type(state.generation) is not int
            or state.generation < 0
            or type(state.full_generation) is not int
            or state.full_generation < 0
            or type(state.armed) is not bool
            or type(state.full_enabled) is not bool
            or type(state.cleanup_pending) is not bool
            or state.status not in TRIP_STATUSES
            or isinstance(state.extra_minutes, bool)
            or not isinstance(state.extra_minutes, (int, float))
            or not isfinite(state.extra_minutes)
            or not 0 <= state.extra_minutes <= 120
            or state.full_owner is not None
            and not isinstance(state.full_owner, str)
            or state.owner_token is not None
            and not isinstance(state.owner_token, str)
            or state.owned_generation is not None
            and (
                type(state.owned_generation) is not int
                or not 0 <= state.owned_generation <= state.full_generation
            )
            or state.captured_target is not None
            and (type(state.captured_target) is not int or not 1 <= state.captured_target <= 100)
        ):
            raise ValueError("malformed trip journal")
        if state.owner_token is not None and (
            not state.owner_token.startswith("trip:")
            or state.captured_departure is None
            or state.captured_target is None
            or state.owned_generation is None
        ):
            raise ValueError("incomplete trip ownership")
        for token in (state.full_owner, state.owner_token):
            if token is None or token == "operator":
                continue
            try:
                request_generation = int(token.removeprefix("trip:"))
            except ValueError as error:
                raise ValueError("invalid Full owner token") from error
            if (
                token != f"trip:{request_generation}"
                or not 0 <= request_generation <= state.generation
            ):
                raise ValueError("invalid Full owner generation")
        if state.owner_token is not None and not state.owns_full:
            raise ValueError("trip lease does not match the current Full generation")
        if state.owner_token is None and (
            state.owned_generation is not None
            or state.captured_departure is not None
            or state.captured_target is not None
            or state.full_owner not in {None, "operator"}
        ):
            raise ValueError("unbound trip lease")
        if (
            state.armed
            and state.departure is None
            or state.full_enabled
            and state.full_owner is None
            or state.full_generation == 0
            and state.full_owner is not None
        ):
            raise ValueError("incomplete Full intent")
        if state.cleanup_pending and not state.owns_full:
            raise ValueError("cleanup lacks current Full ownership")
        return state


@dataclass(frozen=True, slots=True)
class TripChargePlan:
    planned_start: datetime
    planned_hours: float


def calculate_trip_charge_plan(
    *,
    departure: datetime | None,
    target_soc: int,
    soc: float | None,
    capacity_kwh: float | None,
    maximum_power_kw: float | None,
    efficiency_percent: float,
    extra_minutes: float,
    maximum_hours: float,
) -> TripChargePlan | None:
    """Port the wrapper's deficit/efficiency/power calculation without new policy."""
    values = (soc, capacity_kwh, maximum_power_kw, efficiency_percent, extra_minutes, maximum_hours)
    if (
        departure is None
        or departure.tzinfo is None
        or departure.utcoffset() is None
        or type(target_soc) is not int
        or not 1 <= target_soc <= 100
        or any(
            isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value)
            for value in values
        )
        or not 0 <= soc <= 100
        or not 0 < capacity_kwh <= 1000
        or not 0 < maximum_power_kw <= 100
        or not 0 < efficiency_percent <= 100
        or not 0 <= extra_minutes <= 120
        or not 0 < maximum_hours <= 48
    ):
        return None
    hours = (
        max(target_soc - soc, 0)
        * capacity_kwh
        / 100
        / (maximum_power_kw * efficiency_percent / 100)
        + extra_minutes / 60
    )
    if hours > maximum_hours:
        return None
    return TripChargePlan(departure.astimezone(UTC) - timedelta(hours=hours), round(hours, 6))
