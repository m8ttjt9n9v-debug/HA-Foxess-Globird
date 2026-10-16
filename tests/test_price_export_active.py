"""Real service-boundary regressions for the existing price-aware export owner."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.home_energy_orchestrator.active import ActiveFoxessController
from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.foxess_adapter import (
    FoxessServiceAdapter,
    FoxessWriteBlocked,
)
from custom_components.home_energy_orchestrator.models import SiteSnapshot
from custom_components.home_energy_orchestrator.planner.foxess import FoxessCommand

NOW = datetime(2026, 10, 12, 9, tzinfo=UTC)
MODE = "select.price_mode"
CHARGE = "number.price_charge"
DISCHARGE = "number.price_discharge"
SOC = "sensor.price_soc"
GRID = "sensor.price_grid"
BATTERY = "sensor.price_battery"
HOUSE = "sensor.price_house"

PRICE_CONFIG = {
    "automatic_control_enabled": True,
    "automatic_charge_enabled": False,
    "automatic_export_enabled": False,
    "critical_event_sell_enabled": True,
    "aemo_monitor_enabled": True,
    "aemo_region": "NSW1",
    "aemo_export_threshold_per_kwh": 3,
    "foxess_control_owner": "local_modbus",
    "rehearsal_mode": False,
    "sign_conventions_verified": True,
    "foxess_work_mode_entity": MODE,
    "foxess_force_charge_power_entity": CHARGE,
    "foxess_force_discharge_power_entity": DISCHARGE,
    "battery_soc_entity": SOC,
    "battery_power_entity": BATTERY,
    "battery_power_positive_direction": "positive_charge",
    "grid_power_entity": GRID,
    "grid_power_positive_direction": "positive_import",
    "house_load_entity": HOUSE,
    "battery_capacity_kwh": 40,
    "battery_floor_percent": 10,
    "reserve_kwh": 2,
    "inverter_discharge_limit_kw": 15,
    "inverter_charge_limit_kw": 15,
    "export_limit_kw": 15,
    "automatic_export_limit_kwh": 25,
    "house_learning_fallback_kwh": 4,
    "house_away_fallback_kwh": 4,
    "configure_ev": False,
    "configure_solar": False,
}


def seed_price_states(hass, *, soc=80, grid=0, battery=0, house=0.8):
    for entity, value, unit in (
        (SOC, soc, "%"), (GRID, grid, "kW"),
        (BATTERY, battery, "kW"), (HOUSE, house, "kW"),
    ):
        hass.states.async_set(entity, str(value), {"unit_of_measurement": unit}, force_update=True)
    if hass.states.get(MODE) is None:
        hass.states.async_set(MODE, "Self Use", {
            "options": ["Self Use", "Force Charge", "Force Discharge"],
        })
    for entity in (CHARGE, DISCHARGE):
        if hass.states.get(entity) is None:
            hass.states.async_set(entity, "0", {
                "unit_of_measurement": "kW", "min": 0, "max": 15, "step": 0.001,
            })


def register_price_services(hass, monkeypatch, calls, harness=None):
    async def apply(call):
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            entity = entity[0]
        value = call.data.get("value", call.data.get("option"))
        calls.append((entity, value))
        if harness is not None:
            harness.record_service_call(call.domain, call.service, dict(call.data))
        state = hass.states.get(entity)
        hass.states.async_set(entity, str(value), dict(state.attributes), force_update=True)

    hass.services.async_register("number", "set_value", apply)
    hass.services.async_register("select", "select_option", apply)
    original = FoxessServiceAdapter._async_execute_command

    async def fast(adapter, command):
        await original(adapter, FoxessCommand(command.action, command.value))

    monkeypatch.setattr(FoxessServiceAdapter, "_async_execute_command", fast)
    return fast


@pytest.fixture
async def price_rig(hass, monkeypatch, freezer):
    freezer.move_to(NOW)
    seed_price_states(hass)
    config = dict(PRICE_CONFIG)
    def sample(value):
        return SimpleNamespace(value=value, valid=True, fresh=True, updated_at=dt_util.now())
    coordinator = SimpleNamespace(
        entry_id="price-active-test", runtime_config=RuntimeConfiguration.from_mapping(config),
        snapshot=SiteSnapshot(80, 40, 10, 2, 0, 0.8, export_limit_kw=15),
        data=SimpleNamespace(
            available_after_reserve_kwh=25, daily_export_kwh=0, free_energy_remaining_kwh=50,
        ),
        telemetry=SimpleNamespace(
            grid_power=sample(0), battery_power=sample(0), house_load=sample(0.8),
        ),
        learning_remaining_kwh=4,
        zerohero_export=SimpleNamespace(imported_kwh=0),
        manual_test=SimpleNamespace(
            storage_status="valid", is_active=False,
            async_relinquish_for_manual=AsyncMock(),
        ),
        _free_window_hours_remaining=lambda _now: 0,
        async_update_listeners=lambda: None,
        async_request_refresh=AsyncMock(), async_update_forecast=AsyncMock(),
    )
    result = SimpleNamespace(
        region="NSW1", price_trigger_valid=True, price_per_kwh=4,
        interval_start=NOW, interval_end=NOW + timedelta(minutes=5),
    )
    coordinator.market_monitor = SimpleNamespace(current_result=result)
    active = ActiveFoxessController(hass, coordinator)
    coordinator.active_controller = active
    active._charge_storage_status = active._export_storage_status = "valid"
    await active.manual.async_restore_handoff()
    calls = []
    fast = register_price_services(hass, monkeypatch, calls)
    rig = SimpleNamespace(
        hass=hass, active=active, coordinator=coordinator, result=result,
        config=config, calls=calls, fast=fast,
    )
    yield rig
    await active.async_stop()
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize("price", [3, 3.00001, 4])
async def test_price_starts_outside_normal_window_and_fall_restores_same_owner(price_rig, price):
    rig = price_rig
    rig.result.price_per_kwh = price
    await rig.active.async_reconcile()
    assert rig.calls == [(DISCHARGE, 15), (MODE, "Force Discharge")]
    assert rig.active.export_session.authority_source == "price"
    assert rig.active.export_plan.sellable_energy_kwh > 0
    rig.result.price_per_kwh = 2.99999
    await rig.active.async_reconcile()
    assert rig.calls[-2:] == [(MODE, "Self Use"), (DISCHARGE, 0)]
    await rig.active.async_reconcile()
    assert rig.active.export_session.phase == "idle"


@pytest.mark.parametrize("heo_override_configured", [False, True])
async def test_legacy_full_helper_has_authority_only_until_heo_override_first_use(
    price_rig, heo_override_configured,
):
    rig = price_rig
    legacy = "input_boolean.legacy_paid_full"
    rig.config["ev_charge_to_full_entity"] = legacy
    rig.config.pop("ev_charge_to_full_enabled", None)
    if heo_override_configured:
        rig.config["ev_charge_to_full_enabled"] = False
    rig.coordinator.runtime_config = RuntimeConfiguration.from_mapping(rig.config)
    preference = rig.coordinator.runtime_config.ev_preferences
    assert preference.charge_to_full_configured is heo_override_configured
    rig.hass.states.async_set(legacy, "on")
    await rig.active.async_reconcile()
    assert ((MODE, "Force Discharge") in rig.calls) is heo_override_configured


async def test_legacy_paid_full_on_during_settlement_fences_price_force_mode(
    price_rig, monkeypatch,
):
    rig = price_rig
    legacy = "input_boolean.legacy_paid_full"
    rig.config["ev_charge_to_full_entity"] = legacy
    rig.config.pop("ev_charge_to_full_enabled", None)
    rig.coordinator.runtime_config = RuntimeConfiguration.from_mapping(rig.config)
    rig.hass.states.async_set(legacy, "off")
    entered, release = asyncio.Event(), asyncio.Event()

    async def settle(adapter, command):
        await rig.fast(adapter, command)
        if command.action == "set_discharge_power" and command.value > 0:
            entered.set()
            await release.wait()

    monkeypatch.setattr(FoxessServiceAdapter, "_async_execute_command", settle)
    start = asyncio.create_task(rig.active.async_reconcile())
    await entered.wait()
    rig.hass.states.async_set(legacy, "on")
    release.set()
    with pytest.raises(FoxessWriteBlocked):
        await start
    assert (MODE, "Force Discharge") not in rig.calls
    assert rig.active.export_session.authority_source == "price"
    await rig.active.async_reconcile()
    assert float(rig.hass.states.get(DISCHARGE).state) == 0


@pytest.mark.parametrize(
    "problem", ["below_three", "zero", "stale", "sellable_zero", "cap", "daily_missing", "unit"]
)
async def test_price_admission_fails_closed_from_current_evidence(price_rig, problem):
    rig = price_rig
    if problem == "below_three":
        rig.result.price_per_kwh = 2.99999
    elif problem == "zero":
        rig.result.price_per_kwh = 0
    elif problem == "stale":
        rig.coordinator.telemetry.battery_power.fresh = False
    elif problem == "sellable_zero":
        rig.coordinator.data.available_after_reserve_kwh = 4
    elif problem == "cap":
        rig.coordinator.data.daily_export_kwh = 25
    elif problem == "daily_missing":
        rig.coordinator.data.daily_export_kwh = None
    else:
        state = rig.hass.states.get(DISCHARGE)
        rig.hass.states.async_set(DISCHARGE, "0", {**state.attributes, "unit_of_measurement": "W"})
    await rig.active.async_reconcile()
    assert rig.calls == []


async def test_all_day_cap_cannot_reset_by_toggle_or_new_price_block(price_rig, freezer):
    rig = price_rig
    rig.coordinator.data.daily_export_kwh = 25
    for requested in (False, True):
        rig.config["critical_event_sell_enabled"] = requested
        rig.coordinator.runtime_config = RuntimeConfiguration.from_mapping(rig.config)
        await rig.active.async_reconcile()
    freezer.tick(timedelta(minutes=5))
    rig.result.interval_start = dt_util.utcnow()
    rig.result.interval_end = dt_util.utcnow() + timedelta(minutes=5)
    for sample in vars(rig.coordinator.telemetry).values():
        sample.updated_at = dt_util.now()
    seed_price_states(rig.hass)
    await rig.active.async_reconcile()
    assert not rig.calls and rig.active.automatic_export_remaining_kwh == 0


async def test_normal_export_uses_shared_daily_cap_without_price_authority(price_rig, freezer):
    rig = price_rig
    freezer.move_to(dt_util.as_utc(dt_util.now().replace(hour=20, minute=0)))
    rig.config.update(automatic_export_enabled=True, critical_event_sell_enabled=False)
    rig.coordinator.runtime_config = RuntimeConfiguration.from_mapping(rig.config)
    rig.coordinator.data.daily_export_kwh = 25
    await rig.active.async_reconcile()
    assert not rig.calls
    rig.coordinator.data.daily_export_kwh = 0
    await rig.active.async_reconcile()
    assert (MODE, "Force Discharge") in rig.calls
    assert rig.active.export_session.authority_source == "zerohero"


async def test_callback_refreshes_current_inputs_before_deciding(price_rig):
    rig = price_rig

    async def refresh():
        rig.coordinator.data.available_after_reserve_kwh = 4

    rig.coordinator.async_request_refresh.side_effect = refresh
    rig.active._price_changed()
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert rig.coordinator.async_request_refresh.await_count > 0
    assert not rig.calls


async def test_manual_stop_during_settlement_fences_late_force_mode(price_rig, monkeypatch):
    rig = price_rig
    entered, release = asyncio.Event(), asyncio.Event()

    async def settle(adapter, command):
        await rig.fast(adapter, command)
        if command.action == "set_discharge_power" and command.value > 0:
            entered.set()
            await release.wait()

    monkeypatch.setattr(FoxessServiceAdapter, "_async_execute_command", settle)
    start = asyncio.create_task(rig.active.async_reconcile())
    await entered.wait()
    stop = asyncio.create_task(rig.active.manual.async_request("self_use"))
    await asyncio.sleep(0)
    release.set()
    outcomes = await asyncio.gather(start, stop, return_exceptions=True)
    assert isinstance(outcomes[0], FoxessWriteBlocked)
    assert outcomes[1]["accepted"] and outcomes[1]["hold"]
    assert (MODE, "Force Discharge") not in rig.calls
    assert float(rig.hass.states.get(DISCHARGE).state) == 0


async def test_cancellation_retains_owned_marker_for_expired_cleanup(price_rig, monkeypatch):
    rig = price_rig
    entered, release = asyncio.Event(), asyncio.Event()

    async def settle(adapter, command):
        await rig.fast(adapter, command)
        if command.action == "set_discharge_power" and command.value > 0:
            entered.set()
            await release.wait()

    monkeypatch.setattr(FoxessServiceAdapter, "_async_execute_command", settle)
    start = asyncio.create_task(rig.active.async_reconcile())
    await entered.wait()
    start.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await start
    assert rig.active.export_session.authority_source == "price"
    rig.result.price_trigger_valid = False
    await rig.active.async_reconcile()
    await rig.active.async_reconcile()
    assert rig.active.export_session.phase == "idle"
    assert (MODE, "Force Discharge") not in rig.calls
    assert float(rig.hass.states.get(DISCHARGE).state) == 0


async def test_store_failure_prevents_new_positive_but_durable_owner_can_reduce(
    price_rig, monkeypatch
):
    rig = price_rig
    store = rig.active._export_repository.store
    save = store.async_save
    monkeypatch.setattr(store, "async_save", AsyncMock(side_effect=OSError()))
    with pytest.raises(OSError):
        await rig.active.async_reconcile()
    assert not rig.calls and rig.active.export_session.phase == "idle"
    monkeypatch.setattr(store, "async_save", save)
    await rig.active.async_reconcile()
    rig.result.price_trigger_valid = False
    monkeypatch.setattr(store, "async_save", AsyncMock(side_effect=OSError()))
    await rig.active.async_reconcile()
    assert rig.hass.states.get(MODE).state == "Self Use"
    assert float(rig.hass.states.get(DISCHARGE).state) == 0
    assert rig.active.export_session.authority_source == "price"


async def test_known_cleanup_with_missing_ledger_and_physical_evidence(price_rig):
    rig = price_rig
    await rig.active.async_reconcile()
    rig.coordinator.data = rig.coordinator.snapshot = None
    rig.coordinator.telemetry.battery_power.fresh = False
    rig.coordinator.telemetry.grid_power.fresh = False
    rig.result.price_trigger_valid = False
    for entity in (MODE, CHARGE, DISCHARGE):
        state = rig.hass.states.get(entity)
        rig.hass.states.async_set(entity, "unavailable", dict(state.attributes))
    await rig.active.async_reconcile()
    assert (MODE, "Self Use") in rig.calls
    assert rig.active.export_session.authority_source == "price"
    await rig.active.async_reconcile()
    assert rig.active.export_session.phase != "idle"
    rig.coordinator.telemetry.battery_power.fresh = True
    rig.coordinator.telemetry.grid_power.fresh = True
    await rig.active.async_reconcile()
    assert rig.active.export_session.phase == "idle"


async def test_restart_cannot_move_original_price_ownership_to_changed_actuators(price_rig):
    rig = price_rig
    await rig.active.async_reconcile()
    saved = await rig.active._export_repository.store.async_load()
    assert saved["price_actuator_entities"] == [MODE, CHARGE, DISCHARGE]
    await rig.active.async_stop()
    rig.config["foxess_work_mode_entity"] = "select.other_inverter"
    rig.coordinator.runtime_config = RuntimeConfiguration.from_mapping(rig.config)
    mode = rig.hass.states.get(MODE)
    rig.hass.states.async_set("select.other_inverter", "Self Use", dict(mode.attributes))
    restarted = ActiveFoxessController(rig.hass, rig.coordinator)
    rig.coordinator.active_controller = restarted
    await restarted.manual.async_restore_handoff()
    await restarted._async_load_export_session()
    restarted._charge_storage_status = "valid"
    rig.calls.clear()
    try:
        await restarted.async_reconcile()
        assert not rig.calls
        assert restarted.export_session.authority_source == "price"
        assert restarted.export_session.price_actuator_entities == (MODE, CHARGE, DISCHARGE)
        assert rig.hass.states.get(MODE).state == "Force Discharge"
    finally:
        await restarted.async_stop()


@pytest.mark.parametrize("price", [2.99999, 3])
async def test_price_rechecked_during_settlement_at_inclusive_boundary(
    price_rig, monkeypatch, price,
):
    rig = price_rig
    entered, release = asyncio.Event(), asyncio.Event()

    async def settle(adapter, command):
        await rig.fast(adapter, command)
        if command.action == "set_discharge_power" and command.value > 0:
            entered.set()
            await release.wait()

    monkeypatch.setattr(FoxessServiceAdapter, "_async_execute_command", settle)
    start = asyncio.create_task(rig.active.async_reconcile())
    await entered.wait()
    rig.result.price_per_kwh = price
    release.set()
    if price == 3:
        await start
        assert (MODE, "Force Discharge") in rig.calls
        return
    with pytest.raises(FoxessWriteBlocked):
        await start
    await rig.active.async_reconcile()
    await rig.active.async_reconcile()
    assert (MODE, "Force Discharge") not in rig.calls
    assert float(rig.hass.states.get(DISCHARGE).state) == 0
    assert rig.active.export_session.phase == "idle"


async def test_active_price_exhaustion_restores_then_new_block_keeps_daily_cap(price_rig, freezer):
    rig = price_rig
    await rig.active.async_reconcile()
    await rig.active.async_reconcile()
    rig.coordinator.data.daily_export_kwh = 25
    rig.calls.clear()
    await rig.active.async_reconcile()
    await rig.active.async_reconcile()
    assert (MODE, "Self Use") in rig.calls
    assert rig.active.export_session.phase == "idle"
    freezer.tick(timedelta(minutes=5))
    rig.result.interval_start = dt_util.utcnow()
    rig.result.interval_end = dt_util.utcnow() + timedelta(minutes=5)
    seed_price_states(rig.hass)
    for sample in vars(rig.coordinator.telemetry).values():
        sample.updated_at = dt_util.now()
    rig.calls.clear()
    await rig.active.async_reconcile()
    assert not rig.calls and rig.active.automatic_export_remaining_kwh == 0


async def test_persistent_write_blockage_has_bounded_immediate_reconciliation(
    price_rig, monkeypatch
):
    rig = price_rig
    await rig.active.async_reconcile()
    source = rig.active.export_session.authority_source
    calls = 0

    async def blocked():
        nonlocal calls
        calls += 1
        if calls == 3:
            # Bound the old faulty implementation too: this regression never
            # hangs the loop while proving it attempted an unbounded follow-up.
            rig.active._reconcile_stopped = True
        raise FoxessWriteBlocked("persistent write gate")

    monkeypatch.setattr(rig.active, "async_reconcile", blocked)
    rig.active._price_reconcile_requested = True
    await rig.active._async_price_reconcile()
    assert calls <= 2
    assert rig.active.export_session.authority_source == source == "price"


async def test_shrinking_live_resource_deadline_fences_late_force_mode(price_rig, monkeypatch):
    rig = price_rig
    entered, release = asyncio.Event(), asyncio.Event()

    async def settle(adapter, command):
        await rig.fast(adapter, command)
        if command.action == "set_discharge_power" and command.value > 0:
            entered.set()
            await release.wait()

    monkeypatch.setattr(FoxessServiceAdapter, "_async_execute_command", settle)
    start = asyncio.create_task(rig.active.async_reconcile())
    await entered.wait()
    rig.coordinator.data.available_after_reserve_kwh = 4.05
    release.set()
    with pytest.raises(FoxessWriteBlocked):
        await start
    assert (MODE, "Force Discharge") not in rig.calls


async def test_unknown_numeric_feedback_future_retry_anchor_cannot_delay_cleanup(price_rig):
    rig = price_rig
    await rig.active.async_reconcile()
    rig.active.export_session = replace(
        rig.active.export_session, phase="stopping", attempts=2,
        last_command_at=dt_util.now() + timedelta(seconds=20),
    )
    for entity in (MODE, CHARGE, DISCHARGE):
        state = rig.hass.states.get(entity)
        rig.hass.states.async_set(entity, "unavailable", dict(state.attributes))
    rig.result.price_trigger_valid = False
    rig.calls.clear()
    await rig.active.async_reconcile()
    assert rig.calls == [(MODE, "Self Use"), (CHARGE, 0), (DISCHARGE, 0)]
    assert rig.active.export_session.last_command_at <= dt_util.now()
    assert rig.active.export_session.authority_source == "price"
