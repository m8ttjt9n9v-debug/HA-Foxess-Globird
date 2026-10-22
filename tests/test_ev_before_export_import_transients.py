"""Real-controller regression: funded EV top-ups must not chatter on CT spikes."""

from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.planner.ev_before_export import (
    EvBeforeExportImport,
    confirm_before_export_import,
)
from custom_components.home_energy_orchestrator.planner.ev_persistence import EvPersistenceState
from tests.test_ev_backfill_timing import _charging, _fresh, _services
from tests.test_ev_before_export_charging import _case, _now


async def _running(hass, freezer, **config):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now, **config)
    await controller.async_reconcile(now)
    assert controller.target_current_a == 8
    _charging(hass, 8)
    hass.states.async_set("number.car_limit", "50", {"min": 0, "max": 100, "step": 1})
    now += timedelta(seconds=30)
    freezer.move_to(now)
    _fresh(coordinator, now, current_a=8)
    await controller.async_reconcile(now)
    hass.states.async_set(
        "number.car_limit", str(controller.target_limit_percent), {"min": 0, "max": 100, "step": 1}
    )
    await controller.async_reconcile(now)
    assert controller.reconciliation.phase == "confirmed"
    calls.clear()
    return now, calls, coordinator, controller


async def _tick(hass, freezer, coordinator, controller, now, *, grid=0, current=8):
    freezer.move_to(now)
    for state in hass.states.async_all():
        hass.states.async_set(
            state.entity_id, state.state, dict(state.attributes), force_update=True
        )
    _charging(hass, current)
    hass.states.async_set(
        "number.car_limit", str(controller.target_limit_percent), {"min": 0, "max": 100, "step": 1}
    )
    _fresh(coordinator, now, current_a=current, grid_kw=grid)
    await controller.async_reconcile(now)


@pytest.mark.parametrize("spike", [0.030001, 0.3, 0.6, 1.7])
async def test_transient_import_does_not_stop_a_funded_topup(hass, freezer, spike):
    now, calls, coordinator, controller = await _running(hass, freezer)
    for offset, grid in [(30, spike), (40, -0.1), (60, spike), (70, 0), (90, spike)]:
        await _tick(
            hass, freezer, coordinator, controller, now + timedelta(seconds=offset), grid=grid
        )
        assert controller.target_current_a == 8, (
            offset,
            controller.decision_phase,
            controller.last_reason,
            controller.before_export_import,
            controller.reconciliation,
        )
        assert controller.decision_phase == "ev_before_export_charging"
    assert not any(call[:2] == ("switch", "turn_off") for call in calls)


async def test_sustained_import_stops_at_configured_boundary(hass, freezer):
    now, calls, coordinator, controller = await _running(hass, freezer)
    for offset in (10, 40, 69):
        await _tick(
            hass, freezer, coordinator, controller, now + timedelta(seconds=offset), grid=0.5
        )
        assert controller.target_current_a == 8
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=70), grid=0.5)
    assert controller.target_current_a == 0
    assert any(call[:2] == ("switch", "turn_off") for call in calls)


@pytest.mark.parametrize("loss", ["budget", "battery", "stale", "disabled", "service"])
async def test_import_hold_never_masks_loss_of_authority(hass, freezer, loss):
    now, calls, coordinator, controller = await _running(hass, freezer)
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=10), grid=0.5)
    now += timedelta(seconds=20)
    freezer.move_to(now)
    _fresh(coordinator, now, current_a=8, grid_kw=0.5)
    if loss == "budget":
        coordinator.active_controller.export_plan = replace(
            coordinator.active_controller.export_plan,
            sellable_energy_kwh=0,
        )
    elif loss == "battery":
        hass.states.async_set("sensor.site_battery_soc", "20", {"unit_of_measurement": "%"})
    elif loss == "stale":
        coordinator.telemetry = replace(
            coordinator.telemetry,
            house_load=replace(
                coordinator.telemetry.house_load,
                fresh=False,
            ),
        )
    elif loss == "disabled":
        coordinator.update_config_value("ev_before_export_enabled", False)
    else:
        coordinator.telemetry = replace(
            coordinator.telemetry,
            site_grid_current=replace(
                coordinator.telemetry.site_grid_current,
                value=100,
            ),
        )
        hass.states.async_set("sensor.phase_current", "100", {"unit_of_measurement": "A"})
    calls.clear()
    await controller.async_reconcile(now)
    assert controller.target_current_a == 0
    assert any(call[:2] == ("switch", "turn_off") for call in calls)


async def test_restart_does_not_renew_an_import_confirmation_period(hass, freezer):
    now, _, coordinator, controller = await _running(hass, freezer)
    now += timedelta(seconds=10)
    await _tick(hass, freezer, coordinator, controller, now, grid=0.5)
    replacement = ActiveEvController(hass, coordinator)
    await replacement._async_restore()
    assert replacement.before_export_import.since == now
    await _tick(hass, freezer, coordinator, replacement, now + timedelta(seconds=60), grid=0.5)
    assert replacement.target_current_a == 0


