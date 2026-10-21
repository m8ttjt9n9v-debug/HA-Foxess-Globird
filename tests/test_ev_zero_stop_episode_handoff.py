"""A confirmed zero-baseline stop ends only its obsolete positive episode."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.planner.ev import (
    DirectEvseReconciliationState,
    SmartSocketRecoveryState,
)
from custom_components.home_energy_orchestrator.planner.ev_outside_window import PreFreeSessionState
from tests.test_ev_backfill_timing import _fresh, _services
from tests.test_ev_before_export_source_clocks import _native
from tests.test_ev_before_export_source_clocks import (
    native_provider_cleanup as native_provider_cleanup,
)
from tests.test_ev_before_export_source_clocks import (
    utc_clock as utc_clock,
)


def _pending(hass, freezer, *, attempts=5):
    rig = _native(hass, freezer, old_seconds=0)
    for entity, state in (
        ("switch.car_charge", "off"), ("sensor.car_charging", "stopped"),
        ("sensor.car_actual_current", "0"), ("number.car_current", "8"),
    ):
        row = hass.states.get(entity)
        hass.states.async_set(entity, state, dict(row.attributes), force_update=True)
    hass.states.async_set("number.car_limit", "50", {"min": 50, "max": 100, "step": 1})
    rig.provider.data.update({
        "charge_state_charge_current_request": 8,
        "charge_state_charge_limit_soc": 50,
    })
    controller = rig.controller
    controller.reconciliation = DirectEvseReconciliationState(
        8, 50, attempts, rig.now - timedelta(seconds=30), "awaiting_feedback",
    )
    controller.target_current_a = 0
    controller.target_limit_percent = 50
    controller.daily_backfill_stop_pending = True
    controller.daily_backfill_stop_attempts = 2
    controller.daily_backfill_last_stop_at = rig.now - timedelta(seconds=10)
    controller.outside_control_active = True
    controller.outside_stop_requested = True
    controller.last_decision_at = rig.now - timedelta(seconds=30)
    controller.daily_backfill_delivered_kwh = 2.25
    return rig


@pytest.mark.parametrize("attempts", [5, 8])
async def test_confirmed_stop_retires_backoff_and_same_positive_target_starts_promptly(
    hass, freezer, attempts,
):
    rig = _pending(hass, freezer, attempts=attempts)
    calls = _services(hass)
    await rig.controller._async_reconcile_outside_stop(
        rig.now, rig.controller._observation(), gate="ready",
    )

    assert rig.controller.reconciliation == DirectEvseReconciliationState()
    assert not rig.controller.daily_backfill_stop_pending
    assert rig.controller.last_decision_at is None
    assert rig.controller.daily_backfill_delivered_kwh == 2.25
    assert calls == []
    saved = await rig.controller._repository.store.async_load()
    assert saved["reconciliation"]["phase"] == "idle"
    assert saved["reconciliation"]["attempts"] == 0
    assert saved["daily_backfill"]["stop_pending"] is False
    assert saved["daily_backfill"]["delivered_kwh"] == 2.25

    later = rig.now + timedelta(seconds=1)
    freezer.move_to(later)
    _fresh(rig.coordinator, later)
    await rig.controller.async_reconcile(later)
    assert rig.controller.target_current_a == 8
    assert rig.controller.target_limit_percent == 50
    assert rig.controller.reconciliation.attempts == 1
    assert ("switch", "turn_on", {"entity_id": "switch.car_charge"}) in calls


async def test_retired_positive_episode_remains_retired_after_restore(hass, freezer):
    rig = _pending(hass, freezer)
    await rig.controller._async_reconcile_outside_stop(
        rig.now, rig.controller._observation(), gate="ready",
    )
    restored = ActiveEvController(hass, rig.coordinator)
    await restored._async_restore()
    assert restored.reconciliation == DirectEvseReconciliationState()
    assert restored.target_current_a is None
    assert not restored.daily_backfill_stop_pending
    assert restored.daily_backfill_delivered_kwh == 2.25


async def test_recent_native_stop_qualifies_unchanged_ha_and_retained_raw_current(hass, freezer):
    rig = _pending(hass, freezer)
    raw = hass.states.get("sensor.car_actual_current")
    hass.states.async_set(raw.entity_id, "8", dict(raw.attributes))
    later = rig.now + timedelta(hours=1)
    freezer.move_to(later)
    hass.states.async_set("device_tracker.car", "home", force_update=True)
    rig.provider.data.update({
        "charge_state_timestamp": later.timestamp() * 1000,
        "charge_state_charger_actual_current": 8,
    })
    await rig.controller._async_reconcile_outside_stop(
        later, rig.controller._observation(), gate="ready",
    )
    assert rig.controller.reconciliation == DirectEvseReconciliationState()
    assert not rig.controller.daily_backfill_stop_pending


@pytest.mark.parametrize("fault", [
    "switch_on", "charging", "optimistic", "stale_frame", "future_frame", "restored_switch",
])
async def test_unconfirmed_stop_keeps_positive_episode_and_pending_duty(
    hass, freezer, fault,
):
    rig = _pending(hass, freezer)
    prior = rig.controller.reconciliation
    if fault == "switch_on":
        hass.states.async_set("switch.car_charge", "on")
    elif fault == "charging":
        rig.provider.data["charge_state_charging_state"] = "Charging"
        hass.states.async_set("sensor.car_charging", "charging")
    elif fault == "optimistic":
        rig.provider.data["charge_state_charging_state"] = False
    elif fault in {"stale_frame", "future_frame"}:
        rig.provider.data["charge_state_timestamp"] = (
            rig.now + timedelta(seconds=-91 if fault == "stale_frame" else 1)
        ).timestamp() * 1000
    else:
        hass.states.async_set("switch.car_charge", "off", {"restored": True})
    calls = _services(hass)
    await rig.controller._async_reconcile_outside_stop(
        rig.now, rig.controller._observation(), gate="ready",
    )
    assert rig.controller.reconciliation == prior
    assert rig.controller.daily_backfill_stop_pending
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("owner", [
    "positive_baseline", "full", "trip", "daily", "pre_free", "surplus", "recovery",
])
async def test_zero_stop_retirement_preserves_successor_owners(hass, freezer, owner):
    rig = _pending(hass, freezer)
    controller = rig.controller
    prior = controller.reconciliation
    if owner == "positive_baseline":
        rig.coordinator.update_config_value("ev_protected_baseline_a", 1)
    elif owner == "full":
        rig.coordinator.update_config_value("ev_charge_to_full_enabled", True)
        controller.charge_to_full_started_at = rig.now
    elif owner == "trip":
        rig.coordinator.trip_charge = SimpleNamespace(
            owns_full=True, _state=SimpleNamespace(cleanup_pending=False),
            _loaded=True, _invalid_storage=False, _storage_error=False, _dirty=False,
        )
    elif owner == "daily":
        controller.daily_backfill_active = True
    elif owner == "pre_free":
        controller.pre_free_session = PreFreeSessionState(True, rig.now)
    elif owner == "surplus":
        controller.outside_target_active = True
    else:
        controller.smart_recovery = SmartSocketRecoveryState(phase="power_off_dwell")
    await controller._async_reconcile_outside_stop(
        rig.now, controller._observation(), gate="ready",
    )
    assert controller.reconciliation == prior
    if owner == "full":
        assert controller.charge_to_full_started_at == rig.now
    elif owner == "trip":
        assert rig.coordinator.trip_charge.owns_full
    elif owner == "daily":
        assert controller.daily_backfill_active
    elif owner == "pre_free":
        assert controller.pre_free_session.active
    elif owner == "recovery":
        assert controller.smart_recovery.phase == "power_off_dwell"


async def test_failed_stop_checkpoint_restores_episode_and_duty(hass, freezer, monkeypatch):
    rig = _pending(hass, freezer)
    await rig.controller._async_save(rig.now)
    prior = rig.controller.reconciliation
    prior_stop = rig.controller._daily_backfill_cycle_state()
    prior_decision = rig.controller.last_decision_at
    prior_payload = await rig.controller._repository.store.async_load()
    monkeypatch.setattr(
        type(rig.controller._repository), "async_save", AsyncMock(side_effect=RuntimeError("disk")),
    )
    with pytest.raises(RuntimeError, match="disk"):
        await rig.controller._async_reconcile_outside_stop(
            rig.now, rig.controller._observation(), gate="ready",
        )
    assert rig.controller.reconciliation == prior
    assert rig.controller._daily_backfill_cycle_state() == prior_stop
    assert rig.controller.last_decision_at == prior_decision
    assert rig.controller.outside_stop_requested
    assert await rig.controller._repository.store.async_load() == prior_payload
