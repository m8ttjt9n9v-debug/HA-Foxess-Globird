"""Sequential acceptance tests for spending safe morning EV energy sooner.

The physical replay decrements the same discretionary energy pool each control
tick.  It never treats a retained export plan, solar forecast or prior current
target as newly available battery energy.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from math import ceil

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from tests.test_ev_backfill_timing import _at, _charging, _services
from tests.test_ev_pre_free_combined_runtime import _power, _scenario


def _budget(coordinator, energy):
    coordinator.data.available_after_reserve_kwh = 1 + max(energy, 0)


def _set_current_feedback(hass, current, *, maximum=16):
    if current > 0:
        _charging(hass, current)
    else:
        hass.states.async_set("switch.car_charge", "off")
        hass.states.async_set("sensor.car_charging", "stopped")
        hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "A"})
    hass.states.async_set(
        "number.car_current",
        str(max(current, 1)),
        {"min": 1, "max": maximum, "step": 1, "unit_of_measurement": "A"},
    )


@pytest.mark.parametrize(
    ("phases", "inverter_kw", "percent", "maximum", "expected"),
    [
        pytest.param(1, 10, 50, 15, 15, id="slow-single-phase-car"),
        pytest.param(3, 15, 50, 16, 10, id="three-phase-inverter-percentage"),
        pytest.param(3, 8, 50, 16, 5, id="small-three-phase-inverter"),
        pytest.param(3, 15, 20, 16, 4, id="three-phase-low-percentage"),
        pytest.param(1, 3, 40, 16, 5, id="small-single-phase-inverter"),
        pytest.param(3, 3, 30, 16, 1, id="very-small-three-phase-inverter"),
    ],
)
async def test_frontload_total_rate_respects_saved_inverter_percentage(
    hass, phases, inverter_kw, percent, maximum, expected
):
    _services(hass)
    coordinator, controller = _scenario(
        hass,
        budget=2,
        ev_phase_count=phases,
        site_phase_count=phases,
        inverter_discharge_limit_kw=inverter_kw,
        ev_outside_inverter_percent=percent,
        ev_max_current=maximum,
    )
    _set_current_feedback(hass, 0, maximum=maximum)
    _power(hass, coordinator, _at(11), surplus=2.5)
    await controller.async_reconcile(_at(11))

    assert controller.decision_phase == "pre_free_combined"
    assert controller.target_current_a == expected
    assert controller.target_current_a * 230 * phases / 1000 <= inverter_kw * percent / 100
    assert controller.pre_free_plan.planned_energy_kwh == 2


async def test_typical_slow_car_uses_the_same_approved_budget_before_departure(hass):
    _services(hass)
    coordinator, controller = _scenario(
        hass,
        budget=0.93,
        ev_phase_count=1,
        site_phase_count=1,
        ev_max_current=15,
        ev_protected_baseline_a=1,
        free_charge_window_start="11:01:00",
        inverter_discharge_limit_kw=10,
    )
    _set_current_feedback(hass, 1, maximum=15)
    _power(hass, coordinator, _at(9, 33), surplus=0.5, current=1)
    await controller.async_reconcile(_at(9, 33))

    assert controller.target_current_a == 15
    assert controller.pre_free_plan.planned_energy_kwh == pytest.approx(0.93)
    assert controller.decision_phase == "pre_free_combined"


async def test_budget_falls_normally_without_current_changes_on_every_tick(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass, budget=0.5)
    _power(hass, coordinator, _at(11), surplus=0.5)
    await controller.async_reconcile(_at(11))
    accepted = controller.target_current_a
    assert accepted == 5
    _set_current_feedback(hass, accepted)
    initial_calls = len(calls)
    energy = 0.5

    for tick in range(1, 20):
        # The accepted 3.45 kW uses 2.95 kW of discretionary battery power.
        energy -= (accepted * 0.69 - 0.5) / 120
        now = _at(11) + timedelta(seconds=30 * tick)
        _budget(coordinator, energy)
        _power(hass, coordinator, now, surplus=0.5, current=accepted)
        await controller.async_reconcile(now)
        assert controller.target_current_a == accepted

    assert not any(
        data.get("entity_id") == "number.car_current" for _, _, data in calls[initial_calls:]
    )
    assert energy > 0


async def test_house_surge_revokes_budget_and_reanchors_reduction_without_tick_chatter(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass, budget=0.5)
    _power(hass, coordinator, _at(11), surplus=0.5)
    await controller.async_reconcile(_at(11))
    _set_current_feedback(hass, controller.target_current_a)
    # Additional house protection immediately removes 0.3 kWh authority.
    _budget(coordinator, 0.2)
    _power(hass, coordinator, _at(11, 1), surplus=0.5, current=5, house=3)
    await controller.async_reconcile(_at(11, 1))
    lower = controller.target_current_a
    assert lower < 5
    assert lower == 2
    _set_current_feedback(hass, lower)
    after_reduction = len(calls)
    energy = 0.2

    for tick in range(1, 5):
        energy -= (lower * 0.69 - 0.5) / 120
        now = _at(11, 1) + timedelta(seconds=30 * tick)
        _budget(coordinator, energy)
        _power(hass, coordinator, now, surplus=0.5, current=lower, house=3)
        await controller.async_reconcile(now)
        assert controller.target_current_a == lower
    assert not any(
        data.get("entity_id") == "number.car_current" for _, _, data in calls[after_reduction:]
    )


@pytest.mark.parametrize("percent,expected", [(50, 10), (20, 4), (5, 1)])
async def test_exhausted_battery_budget_solar_successor_cannot_bypass_inverter_cap(
    hass, percent, expected
):
    _services(hass)
    coordinator, controller = _scenario(hass, budget=2, ev_outside_inverter_percent=percent)
    _power(hass, coordinator, _at(11), surplus=20)
    await controller.async_reconcile(_at(11))
    _set_current_feedback(hass, controller.target_current_a)
    _budget(coordinator, 0)
    _power(hass, coordinator, _at(11, 1), surplus=20, current=expected)
    await controller.async_reconcile(_at(11, 1))

    assert controller.target_current_a == expected
    assert controller.outside_stage_selection.stage == "morning_solar"
    assert not controller.pre_free_session.active
    assert controller.measured_solar_adjustment.battery_current_a is None
    assert controller.target_current_a * 0.69 <= 15 * percent / 100


async def test_restart_retains_anchored_remaining_hold_not_a_new_energy_budget(hass):
    _services(hass)
    coordinator, controller = _scenario(hass, budget=0.5)
    _power(hass, coordinator, _at(11), surplus=0.5)
    await controller.async_reconcile(_at(11))
    _set_current_feedback(hass, 5)
    # Five minutes at 3.45 kW, of which 0.5 kW is direct solar.
    _budget(coordinator, 0.5 - (3.45 - 0.5) / 12)
    await controller._async_save(_at(11, 5))
    restarted = ActiveEvController(hass, coordinator)
    await restarted._async_restore()
    _power(hass, coordinator, _at(11, 5), surplus=0.5, current=5)
    await restarted.async_reconcile(_at(11, 5))

    assert restarted.target_current_a == 5
    assert restarted.measured_solar_adjustment.changed_at == _at(11)
    assert restarted.pre_free_plan.planned_energy_kwh < 0.5
    assert restarted.decision_phase == "pre_free_combined"


@pytest.mark.parametrize("phases,baseline", [(1, 0), (1, 1), (3, 0), (3, 1)])
@pytest.mark.parametrize("profile", ["steady", "cloud", "house_surge"])
async def test_half_hour_physical_replay_never_spends_more_discretionary_energy_than_approved(
    hass, phases, baseline, profile
):
    _services(hass)
    initial_budget = 0.93
    coordinator, controller = _scenario(
        hass,
        budget=initial_budget,
        ev_phase_count=phases,
        site_phase_count=phases,
        ev_protected_baseline_a=baseline,
        ev_max_current=15,
    )
    energy = initial_budget
    spent = 0.0
    revoked = 0.0
    actual = baseline
    _set_current_feedback(hass, actual, maximum=15)
    for tick in range(60):
        now = _at(11) + timedelta(seconds=30 * tick)
        solar = 0.5 if profile != "cloud" or tick < 4 or tick >= 18 else 0.0
        if profile == "house_surge" and tick == 4:
            deduction = min(energy, 0.25)
            energy -= deduction
            revoked += deduction
        _budget(coordinator, energy)
        _power(hass, coordinator, now, surplus=solar, current=actual)
        await controller.async_reconcile(now)
        actual = controller.target_current_a or 0
        assert actual <= 15
        assert actual * 230 * phases / 1000 <= 7.5
        _set_current_feedback(hass, actual, maximum=15)
        discretionary_kw = max((actual - baseline) * 230 * phases / 1000 - solar, 0)
        delta = discretionary_kw / 120
        assert delta <= energy + 1e-9
        spent += delta
        energy -= delta

    assert spent + revoked <= initial_budget + 1e-9
    assert energy >= -1e-9
    assert spent > 0.5


async def test_departure_immediately_ends_frontload_without_new_current_writes(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _set_current_feedback(hass, controller.target_current_a)
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("device_tracker.car", "not_home")
    hass.states.async_set("sensor.car_charging", "disconnected")
    _power(hass, coordinator, _at(11, 1), current=0)
    before = len(calls)
    await controller.async_reconcile(_at(11, 1))

    assert calls[before:] == []
    assert not controller.pre_free_session.active
    assert controller.measured_solar_adjustment.battery_current_a is None


async def test_independent_free_window_takes_over_frontload_at_exact_boundary(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass, ev_outside_inverter_percent=20)
    await controller.async_reconcile(_at(11))
    assert controller.target_current_a == 4
    _set_current_feedback(hass, 4)
    _power(hass, coordinator, _at(12, 1), surplus=0, current=4)
    before = len(calls)
    await controller.async_reconcile(_at(12, 1))

    assert controller.target_current_a == 16
    assert not controller.pre_free_session.active
    assert controller.measured_solar_adjustment.battery_current_a is None
    assert not any(service == "turn_off" for _, service, _ in calls[before:])


async def test_no_initial_solar_does_not_convert_frontload_into_overnight_charging(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass, ev_pre_free_backfill_timing="conservative")
    _power(hass, coordinator, _at(2), surplus=0)
    await controller.async_reconcile(_at(2))

    assert not controller.pre_free_session.active
    assert controller.pre_free_phase == "waiting_latest_start"
    assert controller.target_current_a in (0, None)
    assert not any(service == "turn_on" for _, service, _ in calls)


async def test_standalone_morning_solar_is_not_reinterpreted_as_battery_frontload(hass):
    _services(hass)
    coordinator, controller = _scenario(hass, ev_pre_free_backfill_enabled=False)
    _power(hass, coordinator, _at(11), surplus=2.5)
    await controller.async_reconcile(_at(11))

    assert controller.target_current_a == 3
    assert not controller.pre_free_session.active
    assert controller.outside_stage_selection.stage == "morning_solar"
    assert controller.measured_solar_adjustment.battery_current_a is None


async def test_lost_house_evidence_discards_frontload_budget_not_solar_evidence(hass):
    _services(hass)
    coordinator, controller = _scenario(hass)
    await controller.async_reconcile(_at(11))
    _set_current_feedback(hass, controller.target_current_a)
    _power(hass, coordinator, _at(11, 1), surplus=2.5, current=10)
    coordinator.telemetry = replace(
        coordinator.telemetry,
        house_load=replace(coordinator.telemetry.house_load, valid=False, fresh=False, value=None),
    )
    await controller.async_reconcile(_at(11, 1))

    assert controller.target_current_a == 3
    assert not controller.pre_free_session.active
    assert controller.measured_solar_adjustment.battery_current_a is None


async def test_reanchored_sub_minimum_downshift_releases_latch_and_actually_stops(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass, ev_outside_inverter_percent=100)
    hass.states.async_set("number.car_current", "6", {"min": 6, "max": 16, "step": 1})
    await controller.async_reconcile(_at(11))
    assert controller.target_current_a == 16
    _charging(hass, 16)
    hass.states.async_set("number.car_current", "16", {"min": 6, "max": 16, "step": 1})
    _budget(coordinator, 0.3)

    # Two minutes remain in the old hold. A reduction must instead be safe
    # over its newly anchored ten minutes, which cannot sustain the 6 A minimum.
    for minute in (8, 9):
        _power(hass, coordinator, _at(11, minute), surplus=0.1, current=16)
        before = len(calls)
        await controller.async_reconcile(_at(11, minute))
        assert controller.target_current_a == 0
        assert not controller.pre_free_session.active
        assert controller.measured_solar_adjustment.battery_current_a is None
        assert controller.decision_phase != "pre_free_backfill"
        assert not any(service == "turn_on" for _, service, _ in calls[before:])

    assert any(service == "turn_off" for _, service, _ in calls)
    assert controller.daily_backfill_stop_pending


async def test_display_rounding_cannot_round_live_raw_energy_authority_up(hass):
    calls = _services(hass)
    coordinator, controller = _scenario(hass, budget=0.0006)
    _power(hass, coordinator, _at(12, 0, 30), surplus=0.6)
    await controller.async_reconcile(_at(12, 0, 30))

    # The legacy plan display rounds .0006 to .001 kWh. A 1 A three-phase
    # request would spend .00075 kWh of battery before the next control tick.
    assert controller.pre_free_plan.planned_energy_kwh == 0.001
    assert controller.target_current_a in (0, None)
    assert not controller.pre_free_session.active
    assert not any(service == "turn_on" for _, service, _ in calls)


@pytest.mark.parametrize("phases", [1, 3])
async def test_quantized_soc_budget_limits_measured_overshoot_to_observation_quantum(hass, phases):
    _services(hass)
    initial_budget = 0.93
    quantum_kwh = 0.4  # A 1%-resolution observation on a synthetic 40 kWh pack.
    coordinator, controller = _scenario(
        hass,
        budget=initial_budget,
        ev_phase_count=phases,
        site_phase_count=phases,
        ev_max_current=15,
    )
    physical_remaining = initial_budget
    observed_remaining = initial_budget
    last_target = 0
    for tick in range(60):
        now = _at(11) + timedelta(seconds=30 * tick)
        # Model sample-and-hold battery SoC: physical energy is not magically
        # known between quantized readings. No additional estimator is assumed.
        if physical_remaining > 0:
            observed_remaining = min(
                initial_budget, ceil(physical_remaining / quantum_kwh) * quantum_kwh
            )
        else:
            observed_remaining = 0
        _budget(coordinator, observed_remaining)
        _power(hass, coordinator, now, surplus=0.5, current=last_target)
        await controller.async_reconcile(now)
        last_target = controller.target_current_a or 0
        _set_current_feedback(hass, last_target, maximum=15)
        battery_kw = max(last_target * 230 * phases / 1000 - 0.5, 0)
        delta = battery_kw / 120
        # Every command remains bounded by observed authority, which is not a
        # promise that the continuous physical pool is measured perfectly.
        assert delta <= observed_remaining + 1e-9
        physical_remaining -= delta
        assert physical_remaining >= -quantum_kwh - 7.5 / 120

    assert physical_remaining <= quantum_kwh
