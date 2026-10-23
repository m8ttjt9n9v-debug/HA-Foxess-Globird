"""Dynamic ordinary backfill must recheck shared funding across every await."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_ev_backfill_timing import _services
from tests.test_ev_before_export_charging import _above_baseline
from tests.test_ev_before_export_source_clocks import _native
from tests.test_ev_before_export_source_clocks import (
    native_provider_cleanup as native_provider_cleanup,
)
from tests.test_ev_before_export_source_clocks import utc_clock as utc_clock
from tests.test_ev_delayed_current_runtime import _modbus, _vehicle

FAULTS = (
    "publisher_failed", "expired", "budget", "house", "reserve", "service",
    "transport_cap", "inverter_cap", "mode_fixed", "import",
)


def _rig(hass, freezer, stage):
    rig = _native(hass, freezer, old_seconds=0)
    rig.now = datetime(2026, 9, 7, 5 if stage == "daily" else 10,
                       0 if stage == "daily" else 58, tzinfo=UTC)
    freezer.move_to(rig.now)
    for state in hass.states.async_all():
        hass.states.async_set(state.entity_id, state.state, dict(state.attributes),
                              force_update=True)
    for key, value in {
        "ev_reservation_mode": "dynamic", "ev_pre_free_backfill_enabled": True,
        "ev_pre_free_backfill_timing": "ready_by", "ev_daily_ready_time": "08:00:00",
        "ev_daily_backfill_energy_kwh": 0, "free_charge_window_start": "11:00:00",
        "free_charge_window_end": "14:00:00",
    }.items():
        rig.coordinator.update_config_value(key, value)
    hass.states.async_set("sensor.car_soc", "50", {"unit_of_measurement": "%"})
    rig.provider.data["charge_state_usable_battery_level"] = 50
    _vehicle(hass, rig, rig.now, actual=0, requested=6, limit=80, charging=False)
    _modbus(hass, rig, rig.now)
    return rig


def _change(hass, rig, freezer, change):
    if change == "publisher_failed":
        rig.provider.last_update_success = False
    elif change == "expired":
        later = datetime.now(UTC) + timedelta(seconds=91)
        freezer.move_to(later)
        _modbus(hass, rig, later, physical_current=8)
    elif change == "budget":
        rig.coordinator.data.available_after_reserve_kwh = 0
    elif change == "house":
        rig.coordinator.learning_remaining_kwh = 100
    elif change == "reserve":
        hass.states.async_set("sensor.site_battery_soc", "19", {"unit_of_measurement": "%"})
    elif change == "service":
        rig.coordinator.telemetry = replace(
            rig.coordinator.telemetry,
            site_grid_current=replace(rig.coordinator.telemetry.site_grid_current, value=100),
        )
    elif change == "transport_cap":
        old = hass.states.get("number.car_current")
        hass.states.async_set(old.entity_id, old.state, {**old.attributes, "max": 2})
    elif change == "inverter_cap":
        rig.coordinator.update_config_value("ev_outside_inverter_percent", 1)
    elif change == "mode_fixed":
        rig.coordinator.update_config_value("ev_reservation_mode", "fixed")
    elif change == "import":
        _modbus(hass, rig, datetime.now(UTC), physical_current=8, grid=2)


@pytest.mark.parametrize("stage", ["daily", "pre_free"])
@pytest.mark.parametrize("change", FAULTS)
async def test_matching_dynamic_backfill_withdraws_lost_authority_during_save(
    hass, freezer, monkeypatch, stage, change,
):
    rig = _rig(hass, freezer, stage)
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.target_current_a == 8
    _vehicle(hass, rig, rig.now, actual=8, requested=8,
             limit=rig.controller.target_limit_percent)
    _modbus(hass, rig, rig.now, physical_current=8)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.reconciliation.phase == "confirmed"
    at = rig.now + timedelta(seconds=30)
    freezer.move_to(at)
    _vehicle(hass, rig, at, actual=8, requested=8, limit=rig.controller.target_limit_percent)
    _modbus(hass, rig, at, physical_current=8)
    saved = False
    original = rig.controller._async_save

    async def save(when=None):
        nonlocal saved
        if not saved:
            saved = True
            await asyncio.sleep(0)
            _change(hass, rig, freezer, change)
        await original(when)

    monkeypatch.setattr(rig.controller, "_async_save", save)
    before = len(calls)
    await rig.controller.async_reconcile(at)
    assert saved and rig.controller.target_current_a == 0
    assert rig.controller.daily_backfill_stop_pending
    assert not _above_baseline(calls[before:])
    assert any(call[:2] == ("switch", "turn_off") for call in calls[before:])


@pytest.mark.parametrize("stage", ["daily", "pre_free"])
@pytest.mark.parametrize("boundary", ["number.car_limit", "number.car_current"])
@pytest.mark.parametrize("change", FAULTS)
async def test_dynamic_start_rechecks_each_awaited_positive_command(
    hass, freezer, stage, boundary, change,
):
    rig = _rig(hass, freezer, stage)
    calls = []
    changed_at = None

    async def accept(call):
        nonlocal changed_at
        calls.append((call.domain, call.service, dict(call.data)))
        if changed_at is None and call.data.get("entity_id") == boundary:
            changed_at = len(calls)
            _change(hass, rig, freezer, change)

    for domain, service in (("number", "set_value"), ("switch", "turn_on"),
                            ("switch", "turn_off")):
        hass.services.async_register(domain, service, accept)
    await rig.controller.async_reconcile(rig.now)
    assert changed_at is not None
    assert not _above_baseline(calls[changed_at:])
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)
    assert rig.controller.target_current_a == 0


@pytest.mark.parametrize("stage", ["daily", "pre_free"])
@pytest.mark.parametrize("change", ["publisher_failed", "budget", "transport_cap", "mode_fixed"])
async def test_dynamic_planned_start_rechecks_checkpoint_before_first_command(
    hass, freezer, monkeypatch, stage, change,
):
    rig = _rig(hass, freezer, stage)
    calls = _services(hass)
    original = rig.controller._async_save
    changed = False

    async def save(when=None):
        nonlocal changed
        if not changed and rig.controller.reconciliation.target_current_a == 8:
            changed = True
            _change(hass, rig, freezer, change)
        await original(when)

    monkeypatch.setattr(rig.controller, "_async_save", save)
    await rig.controller.async_reconcile(rig.now)
    assert changed and rig.controller.target_current_a == 0
    assert not _above_baseline(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("stage", ["daily", "pre_free"])
@pytest.mark.parametrize("actual", [0, 3, 8])
async def test_funded_dynamic_backfill_does_not_invent_current_or_stop_a_safe_ramp(
    hass, freezer, monkeypatch, stage, actual,
):
    rig = _rig(hass, freezer, stage)
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    _vehicle(hass, rig, rig.now, actual=8, requested=8,
             limit=rig.controller.target_limit_percent)
    at = rig.now + timedelta(seconds=30)
    freezer.move_to(at)
    _modbus(hass, rig, at, physical_current=8)
    original = rig.controller._async_save
    published = False

    async def save(when=None):
        nonlocal published
        if not published:
            published = True
            later = at + timedelta(seconds=1)
            freezer.move_to(later)
            _vehicle(hass, rig, later, actual=actual, requested=8,
                     limit=rig.controller.target_limit_percent)
            _modbus(hass, rig, later, physical_current=8)
        await original(when)

    monkeypatch.setattr(rig.controller, "_async_save", save)
    before = len(calls)
    await rig.controller.async_reconcile(at)
    assert published and rig.controller.target_current_a == 8
    assert rig.controller._actual_ev_current_a() == (actual, True)
    assert not any(call[:2] == ("switch", "turn_off") for call in calls[before:])


@pytest.mark.parametrize("stage", ["daily", "pre_free"])
async def test_mode_edit_withdraws_old_epoch_then_next_epoch_may_plan_fixed(hass, freezer, stage):
    rig = _rig(hass, freezer, stage)
    calls = []
    changed = False

    async def accept(call):
        nonlocal changed
        calls.append((call.domain, call.service, dict(call.data)))
        if not changed and call.data.get("entity_id") == "number.car_limit":
            changed = True
            rig.coordinator.update_config_value("ev_reservation_mode", "fixed")

    for domain, service in (("number", "set_value"), ("switch", "turn_on"),
                            ("switch", "turn_off")):
        hass.services.async_register(domain, service, accept)
    await rig.controller.async_reconcile(rig.now)
    assert changed and rig.controller.target_current_a == 0
    assert not _above_baseline(calls)
    at = rig.now + timedelta(seconds=30)
    freezer.move_to(at)
    _vehicle(hass, rig, at, actual=0, requested=6, limit=80, charging=False)
    _modbus(hass, rig, at)
    before = len(calls)
    await rig.controller.async_reconcile(at)
    assert rig.controller.target_current_a == 8
    assert _above_baseline(calls[before:])
    assert not rig.controller._dynamic_backfill_target_selected()


@pytest.mark.parametrize("stage", ["daily", "pre_free"])
async def test_matching_dynamic_target_cannot_outlive_its_existing_timing_boundary(
    hass, freezer, monkeypatch, stage,
):
    rig = _rig(hass, freezer, stage)
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    _vehicle(hass, rig, rig.now, actual=8, requested=8,
             limit=rig.controller.target_limit_percent)
    at = rig.now + timedelta(seconds=30)
    freezer.move_to(at)
    _modbus(hass, rig, at, physical_current=8)
    original = rig.controller._async_save
    crossed = False

    async def save(when=None):
        nonlocal crossed
        if not crossed:
            crossed = True
            later = rig.now.replace(hour=8 if stage == "daily" else 11, minute=0)
            freezer.move_to(later)
            _vehicle(hass, rig, later, actual=8, requested=8,
                     limit=rig.controller.target_limit_percent)
            _modbus(hass, rig, later, physical_current=8)
        await original(when)

    monkeypatch.setattr(rig.controller, "_async_save", save)
    before = len(calls)
    await rig.controller.async_reconcile(at)
    assert crossed and rig.controller.target_current_a == 0
    assert not _above_baseline(calls[before:])
    assert any(call[:2] == ("switch", "turn_off") for call in calls[before:])
