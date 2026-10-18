"""Synthetic oracle vectors for the approved additive pre-free extension.

These are deliberately independent of live sites and of the implementation's
arithmetic. The energy input is the already house-protected AC battery budget;
solar is measured solar left after house demand, not a forecast or another
copy of the budget. The saved outside-window ceiling limits the TOTAL EV rate.
"""

from __future__ import annotations

from dataclasses import replace
from math import inf, nan

import pytest

from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    PreFreeCurrentInputs,
    plan_combined_pre_free_current,
)

BASE = PreFreeCurrentInputs(
    session_active=True,
    planned_energy_kwh=2,
    hours_until_free=1,
    voltage_v=250,
    phase_count=1,
    current_step_a=1,
    baseline_a=0,
    current_ceiling_a=32,
    vehicle_soc_percent=44,
    vehicle_soft_limit_percent=90,
)


@pytest.mark.parametrize(
    ("changes", "solar_kw", "minimum_a", "expected_a"),
    [
        pytest.param(
            {
                "voltage_v": 230,
                "phase_count": 3,
                "hours_until_free": 61 / 60,
                "current_ceiling_a": 10,
            },
            2.5,
            1,
            6,
            id="11am-arrival-three-phase-solar3-house0point5",
        ),
        pytest.param(
            {
                "voltage_v": 230,
                "phase_count": 3,
                "hours_until_free": 61 / 60,
                "current_ceiling_a": 10,
            },
            2,
            1,
            5,
            id="11am-arrival-three-phase-house1",
        ),
        pytest.param(
            {
                "voltage_v": 230,
                "phase_count": 3,
                "hours_until_free": 61 / 60,
                "current_ceiling_a": 10,
            },
            3,
            1,
            7,
            id="11am-arrival-three-phase-no-house-demand",
        ),
        pytest.param(
            {
                "voltage_v": 230,
                "phase_count": 3,
                "hours_until_free": 61 / 60,
                "current_ceiling_a": 10,
            },
            0,
            1,
            2,
            id="11am-arrival-no-solar-remains-battery-backed",
        ),
        pytest.param(
            {
                "voltage_v": 230,
                "phase_count": 3,
                "hours_until_free": 61 / 60,
                "current_ceiling_a": 10,
            },
            40,
            1,
            10,
            id="large-array-cannot-bypass-total-percentage-cap",
        ),
        pytest.param({}, 1, 1, 12, id="single-phase-combines-two-battery-one-solar"),
        pytest.param({"phase_count": 2}, 1, 1, 6, id="two-phase-same-total-power"),
        pytest.param({"phase_count": 3}, 1, 1, 4, id="three-phase-same-total-power"),
        pytest.param({"baseline_a": 1}, 1, 1, 13, id="single-phase-baseline-once"),
        pytest.param(
            {"baseline_a": 1, "phase_count": 2},
            1,
            1,
            7,
            id="two-phase-baseline-once",
        ),
        pytest.param(
            {"baseline_a": 1, "phase_count": 3},
            1,
            1,
            5,
            id="three-phase-baseline-once",
        ),
        pytest.param({"planned_energy_kwh": 0.5}, 0.25, 1, 3, id="fractional-energy"),
        pytest.param(
            {"planned_energy_kwh": 0.5, "phase_count": 3},
            0.25,
            1,
            1,
            id="three-phase-exact-minimum",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.4, "phase_count": 3},
            0.2,
            1,
            0,
            id="three-phase-below-minimum",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.5, "phase_count": 3},
            0.25,
            2,
            0,
            id="physical-minimum-not-assumed-one",
        ),
        pytest.param(
            {"planned_energy_kwh": 1, "phase_count": 3},
            0.25,
            2,
            0,
            id="floor-below-physical-minimum",
        ),
        pytest.param(
            {"planned_energy_kwh": 1.25, "phase_count": 3},
            0.25,
            2,
            2,
            id="combined-power-reaches-physical-minimum",
        ),
        pytest.param({}, -0.5, 1, 8, id="negative-solar-clamped-not-subtracted-twice"),
        pytest.param({"hours_until_free": 2}, 1, 1, 8, id="two-hours-more-gentle"),
        pytest.param({"hours_until_free": 0.5}, 1, 1, 20, id="half-hour-increased-rate"),
        pytest.param({"hours_until_free": 0.25}, 1, 1, 32, id="late-arrival-car-cap"),
        pytest.param({"current_ceiling_a": 10}, 1, 1, 10, id="saved-total-ceiling"),
        pytest.param(
            {"current_ceiling_a": 10, "current_step_a": 2},
            1,
            1,
            10,
            id="two-amp-aligned-cap",
        ),
        pytest.param(
            {"current_ceiling_a": 11, "current_step_a": 2},
            1,
            1,
            10,
            id="unaligned-cap-never-commanded",
        ),
        pytest.param(
            {"current_ceiling_a": 6.75, "current_step_a": 0.5},
            1,
            1,
            6.5,
            id="fractional-unaligned-cap-floored",
        ),
        pytest.param(
            {"current_ceiling_a": 5.5},
            1,
            6,
            0,
            id="ceiling-below-physical-minimum-no-command",
        ),
        pytest.param(
            {"planned_energy_kwh": 1.3},
            0.1,
            6,
            0,
            id="just-below-six-amp-minimum",
        ),
        pytest.param(
            {"planned_energy_kwh": 1.4},
            0.1,
            6,
            6,
            id="solar-below-minimum-helped-by-battery",
        ),
        pytest.param(
            {"planned_energy_kwh": 1.3},
            0.2,
            6,
            6,
            id="battery-below-minimum-helped-by-solar",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.1},
            1.4,
            6,
            6,
            id="tiny-battery-plus-solar-reaches-minimum",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.1},
            0.1,
            1,
            0,
            id="combined-below-one-amp",
        ),
        pytest.param({}, 100, 1, 32, id="large-solar-still-bounded"),
        pytest.param(
            {"planned_energy_kwh": 0.5, "hours_until_free": 1 / 60},
            0,
            1,
            32,
            id="last-minute-cannot-exceed-car-cap",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.001, "hours_until_free": 1 / 3600},
            0,
            1,
            14,
            id="last-second-finite-bounded-target",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.001, "hours_until_free": 100},
            0,
            1,
            0,
            id="tiny-budget-long-horizon",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.125},
            0.125,
            1,
            1,
            id="combine-before-floor-not-two-zero-components",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.125, "baseline_a": 1},
            0.125,
            1,
            2,
            id="baseline-and-combined-fractions-once",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.375, "current_step_a": 2},
            0.125,
            1,
            2,
            id="combine-before-two-amp-floor",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.4, "current_step_a": 2},
            0.225,
            1,
            2,
            id="do-not-round-up-to-next-two-amp-step",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.3, "current_step_a": 0.5},
            0.125,
            1,
            1.5,
            id="fractional-current-step",
        ),
        pytest.param(
            {"voltage_v": 240, "phase_count": 2},
            1,
            1,
            6,
            id="configured-two-phase-voltage",
        ),
        pytest.param(
            {"voltage_v": 240, "phase_count": 3},
            1,
            1,
            4,
            id="configured-three-phase-voltage",
        ),
        pytest.param({"voltage_v": 200}, 1, 1, 15, id="configured-single-phase-voltage"),
        pytest.param(
            {"baseline_a": 31},
            1,
            1,
            32,
            id="baseline-plus-energy-cannot-exceed-total-cap",
        ),
        pytest.param(
            {"vehicle_soft_limit_percent": 80, "vehicle_soc_percent": 79},
            1,
            1,
            12,
            id="below-lower-normal-target",
        ),
        pytest.param(
            {"vehicle_soft_limit_percent": 100, "vehicle_soc_percent": 89.999},
            1,
            1,
            12,
            id="below-normal-hard-cap-even-with-target100",
        ),
        pytest.param(
            {"planned_energy_kwh": 0.125, "baseline_a": 6},
            0.125,
            6,
            7,
            id="physical-protected-baseline-plus-combined-energy",
        ),
        pytest.param({"vehicle_soc_percent": 0}, 1, 1, 12, id="empty-car-is-valid"),
        pytest.param(
            {"planned_energy_kwh": 100},
            100,
            1,
            32,
            id="huge-budget-does-not-satisfy-reserve-objective-by-breaking-cap",
        ),
    ],
)
def test_combined_pre_free_synthetic_power_oracles(changes, solar_kw, minimum_a, expected_a):
    decision = plan_combined_pre_free_current(
        replace(BASE, **changes),
        solar_surplus_kw=solar_kw,
        charger_minimum_a=minimum_a,
        telemetry_valid=True,
    )

    assert decision.current_a == expected_a
    assert decision.phase == "pre_free_combined"


