"""Bounded history for the optional afternoon solar-spill policy extension."""

from datetime import UTC, datetime, timedelta
from math import isfinite

from .timed_average import TimedAverageWindow

SOLAR_SOAK_INTERVAL = timedelta(minutes=5)
SOLAR_SOAK_FLOOR_PERCENT = 90.0


class SolarSoakAverage:
    """Average only contiguous qualified observations, never a stale tail."""

    def __init__(self):
        self.window = TimedAverageWindow(SOLAR_SOAK_INTERVAL)
        self.binding = None

    def clear(self):
        self.window.samples.clear()
        self.binding = None

    def observe(self, now, value, *, binding, max_gap_seconds):
        now = now.astimezone(UTC)
        binding = list(binding)
        if self.needs_reset(now, binding=binding, max_gap_seconds=max_gap_seconds):
            self.clear()
        self.binding = binding
        self.window.observe(now, value, source_valid=True)
        self.window.samples = self.window.samples[-512:]
        result = self.window.result(now)
        # Start with the first observed value, not invented five-minute history.
        return value if result.value is None else result.value

    def needs_reset(self, now, *, binding, max_gap_seconds):
        return (
            self.binding != list(binding)
            or not self.window.samples
            or not 0
            <= (now.astimezone(UTC) - self.window.samples[-1].at.astimezone(UTC)).total_seconds()
            <= max_gap_seconds
        )

    def to_payload(self):
        if not self.window.samples:
            return None
        return {"binding": self.binding, "window": self.window.to_payload()}

    def restore(self, payload, now, *, binding, max_gap_seconds):
        now = now.astimezone(UTC)
        self.clear()
        if not isinstance(payload, dict) or payload.get("binding") != list(binding):
            return False
        window = payload.get("window")
        rows = window.get("samples") if isinstance(window, dict) else None
        if not isinstance(rows, list) or not rows or len(rows) > 512:
            return False
        try:
            last = None
            for row in rows:
                at = datetime.fromisoformat(row["at"])
                value = row["value"]
                if (
                    at.tzinfo is None
                    or at > now
                    or isinstance(value, bool)
                    or not isinstance(value, (float, int))
                    or not isfinite(value)
                    or value < 0
                    or row["source_valid"] is not True
                    or last is not None
                    and not 0 < (at - last).total_seconds() <= max_gap_seconds
                ):
                    return False
                last = at
            if not 0 <= (now - last).total_seconds() <= max_gap_seconds:
                return False
        except (KeyError, ValueError, TypeError):
            return False
        self.window.restore(window, now)
        self.binding = list(binding)
        return True
