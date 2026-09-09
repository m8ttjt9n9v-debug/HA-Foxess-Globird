"""Golden sign/unit vectors from the pilot and reversed-CT test site."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.telemetry import (
    TelemetrySource,
    combine_battery_magnitudes,
    normalize_current_sample,
    normalize_power_sample,
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def power(
    entity_id: str,
    value: float,
    unit: str,
    *,
    multiplier: float = 1,
    age_seconds: float = 0,
):
    return normalize_power_sample(
        TelemetrySource(entity_id, value, unit, NOW - timedelta(seconds=age_seconds)),
        now=NOW,
        max_age_seconds=90,
        multiplier=multiplier,
        positive_direction="canonical",
    )


def test_working_single_phase_pilot_vectors_are_preserved() -> None:
    """Pilot grid is export-positive; split battery is charge-minus-discharge."""
    grid = power("sensor.grid_ct", 4.5, "kW", multiplier=-1)
    charge = power("sensor.battery_charge", 0.2, "kW")
    discharge = power("sensor.battery_discharge", 5.2, "kW")
    battery = combine_battery_magnitudes(charge, discharge)
    solar = power("sensor.pv_power", 200, "W")

    assert grid.value == -4.5  # canonical negative means export
    assert battery.value == -5.0  # canonical negative means discharge
    assert solar.value == 0.2  # canonical positive means generation


def test_reversed_ct_and_signed_foxess_battery_vectors() -> None:
    """Observed FoxESS CT2 and InvBatPower directions normalize independently."""
    grid = power("sensor.grid_ct", 4.495, "kW", multiplier=-1)
    battery = power("sensor.invbatpower", 5.237, "kW", multiplier=-1)
    solar = power("sensor.ct2_meter", -0.8, "kW", multiplier=-1)
    current = normalize_current_sample(
        TelemetrySource("sensor.phase_current", 20, "A", NOW),
        now=NOW,
        max_age_seconds=90,
        multiplier=-1,
        positive_direction="positive_import",
    )

    assert grid.value == -4.495
    assert battery.value == -5.237
    assert solar.value == 0.8
    assert current.value == -20


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [(1200, "W", 1.2), (1.2, "kW", 1.2), (0.0012, "MW", 1.2)],
)
def test_power_units_are_converted_once(value, unit, expected) -> None:
    assert power("sensor.power", value, unit).value == expected


def test_stale_and_future_samples_fail_closed_but_keep_provenance() -> None:
    stale = power("sensor.power", 1, "kW", age_seconds=91)
    future = normalize_power_sample(
        TelemetrySource("sensor.power", 1, "kW", NOW + timedelta(seconds=1)),
        now=NOW,
        max_age_seconds=90,
        multiplier=1,
        positive_direction="positive_import",
    )

    assert stale.value is None
    assert stale.valid is True
    assert stale.fresh is False
    assert stale.reason == "stale"
    assert stale.sources[0].raw_value == 1
    assert future.value is None
    assert future.reason == "future_timestamp"


def test_split_battery_requires_two_nonnegative_magnitudes() -> None:
    missing = power("sensor.battery_discharge", 1, "A")
    negative = power("sensor.battery_charge", -1, "kW")
    discharge = power("sensor.battery_discharge", 1, "kW")

    assert combine_battery_magnitudes(missing, discharge).value is None
    assert combine_battery_magnitudes(negative, discharge).reason == "negative_magnitude"
