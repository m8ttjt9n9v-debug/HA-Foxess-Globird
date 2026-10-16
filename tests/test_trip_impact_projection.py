"""The read-only display uses the selected scheduler without changing its intent."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.util import dt as dt_util

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.planner.trip_charge import (
    calculate_trip_charge_plan,
)
from custom_components.home_energy_orchestrator.trip_impact import build_trip_energy_impact

NOW = datetime(2026, 10, 16, 13, tzinfo=UTC)


@pytest.fixture
async def impact_trip(hass, freezer):
    freezer.move_to(NOW)
    await hass.config.async_set_time_zone("Australia/Sydney")
    runtime = RuntimeConfiguration.from_mapping({
        "free_charge_window_start": "11:00:00", "free_charge_window_end": "14:00:00",
        "peak_window_start": "16:00:00", "peak_window_end": "23:00:00",
        "peak_rate_per_kwh": 0.6, "shoulder_rate_per_kwh": 0.3,
        "discharge_efficiency_percent": 90,
    })
    inputs = dict(
        departure=NOW + timedelta(hours=14), target_soc=80, soc=20,
        capacity_kwh=60, maximum_power_kw=4, efficiency_percent=90,
        extra_minutes=0, maximum_hours=16,
    )
    return SimpleNamespace(
        hass=hass, armed=False, owns_full=False,
        coordinator=SimpleNamespace(
            runtime_config=runtime, ev_controller=object(), learning_remaining_kwh=8,
            data=SimpleNamespace(available_after_floor_kwh=20),
            last_update_success=True,
            telemetry=SimpleNamespace(**{
                name: SimpleNamespace(valid=True, fresh=True, value=0.5)
                for name in ("grid_power", "battery_power", "house_load")
            }),
        ),
        _current_plan_inputs=lambda: dict(inputs),
        _plan=calculate_trip_charge_plan(**inputs), inputs=inputs,
    )


def _legacy(trip, **changes):
    inputs = {**trip.inputs, **changes}
    plan = calculate_trip_charge_plan(**inputs)
    states = trip.hass.states
    states.async_set("input_boolean.heo_trip_charge_scheduled", "on")
    states.async_set("input_boolean.heo_trip_charge_started", "off")
    states.async_set("input_datetime.heo_trip_ready_by", "chosen", {
        "timestamp": inputs["departure"].timestamp(),
    })
    states.async_set("input_select.heo_trip_target_soc", f"{inputs['target_soc']}%")
    for key, entity in (
        ("efficiency_percent", "input_number.heo_trip_charge_efficiency"),
        ("extra_minutes", "input_number.heo_trip_extra_minutes"),
        ("maximum_hours", "input_number.heo_trip_override_timeout"),
    ):
        states.async_set(entity, str(inputs[key]))
    values = {
        "v": 2, "due": inputs["departure"].timestamp(), "target": inputs["target_soc"],
        "soc": inputs["soc"], "cap": inputs["capacity_kwh"], "kw": inputs["maximum_power_kw"],
        "eff": inputs["efficiency_percent"], "extra": inputs["extra_minutes"],
        "maximum": inputs["maximum_hours"], "start": plan.planned_start.timestamp(),
    }
    states.async_set("sensor.heo_trip_charge_plan", json.dumps(values))
    return values


async def test_native_projection_uses_floor_not_extra_reserve_and_same_plan(impact_trip):
    trip = impact_trip
    result = build_trip_energy_impact(trip)
    assert result["source"] == "native" and result["status"] == "estimated"
    assert result["wall_energy_kwh"] == pytest.approx(40)
    assert result["battery_available_for_ev_kwh"] == pytest.approx(20 * 0.9 - 8)
    assert result["charging_start"] == trip._plan.planned_start.isoformat()
    assert result["scope"] == "before_next_free_window_only"
    json.dumps(result, allow_nan=False)


async def test_legacy_request_is_displayed_without_adopting_native_ownership(impact_trip):
    trip = impact_trip
    _legacy(trip, target_soc=60)
    original = (trip.armed, trip.owns_full, trip._plan, dict(trip.inputs))
    result = build_trip_energy_impact(trip)
    assert result["source"] == "legacy" and result["status"] == "estimated"
    assert result["wall_energy_kwh"] == pytest.approx(60 * 0.4 / 0.9)
    assert original == (trip.armed, trip.owns_full, trip._plan, trip.inputs)


@pytest.mark.parametrize("problem", ["target", "soc", "start", "version", "json", "helper"])
async def test_stale_mismatched_or_invalid_legacy_plan_never_becomes_zero_cost(
    impact_trip, problem,
):
    trip = impact_trip
    values = _legacy(trip)
    if problem == "helper":
        trip.hass.states.async_set("input_number.heo_trip_charge_efficiency", "unknown")
    else:
        if problem in {"target", "soc", "start"}:
            values[problem] += 1
        if problem == "version":
            values["v"] = True
        trip.hass.states.async_set(
            "sensor.heo_trip_charge_plan", "bad json" if problem == "json" else json.dumps(values),
        )
    result = build_trip_energy_impact(trip)
    assert result["status"] == "unavailable"
    assert result.get("cost_min") is None


async def test_native_request_has_priority_over_legacy_preview(impact_trip):
    trip = impact_trip
    _legacy(trip, target_soc=60)
    trip.armed = True
    assert build_trip_energy_impact(trip)["source"] == "native"


async def test_missing_budgets_and_invalid_tariffs_are_not_free(impact_trip):
    trip = impact_trip
    trip.coordinator.learning_remaining_kwh = None
    assert build_trip_energy_impact(trip)["cost_min"] is None
    trip.coordinator.learning_remaining_kwh = 8
    runtime = trip.coordinator.runtime_config
    trip.coordinator.runtime_config = replace(
        runtime, nonnegative=replace(runtime.nonnegative, shoulder_rate_per_kwh=None),
    )
    assert build_trip_energy_impact(trip)["status"] == "unavailable"
    trip.coordinator.data = None
    assert build_trip_energy_impact(trip)["reason"] == "energy_budget_unavailable"


async def test_projection_has_no_service_calls_or_state_writes(impact_trip):
    trip = impact_trip
    before = list(trip.hass.states.async_all())
    for _ in range(4):
        assert build_trip_energy_impact(trip)["status"] == "estimated"
    await trip.hass.async_block_till_done()
    assert list(trip.hass.states.async_all()) == before


async def test_in_free_window_does_not_invent_a_tomorrow_battery_budget(impact_trip, freezer):
    trip = impact_trip
    freezer.move_to(dt_util.as_utc(dt_util.now().replace(hour=12)))
    result = build_trip_energy_impact(trip)
    assert result["status"] == "out_of_scope"
    assert result["cost_min"] is None


@pytest.mark.parametrize("problem", ["failed_refresh", "grid_power", "battery_power", "house_load"])
async def test_cached_or_stale_evidence_never_reports_fresh_zero_cost(impact_trip, problem):
    trip = impact_trip
    trip.coordinator.data.available_after_floor_kwh = 100
    if problem == "failed_refresh":
        trip.coordinator.last_update_success = False
    else:
        getattr(trip.coordinator.telemetry, problem).fresh = False
    result = build_trip_energy_impact(trip)
    assert result["status"] == "unavailable"
    assert result.get("cost_min") is None


async def test_expired_unowned_request_is_not_a_new_estimated_charge(impact_trip, freezer):
    trip = impact_trip
    freezer.move_to(trip.inputs["departure"] + timedelta(minutes=1))
    assert build_trip_energy_impact(trip)["reason"] == "departure_passed"


async def test_an_already_owned_late_trip_can_still_show_remaining_impact(impact_trip, freezer):
    trip = impact_trip
    trip.owns_full = True
    freezer.move_to(trip.inputs["departure"] + timedelta(minutes=1))
    assert build_trip_energy_impact(trip)["reason"] != "departure_passed"


async def test_optional_projection_isolates_numeric_errors(impact_trip):
    trip = impact_trip
    trip.inputs["efficiency_percent"] = 5e-324
    trip.hass.states.async_set("input_boolean.heo_trip_charge_scheduled", "on")
    trip.hass.states.async_set("sensor.heo_trip_charge_plan", '{"v":2}')
    result = build_trip_energy_impact(trip)
    assert result["status"] == "unavailable"
