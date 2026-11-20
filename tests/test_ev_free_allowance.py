"""Measured allowance ends free charging, without changing ordinary EV policies."""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.planner.daily_meter import WindowImportAccumulator
from custom_components.home_energy_orchestrator.telemetry import NormalizedSample, TelemetrySource
from tests.test_ev_backfill_timing import _services
from tests.test_ev_solar_soak import _ack, _power, _rig


@pytest.fixture(autouse=True)
def utc_clock(monkeypatch):
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.ev_active.dt_util.now",
        lambda: datetime.now(UTC),
    )


def _meter(coordinator, now, imported):
    coordinator.free_window_import = SimpleNamespace(last_at=now, imported_kwh=imported)


def _case(hass, now, **changes):
    config = dict(
        ev_allowance_guard_enabled=True,
        daily_free_allowance_kwh=50,
        ev_allowance_safety_margin_kwh=2,  # Retired projection must not pace at 48 kWh.
        ev_free_window_priority="ev",
        ev_free_window_charge_limit_percent=90,
        ev_phase_count=3,
        site_phase_count=3,
        ev_solar_spill_enabled=False,
    )
    config.update(changes)
    return _rig(hass, now, **config)


@pytest.mark.parametrize("imported", [0, 24, 48, 49.999])
async def test_ev_priority_uses_maximum_until_measured_allowance(hass, freezer, imported):
    now = datetime(2026, 9, 7, 13, tzinfo=UTC)
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _case(hass, now)
    _meter(coordinator, now, imported)
    _power(hass, coordinator, now, surplus=0, battery_soc=20, solar=0)
    # Neither a large house-battery deficit nor missing stored EV energy may
    # create a forecast-derived current ceiling. Normal live feedback is valid.
    hass.states.async_set("sensor.car_energy", "unavailable")
    coordinator.snapshot = replace(coordinator.snapshot, house_load_kw=12)

    await controller.async_reconcile(now)

    assert controller.policy_route.route == "free_window"
    assert controller.decision_phase == "ev_priority_maximum"
    assert controller.target_current_a == 16
    assert controller.target_limit_percent <= 90


@pytest.mark.parametrize("imported", [50, 50.001, 55])
async def test_exhaustion_uses_outside_policy_even_inside_clock_window(hass, freezer, imported):
    now = datetime(2026, 9, 7, 13, tzinfo=UTC)
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now)
    _meter(coordinator, now, imported)
    _power(hass, coordinator, now, surplus=0, battery_soc=20, solar=0, current=16)

    await controller.async_reconcile(now)

    assert controller.policy_route.route != "free_window"
    assert controller.target_current_a in (None, 0)
    assert not any(service == "turn_on" for _, service, _ in calls)
    assert controller.last_actions == ("stop_charging",)


async def test_exhaustion_interrupts_decision_cadence_and_delayed_ramp(hass, freezer):
    now = datetime(2026, 9, 7, 13, tzinfo=UTC)
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now, house_load_includes_ev=True)
    _meter(coordinator, now, 49.999)
    await controller.async_reconcile(now)
    assert controller.target_current_a == 16
    _ack(hass, controller)
    calls.clear()

    now += timedelta(seconds=1)
    freezer.move_to(now)
    _meter(coordinator, now, 50)
    _power(hass, coordinator, now, surplus=0, battery_soc=20, solar=0, current=2)
    await controller.async_reconcile(now)

    assert controller.target_current_a in (None, 0)
    assert controller.last_actions == ("stop_charging",)
    assert not any(service == "turn_on" for _, service, _ in calls)


async def test_exhausted_window_can_use_existing_solar_soak(hass, freezer):
    now = datetime(2026, 9, 7, 13, tzinfo=UTC)
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _case(hass, now, ev_solar_spill_enabled=True)
    _meter(coordinator, now, 50)
    _power(hass, coordinator, now, surplus=3.43, battery_soc=99)

    await controller.async_reconcile(now)

    assert controller.policy_route.route == "outside_window"
    assert controller.decision_phase == "solar_spill"
    assert 0 < controller.target_current_a < 16
    assert controller.target_current_a * 230 * 3 / 1000 <= 15 * 0.5
    assert controller.target_limit_percent <= 90

    # Existing house-reserve stop remains immediate even though quota is used.
    _ack(hass, controller)
    now += timedelta(seconds=1)
    freezer.move_to(now)
    _meter(coordinator, now, 50)
    _power(hass, coordinator, now, surplus=3.43, battery_soc=20, current=5)
    await controller.async_reconcile(now)
    assert controller.target_current_a == 0


@pytest.mark.parametrize("imported", [49.999, 50, 55, None])
async def test_charge_to_full_remains_explicit_maximum_override(hass, freezer, imported):
    now = datetime(2026, 9, 7, 13, tzinfo=UTC)
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _case(hass, now, ev_charge_to_full_enabled=True)
    _meter(coordinator, now if imported is not None else None, imported or 0)
    _power(hass, coordinator, now, surplus=0, battery_soc=20, solar=0)

    await controller.async_reconcile(now)

    assert controller.target_current_a == 16
    assert controller.target_limit_percent == 100
    assert coordinator.free_window_import.imported_kwh == (imported or 0)


@pytest.mark.parametrize("fault", ["missing", "yesterday", "future", "nan"])
async def test_unknown_allowance_cannot_grant_free_charging(hass, freezer, fault):
    now = datetime(2026, 9, 7, 13, tzinfo=UTC)
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _case(hass, now)
    at = {"missing": None, "yesterday": now - timedelta(days=1),
          "future": now + timedelta(seconds=1), "nan": now}[fault]
    coordinator.free_window_import = SimpleNamespace(
        last_at=at, imported_kwh=float("nan") if fault == "nan" else 0,
    )
    await controller.async_reconcile(now)
    assert controller.policy_route.route != "free_window"
    assert controller.target_current_a in (None, 0)


