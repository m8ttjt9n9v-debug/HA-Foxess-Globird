"""Independent power and elapsed-time oracles for morning front-loading.

Only already-approved discretionary AC energy is offered sooner.  These tests
deliberately vary topology, inverter-derived ceilings, physical steps and the
remaining control-hold interval; they do not use a live-site entity or forecast.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import inf, nan
from zoneinfo import ZoneInfo

import pytest

from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    MeasuredSolarAdjustmentState,
    PreFreeCurrentInputs,
    plan_combined_pre_free_current,
    pre_free_frontload_horizon_hours,
    rate_limit_measured_solar_current,
)

BASE = PreFreeCurrentInputs(
    session_active=True,
    planned_energy_kwh=0.5,
    hours_until_free=2,
    voltage_v=250,
    phase_count=1,
    current_step_a=1,
    baseline_a=0,
    current_ceiling_a=32,
    vehicle_soc_percent=44,
    vehicle_soft_limit_percent=90,
)


@pytest.mark.parametrize(
    ("changes", "solar_kw", "horizon_h", "minimum_a", "expected_a"),
    [
        pytest.param({}, 0.5, 1 / 6, 1, 14, id="half-kwh-spent-in-ten-minutes"),
        pytest.param({"phase_count": 2}, 0.5, 1 / 6, 1, 7, id="two-phase-power-conversion"),
        pytest.param({"phase_count": 3}, 0.5, 1 / 6, 1, 4, id="three-phase-power-conversion"),
        pytest.param({"baseline_a": 1}, 0.5, 1 / 6, 1, 15, id="protected-baseline-added-once"),
        pytest.param(
            {
                "planned_energy_kwh": 0.93,
                "voltage_v": 230,
                "baseline_a": 1,
                "hours_until_free": 88 / 60,
                "current_ceiling_a": 15,
            },
            1.4,
            1 / 6,
            1,
            15,
            id="slow-single-phase-departing-car-gets-full-permitted-rate",
        ),
        pytest.param(
            {"current_ceiling_a": 10}, 30, 1 / 6, 1, 10, id="large-solar-not-above-total-cap"
        ),
        pytest.param({"current_ceiling_a": 3}, 0.5, 1 / 6, 1, 3, id="small-inverter-cap"),
        pytest.param(
            {"current_ceiling_a": 4, "phase_count": 3},
            0.5,
            1 / 6,
            1,
            4,
            id="three-phase-small-inverter-cap",
        ),
        pytest.param(
            {"current_ceiling_a": 1, "phase_count": 3},
            100,
            1 / 6,
            1,
            1,
            id="very-small-three-phase-inverter",
        ),
        pytest.param(
            {"current_ceiling_a": 10.9}, 100, 1 / 6, 1, 10, id="unaligned-current-cap-floors"
        ),
        pytest.param({"current_step_a": 2}, 0.5, 1 / 6, 1, 14, id="two-amp-step"),
        pytest.param(
            {"current_step_a": 2, "current_ceiling_a": 13},
            100,
            1 / 6,
            1,
            12,
            id="unaligned-two-amp-cap",
        ),
        pytest.param({"current_step_a": 0.5}, 0.375, 1 / 6, 1, 13.5, id="half-amp-step"),
        pytest.param({"voltage_v": 240, "phase_count": 3}, 0.6, 1 / 6, 1, 5, id="three-phase-240v"),
        pytest.param({"voltage_v": 200}, 0.6, 1 / 6, 1, 18, id="configured-voltage-not-assumed"),
        pytest.param(
            {"planned_energy_kwh": 1 / 24},
            0.25,
            1 / 6,
            1,
            2,
            id="combine-before-current-quantization",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.01},
            0.125,
            1 / 6,
            1,
            0,
            id="sub-one-amp-opportunity-not-rounded-up",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.01, "baseline_a": 1},
            0.125,
            1 / 6,
            1,
            1,
            id="substep-energy-retains-only-baseline",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.2, "phase_count": 3},
            0.2,
            1 / 6,
            2,
            0,
            id="below-physical-minimum-no-command",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.2, "phase_count": 3},
            0.3,
            1 / 6,
            2,
            2,
            id="combined-exact-physical-minimum",
        ),
        pytest.param(
            {"current_ceiling_a": 5.9}, 100, 1 / 6, 6, 0, id="ceiling-below-physical-minimum"
        ),
        pytest.param({}, -2, 1 / 6, 1, 12, id="negative-net-solar-cannot-manufacture-energy"),
        pytest.param({}, 0, 1 / 6, 1, 12, id="admitted-session-continues-through-cloud"),
        pytest.param({}, 0.5, 1 / 12, 1, 26, id="five-minutes-left-in-hold"),
        pytest.param({}, 0.5, 1 / 60, 1, 32, id="one-minute-left-still-cap-bounded"),
        pytest.param(
            {"planned_energy_kwh": 0.01}, 0.5, 1 / 60, 1, 4, id="small-energy-short-horizon"
        ),
        pytest.param(
            {"planned_energy_kwh": 0.1}, 0.5, 1 / 3600, 1, 32, id="one-second-left-finite-cap"
        ),
        pytest.param(
            {"planned_energy_kwh": 100},
            100,
            1 / 6,
            1,
            32,
            id="huge-budget-never-expands-physical-cap",
        ),
        pytest.param(
            {"vehicle_soc_percent": 89.9, "vehicle_soft_limit_percent": 100},
            0.5,
            1 / 6,
            1,
            14,
            id="below-normal-hard-90-cap",
        ),
        pytest.param(
            {"vehicle_soc_percent": 79.9, "vehicle_soft_limit_percent": 80},
            0.5,
            1 / 6,
            1,
            14,
            id="below-configured-lower-target",
        ),
    ],
)
def test_frontload_power_oracles(changes, solar_kw, horizon_h, minimum_a, expected_a):
    decision = plan_combined_pre_free_current(
        replace(BASE, **changes),
        solar_surplus_kw=solar_kw,
        charger_minimum_a=minimum_a,
        telemetry_valid=True,
        battery_spending_hours=horizon_h,
    )

    assert decision.current_a == expected_a
    assert decision.phase == "pre_free_combined"


@pytest.mark.parametrize("baseline", [0, 1])
@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"session_active": False}, id="not-admitted"),
        pytest.param({"planned_energy_kwh": 0}, id="budget-exhausted"),
        pytest.param({"hours_until_free": 0}, id="free-boundary"),
        pytest.param({"vehicle_soc_percent": 90}, id="normal-hard-cap"),
        pytest.param(
            {"vehicle_soc_percent": 90, "vehicle_soft_limit_percent": 100},
            id="configured100-not-full-authority",
        ),
        pytest.param(
            {"vehicle_soc_percent": 80, "vehicle_soft_limit_percent": 80},
            id="configured-target-met",
        ),
    ],
)
def test_frontload_never_grants_new_energy_or_charge_authority(baseline, changes):
    decision = plan_combined_pre_free_current(
        replace(BASE, baseline_a=baseline, **changes),
        solar_surplus_kw=40,
        charger_minimum_a=1,
        telemetry_valid=True,
        battery_spending_hours=1 / 6,
    )

    assert decision.current_a == baseline
    assert decision.phase == "pre_free_inactive"


@pytest.mark.parametrize("baseline", [0, 1])
def test_frontload_does_not_bypass_invalid_electrical_evidence(baseline):
    decision = plan_combined_pre_free_current(
        replace(BASE, baseline_a=baseline),
        solar_surplus_kw=40,
        charger_minimum_a=1,
        telemetry_valid=False,
        battery_spending_hours=1 / 6,
    )

    assert decision.current_a == baseline
    assert decision.phase == "pre_free_combined_telemetry_unavailable"


def test_optional_horizon_preserves_legacy_arithmetic_when_not_supplied():
    ordinary = dict(solar_surplus_kw=0.5, charger_minimum_a=1, telemetry_valid=True)

    assert plan_combined_pre_free_current(BASE, **ordinary).current_a == 3
    assert (
        plan_combined_pre_free_current(BASE, battery_spending_hours=None, **ordinary).current_a == 3
    )
    assert (
        plan_combined_pre_free_current(BASE, battery_spending_hours=1 / 6, **ordinary).current_a
        == 14
    )


def _now():
    return datetime(2026, 10, 19, 9, 33, tzinfo=UTC)


def _accepted(*, changed_at=None, phase="morning_solar", battery_current_a=3):
    return MeasuredSolarAdjustmentState(
        phase=phase,
        target_current_a=15,
        changed_at=_now() if changed_at is None else changed_at,
        battery_current_a=battery_current_a,
    )


@pytest.mark.parametrize(
    ("elapsed_seconds", "expected_seconds"),
    [
        (0, 600),
        (1, 599),
        (30, 570),
        (59, 541),
        (60, 540),
        (299, 301),
        (300, 300),
        (599, 30),
        (600, 600),
        (601, 600),
        (1200, 600),
    ],
)
def test_horizon_is_anchored_to_accepted_adjustment_not_rolling(elapsed_seconds, expected_seconds):
    value = pre_free_frontload_horizon_hours(
        _accepted(), now=_now() + timedelta(seconds=elapsed_seconds), hours_until_free=2
    )

    assert value * 3600 == pytest.approx(expected_seconds)


@pytest.mark.parametrize("remaining_seconds", [0, 1, 30, 300, 599])
def test_horizon_respects_free_boundary_without_using_sub_control_tick_energy(remaining_seconds):
    value = pre_free_frontload_horizon_hours(
        _accepted(), now=_now(), hours_until_free=remaining_seconds / 3600
    )

    assert value * 3600 == pytest.approx(max(remaining_seconds, 30) if remaining_seconds > 0 else 0)


@pytest.mark.parametrize(
    "state",
    [
        pytest.param(MeasuredSolarAdjustmentState(), id="no-previous-session"),
        pytest.param(_accepted(phase="solar_spill"), id="post-free-solar-not-authority"),
        pytest.param(_accepted(battery_current_a=None), id="solar-only-not-combined-authority"),
        pytest.param(
            _accepted(changed_at=_now() + timedelta(minutes=1)), id="future-accepted-clock"
        ),
    ],
)
def test_unrelated_or_untrusted_hold_does_not_supply_an_old_deadline(state):
    value = pre_free_frontload_horizon_hours(
        state, now=_now() + timedelta(seconds=30), hours_until_free=2
    )

    assert value == pytest.approx(1 / 6)


@pytest.mark.parametrize("invalid", [-1, inf, -inf, nan])
def test_horizon_rejects_invalid_remaining_free_time(invalid):
    with pytest.raises(ValueError):
        pre_free_frontload_horizon_hours(_accepted(), now=_now(), hours_until_free=invalid)


@pytest.mark.parametrize("invalid", [0, -1, inf, -inf, nan])
def test_combined_frontload_rejects_invalid_spending_horizon_for_active_request(invalid):
    with pytest.raises(ValueError):
        plan_combined_pre_free_current(
            BASE,
            solar_surplus_kw=0.5,
            charger_minimum_a=1,
            telemetry_valid=True,
            battery_spending_hours=invalid,
        )


def test_sub_tick_spending_horizon_does_not_authorise_a_one_second_energy_burst():
    decision = plan_combined_pre_free_current(
        replace(BASE, planned_energy_kwh=0.001, hours_until_free=1 / 3600),
        solar_surplus_kw=0,
        charger_minimum_a=1,
        telemetry_valid=True,
        battery_spending_hours=1 / 3600,
    )

    # 0.001 kWh is less than a single 250 W amp for the next 30-second tick.
    assert decision.current_a == 0


def test_explicit_zero_horizon_is_rejected_even_at_inactive_free_boundary():
    with pytest.raises(ValueError):
        plan_combined_pre_free_current(
            replace(BASE, hours_until_free=0),
            solar_surplus_kw=0.5,
            charger_minimum_a=1,
            telemetry_valid=True,
            battery_spending_hours=0,
        )


def test_horizon_uses_physical_elapsed_time_across_spring_clock_change():
    timezone = ZoneInfo("Australia/Sydney")
    before = datetime(2026, 10, 4, 1, 59, tzinfo=timezone)
    after = datetime(2026, 10, 4, 3, 1, tzinfo=timezone)

    value = pre_free_frontload_horizon_hours(
        _accepted(changed_at=before), now=after, hours_until_free=1
    )

    assert value * 60 == pytest.approx(8)


def test_horizon_uses_physical_elapsed_time_across_repeated_autumn_clock_hour():
    timezone = ZoneInfo("Australia/Sydney")
    before = datetime(2026, 4, 5, 2, 59, tzinfo=timezone, fold=0)
    after = datetime(2026, 4, 5, 2, 1, tzinfo=timezone, fold=1)

    value = pre_free_frontload_horizon_hours(
        _accepted(changed_at=before), now=after, hours_until_free=1
    )

    assert value * 60 == pytest.approx(8)


@pytest.mark.parametrize(
    ("accepted", "observed", "expected_phase", "expected_current"),
    [
        pytest.param(
            datetime(2026, 10, 4, 1, 59),
            datetime(2026, 10, 4, 3, 1),
            "held",
            3,
            id="spring-wall-hour-does-not-skip-ten-minute-hold",
        ),
        pytest.param(
            datetime(2026, 4, 5, 2, 59, fold=0),
            datetime(2026, 4, 5, 2, 9, fold=1),
            "updated",
            4,
            id="autumn-repeated-hour-does-not-extend-ten-minute-hold",
        ),
    ],
)
def test_combined_adjustment_cadence_uses_physical_elapsed_time(
    accepted, observed, expected_phase, expected_current
):
    timezone = ZoneInfo("Australia/Sydney")
    decision = rate_limit_measured_solar_current(
        MeasuredSolarAdjustmentState(
            phase="morning_solar",
            target_current_a=3,
            changed_at=accepted.replace(tzinfo=timezone),
            battery_current_a=2,
        ),
        now=observed.replace(tzinfo=timezone),
        policy_phase="morning_solar",
        requested_current_a=4,
        charger_minimum_a=1,
        current_step_a=1,
        immediate_curtailment=False,
        require_stable_target=False,
    )

    assert decision.phase == expected_phase
    assert decision.target_current_a == expected_current


def test_frontload_captures_more_before_early_departure_without_expanding_budget():
    inputs = replace(
        BASE,
        planned_energy_kwh=0.93,
        hours_until_free=88 / 60,
        voltage_v=230,
        baseline_a=1,
        current_ceiling_a=15,
    )
    ordinary = dict(solar_surplus_kw=0.5, charger_minimum_a=1, telemetry_valid=True)
    original = plan_combined_pre_free_current(inputs, **ordinary).current_a
    frontload = plan_combined_pre_free_current(
        inputs, battery_spending_hours=1 / 6, **ordinary
    ).current_a

    # Ten minutes until departure: compare the same energy source and limits.
    # Baseline and concurrent measured solar do not consume discretionary energy.
    assert original == 5
    assert frontload == 15
    extra_vehicle_wall_kwh = (frontload - original) * 0.230 / 6
    battery_spend_kwh = max((frontload - 1) * 0.230 - 0.5, 0) / 6
    assert extra_vehicle_wall_kwh == pytest.approx(0.3833333333)
    assert battery_spend_kwh <= inputs.planned_energy_kwh
