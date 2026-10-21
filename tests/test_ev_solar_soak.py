"""Afternoon buffered solar capture, with original outside limits and owners."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    plan_solar_spill_current,
)
from custom_components.home_energy_orchestrator.planner.ev_solar_soak import SolarSoakAverage
from custom_components.home_energy_orchestrator.telemetry import NormalizedSample, TelemetrySource
from tests.test_ev_backfill_timing import _fresh, _services
from tests.test_ev_before_export_charging import _case
from tests.test_ev_outside_window import SOLAR


def _now():
    return datetime(2026, 9, 7, 16, tzinfo=UTC)


@pytest.fixture(autouse=True)
def utc_clock(monkeypatch):
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.ev_active.dt_util.now",
        lambda: datetime.now(UTC),
    )


def _rig(hass, now, **config):
    changes = dict(
        ev_before_export_enabled=False,
        configure_solar=True,
        solar_power_entity="sensor.solar",
        ev_solar_spill_enabled=True,
        ev_outside_inverter_percent=50,
    )
    changes.update(config)
    coordinator, controller = _case(hass, now, **changes)
    _power(hass, coordinator, now)
    return coordinator, controller


def _power(hass, coordinator, now, *, surplus=3.43, current=0, battery_soc=99, solar=None):
    _fresh(coordinator, now, current_a=current)
    phases = coordinator.config["ev_phase_count"]
    battery = surplus - current * 230 * phases / 1000

    def sample(entity, value):
        return NormalizedSample(
            value,
            "kW",
            (TelemetrySource(entity, value, "kW", now),),
            "positive_charge",
            True,
            True,
            "ok",
        )

    coordinator.telemetry = replace(
        coordinator.telemetry,
        battery_power=sample("sensor.battery_power", battery),
        solar_power=sample("sensor.solar", surplus + 0.2 if solar is None else solar),
    )
    coordinator.snapshot = replace(coordinator.snapshot, battery_soc=battery_soc, grid_power_kw=0)
    for entity, value, unit in [
        ("sensor.site_battery_soc", battery_soc, "%"),
        ("sensor.site_grid", 0, "kW"),
        ("sensor.battery_power", battery, "kW"),
        ("sensor.house", 0.2, "kW"),
        ("sensor.solar", surplus + 0.2 if solar is None else solar, "kW"),
        ("sensor.car_actual_current", current, "A"),
    ]:
        hass.states.async_set(entity, str(value), {"unit_of_measurement": unit}, force_update=True)
    for entity, state in [
        ("device_tracker.car", "home"),
        ("binary_sensor.car_cable", "on"),
        ("sensor.car_charging", "charging" if current else "stopped"),
        ("switch.car_charge", "on" if current else "off"),
    ]:
        hass.states.async_set(entity, state, force_update=True)
    for entity in [
        "sensor.car_soc",
        "number.car_current",
        "number.car_limit",
        "select.foxess_mode",
    ]:
        old = hass.states.get(entity)
        hass.states.async_set(entity, old.state, dict(old.attributes), force_update=True)


def _ack(hass, controller):
    hass.states.async_set(
        "number.car_current",
        str(controller.target_current_a),
        {"min": 1, "max": 16, "step": 1, "unit_of_measurement": "A"},
    )
    hass.states.async_set(
        "number.car_limit",
        str(controller.target_limit_percent),
        {"min": 0, "max": 100, "step": 1, "unit_of_measurement": "%"},
    )


@pytest.mark.parametrize(
    "phases,step,mean,cap,expected",
    [
        (1, 1, 0.231, 15, 2),
        (1, 1, 0.46, 15, 2),
        (3, 1, 3.43, 16, 5),
        (3, 2, 3.43, 16, 6),
        (3, 2, 9, 3, 2),
        (1, 1, 4, 5.5, 5),
    ],
)
def test_mean_is_rounded_up_once_then_clipped_to_supported_cap(phases, step, mean, cap, expected):
    row = replace(
        SOLAR, voltage_v=230, phase_count=phases, current_step_a=step, current_ceiling_a=cap
    )
    decision = plan_solar_spill_current(
        row, buffered=True, mean_surplus_kw=mean, sellable_energy_kwh=10, solar_generation_kw=4
    )
    assert decision.current_a == expected
    assert decision.current_a <= cap


@pytest.mark.parametrize("soc", [89, 90, 90.0001, 92, 99, 100])
@pytest.mark.parametrize("budget", [None, 0, 0.00001, 1])
def test_buffer_boundary_and_budget_are_not_replaced_by_full_battery(soc, budget):
    decision = plan_solar_spill_current(
        replace(SOLAR, battery_soc_percent=soc),
        buffered=True,
        mean_surplus_kw=3.43,
        sellable_energy_kwh=budget,
        solar_generation_kw=4,
    )
    assert (decision.current_a > 0) == (soc > 90 and budget == 1)


def test_average_is_time_weighted_not_sample_weighted_and_restores_without_tail():
    average = SolarSoakAverage()
    now = _now()
    for seconds, value in [(0, 1), (60, 5), (120, 5), (180, 5), (240, 5), (300, 9)]:
        result = average.observe(
            now + timedelta(seconds=seconds), value, binding=["same"], max_gap_seconds=90
        )
    assert result == pytest.approx(4.2)
    restored = SolarSoakAverage()
    assert restored.restore(
        average.to_payload(), now + timedelta(seconds=320), binding=["same"], max_gap_seconds=90
    )
    assert restored.window.result(now + timedelta(seconds=320)).value == pytest.approx(4.733333)
    assert not restored.restore(
        average.to_payload(), now + timedelta(seconds=391), binding=["same"], max_gap_seconds=90
    )
    assert restored.window.samples == []
    assert (
        average.observe(now + timedelta(seconds=391), 0.2, binding=["same"], max_gap_seconds=90)
        == 0.2
    )


@pytest.mark.parametrize("fault", ["binding", "future", "invalid", "order", "gap", "nan"])
def test_corrupt_history_cannot_survive_restore(fault):
    a = SolarSoakAverage()
    now = _now()
    a.observe(now, 5, binding=["same"], max_gap_seconds=90)
    payload = a.to_payload()
    rows = payload["window"]["samples"]
    if fault == "binding":
        payload["binding"] = ["other"]
    elif fault == "future":
        rows[0]["at"] = (now + timedelta(seconds=1)).isoformat()
    elif fault == "invalid":
        rows[0]["source_valid"] = False
    elif fault == "order":
        rows.append(dict(rows[0]))
    elif fault == "gap":
        rows[0]["at"] = (now - timedelta(seconds=91)).isoformat()
    elif fault == "nan":
        rows[0]["value"] = float("nan")
    assert not a.restore(payload, now, binding=["same"], max_gap_seconds=90)
    assert a.window.samples == []


@pytest.mark.parametrize(
    "phases,inverter,percent,maximum,expected",
    [
        (1, 10, 50, 15, 15),
        (3, 15, 50, 16, 10),
        (3, 8, 50, 16, 5),
        (1, 3, 40, 16, 5),
    ],
)
async def test_runtime_uses_saved_inverter_percentage_after_rounding(
    hass,
    freezer,
    phases,
    inverter,
    percent,
    maximum,
    expected,
):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(
        hass,
        now,
        ev_phase_count=phases,
        site_phase_count=phases,
        inverter_discharge_limit_kw=inverter,
        ev_outside_inverter_percent=percent,
        ev_max_current=maximum,
    )
    _power(hass, coordinator, now, surplus=10)
    await controller.async_reconcile(now)
    assert controller.decision_phase == "solar_spill"
    assert controller.target_current_a == expected
    assert controller.target_current_a * 230 * phases / 1000 <= inverter * percent / 100


async def test_clouds_cannot_reset_five_minute_clock_or_make_every_tick_write(hass, freezer):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _rig(hass, now)
    targets = []
    for seconds in range(0, 931, 30):
        at = now + timedelta(seconds=seconds)
        freezer.move_to(at)
        _power(
            hass,
            coordinator,
            at,
            surplus=(1 if seconds == 0 else (3.2 if seconds % 60 else 3.6)),
            current=controller.target_current_a or 0,
        )
        await controller.async_reconcile(at)
        targets.append(controller.target_current_a)
        _ack(hass, controller)
    assert targets[0] == 2
    assert all(x == 2 for x in targets[:10]), targets
    assert targets[10] == 5
    assert controller.solar_soak_average.window.result(at).value == pytest.approx(3.4)
    writes = [
        x
        for x in calls
        if x[:2] == ("number", "set_value") and x[2]["entity_id"] == "number.car_current"
    ]
    assert len(writes) <= 4


@pytest.mark.parametrize(
    "fault", ["solar_zero", "solar_stale", "budget_zero", "battery_90", "import", "service"]
)
async def test_safety_loss_curtails_at_next_tick_not_three_or_five_minutes(hass, freezer, fault):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(hass, now)
    await controller.async_reconcile(now)
    assert controller.target_current_a == 5
    _ack(hass, controller)
    at = now + timedelta(seconds=30)
    freezer.move_to(at)
    _power(hass, coordinator, at, current=5)
    if fault == "solar_zero":
        _power(hass, coordinator, at, current=5, solar=0)
    elif fault == "solar_stale":
        coordinator.telemetry = replace(
            coordinator.telemetry,
            solar_power=replace(coordinator.telemetry.solar_power, fresh=False),
        )
    elif fault == "budget_zero":
        coordinator.data.available_after_reserve_kwh = 0
    elif fault == "battery_90":
        _power(hass, coordinator, at, current=5, battery_soc=90)
    elif fault == "import":
        _fresh(coordinator, at, grid_kw=1, current_a=5)
    elif fault == "service":
        coordinator.telemetry = replace(
            coordinator.telemetry,
            site_grid_current=replace(coordinator.telemetry.site_grid_current, value=79.9),
        )
    await controller.async_reconcile(at)
    assert controller.target_current_a < 5
    if fault != "service":
        assert not controller.solar_soak_average.window.samples


@pytest.mark.parametrize("live_soc", [90, 89.9, 20])
async def test_live_battery_floor_wins_over_lagging_snapshot(hass, freezer, live_soc):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(hass, now)
    await controller.async_reconcile(now)
    _ack(hass, controller)
    at = now + timedelta(seconds=30)
    freezer.move_to(at)
    _power(hass, coordinator, at, current=5)
    hass.states.async_set("sensor.site_battery_soc", str(live_soc), {"unit_of_measurement": "%"})
    assert coordinator.snapshot.battery_soc == 99
    assert not controller._solar_soak_write_authorized()
    await controller.async_reconcile(at)
    assert controller.target_current_a == 0


@pytest.mark.parametrize(
    "fault", ["solar", "budget", "soc", "full", "disabled", "priority", "bad_priority", "cap"]
)
async def test_each_positive_service_rechecks_current_authority(hass, freezer, fault):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(hass, now)
    await controller.async_reconcile(now)
    assert controller._solar_soak_write_authorized()
    if fault == "solar":
        coordinator.telemetry = replace(
            coordinator.telemetry, solar_power=replace(coordinator.telemetry.solar_power, value=0)
        )
    elif fault == "budget":
        coordinator.data.available_after_reserve_kwh = 0
    elif fault == "soc":
        hass.states.async_set("sensor.site_battery_soc", "90", {"unit_of_measurement": "%"})
    else:
        delta = {
            "full": {"ev_charge_to_full_enabled": True},
            "disabled": {"ev_solar_spill_enabled": False},
            "priority": {
                "ev_before_export_enabled": True,
                "ev_before_export_soc_target_percent": 40,
            },
            "bad_priority": {
                "ev_before_export_enabled": True,
                "ev_before_export_soc_target_percent": float("nan"),
            },
            "cap": {"ev_outside_inverter_percent": 1},
        }[fault]
        coordinator.config.update(delta)
        coordinator.runtime_config = RuntimeConfiguration.from_mapping(coordinator.config)
    assert not controller._solar_soak_write_authorized()


async def test_lost_budget_between_services_cannot_start_and_cleanup_still_works(hass, freezer):
    now = _now()
    freezer.move_to(now)
    calls = []
    coordinator, controller = _rig(hass, now)

    async def accept(call):
        calls.append((call.domain, call.service, dict(call.data)))
        coordinator.data.available_after_reserve_kwh = 0

    hass.services.async_register("number", "set_value", accept)
    hass.services.async_register("switch", "turn_on", accept)
    hass.services.async_register("switch", "turn_off", accept)
    await controller.async_reconcile(now)
    assert len(calls) == 1
    assert not any(x[1] == "turn_on" for x in calls)
    at = now + timedelta(seconds=30)
    freezer.move_to(at)
    _power(hass, coordinator, at, current=5)
    await controller.async_reconcile(at)
    assert not controller._solar_soak_active
    assert controller.target_current_a == 0
    assert any(x[1] == "turn_off" for x in calls)


@pytest.mark.parametrize("delay", [30, 91])
async def test_restart_keeps_only_recent_bound_history_and_existing_cadence(hass, freezer, delay):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(hass, now)
    await controller.async_reconcile(now)
    await controller._async_save(now)
    at = now + timedelta(seconds=delay)
    freezer.move_to(at)
    restored = ActiveEvController(hass, coordinator)
    await restored._async_restore()
    assert bool(restored.solar_soak_average.window.samples) == (delay <= 90)
    _power(hass, coordinator, at, surplus=0.7)
    await restored.async_reconcile(at)
    assert restored.target_current_a == (5 if delay <= 90 else 2)


@pytest.mark.parametrize(
    "field",
    [
        "battery_power_entity",
        "battery_charge_power_entity",
        "battery_discharge_power_entity",
        "solar_power_entity",
        "ev_actual_current_entity",
    ],
)
async def test_source_rebinding_discards_the_old_mean(hass, freezer, field):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(hass, now)
    await controller.async_reconcile(now)
    payload = controller.solar_soak_average.to_payload()
    coordinator.config[field] = "sensor.different_source"
    coordinator.runtime_config = RuntimeConfiguration.from_mapping(coordinator.config)
    assert not controller.solar_soak_average.restore(
        payload, now, binding=controller._solar_soak_binding(), max_gap_seconds=90
    )


async def test_post_free_to_legacy_pre_free_spill_does_not_hold_buffered_target(hass, freezer):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(hass, now)
    await controller.async_reconcile(now)
    assert controller.target_current_a == 5
    _ack(hass, controller)
    at = now.replace(hour=23)
    freezer.move_to(at)
    _power(hass, coordinator, at, current=5, surplus=0.7, battery_soc=100)
    await controller.async_reconcile(at)
    assert controller.target_current_a == 1
    assert not controller.solar_soak_average.window.samples
    assert not controller._solar_soak_active


@pytest.mark.parametrize("owner", ["full", "free", "before_export"])
async def test_higher_priority_owner_gets_its_own_current_without_solar_history(
    hass, freezer, owner
):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _rig(hass, now)
    await controller.async_reconcile(now)
    _ack(hass, controller)
    at = now + timedelta(seconds=30)
    freezer.move_to(at)
    _power(hass, coordinator, at, current=5)
    delta = {
        "full": {"ev_charge_to_full_enabled": True},
        "free": {"free_charge_window_start": "16:00:00", "free_charge_window_end": "17:00:00"},
        "before_export": {
            "ev_before_export_enabled": True,
            "ev_before_export_soc_target_percent": 40,
        },
    }[owner]
    coordinator.config.update(delta)
    coordinator.runtime_config = RuntimeConfiguration.from_mapping(coordinator.config)
    await controller.async_reconcile(at)
    assert not controller._solar_soak_active
    assert not controller.solar_soak_average.window.samples
    assert not controller.decision_phase.startswith("solar_spill")
