"""One house-protected energy pool for EV reservation and automatic export.

The existing export arithmetic subtracts house and mandatory EV keepalive
once. This separately selected extension splits the remaining pool between
one fixed OR current-SoC reservation and unreserved export energy. The EV may
use its own reservation; it is not capped by the unreserved export balance.

This is energy accounting, not charging or export authority. The caller still
qualifies source freshness, admission/recovery journals, physical ownership,
reserve, SoC and power limits. No journey energy or future charging is assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class EvReservationInputs:
    """Already-qualified AC/wall energy and explicit reservation settings.

    ``available_ac_after_reserve_kwh`` has already had the home battery's
    floor/reserve and discharge efficiency applied. ``fixed_remaining_kwh``
    is the existing ready-cycle allocation after confirmed delivery. Dynamic
    mode ignores that fixed amount, so the two reservations cannot accumulate.
    Automatic vehicle/house presence is intentionally not an input.
    """

    available_ac_after_reserve_kwh: float | None
    protected_house_kwh: float | None
    keepalive_kwh: float | None
    mode: str = "fixed"
    fixed_remaining_kwh: float | None = 0.0
    soc_percent: float | None = None
    minimum_soc_percent: float | None = None
    buffer_soc_percent: float | None = None
    normal_target_soc_percent: float | None = None
    capacity_kwh: float | None = None
    charge_efficiency_percent: float | None = None
    extended_away: bool = False


@dataclass(frozen=True, slots=True)
class EvReservationBudget:
    """A conserved pool, requested protection and its currently funded share.

    A valid budget is not permission to command a device. Invalid evidence
    yields no positive energy authority, rather than a guessed reservation.
    ``protected_ev_kwh`` includes keepalive plus the selected requested reserve;
    the funded reserve and EV-available energy never exceed the current pool.
    """

    valid: bool
    reason: str
    mode: str
    target_soc_percent: float | None = None
    available_after_house_kwh: float = 0.0
    ev_available_kwh: float = 0.0
    requested_reservation_kwh: float = 0.0
    funded_reservation_kwh: float = 0.0
    reservation_shortfall_kwh: float = 0.0
    protected_ev_kwh: float = 0.0
    exportable_kwh: float = 0.0


def _number(value: object, *, minimum: float = 0.0, maximum: float | None = None) -> bool:
    try:
        return (
            type(value) in (int, float)
            and isfinite(value)
            and value >= minimum
            and (maximum is None or value <= maximum)
        )
    except OverflowError:
        return False


def calculate_ev_reservation_budget(inputs: EvReservationInputs) -> EvReservationBudget:
    """Split one current pool without withholding it from its EV beneficiary.

    Dynamic reservation always covers the wall-energy deficit to the human
    minimum plus its existing buffer, clipped to the normal charging target.
    The budget is stateless and continuous across the minimum; existing
    persisted charging admission/release hysteresis remains the caller's job.
    No extra start/stop boundary or delay belongs in this arithmetic.

    The explicit Extended Away input releases only the discretionary EV
    reservation; it does not release a physically required keepalive or house
    protection. It cannot be inferred from automatic presence. A caller without
    an explicit Extended Away setting must leave it false.
    """
    def invalid(reason: str) -> EvReservationBudget:
        return EvReservationBudget(False, reason, inputs.mode)

    if type(inputs.mode) is not str or inputs.mode not in {"fixed", "dynamic"}:
        return invalid("reservation_mode_invalid")
    if type(inputs.extended_away) is not bool:
        return invalid("extended_away_invalid")
    if not all(_number(value) for value in (
        inputs.available_ac_after_reserve_kwh, inputs.protected_house_kwh, inputs.keepalive_kwh,
    )):
        return invalid("protected_energy_unavailable")

    target = None
    if inputs.extended_away:
        requested = 0.0
        reason = "extended_away"
    elif inputs.mode == "fixed":
        if not _number(inputs.fixed_remaining_kwh):
            return invalid("fixed_reservation_invalid")
        requested = float(inputs.fixed_remaining_kwh)
        reason = "fixed_reservation"
    else:
        if not all(_number(value, maximum=100) for value in (
            inputs.soc_percent, inputs.minimum_soc_percent, inputs.buffer_soc_percent,
            inputs.normal_target_soc_percent,
        )):
            return invalid("vehicle_soc_or_target_invalid")
        if not _number(inputs.capacity_kwh, maximum=1000) or inputs.capacity_kwh <= 0:
            return invalid("vehicle_capacity_invalid")
        if (
            not _number(inputs.charge_efficiency_percent, maximum=100)
            or inputs.charge_efficiency_percent <= 0
        ):
            return invalid("charge_efficiency_invalid")
        target = min(
            inputs.minimum_soc_percent + inputs.buffer_soc_percent,
            inputs.normal_target_soc_percent,
            100.0,
        )
        # Same capacity × SoC deficit / charge-efficiency conversion as the
        # retained EV wall-energy planner, without presentation rounding that
        # could turn a small protected deficit into export authority.
        requested = (
            inputs.capacity_kwh * max(target - inputs.soc_percent, 0.0)
            / inputs.charge_efficiency_percent
        )
        reason = "dynamic_reservation"

    protected_ev = inputs.keepalive_kwh + requested
    if not isfinite(requested) or not isfinite(protected_ev):
        return invalid("reservation_energy_invalid")
    after_house = max(inputs.available_ac_after_reserve_kwh - inputs.protected_house_kwh, 0.0)
    ev_available = max(after_house - inputs.keepalive_kwh, 0.0)
    funded = min(requested, ev_available)
    exportable = max(ev_available - requested, 0.0)
    return EvReservationBudget(
        valid=True,
        reason=reason,
        mode=inputs.mode,
        target_soc_percent=target,
        available_after_house_kwh=after_house,
        ev_available_kwh=ev_available,
        requested_reservation_kwh=requested,
        funded_reservation_kwh=funded,
        reservation_shortfall_kwh=max(requested - funded, 0.0),
        protected_ev_kwh=protected_ev,
        exportable_kwh=exportable,
    )
