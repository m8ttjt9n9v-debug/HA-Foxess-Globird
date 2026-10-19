"""Invented minute-energy comparisons, not historical or live-site acceptance.

The same 61-minute physical model is replayed against the old solar-only /
latest-start policy and the combined policy. It begins with 2 kWh of already
house-protected AC energy at 11:00; free power starts at 12:01. PV is 3 kW and
house demand is 0.5 kW except for the documented cloud/surge intervals. Current
is realised immediately, electrical evidence is valid, service headroom is
ample, and vehicle room is ample (44% with a 90% normal target). No efficiency
is applied twice: the initial pool and EV delivery are both measured at AC.
The sudden house-surge profile deliberately exceeds the protected house model:
house-only deficit remains visible rather than being misreported as an EV
command consuming more than its observed discretionary budget.

Single-phase hardware is capped at 15 A; three-phase hardware at 16 A. Both
retain the same 15 kW inverter / 50% TOTAL EV ceiling. The smallest current
step/minimum is 1 A. Unused actual solar charges the pool; actual house demand
and EV delivery deplete it. This intentionally does not reuse a static budget.

The combined runtime's actual limiter/context method is exercised without a
Home Assistant instance or service calls. This bounded toy model proves these
specific counterexamples no longer starve a moving target; it does not prove
forecast accuracy, physical actuator response, or guaranteed reserve depletion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import floor
from types import SimpleNamespace

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    MeasuredSolarAdjustmentState,
    PreFreeCurrentInputs,
    PreFreePlanInputs,
    calculate_pre_free_plan,
    plan_combined_pre_free_current,
    plan_pre_free_current,
    pre_free_frontload_horizon_hours,
    rate_limit_measured_solar_current,
)

START = datetime(2026, 10, 18, 11, tzinfo=UTC)
FREE_START = START + timedelta(minutes=61)


@dataclass(frozen=True)
class MinuteResult:
    minute: int
    current_a: float
    remaining_safe_ac_kwh: float
    unprotected_house_shortfall_kwh: float


@dataclass(frozen=True)
class ReplayResult:
    trace: tuple[MinuteResult, ...]
    delivered_ev_ac_kwh: float
    net_solar_minus_house_kwh: float
    total_current_ceiling_a: float

    @property
    def remaining_safe_ac_kwh(self):
        return self.trace[-1].remaining_safe_ac_kwh


def _actual_solar_minus_house(profile, minute):
    pv, house = 3.0, 0.5
    if profile == "clouds":
        pv = 0.5 if 15 <= minute < 30 else 1.0 if 45 <= minute < 50 else 3.0
    if profile == "house_surge" and 20 <= minute < 30:
        house = 6.0
    return pv - house


def _replay(*, phases, profile, combined):
    physical_maximum = 15 if phases == 1 else 16
    ceiling = min(physical_maximum, floor(7.5 / (0.230 * phases)))
    context = SimpleNamespace(measured_solar_adjustment=MeasuredSolarAdjustmentState())
    remaining, delivered, net_solar = 2.0, 0.0, 0.0
    active = False
    house_shortfall = 0.0
    trace = []
    for minute in range(61):
        now = START + timedelta(minutes=minute)
        actual_surplus = _actual_solar_minus_house(profile, minute)
        budget = max(remaining, 0.0)
        inputs = PreFreeCurrentInputs(
            session_active=True,
            planned_energy_kwh=budget,
            hours_until_free=(61 - minute) / 60,
            voltage_v=230,
            phase_count=phases,
            current_step_a=1,
            baseline_a=0,
            current_ceiling_a=ceiling,
            vehicle_soc_percent=44,
            vehicle_soft_limit_percent=90,
        )
        raw_solar = min(floor(max(actual_surplus, 0.0) / (0.230 * phases)), physical_maximum)
        if combined and budget > 0 and (actual_surplus > 0 or active):
            raw_target = plan_combined_pre_free_current(
                inputs,
                solar_surplus_kw=max(actual_surplus, 0),
                charger_minimum_a=1,
                telemetry_valid=True,
                battery_spending_hours=pre_free_frontload_horizon_hours(
                    context.measured_solar_adjustment,
                    now=now,
                    hours_until_free=inputs.hours_until_free,
                ),
            ).current_a
            active = raw_target >= 1
            current = (
                ActiveEvController._combined_pre_free_adjustment(
                    context,
                    now,
                    inputs,
                    raw_target,
                    charger_minimum_a=1,
                    solar_surplus_kw=max(actual_surplus, 0),
                )
                if active
                else 0.0
            )
        else:
            if combined:
                active = False
            else:
                old_plan = calculate_pre_free_plan(
                    PreFreePlanInputs(
                        discretionary_ac_kwh=budget,
                        vehicle_wall_room_kwh=100,
                        baseline_a=0,
                        current_ceiling_a=ceiling,
                        voltage_v=230,
                        phase_count=phases,
                        free_window_start=FREE_START,
                    )
                )
                active = budget > 0 and (
                    active or old_plan.planned_start is not None and now >= old_plan.planned_start
                )
            if active:
                current = plan_pre_free_current(inputs).current_a
                context.measured_solar_adjustment = MeasuredSolarAdjustmentState()
            else:
                if context.measured_solar_adjustment.battery_current_a is not None:
                    context.measured_solar_adjustment = MeasuredSolarAdjustmentState()
                adjustment = rate_limit_measured_solar_current(
                    context.measured_solar_adjustment,
                    now=now,
                    policy_phase="morning_solar",
                    requested_current_a=raw_solar,
                    charger_minimum_a=1,
                    current_step_a=1,
                    immediate_curtailment=False,
                )
                current = adjustment.target_current_a
                context.measured_solar_adjustment = adjustment.state

        ev_kw = current * 0.230 * phases
        # The controller cannot promise that unexpected house-only consumption
        # never exceeds a previously protected estimate. It can and must avoid
        # issuing EV energy beyond the positive budget it actually observes.
        assert max(ev_kw - max(actual_surplus, 0), 0) / 60 <= budget + 1e-9
        house_shortfall += max(-(remaining + min(actual_surplus, 0) / 60), 0) - max(-remaining, 0)
        delivered += ev_kw / 60
        net_solar += actual_surplus / 60
        previous_remaining = remaining
        remaining -= (ev_kw - actual_surplus) / 60
        if previous_remaining >= 0 and remaining < 0:
            assert ev_kw == 0
            assert actual_surplus < 0
        trace.append(MinuteResult(minute, current, remaining, house_shortfall))

    return ReplayResult(tuple(trace), delivered, net_solar, ceiling)


@pytest.mark.parametrize("phases", [1, 3], ids=["single-phase-15A", "three-phase-16A"])
@pytest.mark.parametrize("profile", ["stable", "clouds", "house_surge"])
def test_combined_replay_uses_at_least_as_much_safe_energy_without_exceeding_limits(
    phases, profile
):
    old = _replay(phases=phases, profile=profile, combined=False)
    new = _replay(phases=phases, profile=profile, combined=True)

    assert len(new.trace) == 61
    # 0.02 kWh is less than two minutes of one three-phase current step; it
    # allows small boundary quantisation, not the prior 0.3-0.5 kWh regression.
    assert new.remaining_safe_ac_kwh <= old.remaining_safe_ac_kwh + 0.02
    assert new.delivered_ev_ac_kwh >= old.delivered_ev_ac_kwh - 0.02
    assert new.net_solar_minus_house_kwh == pytest.approx(old.net_solar_minus_house_kwh)
    for result in (old, new):
        assert result.remaining_safe_ac_kwh == pytest.approx(
            2 + result.net_solar_minus_house_kwh - result.delivered_ev_ac_kwh
        )
        for sample in result.trace:
            assert sample.remaining_safe_ac_kwh >= -sample.unprotected_house_shortfall_kwh - 1e-9
            if profile != "house_surge":
                assert sample.remaining_safe_ac_kwh >= -1e-9
            assert 0 <= sample.current_a <= result.total_current_ceiling_a
            assert sample.current_a == floor(sample.current_a)
            assert sample.current_a * 0.230 * phases <= 7.5
