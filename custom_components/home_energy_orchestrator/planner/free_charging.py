"""Measured daily allowance eligibility; no forecasts or charger allocation."""

from datetime import datetime
from math import isfinite


def remaining_free_allowance(
    *, allowance_kwh: float, imported_kwh: float, measured_at: datetime | None, now: datetime,
) -> float | None:
    """Use only this accounting day's known, non-future import counter."""
    if (
        measured_at is None or measured_at.tzinfo is None or now.tzinfo is None
        or measured_at > now or measured_at.astimezone(now.tzinfo).date() != now.date()
        or isinstance(allowance_kwh, bool) or isinstance(imported_kwh, bool)
        or not isfinite(allowance_kwh) or not isfinite(imported_kwh)
        or allowance_kwh < 0 or imported_kwh < 0
    ):
        return None
    return max(allowance_kwh - imported_kwh, 0.0)


def free_allowance_available(remaining_kwh: float | None) -> bool:
    """A non-positive or unknown balance grants no automatic free charging."""
    return remaining_kwh is not None and isfinite(remaining_kwh) and remaining_kwh > 0
