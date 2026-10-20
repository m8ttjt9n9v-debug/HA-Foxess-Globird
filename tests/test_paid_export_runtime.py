"""Paid-cap accounting at the real ordinary/price export service boundary.

Physical daily and bonus export remain independent evidence. These tests drive
the existing controller and adapter: no paid-meter helper is mocked.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util

from custom_components.home_energy_orchestrator.active import ActiveFoxessController
from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.foxess_adapter import (
    FoxessServiceAdapter,
    FoxessWriteBlocked,
)
from tests.test_price_export_active import (
    CHARGE,
    DISCHARGE,
    MODE,
    seed_price_states,
)
from tests.test_price_export_active import (
    price_rig as price_rig,
)


def _source(rig, freezer, source):
    """Select a genuine existing admission path and refresh its clock cohort."""
    if source == "zerohero":
        freezer.move_to(dt_util.as_utc(dt_util.now().replace(hour=20, minute=0)))
    rig.config.update(
        automatic_export_enabled=source == "zerohero",
        critical_event_sell_enabled=source == "price",
    )
    rig.coordinator.runtime_config = RuntimeConfiguration.from_mapping(rig.config)
    seed_price_states(rig.hass)
    for sample in vars(rig.coordinator.telemetry).values():
        sample.updated_at = dt_util.now()


@pytest.mark.parametrize("source", ["zerohero", "price"])
async def test_unpaid_solar_does_not_spend_either_automatic_export_cap(
    price_rig, freezer, source,
):
    rig = price_rig
    _source(rig, freezer, source)
    rig.coordinator.data.daily_export_kwh = 50
    rig.coordinator.zerohero_export.imported_kwh = 40
    rig.coordinator.data.paid_export_kwh = 5

    await rig.active.async_reconcile()

    assert rig.active.automatic_export_remaining_kwh == 20
    assert rig.active.export_plan.sellable_energy_kwh > 0
    assert rig.active.export_plan.planned_export_energy_kwh > 0
    assert rig.active.export_session.authority_source == source
    assert rig.calls == [(DISCHARGE, 15), (MODE, "Force Discharge")]
    # More physical overflow cannot shrink a paid-only allowance.
    rig.coordinator.data.daily_export_kwh = 70
    rig.coordinator.zerohero_export.imported_kwh = 60
    await rig.active.async_reconcile()
    assert rig.active.automatic_export_remaining_kwh == 20
    assert rig.coordinator.data.daily_export_kwh == 70
    assert rig.coordinator.zerohero_export.imported_kwh == 60


@pytest.mark.parametrize("source", ["zerohero", "price"])
@pytest.mark.parametrize("missing", ["value", "attribute"])
async def test_missing_paid_meter_never_falls_back_to_total_or_bonus_export(
    price_rig, freezer, source, missing,
):
    rig = price_rig
    _source(rig, freezer, source)
    rig.coordinator.data.daily_export_kwh = 0
    rig.coordinator.zerohero_export.imported_kwh = 0
    if missing == "attribute":
        del rig.coordinator.data.paid_export_kwh
    else:
        rig.coordinator.data.paid_export_kwh = None

    await rig.active.async_reconcile()

    assert rig.active.automatic_export_remaining_kwh is None
    assert rig.active.export_plan is None
    assert rig.active.export_session.phase == "idle"
    assert rig.calls == []


@pytest.mark.parametrize("source", ["zerohero", "price"])
@pytest.mark.parametrize("invalid", [-1, float("nan"), float("inf"), True, "invalid"])
async def test_invalid_paid_meter_cannot_enlarge_or_restore_an_allowance(
    price_rig, freezer, source, invalid,
):
    rig = price_rig
    _source(rig, freezer, source)
    rig.coordinator.data.paid_export_kwh = invalid
    rig.coordinator.data.daily_export_kwh = 0
    rig.coordinator.zerohero_export.imported_kwh = 0

    await rig.active.async_reconcile()

    assert rig.active.automatic_export_remaining_kwh is None
    assert rig.active.export_plan is None
    assert rig.calls == []


@pytest.mark.parametrize("source", ["zerohero", "price"])
async def test_unsaved_paid_meter_cannot_grant_positive_export(
    price_rig, freezer, source,
):
    rig = price_rig
    _source(rig, freezer, source)
    rig.coordinator._paid_export_storage_ready = False
    rig.coordinator.data.paid_export_kwh = 0

    await rig.active.async_reconcile()

    assert rig.active.automatic_export_remaining_kwh is None
    assert rig.active.export_plan is None
    assert rig.calls == []


@pytest.mark.parametrize("source", ["zerohero", "price"])
@pytest.mark.parametrize("loss", ["exhausted", "missing", "unsaved"])
@pytest.mark.parametrize("phase", ["starting", "active", "recovering"])
async def test_paid_cap_loss_restores_active_export_without_positive_reassertion(
    price_rig, freezer, source, loss, phase,
):
    rig = price_rig
    _source(rig, freezer, source)
    await rig.active.async_reconcile()
    await rig.active.async_reconcile()
    assert rig.active.export_session.phase == "active"
    assert rig.hass.states.get(MODE).state == "Force Discharge"
    rig.active.export_session = replace(rig.active.export_session, phase=phase)
    if loss == "exhausted":
        rig.coordinator.data.paid_export_kwh = 25
    elif loss == "missing":
        rig.coordinator.data.paid_export_kwh = None
    else:
        rig.coordinator._paid_export_storage_ready = False
    rig.calls.clear()

    # The retained starting reducer first acknowledges matching forced feedback.
    # One subsequent tick requests cleanup, then fresh zero feedback clears it.
    # No tick is allowed another positive command after cap authority is lost.
    await rig.active.async_reconcile()
    await rig.active.async_reconcile()
    await rig.active.async_reconcile()

    assert rig.calls == [(MODE, "Self Use"), (DISCHARGE, 0)]
    assert rig.active.export_session.phase == "idle"
    assert rig.hass.states.get(MODE).state == "Self Use"
    assert float(rig.hass.states.get(CHARGE).state) == 0
    assert float(rig.hass.states.get(DISCHARGE).state) == 0


@pytest.mark.parametrize("source", ["zerohero", "price"])
async def test_paid_exhaustion_survives_toggle_new_block_and_controller_reload(
    price_rig, freezer, source,
):
    rig = price_rig
    _source(rig, freezer, source)
    # The physical total is deliberately zero: the paid evidence alone controls
    # the cap, not either retained old counter or a newly created session.
    rig.coordinator.data.daily_export_kwh = 0
    rig.coordinator.zerohero_export.imported_kwh = 0
    rig.coordinator.data.paid_export_kwh = 25
    for requested in (False, True):
        rig.config["automatic_export_enabled"] = requested
        rig.config["critical_event_sell_enabled"] = requested
        rig.coordinator.runtime_config = RuntimeConfiguration.from_mapping(rig.config)
        await rig.active.async_reconcile()
    freezer.tick(timedelta(minutes=5))
    rig.result.interval_start = dt_util.utcnow()
    rig.result.interval_end = dt_util.utcnow() + timedelta(minutes=5)
    _source(rig, freezer, source)
    await rig.active._export_repository.async_save(rig.active.export_session)
    await rig.active.async_stop()
    restored = ActiveFoxessController(rig.hass, rig.coordinator)
    rig.coordinator.active_controller = restored
    await restored.manual.async_restore_handoff()
    await restored._async_load_export_session()
    restored._charge_storage_status = "valid"
    try:
        await restored.async_reconcile()
        assert restored.automatic_export_remaining_kwh == 0
        assert restored.export_plan.planned_export_energy_kwh == 0
        assert restored.export_session.phase == "idle"
        assert rig.calls == []
    finally:
        await restored.async_stop()


async def test_price_and_evening_ownership_share_the_same_remaining_paid_cap(
    price_rig, freezer,
):
    rig = price_rig
    rig.coordinator.data.paid_export_kwh = 7
    await rig.active.async_reconcile()
    await rig.active.async_reconcile()
    assert rig.active.export_session.authority_source == "price"
    assert rig.active.automatic_export_remaining_kwh == 18
    rig.coordinator.data.paid_export_kwh = 12
    rig.result.price_per_kwh = 2
    await rig.active.async_reconcile()
    await rig.active.async_reconcile()
    assert rig.active.export_session.phase == "idle"

    _source(rig, freezer, "zerohero")
    freezer.move_to(dt_util.as_utc(dt_util.now().replace(hour=20, minute=30)))
    seed_price_states(rig.hass)
    for sample in vars(rig.coordinator.telemetry).values():
        sample.updated_at = dt_util.now()
    rig.coordinator.data.daily_export_kwh = 60
    rig.coordinator.zerohero_export.imported_kwh = 40
    rig.calls.clear()
    await rig.active.async_reconcile()

    assert rig.active.export_session.authority_source == "zerohero"
    assert rig.active.automatic_export_remaining_kwh == 13
    assert rig.active.export_plan.planned_export_energy_kwh == 13
    assert rig.calls == [(DISCHARGE, 15), (MODE, "Force Discharge")]


@pytest.mark.parametrize("source", ["zerohero", "price"])
async def test_paid_cap_exhausted_during_staging_fences_late_force_mode(
    price_rig, freezer, monkeypatch, source,
):
    rig = price_rig
    _source(rig, freezer, source)
    entered, release = asyncio.Event(), asyncio.Event()

    async def settle(adapter, command):
        await rig.fast(adapter, command)
        if command.action == "set_discharge_power" and command.value > 0:
            entered.set()
            await release.wait()

    monkeypatch.setattr(FoxessServiceAdapter, "_async_execute_command", settle)
    start = asyncio.create_task(rig.active.async_reconcile())
    await entered.wait()
    rig.coordinator.data.paid_export_kwh = 25
    release.set()
    with pytest.raises(FoxessWriteBlocked):
        await start
    assert (MODE, "Force Discharge") not in rig.calls
    await rig.active.async_reconcile()
    await rig.active.async_reconcile()
    assert rig.active.export_session.phase == "idle"
    assert float(rig.hass.states.get(DISCHARGE).state) == 0
