"""Golden sign/unit vectors from the pilot and reversed-CT test site."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.telemetry import (
    TelemetrySource,
    battery_power_from_magnitudes_or_signed,
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


@pytest.mark.parametrize(
    ("charge_kw", "charge_age", "discharge_kw", "discharge_age", "signed_raw", "expected"),
    [
        (9.713, 0, 0, 650, -9.713, 9.713),
        (0, 650, 4.2, 0, 4.2, -4.2),
    ],
)
def test_stale_inactive_magnitude_uses_fresh_signed_battery(
    charge_kw: float,
    charge_age: float,
    discharge_kw: float,
    discharge_age: float,
    signed_raw: float,
    expected: float,
) -> None:
    """A steady zero must not strand recovered same-inverter telemetry."""
    charge = power(
        "sensor.battery_charge", charge_kw, "kW", age_seconds=charge_age
    )
    discharge = power(
        "sensor.battery_discharge", discharge_kw, "kW", age_seconds=discharge_age
    )
    signed = power("sensor.invbatpower", signed_raw, "kW", multiplier=-1)

    battery = battery_power_from_magnitudes_or_signed(charge, discharge, signed)

    assert battery.value == expected
    assert battery.valid is True
    assert battery.fresh is True
    assert battery.reason == "signed_fallback_pair_stale"
    assert [source.entity_id for source in battery.sources] == [
        "sensor.battery_charge",
        "sensor.battery_discharge",
        "sensor.invbatpower",
    ]


def test_fresh_pair_keeps_priority_over_signed_battery() -> None:
    charge = power("sensor.battery_charge", 0, "kW")
    discharge = power("sensor.battery_discharge", 3, "kW")
    signed = power("sensor.invbatpower", 99, "kW")

    battery = battery_power_from_magnitudes_or_signed(charge, discharge, signed)

    assert battery.value == -3
    assert battery.reason == "ok"
    assert len(battery.sources) == 2


def test_genuine_stale_or_disconnected_battery_telemetry_stays_unavailable() -> None:
    stale_charge = power("sensor.battery_charge", 2, "kW", age_seconds=650)
    stale_discharge = power("sensor.battery_discharge", 0, "kW", age_seconds=650)
    stale_signed = power("sensor.invbatpower", -2, "kW", multiplier=-1, age_seconds=650)
    disconnected_charge = normalize_power_sample(
        TelemetrySource("sensor.battery_charge", "unavailable", "kW", NOW),
        now=NOW,
        max_age_seconds=90,
        multiplier=1,
        positive_direction="positive_magnitude",
    )
    fresh_signed = power("sensor.invbatpower", -2, "kW", multiplier=-1)

    assert (
        battery_power_from_magnitudes_or_signed(
            stale_charge, stale_discharge, stale_signed
        ).value
        is None
    )
    disconnected = battery_power_from_magnitudes_or_signed(
        disconnected_charge,
        power("sensor.battery_discharge", 0, "kW"),
        fresh_signed,
    )
    assert disconnected.value is None
    assert disconnected.reason == "charge_source_unavailable"


def test_invalid_magnitude_is_not_hidden_by_signed_fallback() -> None:
    negative = power("sensor.battery_charge", -1, "kW")
    stale_discharge = power("sensor.battery_discharge", 0, "kW", age_seconds=650)
    signed = power("sensor.invbatpower", -1, "kW", multiplier=-1)

    battery = battery_power_from_magnitudes_or_signed(negative, stale_discharge, signed)

    assert battery.value is None
    assert battery.reason == "negative_magnitude"
