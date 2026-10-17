"""Render the shared display against actual Home Assistant template helpers."""

from pathlib import Path

import pytest
import yaml
from homeassistant.helpers.template import Template

from scripts.trip_charge_wrapper import build_card
from scripts.trip_impact_card import build_trip_impact_card

ROOT = Path(__file__).resolve().parents[1]
ENTITY = "sensor.home_energy_trip_charge_status"
ESTIMATE = {
    "status": "estimated",
    "source": "native",
    "scope": "before_next_free_window_only",
    "pack_energy_kwh": 8.1,
    "wall_energy_kwh": 9.0,
    "before_free_kwh": 9.0,
    "during_free_kwh": 0.0,
    "after_free_kwh": 0.0,
    "battery_available_for_ev_kwh": 5.0,
    "battery_contribution_kwh": 5.0,
    "extra_paid_energy_kwh": 4.0,
    "cost_min": 1.0,
    "cost_max": 2.0,
}


def _render(hass, impact):
    hass.states.async_set(ENTITY, "waiting_for_start", {"energy_impact": impact})
    result = Template(build_trip_impact_card()["content"], hass).async_render(parse_result=False)
    return " ".join(result.split())


async def test_range_is_pre_free_cost_not_total_trip_cost(hass):
    result = _render(hass, ESTIMATE)
    assert "Extra cost before free power: $1.00–$2.00" in result
    assert "Energy needed: **9.0 kWh**, including charging losses" in result
    assert "Extra paid energy before free power: **4.0 kWh**" in result
    assert "not the total trip cost" in result
    assert "house power moved onto the grid" in result
    assert "No future solar or export forecast" in result
    assert "Supply charges, lost export earnings and the ZEROHERO credit are excluded" in result
    assert "battery protection and slower charging near full" in result
    assert "The rest of this trip charge" not in result


async def test_zero_is_valid_and_single_cost_is_not_a_range(hass):
    result = _render(
        hass,
        {**ESTIMATE, "extra_paid_energy_kwh": 0, "cost_min": 0, "cost_max": 0},
    )
    assert "Extra cost before free power: $0.00**" in result
    assert "Extra paid energy before free power: **0.0 kWh**" in result
    assert "not available" not in result
    assert "$0.00–" not in result


async def test_legacy_estimate_is_not_confused_with_native_scheduler_status(hass):
    result = _render(hass, {**ESTIMATE, "source": "legacy"})
    assert "Estimate uses your existing trip helpers" in result
    assert "Extra cost before free power: $1.00–$2.00" in result
    assert "legacy_conflict" not in result
    assert "fault" not in result


@pytest.mark.parametrize(
    "field,value",
    [
        ("wall_energy_kwh", None),
        ("before_free_kwh", "unknown"),
        ("battery_contribution_kwh", -1),
        ("extra_paid_energy_kwh", "0"),
        ("cost_min", True),
        ("cost_min", -0.01),
        ("cost_min", float("nan")),
        ("cost_max", float("inf")),
    ],
)
async def test_invalid_required_value_does_not_claim_zero_cost(hass, field, value):
    result = _render(hass, {**ESTIMATE, field: value})
    assert "not available yet" in result
    assert "Extra cost before free power:" not in result
    assert "$0.00" not in result
    assert "nan" not in result.lower()


async def test_reversed_cost_range_is_unavailable(hass):
    result = _render(hass, {**ESTIMATE, "cost_min": 3, "cost_max": 2})
    assert "not available yet" in result
    assert "Extra cost before free power:" not in result


async def test_future_or_missing_scope_is_not_presented_as_pre_free_cost(hass):
    result = _render(hass, {**ESTIMATE, "scope": "entire_trip"})
    assert "not available yet" in result
    assert "Extra cost before free power:" not in result


async def test_estimate_end_uses_home_assistant_local_time(hass):
    await hass.config.async_set_time_zone("Australia/Sydney")
    result = _render(
        hass,
        {**ESTIMATE, "until_free_start": "2026-10-17T00:01:00+00:00"},
    )
    assert "Sat 17 Oct, 11:01" in result


@pytest.mark.parametrize("impact", [None, {}, [], "unavailable", 12])
async def test_missing_or_old_projection_never_implies_zero(hass, impact):
    result = _render(hass, impact)
    assert "not available" in result
    assert "$0.00" not in result


async def test_missing_attribute_explains_required_version(hass):
    hass.states.async_set(ENTITY, "waiting_for_start")
    result = Template(build_trip_impact_card()["content"], hass).async_render(parse_result=False)
    assert "needs an HEO version that provides trip energy-impact data" in result
    assert "$0.00" not in result


async def test_scope_crossing_separates_later_energy_from_current_battery_cost(hass):
    result = _render(
        hass,
        {**ESTIMATE, "during_free_kwh": 5.0, "after_free_kwh": 2.0},
    )
    assert "5.0 kWh during" in result
    assert "2.0 kWh after" in result
    assert "Later charging costs are not estimated from the current house battery" in result


@pytest.mark.parametrize("status", ["out_of_scope", "already_at_target", "unavailable"])
async def test_non_estimates_do_not_render_a_cost(hass, status):
    result = _render(hass, {"status": status})
    assert "Extra cost before free power:" not in result
    if status == "out_of_scope":
        assert "does not mean the whole trip will be free" in result
    elif status == "already_at_target":
        assert "No extra trip charging is currently needed" in result
    else:
        assert "not available yet" in result


async def test_untrusted_reason_is_not_rendered_as_markup(hass):
    result = _render(
        hass,
        {"status": "unavailable", "reason": "<script>alert('private')</script>"},
    )
    assert "<script>" not in result
    assert "private" not in result


async def test_paused_trip_explains_why_no_cost_is_shown(hass):
    result = _render(hass, {"status": "unavailable", "reason": "trip_paused"})
    assert "The trip is paused" in result
    assert "estimate will update when charging resumes" in result
    assert "Extra cost before free power:" not in result


def test_native_and_legacy_examples_use_identical_read_only_card():
    expected = build_trip_impact_card()
    dashboard = yaml.safe_load((ROOT / "examples/dashboard.yaml").read_text())
    trip = next(view for view in dashboard["views"] if view["path"] == "trip-charge")
    assert expected in [card for section in trip["sections"] for card in section["cards"]]
    assert expected in build_card()["cards"]
    legacy = yaml.safe_load((ROOT / "examples/trip-charge-card.yaml").read_text())
    assert expected in legacy["cards"]
    assert set(expected) == {"type", "title", "content"}
    assert expected["type"] == "markdown"
    assert "service" not in expected
    assert "action" not in expected