async def test_zero_confirmation_retains_previous_immediate_import_stop(hass, freezer):
    now, calls, coordinator, controller = await _running(
        hass,
        freezer,
        ev_before_export_import_confirm_seconds=0,
    )
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=10), grid=0.5)
    assert controller.target_current_a == 0
    assert any(call[:2] == ("switch", "turn_off") for call in calls)


async def test_existing_import_never_grants_a_new_start(hass, freezer):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now)
    _fresh(coordinator, now, grid_kw=0.5)
    await controller.async_reconcile(now)
    assert controller.target_current_a == 0
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


async def test_import_hold_cannot_raise_current_or_authorize_positive_writes(hass, freezer):
    now, calls, coordinator, controller = await _running(hass, freezer)
    coordinator.update_config_value("ev_outside_inverter_percent", 100)
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=10), grid=0.5)
    assert controller.target_current_a == 8
    assert not controller._writes_still_authorized()
    assert not calls


@pytest.mark.parametrize("changed", ["inverter_cap", "budget"])
async def test_reduced_ceiling_during_import_stops_instead_of_retaining_old_current(
    hass, freezer, changed,
):
    now, calls, coordinator, controller = await _running(hass, freezer)
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=10), grid=0.5)
    if changed == "inverter_cap":
        coordinator.update_config_value("ev_outside_inverter_percent", 10)
    else:
        coordinator.active_controller.export_plan = replace(
            coordinator.active_controller.export_plan, sellable_energy_kwh=0.07,
        )
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=20), grid=0.5)
    assert controller.target_current_a == 0
    assert any(call[:2] == ("switch", "turn_off") for call in calls)


async def test_import_appearing_between_commands_cannot_start_the_car(hass, freezer):
    now = _now()
    freezer.move_to(now)
    coordinator, controller = _case(hass, now)
    calls = []

    async def spike_after_limit(call):
        calls.append((call.domain, call.service, dict(call.data)))
        _fresh(coordinator, now, grid_kw=0.5)

    for domain, service in [("number", "set_value"), ("switch", "turn_on")]:
        hass.services.async_register(domain, service, spike_after_limit)
    await controller.async_reconcile(now)
    assert len(calls) == 1
    assert calls[0][2]["entity_id"] == "number.car_limit"
    assert controller.last_reason == "ev_write_gate_closed"


async def test_duration_edit_during_import_does_not_renew_the_hold(hass, freezer):
    now, calls, coordinator, controller = await _running(hass, freezer)
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=10), grid=0.5)
    coordinator.update_config_value("ev_before_export_import_confirm_seconds", 120)
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=20), grid=0.5)
    assert controller.target_current_a == 0
    assert any(call[:2] == ("switch", "turn_off") for call in calls)


async def test_confirmed_session_remains_stable_after_retry_episode_rearms(hass, freezer):
    now, calls, coordinator, controller = await _running(hass, freezer)
    # The retained direct reconciler retires its old command count after a
    # healthy capped retry interval. Confirmed physical ownership still exists.
    now += timedelta(minutes=31)
    await _tick(hass, freezer, coordinator, controller, now)
    assert controller.reconciliation.phase == "confirmed"
    assert controller.reconciliation.attempts == 0
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=10), grid=0.5)
    assert controller.target_current_a == 8
    assert not any(call[:2] == ("switch", "turn_off") for call in calls)


@pytest.mark.parametrize("elapsed,allowed", [(0, True), (59.999, True), (60, False), (61, False)])
def test_import_confirmation_exact_boundary_and_unchanged_sample(elapsed, allowed):
    now = _now()
    state, result = confirm_before_export_import(
        EvBeforeExportImport(), binding=("grid",), now=now,
        source_at=now, importing=True, retain_existing=True, seconds=60,
    )
    assert result
    later, result = confirm_before_export_import(
        state, binding=("grid",), now=now + timedelta(seconds=elapsed),
        source_at=now, importing=True, retain_existing=True, seconds=60,
    )
    assert later.since == now
    assert result is allowed


@pytest.mark.parametrize("payload", [True, {}, {"valid": True, "binding": []},
    {"valid": True, "binding": ["grid"], "since": "2099-01-01T00:00:00+00:00"},
    {"valid": True, "binding": ["grid"], "since": "2026-01-01T00:00:00"},
    {"valid": True, "binding": 123, "since": None},
])
def test_corrupt_optional_import_state_does_not_erase_other_ev_state(payload):
    encoded = EvPersistenceState(restored_at=_now(), outside_control_active=True).to_payload()
    encoded["before_export_import"] = payload
    decoded = EvPersistenceState.from_payload(encoded, _now())
    assert decoded.outside_control_active
    assert not decoded.before_export_import.valid


def test_import_state_roundtrip_keeps_original_deadline():
    state = EvPersistenceState(
        restored_at=_now(), before_export_import=EvBeforeExportImport(_now(), ("grid",)),
    )
    restored = EvPersistenceState.from_payload(state.to_payload(), _now() + timedelta(seconds=30))
    assert restored.before_export_import == state.before_export_import