async def test_counter_restart_solar_jitter_and_daily_reset(hass, freezer):
    now = datetime(2026, 9, 7, 13, tzinfo=UTC)
    freezer.move_to(now)
    _services(hass)
    coordinator, _ = _case(hass, now)
    meter = WindowImportAccumulator(window_start=time(12, 1), window_end=time(14, 59))
    meter.restore({"date": now.date().isoformat(), "imported_kwh": 50,
                   "last_at": now.isoformat(), "last_import_kw": 0}, now)
    coordinator.free_window_import = meter
    controller = ActiveEvController(hass, coordinator)
    for power in [0, -0.01, 0.01, -1, 0]:
        now += timedelta(seconds=5)
        freezer.move_to(now)
        meter.observe(power, now)
        _power(hass, coordinator, now, surplus=0, solar=0, battery_soc=20)
        await controller.async_reconcile(now)
        assert controller.policy_route.route != "free_window"
        assert controller.target_current_a in (None, 0)
        assert meter.imported_kwh >= 50

    now += timedelta(days=1)
    freezer.move_to(now)
    meter.observe(0, now)
    _power(hass, coordinator, now, surplus=0, solar=0, battery_soc=20)
    await controller.async_reconcile(now)
    assert controller.policy_route.route == "free_window"
    assert controller.target_current_a == 16
    assert meter.imported_kwh == 0


@pytest.mark.parametrize("imported", [0, 50])
async def test_safety_lock_still_prevents_commands(hass, freezer, imported):
    now = datetime(2026, 9, 7, 13, tzinfo=UTC)
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now, rehearsal_mode=True, ev_charge_to_full_enabled=True)
    _meter(coordinator, now, imported)
    await controller.async_reconcile(now)
    assert all(action.startswith("would_") for action in controller.last_actions)
    assert controller.writes_performed == 0
    assert calls == []


@pytest.mark.parametrize("cap", [24, 50, 75])
async def test_configured_allowance_boundary_and_explicit_opt_out(hass, freezer, cap):
    now = datetime(2026, 9, 7, 13, tzinfo=UTC)
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _case(hass, now, daily_free_allowance_kwh=cap)
    _meter(coordinator, now, cap - 0.001)
    assert controller._free_window(now)[0]
    _meter(coordinator, now, cap)
    assert not controller._free_window(now)[0]
    coordinator.update_config_value("ev_allowance_guard_enabled", False)
    assert controller._free_window(now)[0]


async def test_charge_to_full_cancellation_after_exhaustion_returns_to_normal(hass, freezer):
    now = datetime(2026, 9, 7, 13, tzinfo=UTC)
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now, ev_charge_to_full_enabled=True)
    _meter(coordinator, now, 50)
    await controller.async_reconcile(now)
    assert controller.target_current_a == 16
    _ack(hass, controller)
    coordinator.update_config_value("ev_charge_to_full_enabled", False)
    calls.clear()
    now += timedelta(seconds=1)
    freezer.move_to(now)
    _power(hass, coordinator, now, surplus=0, current=16, solar=0, battery_soc=20)
    await controller.async_reconcile(now)
    assert controller.target_current_a == 0
    assert controller.target_limit_percent <= 90
    assert not any(service == "turn_on" for _, service, _ in calls)


async def test_exhaustion_during_awaited_command_withdraws_old_free_plan(hass, freezer):
    now = datetime(2026, 9, 7, 13, tzinfo=UTC)
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now)
    _meter(coordinator, now, 49.999)

    async def exhaust_after_limit(call):
        calls.append((call.domain, call.service, dict(call.data)))
        _meter(coordinator, now, 50)

    hass.services.async_register("number", "set_value", exhaust_after_limit)
    await controller.async_reconcile(now)
    assert controller.last_actions == ("set_charge_limit",)
    assert controller.last_reason == "ev_write_gate_closed"
    assert not any(service == "turn_on" for _, service, _ in calls)


@pytest.mark.parametrize("fault", ["service_overrun", "missing_service_current", "away"])
async def test_free_allowance_never_bypasses_existing_live_safety(hass, freezer, fault):
    now = datetime(2026, 9, 7, 13, tzinfo=UTC)
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now)
    _meter(coordinator, now, 49)
    if fault == "service_overrun":
        hass.states.async_set("sensor.phase_current", "100", {"unit_of_measurement": "A"})
        coordinator.runtime_config = RuntimeConfiguration.from_mapping({
            **coordinator.config, "site_grid_current_entity": "sensor.phase_current",
        })
        coordinator.telemetry = replace(
            coordinator.telemetry,
            site_grid_current=NormalizedSample(
                100, "A", (TelemetrySource("sensor.phase_current", 100, "A", now),),
                "positive_import", True, True, "ok",
            ),
        )
        for offset in (180, 120, 60, 0):
            controller.grid_average.observe(
                now - timedelta(seconds=offset), 100, source_valid=True,
            )
    elif fault == "missing_service_current":
        hass.states.async_set("sensor.phase_current", "unavailable")
        coordinator.telemetry = replace(
            coordinator.telemetry,
            site_grid_current=replace(
                coordinator.telemetry.site_grid_current, value=None, valid=False, fresh=False,
            ),
        )
    else:
        hass.states.async_set("device_tracker.car", "not_home")
    await controller.async_reconcile(now)
    assert controller.target_current_a in (None, 0, 1)
    if fault != "service_overrun":
        assert not any(service == "turn_on" for _, service, _ in calls)
    assert not any(
        service == "set_value" and call.get("entity_id") == "number.car_current"
        and call["value"] > 1 for _, service, call in calls
    )
