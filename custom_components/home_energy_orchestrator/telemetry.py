"""Canonical, timestamp-aware telemetry normalization.

All planners and entities consume this model. Raw Home Assistant sensor signs
must never escape this boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from .normalise import current_to_a, power_to_kw


@dataclass(frozen=True, slots=True)
class TelemetrySource:
    """Raw evidence retained for commissioning and diagnostics."""

    entity_id: str
    raw_value: object
    raw_unit: str | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class NormalizedSample:
    """One quantity in HEO's canonical sign and unit convention."""

    value: float | None
    unit: str
    sources: tuple[TelemetrySource, ...]
    positive_direction: str
    valid: bool
    fresh: bool
    reason: str

    @property
    def updated_at(self) -> datetime | None:
        """Return the newest source timestamp, for coherent-sample checks."""
        timestamps = [source.updated_at for source in self.sources if source.updated_at]
        return max(timestamps) if timestamps else None


@dataclass(frozen=True, slots=True)
class NormalizedTelemetry:
    """The only signed power/current surface used by HEO runtime code."""

    grid_power: NormalizedSample
    battery_power: NormalizedSample
    solar_power: NormalizedSample
    house_load: NormalizedSample
    site_grid_current: NormalizedSample


def unavailable_sample(
    *, unit: str, positive_direction: str, reason: str, sources: tuple[TelemetrySource, ...] = ()
) -> NormalizedSample:
    """Construct an explicit invalid sample instead of inventing zero."""
    return NormalizedSample(
        value=None,
        unit=unit,
        sources=sources,
        positive_direction=positive_direction,
        valid=False,
        fresh=False,
        reason=reason,
    )


def normalize_sample(
    source: TelemetrySource,
    *,
    now: datetime,
    max_age_seconds: float,
    converter: Callable[[float, str | None], float],
    unit: str,
    multiplier: float,
    positive_direction: str,
) -> NormalizedSample:
    """Convert unit/sign once and reject missing, stale, or future evidence."""
    if source.raw_value in (None, "", "unknown", "unavailable"):
        return unavailable_sample(
            unit=unit,
            positive_direction=positive_direction,
            reason="source_unavailable",
            sources=(source,),
        )
    try:
        raw = float(source.raw_value)
        value = converter(raw, source.raw_unit) * multiplier
    except (TypeError, ValueError):
        return unavailable_sample(
            unit=unit,
            positive_direction=positive_direction,
            reason="invalid_value_or_unit",
            sources=(source,),
        )
    if not isfinite(value):
        return unavailable_sample(
            unit=unit,
            positive_direction=positive_direction,
            reason="non_finite_value",
            sources=(source,),
        )
    if source.updated_at is None:
        return unavailable_sample(
            unit=unit,
            positive_direction=positive_direction,
            reason="missing_timestamp",
            sources=(source,),
        )
    age = (now - source.updated_at).total_seconds()
    if age < 0:
        return NormalizedSample(
            value=None,
            unit=unit,
            sources=(source,),
            positive_direction=positive_direction,
            valid=True,
            fresh=False,
            reason="future_timestamp",
        )
    if age > max_age_seconds:
        return NormalizedSample(
            value=None,
            unit=unit,
            sources=(source,),
            positive_direction=positive_direction,
            valid=True,
            fresh=False,
            reason="stale",
        )
    return NormalizedSample(
        value=value,
        unit=unit,
        sources=(source,),
        positive_direction=positive_direction,
        valid=True,
        fresh=True,
        reason="ok",
    )


def normalize_power_sample(
    source: TelemetrySource,
    *,
    now: datetime,
    max_age_seconds: float,
    multiplier: float,
    positive_direction: str,
) -> NormalizedSample:
    """Return a canonical kW power sample."""
    return normalize_sample(
        source,
        now=now,
        max_age_seconds=max_age_seconds,
        converter=power_to_kw,
        unit="kW",
        multiplier=multiplier,
        positive_direction=positive_direction,
    )


def normalize_current_sample(
    source: TelemetrySource,
    *,
    now: datetime,
    max_age_seconds: float,
    multiplier: float,
    positive_direction: str,
) -> NormalizedSample:
    """Return a canonical ampere current sample."""
    return normalize_sample(
        source,
        now=now,
        max_age_seconds=max_age_seconds,
        converter=current_to_a,
        unit="A",
        multiplier=multiplier,
        positive_direction=positive_direction,
    )


def combine_battery_magnitudes(
    charge: NormalizedSample, discharge: NormalizedSample
) -> NormalizedSample:
    """Preserve the pilot convention: positive charge minus discharge."""
    sources = (*charge.sources, *discharge.sources)
    if charge.value is None or discharge.value is None:
        reason = (
            f"charge_{charge.reason}"
            if charge.value is None
            else f"discharge_{discharge.reason}"
        )
        return unavailable_sample(
            unit="kW",
            positive_direction="positive_charge",
            reason=reason,
            sources=sources,
        )
    if charge.value < 0 or discharge.value < 0:
        return unavailable_sample(
            unit="kW",
            positive_direction="positive_charge",
            reason="negative_magnitude",
            sources=sources,
        )
    return NormalizedSample(
        value=charge.value - discharge.value,
        unit="kW",
        sources=sources,
        positive_direction="positive_charge",
        valid=charge.valid and discharge.valid,
        fresh=charge.fresh and discharge.fresh,
        reason="ok",
    )
