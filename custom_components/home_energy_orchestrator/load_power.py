"""Read-only house/EV power composition; no control or energy authority."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class HouseEvLoad:
    """An honest split, with an explicit reason when subtraction is unsafe."""

    house_power_kw: float | None
    ev_power_kw: float | None
    reason: str


def _nonnegative(value: float | None) -> bool:
    return value is not None and not isinstance(value, bool) and isfinite(value) and value >= 0


def split_house_ev_load(
    *,
    house_kw: float | None,
    includes_ev: bool,
    ev_configured: bool,
    current_a: float | None,
    voltage_v: float | None,
    phase_count: float | None,
) -> HouseEvLoad:
    """Use actual state-qualified current, never requested/maximum current.

    Voltage and phases are commissioned values, so EV power is an estimate.
    A source already excluding EV is never reduced again. Invalid raw demand
    or an impossible subtraction is not hidden by absolute value or a clamp.
    """
    ev_kw = None
    if not ev_configured:
        ev_kw = 0.0
    elif _nonnegative(current_a):
        if current_a == 0:
            ev_kw = 0.0
        elif (
            _nonnegative(voltage_v)
            and voltage_v > 0
            and phase_count in (1, 2, 3)
            and not isinstance(phase_count, bool)
        ):
            ev_kw = current_a * voltage_v * phase_count / 1000
    if not _nonnegative(house_kw):
        return HouseEvLoad(None, ev_kw, "house_load_unavailable")
    if not includes_ev or not ev_configured:
        return HouseEvLoad(house_kw, ev_kw, "already_excludes_ev")
    if ev_kw is None:
        return HouseEvLoad(None, ev_kw, "ev_power_unavailable")
    house_only = house_kw - ev_kw
    if house_only < 0:
        return HouseEvLoad(None, ev_kw, "ev_exceeds_total_house_load")
    return HouseEvLoad(house_only, ev_kw, "ev_subtracted_once")
