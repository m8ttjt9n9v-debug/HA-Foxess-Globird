"""Read-only incremental trip-energy liability before the next free window.

This is not a dispatch plan or an exact EV energy-source breakdown. Spending
house-battery energy on the car can cause paid house imports later, so the
existing house forecast is deducted once before crediting battery energy.
Future solar, power headroom, exports, the supply charge and lost credits or
export revenue are not modelled. No current battery balance is carried across
the free window to invent a whole-trip cost.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from math import isfinite

_ENERGY_FIELDS = (
    "pack_energy_kwh", "wall_energy_kwh", "before_free_kwh", "during_free_kwh",
    "after_free_kwh", "battery_available_for_ev_kwh", "battery_contribution_kwh",
    "extra_paid_energy_kwh", "cost_min", "cost_max",
)


def _aware(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def _import_rates_between(start, finish, peak_start, peak_end, peak_rate, shoulder_rate):
    """Find applicable rates, including repeated or skipped local clock times.

Only band presence is needed, not duration. Test both sides of each local
boundary and the intervening midpoints. Both folds preserve repeated autumn
times; the clock-time checks reject imaginary spring boundary conversions.
"""
    if peak_start == peak_end:
        return (peak_rate,)
    local_zone = start.tzinfo
    start_utc, finish_utc = start.astimezone(UTC), finish.astimezone(UTC)
    points = {start_utc, finish_utc}
    day = start.date()
    last_day = finish.astimezone(local_zone).date()
    # A daily band must occur within a multi-day interval. Avoid expanding an
    # accidentally distant 'next' window into an unbounded calendar forecast.
    if (last_day - day).days > 3:
        return (peak_rate, shoulder_rate)
    while day <= last_day:
        for boundary in (peak_start, peak_end):
            for fold in (0, 1):
                at = datetime.combine(day, boundary, local_zone).replace(fold=fold).astimezone(UTC)
                if start_utc < at < finish_utc:
                    points.add(at)
        day += timedelta(days=1)
    ordered = sorted(points)
    probes = []
    for left, right in zip(ordered, ordered[1:], strict=False):
        probes.extend((left, left + (right - left) / 2, right - timedelta(microseconds=1)))
    rates = set()
    for at in probes:
        clock = at.astimezone(local_zone).time().replace(tzinfo=None)
        peak = (
            peak_start <= clock < peak_end
            if peak_start < peak_end
            else clock >= peak_start or clock < peak_end
        )
        rates.add(peak_rate if peak else shoulder_rate)
    return tuple(rates)


def estimate_pre_free_impact(
    *, now, planned_start, next_free_start, next_free_end, soc, target_soc,
    capacity_kwh, maximum_power_kw, ev_efficiency_percent, battery_after_floor_kwh,
    protected_house_kwh, discharge_efficiency_percent, peak_start, peak_end,
    peak_rate, shoulder_rate,
) -> dict[str, object]:
    """Estimate remaining energy and pre-free incremental grid-cost bounds.

    All energy inputs are kWh, power is kW and rates are currency/kWh.
    ``now`` supplies the site's timezone for local tariff bands. The caller
    must supply the active scheduler's current SoC, target and planned start,
    and the existing house forecast through the next free-window start.
    Planning margin changes the start, not the amount of energy required.
    """
    result = {
        "status": "unavailable", "reason": "invalid_inputs",
        "scope": "before_next_free_window_only",
        "as_of": now.isoformat() if _aware(now) else None,
        "until_free_start": next_free_start.isoformat() if _aware(next_free_start) else None,
        "charging_start": None, "estimated_charging_end": None,
        **dict.fromkeys(_ENERGY_FIELDS),
    }
    numeric = (
        soc, target_soc, capacity_kwh, maximum_power_kw, ev_efficiency_percent,
        battery_after_floor_kwh, protected_house_kwh, discharge_efficiency_percent,
        peak_rate, shoulder_rate,
    )
    if (
        not all(_aware(value) for value in (now, planned_start, next_free_start, next_free_end))
        or not all(_number(value) for value in numeric)
        or not 0 <= soc <= 100
        or not 1 <= target_soc <= 100
        or not 0 < capacity_kwh <= 1000
        or not 0 < maximum_power_kw <= 100
        or not 0 < ev_efficiency_percent <= 100
        or not 0 < discharge_efficiency_percent <= 100
        or min(battery_after_floor_kwh, protected_house_kwh, peak_rate, shoulder_rate) < 0
        or any(not isinstance(value, time) or value.tzinfo is not None
               for value in (peak_start, peak_end))
    ):
        return result
    current = now.astimezone(UTC)
    start = max(current, planned_start.astimezone(UTC))
    free_start, free_end = next_free_start.astimezone(UTC), next_free_end.astimezone(UTC)
    if free_end <= free_start:
        return result
    pack = max(target_soc - soc, 0) * capacity_kwh / 100
    efficiency = ev_efficiency_percent / 100
    if efficiency == 0:
        return result
    wall = pack / efficiency
    if not isfinite(wall):
        return result
    try:
        finish = start + timedelta(hours=wall / maximum_power_kw)
    except (OverflowError, ValueError):
        return result
    before = max((min(finish, free_start) - start).total_seconds(), 0) / 3600 * maximum_power_kw
    during = max(
        (min(finish, free_end) - max(start, free_start)).total_seconds(), 0
    ) / 3600 * maximum_power_kw
    after = max((finish - max(start, free_end)).total_seconds(), 0) / 3600 * maximum_power_kw
    spare = max(
        battery_after_floor_kwh * (discharge_efficiency_percent / 100) - protected_house_kwh, 0
    )
    result.update(
        pack_energy_kwh=pack, wall_energy_kwh=wall,
        before_free_kwh=min(before, wall), during_free_kwh=min(during, wall),
        after_free_kwh=min(after, wall), battery_available_for_ev_kwh=spare,
        charging_start=start.isoformat(), estimated_charging_end=finish.isoformat(),
    )
    if pack == 0:
        result.update(
            status="already_at_target", reason="no_remaining_charge_needed",
            battery_contribution_kwh=0.0, extra_paid_energy_kwh=0.0, cost_min=0.0, cost_max=0.0,
        )
        return result
    if current >= free_start or start >= free_start:
        result.update(
            status="out_of_scope",
            reason=(
                "free_window_started" if current >= free_start
                else "charging_starts_at_or_after_free"
            ),
        )
        return result
    contribution = min(before, spare)
    paid = max(before - contribution, 0)
    rates = _import_rates_between(
        start.astimezone(now.tzinfo), free_start.astimezone(now.tzinfo),
        peak_start, peak_end, peak_rate, shoulder_rate,
    )
    costs = (paid * min(rates), paid * max(rates))
    if not all(isfinite(value) for value in costs):
        result.update(reason="cost_out_of_range")
        return result
    result.update(
        status="estimated", reason="pre_free_incremental_grid_liability",
        battery_contribution_kwh=contribution, extra_paid_energy_kwh=paid,
        cost_min=costs[0], cost_max=costs[1],
    )
    return result
