"""Canonical, timestamp-aware telemetry normalization.

All planners and entities consume this model. Raw Home Assistant sensor signs
must never escape this boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from .const import (
    BATTERY_POSITIVE_CHARGE,
    GRID_POSITIVE_IMPORT,
    SOLAR_GENERATION_POSITIVE,
)
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


@dataclass(frozen=True, slots=True)
class SiteTelemetrySources:
    """Raw Home Assistant observations captured together for one cycle."""

    grid_power: TelemetrySource | None
    signed_battery_power: TelemetrySource | None
    battery_charge_power: TelemetrySource | None
    battery_discharge_power: TelemetrySource | None
    solar_power: TelemetrySource | None
    house_load: TelemetrySource | None
    site_grid_current: TelemetrySource | None
    phase_grid_power: tuple[TelemetrySource | None, ...] = ()
    phase_grid_voltage: tuple[TelemetrySource | None, ...] = ()


@dataclass(frozen=True, slots=True)
class TelemetryNormalizationConfiguration:
    """Immutable sign, freshness and fallback configuration."""

    max_age_seconds: float
    grid_power_direction: str
    battery_power_direction: str
    solar_configured: bool
    solar_generation_direction: str
    site_grid_current_direction: str
    site_phase_count: float | None
    voltage_v: float | None


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


def most_loaded_phase_current(
    powers: tuple[TelemetrySource | None, ...],
    voltages: tuple[TelemetrySource | None, ...],
    *,
    now: datetime,
    max_age_seconds: float,
    power_positive_direction: str,
) -> NormalizedSample:
    """Derive import-positive grid current from three matched CT/voltage pairs.

    Aggregate three-phase kW cannot reveal the most-loaded phase. A missing,
    stale, or implausible reading on *any* phase therefore blocks this source.
    """
    raw_sources = tuple(source for source in (*powers, *voltages) if source is not None)
    if len(powers) != 3 or len(voltages) != 3 or len(raw_sources) != 6:
        return unavailable_sample(
            unit="A", positive_direction=GRID_POSITIVE_IMPORT,
            reason="incomplete_phase_mapping", sources=raw_sources,
        )
    sign = 1.0 if power_positive_direction == GRID_POSITIVE_IMPORT else -1.0
    currents: list[float] = []
    for power_source, voltage_source in zip(powers, voltages, strict=True):
        assert power_source is not None and voltage_source is not None
        power = normalize_power_sample(
            power_source, now=now, max_age_seconds=max_age_seconds,
            multiplier=sign, positive_direction=GRID_POSITIVE_IMPORT,
        )
        voltage = normalize_sample(
            voltage_source, now=now, max_age_seconds=max_age_seconds,
            converter=lambda value, unit: value if unit == "V" else float("nan"),
            unit="V", multiplier=1.0, positive_direction="positive_voltage",
        )
        if power.value is None or voltage.value is None:
            return unavailable_sample(
                unit="A", positive_direction=GRID_POSITIVE_IMPORT,
                reason=f"phase_{power.reason if power.value is None else voltage.reason}",
                sources=raw_sources,
            )
        if not 180 <= voltage.value <= 300:
            return unavailable_sample(
                unit="A", positive_direction=GRID_POSITIVE_IMPORT,
                reason="implausible_phase_voltage", sources=raw_sources,
            )
        currents.append(power.value * 1000 / voltage.value)
    return NormalizedSample(
        value=max(currents), unit="A", sources=raw_sources,
        positive_direction=GRID_POSITIVE_IMPORT, valid=True, fresh=True,
        reason="derived_from_phase_grid_power_and_voltage",
    )


def combine_battery_magnitudes(
    charge: NormalizedSample, discharge: NormalizedSample
) -> NormalizedSample:
    """Preserve the pilot convention: positive charge minus discharge."""
    sources = (*charge.sources, *discharge.sources)
    if (charge.value is not None and charge.value < 0) or (
        discharge.value is not None and discharge.value < 0
    ):
        return unavailable_sample(
            unit="kW",
            positive_direction="positive_charge",
            reason="negative_magnitude",
            sources=sources,
        )
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
    return NormalizedSample(
        value=charge.value - discharge.value,
        unit="kW",
        sources=sources,
        positive_direction="positive_charge",
        valid=charge.valid and discharge.valid,
        fresh=charge.fresh and discharge.fresh,
        reason="ok",
    )


def battery_power_from_magnitudes_or_signed(
    charge: NormalizedSample,
    discharge: NormalizedSample,
    signed: NormalizedSample,
) -> NormalizedSample:
    """Prefer the pilot pair, with a bounded fresh signed fallback."""
    paired = combine_battery_magnitudes(charge, discharge)
    if paired.value is not None:
        return paired
    if paired.reason == "negative_magnitude":
        return paired

    pair_reasons = {charge.reason, discharge.reason}
    stale_pair_only = "stale" in pair_reasons and pair_reasons <= {"ok", "stale"}
    if (
        stale_pair_only
        and signed.value is not None
        and signed.valid
        and signed.fresh
    ):
        return NormalizedSample(
            value=signed.value,
            unit="kW",
            sources=(*paired.sources, *signed.sources),
            positive_direction="positive_charge",
            valid=True,
            fresh=True,
            reason="signed_fallback_pair_stale",
        )
    return paired


def _configured_power_sample(
    source: TelemetrySource | None,
    *,
    now: datetime,
    max_age_seconds: float,
    direction: str,
    positive_direction: str,
) -> NormalizedSample:
    if source is None:
        return unavailable_sample(
            unit="kW",
            positive_direction=positive_direction,
            reason="not_configured",
        )
    return normalize_power_sample(
        source,
        now=now,
        max_age_seconds=max_age_seconds,
        multiplier=1.0 if direction == positive_direction else -1.0,
        positive_direction=positive_direction,
    )


def normalize_site_telemetry(
    sources: SiteTelemetrySources,
    configuration: TelemetryNormalizationConfiguration,
    *,
    now: datetime,
) -> NormalizedTelemetry:
    """Build the canonical signed telemetry surface from captured sources."""
    grid = _configured_power_sample(
        sources.grid_power,
        now=now,
        max_age_seconds=configuration.max_age_seconds,
        direction=configuration.grid_power_direction,
        positive_direction=GRID_POSITIVE_IMPORT,
    )
    signed_battery = _configured_power_sample(
        sources.signed_battery_power,
        now=now,
        max_age_seconds=configuration.max_age_seconds,
        direction=configuration.battery_power_direction,
        positive_direction=BATTERY_POSITIVE_CHARGE,
    )
    if (
        sources.battery_charge_power is not None
        or sources.battery_discharge_power is not None
    ):
        charge = (
            normalize_power_sample(
                sources.battery_charge_power,
                now=now,
                max_age_seconds=configuration.max_age_seconds,
                multiplier=1.0,
                positive_direction="positive_magnitude",
            )
            if sources.battery_charge_power is not None
            else unavailable_sample(
                unit="kW",
                positive_direction="positive_magnitude",
                reason="not_configured",
            )
        )
        discharge = (
            normalize_power_sample(
                sources.battery_discharge_power,
                now=now,
                max_age_seconds=configuration.max_age_seconds,
                multiplier=1.0,
                positive_direction="positive_magnitude",
            )
            if sources.battery_discharge_power is not None
            else unavailable_sample(
                unit="kW",
                positive_direction="positive_magnitude",
                reason="not_configured",
            )
        )
        battery = battery_power_from_magnitudes_or_signed(
            charge, discharge, signed_battery
        )
    else:
        battery = signed_battery

    solar = (
        _configured_power_sample(
            sources.solar_power,
            now=now,
            max_age_seconds=configuration.max_age_seconds,
            direction=configuration.solar_generation_direction,
            positive_direction=SOLAR_GENERATION_POSITIVE,
        )
        if configuration.solar_configured
        else NormalizedSample(
            value=0.0,
            unit="kW",
            sources=(),
            positive_direction=SOLAR_GENERATION_POSITIVE,
            valid=True,
            fresh=True,
            reason="configured_absent",
        )
    )
    house = _configured_power_sample(
        sources.house_load,
        now=now,
        max_age_seconds=configuration.max_age_seconds,
        direction="positive_consumption",
        positive_direction="positive_consumption",
    )

    current = None
    if sources.site_grid_current is not None:
        current = normalize_current_sample(
            sources.site_grid_current,
            now=now,
            max_age_seconds=configuration.max_age_seconds,
            multiplier=(
                1.0
                if configuration.site_grid_current_direction
                == GRID_POSITIVE_IMPORT
                else -1.0
            ),
            positive_direction=GRID_POSITIVE_IMPORT,
        )
    if (current is None or current.value is None) and any(sources.phase_grid_power):
        current = most_loaded_phase_current(
            sources.phase_grid_power,
            sources.phase_grid_voltage,
            now=now,
            max_age_seconds=configuration.max_age_seconds,
            power_positive_direction=configuration.site_grid_current_direction,
        )
    if (current is None or current.value is None) and grid.value is not None:
        phase_count = configuration.site_phase_count
        if (
            phase_count is None
            or not isfinite(phase_count)
            or phase_count < 1
            or not phase_count.is_integer()
        ):
            raise ValueError("site phase count must be a positive integer")
    else:
        phase_count = configuration.site_phase_count
    if (
        (current is None or current.value is None)
        and phase_count == 1
        and grid.value is not None
    ):
        voltage = configuration.voltage_v
        if voltage is None or not isfinite(voltage):
            raise ValueError("voltage must be finite")
        current = (
            NormalizedSample(
                value=grid.value * 1000 / voltage,
                unit="A",
                sources=(
                    *(current.sources if current is not None else ()),
                    *grid.sources,
                ),
                positive_direction=GRID_POSITIVE_IMPORT,
                valid=grid.valid,
                fresh=grid.fresh,
                reason=(
                    "derived_from_grid_power"
                    if sources.site_grid_current is None
                    else "derived_from_grid_power_current_fallback"
                ),
            )
            if voltage > 0
            else unavailable_sample(
                unit="A",
                positive_direction=GRID_POSITIVE_IMPORT,
                reason="invalid_voltage",
                sources=grid.sources,
            )
        )
    if current is None:
        current = unavailable_sample(
            unit="A",
            positive_direction=GRID_POSITIVE_IMPORT,
            reason="multiphase_mapping_required",
        )
    return NormalizedTelemetry(grid, battery, solar, house, current)