@pytest.mark.parametrize("baseline", [0, 1])
@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"session_active": False}, id="not-admitted"),
        pytest.param({"planned_energy_kwh": 0}, id="no-battery-budget"),
        pytest.param({"hours_until_free": 0}, id="exact-free-boundary"),
        pytest.param({"vehicle_soc_percent": 90}, id="at-normal-hard-cap"),
        pytest.param(
            {"vehicle_soc_percent": 90, "vehicle_soft_limit_percent": 100},
            id="target100-cannot-bypass-normal-hard-cap",
        ),
        pytest.param(
            {"vehicle_soc_percent": 80, "vehicle_soft_limit_percent": 80},
            id="at-lower-soft-target",
        ),
        pytest.param(
            {"vehicle_soc_percent": 81, "vehicle_soft_limit_percent": 80},
            id="above-lower-soft-target",
        ),
    ],
)
def test_noneligible_combined_opportunity_returns_only_protected_baseline(baseline, changes):
    decision = plan_combined_pre_free_current(
        replace(BASE, baseline_a=baseline, **changes),
        solar_surplus_kw=20,
        charger_minimum_a=1,
        telemetry_valid=True,
    )

    assert decision.current_a == baseline
    assert decision.phase == "pre_free_inactive"


@pytest.mark.parametrize("baseline", [0, 1])
def test_invalid_telemetry_never_authorises_a_combined_increase(baseline):
    decision = plan_combined_pre_free_current(
        replace(BASE, baseline_a=baseline),
        solar_surplus_kw=20,
        charger_minimum_a=1,
        telemetry_valid=False,
    )

    assert decision.current_a == baseline
    assert decision.phase == "pre_free_combined_telemetry_unavailable"


