"""Sleeping planning evidence through both real controllers, never EV authority."""

from datetime import timedelta

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.ev_current_measurement import measure_ev_soc
from custom_components.home_energy_orchestrator.foxess_adapter import FoxessWriteBlocked
from custom_components.home_energy_orchestrator.planner.foxess_export_policy import (
    evaluate_foxess_export_policy,
)
from tests.test_ev_dynamic_reservation_runtime import (
    _budget,
    _context,
    _publish_vehicle,
    _rig,
    _services,
)
from tests.test_ev_dynamic_reservation_runtime import (
    native_provider_cleanup as native_provider_cleanup,
)
from tests.test_ev_dynamic_reservation_runtime import (
    utc_clock as utc_clock,
)


def _sleep(hass, rig, *, soc=53, age_seconds=450, home=False, connected=False):
    _publish_vehicle(hass, rig, soc=soc, home=home, connected=connected)
    rig.provider.data.update({
        "state": "asleep",
        "charge_state_timestamp": (rig.now - timedelta(seconds=age_seconds)).timestamp() * 1000,
    })


@pytest.mark.parametrize("soc,reserved", [(35, 3.6), (40, 0.6), (41, 0), (53, 0)])
@pytest.mark.parametrize("price", [False, True])
async def test_sleeping_away_ev_reserves_shortfall_without_blanking_export(
    hass, freezer, soc, reserved, price,
):
    rig = await _rig(hass, freezer)
    _sleep(hass, rig, soc=soc)
    budget = _budget(rig)
    assert budget.valid
    assert budget.requested_reservation_kwh == pytest.approx(reserved)
    assert budget.exportable_kwh == pytest.approx(19 - reserved)
    policy = evaluate_foxess_export_policy(_context(hass, rig, price=price))
    assert policy.eligible
    assert policy.protected_ev_kwh == pytest.approx(reserved)
    assert policy.export_plan.sellable_energy_kwh > 0
    assert not rig.controller.dynamic_topup_requested(rig.now)
    # A useful planning reading is explicitly NOT fresh EV command evidence.
    assert measure_ev_soc(hass, rig.controller._capture_feedback(), now=rig.now,
                          max_age_seconds=90) is None


async def test_sleeping_reservation_survives_controller_recreation_without_renewing_clock(
    hass, freezer,
):
    rig = await _rig(hass, freezer)
    _sleep(hass, rig, soc=35)
    stamp = rig.provider.data["charge_state_timestamp"]
    for _ in range(3):
        assert rig.controller.daily_backfill_protection_kwh(rig.now) == pytest.approx(3.6)
    await rig.controller._async_save(rig.now)
    replacement = ActiveEvController(hass, rig.coordinator)
    rig.coordinator.ev_controller = replacement
    await replacement._async_restore()
    assert replacement.daily_backfill_protection_kwh(rig.now) == pytest.approx(3.6)
    assert rig.provider.data["charge_state_timestamp"] == stamp


async def test_sleeping_planning_can_start_export_but_cannot_start_ev(
    hass, freezer, monkeypatch,
):
    rig = await _rig(hass, freezer)
    calls = _services(hass, monkeypatch, rig)
    _sleep(hass, rig)
    await rig.fox.async_reconcile()
    assert rig.fox.export_plan is not None
    assert rig.fox.export_effective_enabled
    assert rig.fox.ev_before_export_decision.reason == "dynamic_reserved"
    assert rig.fox.export_session.phase in {"starting", "active"}
    assert any(value == "Force Discharge" for _, value in calls)
    assert not any(entity.startswith("number.car_") or entity == "switch.car_charge"
                   for entity, _ in calls)


@pytest.mark.parametrize("fault", ["age_shrink", "expired", "online", "offline", "failed"])
async def test_active_export_withdraws_when_sleeping_planning_authority_is_lost(
    hass, freezer, monkeypatch, fault,
):
    rig = await _rig(hass, freezer)
    calls = _services(hass, monkeypatch, rig)
    # This frame is within the asleep window, but past the online unplugged one.
    _sleep(hass, rig, age_seconds=7200 if fault == "online" else 450)
    await rig.fox.async_reconcile()
    assert any(value == "Force Discharge" for _, value in calls)
    calls.clear()
    if fault == "age_shrink":
        rig.coordinator.update_config_value("ev_reservation_soc_max_age_hours", 0.025)
    elif fault == "expired":
        rig.provider.data["charge_state_timestamp"] = (
            rig.now - timedelta(hours=24, microseconds=1)
        ).timestamp() * 1000
    elif fault == "failed":
        rig.provider.last_update_success = False
    else:
        rig.provider.data["state"] = fault
    await rig.fox.async_reconcile()
    assert not rig.fox.export_effective_enabled
    assert rig.fox.ev_before_export_decision.reason == "dynamic_energy_unavailable"
    assert ("select.foxess_mode", "Self Use") in calls
    assert not any(value == "Force Discharge" for _, value in calls)


@pytest.mark.parametrize("fault", ["age_shrink", "offline", "failed"])
async def test_export_positive_command_rechecks_planning_authority_after_awaited_save(
    hass, freezer, monkeypatch, fault,
):
    rig = await _rig(hass, freezer)
    calls = _services(hass, monkeypatch, rig)
    _sleep(hass, rig)
    repository = type(rig.fox._export_repository)
    save = repository.async_save

    async def changed_while_saved(self, state):
        await save(self, state)
        if self is not rig.fox._export_repository:
            return
        if fault == "age_shrink":
            rig.coordinator.update_config_value("ev_reservation_soc_max_age_hours", 0.025)
        elif fault == "offline":
            rig.provider.data["state"] = "offline"
        else:
            rig.provider.last_update_success = False

    monkeypatch.setattr(repository, "async_save", changed_while_saved)
    with pytest.raises(FoxessWriteBlocked):
        await rig.fox.async_reconcile()
    assert not any(value == "Force Discharge" for _, value in calls)
    assert not any(entity == "number.foxess_discharge" and value > 0
                   for entity, value in calls)


async def test_reconnect_requires_fresh_physical_ev_evidence_not_sleeping_planning_soc(
    hass, freezer, monkeypatch,
):
    rig = await _rig(hass, freezer)
    calls = _services(hass, monkeypatch, rig)
    _sleep(hass, rig, soc=35, home=True, connected=True)
    assert _budget(rig).valid
    # A retained reservation can be counted, but cannot clear the returned
    # vehicle's fresh physical handoff or start its positive charging writer.
    assert not rig.fox._ev_before_export_handoff_ready(rig.now)
    await rig.controller.async_reconcile(rig.now)
    assert not any(entity == "switch.car_charge" and value == "on"
                   or entity == "number.car_current" and value > 0 for entity, value in calls)

