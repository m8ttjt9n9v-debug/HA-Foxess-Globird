"""Restart-safe time-weighted averages for matched control feedback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite


@dataclass(frozen=True, slots=True)
class TimedSample:
    """One source observation and its validity at that instant."""

    at: datetime
    value: float
    source_valid: bool


@dataclass(frozen=True, slots=True)
class TimedAverageResult:
    """Average-step value plus evidence used by the Mangerton policy."""

    value: float | None
    age_coverage_ratio: float
    source_value_valid: bool


class TimedAverageWindow:
    """Retain one anchor sample plus observations inside a fixed window."""

    def __init__(self, duration: timedelta) -> None:
        if duration <= timedelta(0):
            raise ValueError("average duration must be positive")
        self.duration = duration
        self.samples: list[TimedSample] = []

    def observe(self, at: datetime, value: float, *, source_valid: bool) -> None:
        """Append a monotonic sample and prune history without losing its anchor."""
        _validate_datetime(at)
        if not isfinite(value):
            raise ValueError("sample value must be finite")
        if self.samples and at < self.samples[-1].at:
            raise ValueError("samples must be chronological")
        sample = TimedSample(at, value, source_valid)
        if self.samples and at == self.samples[-1].at:
            self.samples[-1] = sample
        else:
            self.samples.append(sample)
        self._prune(at)

    def result(self, now: datetime) -> TimedAverageResult:
        """Calculate HA statistics-style average_step and age coverage."""
        _validate_datetime(now)
        if not self.samples or now < self.samples[-1].at:
            return TimedAverageResult(None, 0.0, False)
        self._prune(now)
        cutoff = now - self.duration
        first_covered = max(self.samples[0].at, cutoff)
        covered_seconds = max((now - first_covered).total_seconds(), 0.0)
        ratio = min(covered_seconds / self.duration.total_seconds(), 1.0)
        if covered_seconds <= 0:
            return TimedAverageResult(None, 0.0, self.samples[-1].source_valid)
        energy = 0.0
        for index, sample in enumerate(self.samples):
            segment_start = max(sample.at, cutoff)
            segment_end = (
                min(self.samples[index + 1].at, now)
                if index + 1 < len(self.samples)
                else now
            )
            if segment_end > segment_start:
                energy += sample.value * (segment_end - segment_start).total_seconds()
        return TimedAverageResult(
            round(energy / covered_seconds, 6),
            round(ratio, 6),
            self.samples[-1].source_valid,
        )

    def to_payload(self) -> dict[str, object]:
        """Return storage-safe state; configuration supplies the duration."""
        return {
            "samples": [
                {
                    "at": sample.at.isoformat(),
                    "value": sample.value,
                    "source_valid": sample.source_valid,
                }
                for sample in self.samples
            ]
        }

    def restore(self, payload: object, now: datetime) -> None:
        """Restore only ordered, timezone-aware, recent samples."""
        _validate_datetime(now)
        restored: list[TimedSample] = []
        if isinstance(payload, dict) and isinstance(payload.get("samples"), list):
            try:
                for item in payload["samples"]:
                    if not isinstance(item, dict):
                        raise ValueError
                    at = datetime.fromisoformat(str(item["at"]))
                    value = float(item["value"])
                    valid = item["source_valid"]
                    _validate_datetime(at)
                    if not isfinite(value) or not isinstance(valid, bool):
                        raise ValueError
                    if at > now or (restored and at <= restored[-1].at):
                        raise ValueError
                    restored.append(TimedSample(at, value, valid))
            except (KeyError, TypeError, ValueError):
                restored = []
        self.samples = restored
        self._prune(now)

    def _prune(self, now: datetime) -> None:
        cutoff = now - self.duration
        while len(self.samples) > 1 and self.samples[1].at <= cutoff:
            self.samples.pop(0)


def _validate_datetime(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("sample times must be timezone-aware")
