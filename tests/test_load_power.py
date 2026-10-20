"""State-qualified load presentation and explicit energy-balance regressions."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.load_power import split_house_ev_load
from custom_components.home_energy_orchestrator.telemetry import (
    SiteTelemetrySources,
    TelemetryNormalizationConfiguration,
    TelemetrySource,
    normalize_site_telemetry,
)
from custom_components.home_energy_orchestrator.telemetry_adapter import (
    TelemetryEntityIds,
    capture_site_telemetry,
    display_ev_current_a,
)

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.mark.parametrize("includes_ev,expected", [(True, 2.19), (False, 5.46)])
def test_fleet_house_split_subtracts_measured_ev_exactly_once(includes_ev, expected):
    result = split_house_ev_load(
        house_kw=5.46,
        includes_ev=includes_ev,
        ev_configured=True,
        current_a=15,
        voltage_v=218,
        phase_count=1,
    )
    assert result.ev_power_kw == pytest.approx(3.27)
    assert result.house_power_kw == pytest.approx(expected)


@pytest.mark.parametrize("house_kw", [-4.5, float("nan"), float("inf"), None])
def test_invalid_house_input_is_not_hidden_as_zero_or_absolute_value(house_kw):
    result = split_house_ev_load(
        house_kw=house_kw,
        includes_ev=False,
        ev_configured=False,
        current_a=None,
        voltage_v=None,
        phase_count=None,
    )
    assert result.house_power_kw is None


def sources(grid=3500, solar=4920, battery=7990, house=-4500):
    def power(name, value):
        return TelemetrySource("sensor." + name, value, "W", NOW)

    return SiteTelemetrySources(
        grid_power=power("grid", grid),
        signed_battery_power=power("battery", battery),
        battery_charge_power=None,
        battery_discharge_power=None,
        solar_power=power("solar", solar),
        house_load=power("house", house),
        site_grid_current=None,
    )


def config(method="sensor"):
    return TelemetryNormalizationConfiguration(
        max_age_seconds=90,
        grid_power_direction="positive_import",
        battery_power_direction="positive_charge",
        solar_configured=True,
        solar_generation_direction="generation_positive",
        site_grid_current_direction="positive_import",
        site_phase_count=1,
        voltage_v=230,
        house_load_source=method,
    )


def test_native_negative_house_source_is_invalid_with_raw_provenance_retained():
    result = normalize_site_telemetry(sources(), config(), now=NOW).house_load
    assert result.value is None and result.valid is False
    assert result.reason == "negative_house_load"
    assert result.sources[0].raw_value == -4500


@pytest.mark.parametrize(
    "grid,solar,battery,expected",
    [
        (3500, 4920, 7990, 0.43),  # external AC solar plus grid charging
        (500, 0, 0, 0.5),  # night grid supply
        (0, 0, -1500, 1.5),  # battery self use
        (-3000, 4000, 0, 1),  # solar export
        (-2000, 0, -3000, 1),  # battery export
        (0, 4000, 3000, 1),  # solar battery charging
    ],
)
def test_explicit_balance_uses_signed_flows_not_the_broken_native_load(
    grid,
    solar,
    battery,
    expected,
):
    result = normalize_site_telemetry(
        sources(grid, solar, battery),
        config("power_balance"),
        now=NOW,
    ).house_load
    assert result.value == pytest.approx(expected)
    assert result.valid and result.fresh
    assert result.reason == "derived_from_power_balance"
    assert {s.entity_id for s in result.sources} == {
        "sensor.grid",
        "sensor.solar",
        "sensor.battery",
    }


@pytest.mark.parametrize("field", ["grid_power", "solar_power", "signed_battery_power"])
def test_balance_does_not_promote_stale_dependencies_to_fresh_house_load(field):
    from dataclasses import replace

    value = sources()
    stale = replace(getattr(value, field), updated_at=NOW - timedelta(minutes=20))
    result = normalize_site_telemetry(
        replace(value, **{field: stale}),
        config("power_balance"),
        now=NOW,
    ).house_load
    assert result.value is None and not result.valid


def test_balance_does_not_turn_impossible_result_positive():
    result = normalize_site_telemetry(
        sources(grid=3500, solar=0, battery=8000),
        config("power_balance"),
        now=NOW,
    ).house_load
    assert result.value is None and result.reason == "negative_house_load"


@pytest.mark.parametrize("mode", ["power_balance", "power_balance_cloud_solar"])
def test_whole_site_balance_topology_and_return_to_sensor_preserve_saved_flag(mode):
    saved = {"house_load_source": mode, "house_load_includes_ev": False, "configure_ev": True}
    assert RuntimeConfiguration.from_mapping(saved).house.load_includes_ev is True
    assert saved["house_load_includes_ev"] is False
    saved["house_load_source"] = "sensor"
    assert RuntimeConfiguration.from_mapping(saved).house.load_includes_ev is False


@pytest.mark.parametrize(
    "age,accepted", [(90, True), (91, True), (300, True), (600, True), (601, False)]
)
def test_cloud_solar_bound_is_explicit_and_does_not_relax_canonical_solar(age, accepted):
    raw = sources()
    solar = replace(raw.solar_power, updated_at=NOW - timedelta(seconds=age))
    raw = replace(raw, solar_power=solar)
    result = normalize_site_telemetry(raw, config("power_balance_cloud_solar"), now=NOW)
    assert result.house_load.valid is accepted
    assert result.solar_power.fresh is (age <= 90)
    fast = normalize_site_telemetry(raw, config("power_balance"), now=NOW)
    assert fast.house_load.valid is (age <= 90)
    if accepted:
        assert result.house_load.updated_at == solar.updated_at


@pytest.mark.parametrize("field", ["grid_power", "signed_battery_power"])
def test_cloud_profile_keeps_fast_local_dependencies_at_original_age(field):
    raw = sources()
    raw = replace(
        raw, **{field: replace(getattr(raw, field), updated_at=NOW - timedelta(seconds=91))}
    )
    result = normalize_site_telemetry(raw, config("power_balance_cloud_solar"), now=NOW)
    assert result.house_load.value is None


@pytest.mark.parametrize("field", ["grid_power", "solar_power", "signed_battery_power"])
@pytest.mark.parametrize("failure", ["future", "missing", "unit", "unavailable"])
def test_balance_rejects_invalid_dependency_instead_of_zero(field, failure):
    raw = sources()
    changes = {
        "future": {"updated_at": NOW + timedelta(seconds=1)},
        "missing": {"updated_at": None},
        "unit": {"raw_unit": "kWh"},
        "unavailable": {"raw_value": "unavailable"},
    }[failure]
    raw = replace(raw, **{field: replace(getattr(raw, field), **changes)})
    assert (
        normalize_site_telemetry(raw, config("power_balance_cloud_solar"), now=NOW).house_load.value
        is None
    )


def test_balance_capture_rejects_restored_dependencies(hass):
    ids = TelemetryEntityIds("sensor.grid", None, None, None, None, None, None)
    hass.states.async_set("sensor.grid", "1", {"unit_of_measurement": "kW", "restored": True})
    result = capture_site_telemetry(hass, ids, balance_mode=True)
    assert result.grid_power.raw_value is None and result.grid_power.updated_at is None


@pytest.mark.parametrize(
    "charging", ["stopped", "complete", "disconnected", "no_power", "starting"]
)
def test_explicit_fresh_stopped_state_is_zero_even_if_actual_current_retained(
    hass, freezer, charging
):
    freezer.move_to(NOW)
    hass.states.async_set("sensor.charging", charging)
    hass.states.async_set("sensor.actual", "15", {"unit_of_measurement": "A"})
    assert (
        display_ev_current_a(hass, "sensor.charging", "sensor.actual", now=NOW, max_age_seconds=90)
        == 0
    )


@pytest.mark.parametrize("failure", ["stale", "future", "restored", "unknown", "unavailable"])
def test_unqualified_charging_state_is_unknown_not_zero(hass, freezer, failure):
    freezer.move_to(NOW - timedelta(seconds=91) if failure == "stale" else NOW)
    hass.states.async_set(
        "sensor.charging",
        failure if failure in {"unknown", "unavailable"} else "charging",
        {"restored": failure == "restored"},
    )
    hass.states.async_set("sensor.actual", "15", {"unit_of_measurement": "A"})
    test_now = NOW - timedelta(seconds=1) if failure == "future" else NOW
    assert (
        display_ev_current_a(
            hass, "sensor.charging", "sensor.actual", now=test_now, max_age_seconds=90
        )
        is None
    )


@pytest.mark.parametrize(
    "value,unit,expected",
    [
        ("15", "A", 15),
        ("15000", "mA", 15),
        ("nan", "A", None),
        ("-1", "A", None),
        ("15", "W", None),
    ],
)
def test_display_actual_current_units_and_retention(hass, freezer, value, unit, expected):
    freezer.move_to(NOW - timedelta(hours=10))
    hass.states.async_set("sensor.actual", value, {"unit_of_measurement": unit})
    freezer.move_to(NOW)
    hass.states.async_set("sensor.charging", "charging")
    assert (
        display_ev_current_a(hass, "sensor.charging", "sensor.actual", now=NOW, max_age_seconds=90)
        == expected
    )


@pytest.mark.parametrize("phase,expected", [(1, 3.68), (3, 11.04)])
def test_display_phase_power_is_estimated_not_the_requested_current(phase, expected):
    result = split_house_ev_load(
        house_kw=15,
        includes_ev=True,
        ev_configured=True,
        current_a=16,
        voltage_v=230,
        phase_count=phase,
    )
    assert result.ev_power_kw == pytest.approx(expected)
    assert result.house_power_kw == pytest.approx(15 - expected)


def test_impossible_split_is_not_zero_and_no_ev_site_needs_no_ev_helpers():
    result = split_house_ev_load(
        house_kw=1, includes_ev=True, ev_configured=True, current_a=15, voltage_v=230, phase_count=1
    )
    assert result.house_power_kw is None and result.reason == "ev_exceeds_total_house_load"
    result = split_house_ev_load(
        house_kw=1,
        includes_ev=True,
        ev_configured=False,
        current_a=None,
        voltage_v=None,
        phase_count=None,
    )
    assert result.house_power_kw == 1 and result.ev_power_kw == 0