@pytest.mark.parametrize(
    "field",
    [
        "planned_energy_kwh",
        "hours_until_free",
        "voltage_v",
        "current_step_a",
        "baseline_a",
        "current_ceiling_a",
        "vehicle_soc_percent",
        "vehicle_soft_limit_percent",
    ],
)
@pytest.mark.parametrize("invalid", [-1, inf, -inf, nan])
def test_combined_inputs_reject_nonfinite_or_negative_quantities(field, invalid):
    with pytest.raises(ValueError):
        plan_combined_pre_free_current(
            replace(BASE, **{field: invalid}),
            solar_surplus_kw=1,
            charger_minimum_a=1,
            telemetry_valid=True,
        )


@pytest.mark.parametrize("invalid", [inf, -inf, nan])
def test_solar_must_be_finite_even_though_its_signed_value_may_be_negative(invalid):
    with pytest.raises(ValueError):
        plan_combined_pre_free_current(
            BASE,
            solar_surplus_kw=invalid,
            charger_minimum_a=1,
            telemetry_valid=True,
        )


@pytest.mark.parametrize("invalid", [-1, inf, -inf, nan])
def test_physical_minimum_must_be_finite_and_nonnegative(invalid):
    with pytest.raises(ValueError):
        plan_combined_pre_free_current(
            BASE,
            solar_surplus_kw=1,
            charger_minimum_a=invalid,
            telemetry_valid=True,
        )


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"phase_count": 0}, id="no-phases"),
        pytest.param({"phase_count": -1}, id="negative-phase-count"),
        pytest.param({"voltage_v": 0}, id="zero-voltage"),
        pytest.param({"current_step_a": 0}, id="zero-current-step"),
        pytest.param({"baseline_a": 33}, id="baseline-above-ceiling"),
    ],
)
def test_invalid_electrical_envelope_cannot_authorise_a_command(changes):
    with pytest.raises(ValueError):
        plan_combined_pre_free_current(
            replace(BASE, **changes),
            solar_surplus_kw=1,
            charger_minimum_a=1,
            telemetry_valid=True,
        )
