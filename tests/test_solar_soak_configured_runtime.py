"""Configured afternoon solar values drive the actual shared EV controller."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    plan_solar_spill_current,
)
from tests.test_ev_backfill_timing import _services
from tests.test_ev_outside_window import SOLAR
from tests.test_ev_solar_soak import _ack, _now, _power, _rig


@pytest.mark.parametrize("field,expected", [
    ("ev_solar_soak_battery_soc_percent", 100),
    ("ev_solar_soak_average_minutes", 5),
    ("ev_solar_soak_adjustment_minutes", 5),
])
def test_corrupt_saved_huge_integer_cannot_crash_typed_runtime(field, expected):
    runtime = RuntimeConfiguration.from_mapping({field: 10**1000})
    assert runtime.ev_numbers.value(field, -1) == expected


@pytest.fixture(autouse=True)
def utc_clock(monkeypatch):
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.ev_active.dt_util.now",
        lambda: datetime.now(UTC),
    )


@pytest.mark.parametrize("floor", [0, 20, 75, 90, 95, 100])
@pytest.mark.parametrize("soc", [75, 90, 95, 100])
def test_pure_buffer_floor_is_explicit_not_a_policy_literal(floor, soc):
    result = plan_solar_spill_current(
        replace(SOLAR, battery_soc_percent=soc), buffered=True,
        mean_surplus_kw=3.43, sellable_energy_kwh=10, solar_generation_kw=4,
        buffer_floor_percent=floor,
    )
    assert (result.current_a > 0) == (soc > floor)


@pytest.mark.parametrize("floor", [None, True, -1, 101, float("nan"), float("inf")])
def test_missing_or_invalid_explicit_floor_cannot_authorise_buffer(floor):
    result = plan_solar_spill_current(
        SOLAR, buffered=True, mean_surplus_kw=3.43, sellable_energy_kwh=10,
        solar_generation_kw=4, buffer_floor_percent=floor,
    )
    assert result.current_a == 0


@pytest.mark.parametrize("floor,reserve,soc,allowed", [
    (75, 20, 80, True), (95, 20, 94, False), (75, 85, 80, False),
    (75, 85, 86, True), (100, 20, 100, False),
])
async def test_actual_controller_uses_configured_floor_and_higher_existing_reserve(
    hass, freezer, floor, reserve, soc, allowed,
):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(
        hass, now, ev_solar_soak_battery_soc_percent=floor,
        ev_outside_battery_reserve_percent=reserve,
    )
    _power(hass, coordinator, now, battery_soc=soc)
    await controller.async_reconcile(now)
    assert controller._solar_soak_active is allowed
    if allowed:
        assert controller.target_current_a == 5
    else:
        assert controller.target_current_a in (None, 0)


@pytest.mark.parametrize("mean_minutes,expected", [(1, 6), (10, 5)])
async def test_runtime_uses_saved_average_separately_from_update_interval(
    hass, freezer, mean_minutes, expected,
):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(
        hass, now, ev_solar_soak_average_minutes=mean_minutes,
        ev_solar_soak_adjustment_minutes=1,
    )
    trace = []
    for seconds in range(0, 151, 30):
        at = now + timedelta(seconds=seconds)
        freezer.move_to(at)
        _power(hass, coordinator, at, surplus=1 if seconds < 60 else 4,
               current=controller.target_current_a or 0)
        await controller.async_reconcile(at)
        _ack(hass, controller)
        trace.append((seconds, controller.target_current_a,
                      controller.solar_soak_average.window.result(at).value,
                      controller.measured_solar_adjustment.changed_at))
    assert controller.solar_soak_average.window.duration == timedelta(minutes=mean_minutes)
    assert controller.target_current_a == expected, trace


@pytest.mark.parametrize("cadence,expected", [(1, 5), (10, 2)])
async def test_saved_adjustment_period_controls_ordinary_updates(hass, freezer, cadence, expected):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(
        hass, now, ev_solar_soak_adjustment_minutes=cadence,
    )
    for seconds in range(0, 151, 30):
        at = now + timedelta(seconds=seconds)
        freezer.move_to(at)
        _power(hass, coordinator, at, surplus=1 if seconds == 0 else 3.43,
               current=controller.target_current_a or 0)
        await controller.async_reconcile(at)
        _ack(hass, controller)
    assert controller.target_current_a == expected


async def test_raising_floor_curtails_before_any_positive_service_or_long_cadence(hass, freezer):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(hass, now, ev_solar_soak_adjustment_minutes=30)
    _power(hass, coordinator, now, battery_soc=92)
    await controller.async_reconcile(now)
    _ack(hass, controller)
    assert controller.target_current_a == 5
    coordinator.update_config_value("ev_solar_soak_battery_soc_percent", 95)
    assert not controller._solar_soak_write_authorized()
    at = now + timedelta(seconds=30)
    freezer.move_to(at)
    _power(hass, coordinator, at, current=5, battery_soc=92)
    await controller.async_reconcile(at)
    assert controller.target_current_a == 0
    assert not controller.solar_soak_average.window.samples


@pytest.mark.parametrize("field,value", [
    ("ev_solar_soak_battery_soc_percent", 95),
    ("ev_solar_soak_average_minutes", 10),
    ("ev_solar_soak_adjustment_minutes", 10),
])
async def test_changed_policy_does_not_restore_old_mean_or_cadence(hass, freezer, field, value):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(hass, now)
    await controller.async_reconcile(now)
    await controller._async_save(now)
    coordinator.update_config_value(field, value)
    at = now + timedelta(seconds=30)
    freezer.move_to(at)
    restored = ActiveEvController(hass, coordinator)
    await restored._async_restore()
    assert not restored.solar_soak_average.window.samples
    _power(hass, coordinator, at, surplus=0.7)
    await restored.async_reconcile(at)
    assert restored.target_current_a == 2


async def test_runtime_window_change_starts_new_evidence_and_leaves_other_settings(hass, freezer):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(hass, now)
    await controller.async_reconcile(now)
    _ack(hass, controller)
    before = dict(coordinator.config)
    coordinator.update_config_value("ev_solar_soak_average_minutes", 2)
    at = now + timedelta(seconds=30)
    freezer.move_to(at)
    _power(hass, coordinator, at, surplus=0.7, current=5)
    await controller.async_reconcile(at)
    assert controller.target_current_a == 2
    assert len(controller.solar_soak_average.window.samples) == 1
    assert controller.solar_soak_average.window.duration == timedelta(minutes=2)
    assert {k: v for k, v in coordinator.config.items() if k in before} == before
    assert RuntimeConfiguration.from_mapping(coordinator.config).ev_policy.solar_spill_enabled
