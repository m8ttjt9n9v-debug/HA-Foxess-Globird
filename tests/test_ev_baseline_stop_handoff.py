"""A completed positive-baseline handoff retires only its old daily stop.

Synthetic Home Assistant states, the real EV controller, adapter and Store are
used throughout. No provider, vehicle, inverter or live site is contacted.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.maintenance_safety import _ev_runtime
from custom_components.home_energy_orchestrator.planner.ev import SmartSocketRecoveryState
from custom_components.home_energy_orchestrator.planner.ev_outside_window import PreFreeSessionState
from tests.test_ev_backfill_timing import _charging, _fresh, _services, _site
from tests.test_ev_before_export_charging import _case

NOW = datetime(2026, 9, 7, 16, tzinfo=UTC)


def _limit_feedback(hass, target):
    row = hass.states.get("number.car_limit")
    represented = max(min(target, row.attributes["max"]), row.attributes["min"])
    hass.states.async_set(
        "number.car_limit", str(represented), dict(row.attributes), force_update=True
    )


async def _pending_baseline(hass, freezer, *, configured=1):
    """Build confirmed baseline through normal reconciliation, then old journal duty."""
    freezer.move_to(NOW)
    calls = _services(hass)
    coordinator, controller = _site(
        hass, ev_protected_baseline_a=configured, ev_pre_free_backfill_enabled=False
    )
    coordinator.ev_controller = controller
    _charging(hass, 1)
    _fresh(coordinator, NOW, current_a=1)
    await controller.async_reconcile(NOW)
    assert controller.target_current_a == 1
    freezer.tick(timedelta(seconds=1))
    _charging(hass, 1)
    _limit_feedback(hass, controller.target_limit_percent)
    _fresh(coordinator, NOW + timedelta(seconds=1), current_a=1)
    await controller.async_reconcile(NOW + timedelta(seconds=1))
    assert controller.reconciliation.phase == "confirmed", (
        f"limit target={controller.target_limit_percent}, "
        f"limit feedback={hass.states.get('number.car_limit').state}, "
        f"current feedback={hass.states.get('number.car_current').state}, "
        f"switch={hass.states.get('switch.car_charge').state}, "
        f"reason={controller.last_reason}, calls={calls}"
    )
    assert controller.outside_control_active
    controller.daily_backfill_stop_pending = True
    controller.daily_backfill_stop_attempts = 2
    controller.daily_backfill_last_stop_at = NOW - timedelta(seconds=30)
    controller.daily_backfill_delivered_kwh = 2.25
    controller.daily_backfill_cycle_ready_at = NOW.replace(hour=8) + timedelta(days=1)
    await controller._async_save(NOW + timedelta(seconds=1))
    calls.clear()
    freezer.tick(timedelta(seconds=1))
    return NOW + timedelta(seconds=2), coordinator, controller, calls


@pytest.mark.parametrize("configured", [1, 0.5])
async def test_confirmed_positive_baseline_retires_only_daily_stop_duty(
    hass,
    freezer,
    configured,
):
    now, _, controller, calls = await _pending_baseline(hass, freezer, configured=configured)
    prior = await controller._repository.store.async_load()

    await controller.async_reconcile(now)

    assert not controller.daily_backfill_stop_pending, (
        controller.outside_target_active,
        controller.outside_control_active,
        controller.decision_phase,
        controller.target_current_a,
        controller.target_limit_percent,
    )
    assert controller.daily_backfill_stop_attempts == 0
    assert controller.daily_backfill_last_stop_at is None
    assert not controller.outside_stop_requested
    assert controller.outside_control_active  # Keepalive ownership is not released.
    assert controller.target_current_a == controller.reconciliation.target_current_a == 1
    assert controller.reconciliation.phase == "confirmed"
    assert controller.last_saved_at == now  # Not the ordinary one-minute checkpoint.
    assert calls == []
    saved = await controller._repository.store.async_load()
    assert saved["daily_backfill"]["stop_pending"] is False
    assert saved["daily_backfill"]["stop_attempts"] == 0
    assert saved["daily_backfill"]["last_stop_at"] is None
    for key in ["cycle_ready_at", "delivered_kwh", "active", "session_target_kwh"]:
        assert saved["daily_backfill"][key] == prior["daily_backfill"][key]
    assert saved["outside_control_active"] is True
    assert saved["pre_free_session"] == prior["pre_free_session"]
    assert saved["driving_history"] == prior["driving_history"]
    blockers = set()
    _ev_runtime(controller, blockers)
    assert "ev_session_active" in blockers  # Connected keepalive still blocks maintenance.


@pytest.mark.parametrize(
    "failure",
    [
        "actual_high",
        "requested_high",
        "awaiting",
        "faulted",
        "stale_actual",
        "stale_switch",
        "stale_cable",
        "stale_home",
        "restored_actual",
        "wrong_actual_unit",
        "wrong_requested_unit",
        "missing_actual",
        "missing_switch",
        "recovery",
        "pre_free",
        "daily_active",
        "full",
        "trip",
        "trip_cleanup",
        "smart_path",
        "outside_target",
    ],
)
async def test_unconfirmed_feedback_or_another_owner_keeps_daily_stop_pending(
    hass,
    freezer,
    failure,
):
    now, coordinator, controller, calls = await _pending_baseline(hass, freezer)
    # Isolate the lifecycle retirement boundary from new normal policy decisions.
    # Disabled EV control is not permission to erase an existing cleanup duty.
    coordinator.update_config_value("ev_automatic_control_enabled", False)
    if failure.startswith("stale_"):
        stale = {
            "stale_actual": "sensor.car_actual_current",
            "stale_switch": "switch.car_charge",
            "stale_cable": "binary_sensor.car_cable",
            "stale_home": "device_tracker.car",
        }[failure]
        freezer.tick(timedelta(seconds=91))
        now += timedelta(seconds=91)
        for row in hass.states.async_all():
            if row.entity_id != stale:
                hass.states.async_set(
                    row.entity_id, row.state, dict(row.attributes), force_update=True
                )
        _fresh(coordinator, now, current_a=1)
    elif failure in {"actual_high", "requested_high"}:
        entity = "sensor.car_actual_current" if failure == "actual_high" else "number.car_current"
        row = hass.states.get(entity)
        hass.states.async_set(entity, "2", dict(row.attributes), force_update=True)
    elif failure in {"awaiting", "faulted"}:
        controller.reconciliation = replace(
            controller.reconciliation,
            phase={
                "awaiting": "awaiting_feedback",
                "faulted": "blocked",
            }[failure],
        )
    elif failure == "restored_actual":
        hass.states.async_set(
            "sensor.car_actual_current",
            "1",
            {
                "unit_of_measurement": "A",
                "restored": True,
            },
        )
    elif failure in {"wrong_actual_unit", "wrong_requested_unit"}:
        entity = (
            "sensor.car_actual_current" if failure == "wrong_actual_unit" else "number.car_current"
        )
        row = hass.states.get(entity)
        hass.states.async_set(entity, "1", {**row.attributes, "unit_of_measurement": "kW"})
    elif failure.startswith("missing_"):
        hass.states.async_remove(
            {
                "missing_actual": "sensor.car_actual_current",
                "missing_switch": "switch.car_charge",
            }[failure]
        )
    elif failure == "recovery":
        controller.smart_recovery = SmartSocketRecoveryState(phase="power_off_dwell")
    elif failure == "pre_free":
        controller.pre_free_session = PreFreeSessionState(True, NOW)
    elif failure == "daily_active":
        controller.daily_backfill_active = True
    elif failure == "full":
        coordinator.update_config_value("ev_charge_to_full_enabled", True)
        controller.charge_to_full_started_at = NOW
    elif failure in {"trip", "trip_cleanup"}:
        coordinator.trip_charge = SimpleNamespace(
            owns_full=failure == "trip",
            _state=SimpleNamespace(armed=True, cleanup_pending=failure == "trip_cleanup"),
            _loaded=True,
            _invalid_storage=False,
            _storage_error=False,
            _dirty=False,
            async_reconcile_before_ev_locked=AsyncMock(return_value=True),
        )
    elif failure == "smart_path":
        coordinator.update_config_value("ev_charge_path", "smart_socket")
        coordinator.update_config_value("ev_smart_socket_entity", "switch.car_socket")
        coordinator.update_config_value("ev_smart_socket_current_limit_a", 10)
    elif failure == "outside_target":
        controller.outside_target_active = True

    await controller.async_reconcile(now)

    assert controller.daily_backfill_stop_pending
    assert controller.daily_backfill_stop_attempts == 2
    assert controller.daily_backfill_last_stop_at == NOW - timedelta(seconds=30)
    assert calls == []


async def test_restored_pending_baseline_waits_for_fresh_confirmation_then_checkpoints(
    hass,
    freezer,
):
    now, coordinator, controller, calls = await _pending_baseline(hass, freezer)
    coordinator.update_config_value("ev_automatic_control_enabled", False)
    freezer.tick(timedelta(seconds=91))
    now += timedelta(seconds=91)
    restored = ActiveEvController(hass, coordinator)
    coordinator.ev_controller = restored
    await restored._async_restore()
    assert restored.daily_backfill_stop_pending
    await restored.async_reconcile(now)
    assert restored.daily_backfill_stop_pending

    for row in hass.states.async_all():
        hass.states.async_set(row.entity_id, row.state, dict(row.attributes), force_update=True)
    _fresh(coordinator, now, current_a=1)
    await restored.async_reconcile(now)

    assert not restored.daily_backfill_stop_pending
    assert restored.outside_control_active
    assert restored.daily_backfill_delivered_kwh == 2.25
    assert restored.target_current_a == 1 and restored.reconciliation.phase == "confirmed"
    assert calls == []
    saved = await restored._repository.store.async_load()
    assert saved["daily_backfill"]["stop_pending"] is False


async def test_failed_baseline_handoff_checkpoint_keeps_pending_duty_and_blocks_false_idle(
    hass,
    freezer,
    monkeypatch,
):
    now, _, controller, calls = await _pending_baseline(hass, freezer)
    controller.outside_stop_requested = True
    store = controller._repository.store
    prior = await store.async_load()
    monkeypatch.setattr(
        store, "async_save", AsyncMock(side_effect=OSError("synthetic save failure"))
    )

    with pytest.raises(OSError):
        await controller.async_reconcile(now)

    assert controller.daily_backfill_stop_pending
    assert controller.daily_backfill_stop_attempts == 2
    assert controller.daily_backfill_last_stop_at == NOW - timedelta(seconds=30)
    assert controller.outside_stop_requested
    assert controller.outside_control_active
    assert await store.async_load() == prior
    assert calls == []
    blockers = set()
    _ev_runtime(controller, blockers)
    assert "ev_session_active" in blockers


async def test_zero_baseline_retains_stop_until_switch_off_feedback(hass, freezer):
    now, coordinator, controller, calls = await _pending_baseline(hass, freezer)
    coordinator.update_config_value("ev_protected_baseline_a", 0)
    controller.last_decision_at = None
    freezer.tick(timedelta(seconds=60))
    now += timedelta(seconds=60)  # Respect the retained second-stop retry interval.
    await controller.async_reconcile(now)
    assert controller.daily_backfill_stop_pending
    assert any(service == "turn_off" for _, service, _ in calls)
    hass.states.async_set("switch.car_charge", "off")
    hass.states.async_set("sensor.car_charging", "stopped")
    hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "A"})
    await controller.async_reconcile(now + timedelta(seconds=1))
    assert not controller.daily_backfill_stop_pending
    assert not controller.outside_control_active


async def test_ready_by_curtailment_finishes_after_actual_baseline_feedback(hass, freezer):
    start = NOW.replace(hour=5)
    freezer.move_to(start)
    calls = _services(hass)
    coordinator, controller = _site(hass, ev_protected_baseline_a=1)
    _fresh(coordinator, start)
    await controller.async_reconcile(start)
    assert controller.daily_backfill_active and controller.target_current_a == 8
    _charging(hass, 8)
    _limit_feedback(hass, controller.target_limit_percent)

    now = start + timedelta(minutes=3)
    freezer.move_to(now)
    coordinator.data.available_after_reserve_kwh = 4  # Less than protected house energy.
    _fresh(coordinator, now, current_a=8)
    await controller.async_reconcile(now)
    assert not controller.daily_backfill_active
    assert controller.daily_backfill_stop_pending
    assert controller.target_current_a == 1
    assert any(
        data.get("entity_id") == "number.car_current" and data.get("value") == 1
        for _, _, data in calls
    )
    delivered = controller.daily_backfill_delivered_kwh
    calls.clear()

    now += timedelta(seconds=30)
    freezer.move_to(now)
    _charging(hass, 1)
    hass.states.async_set("device_tracker.car", "home", force_update=True)
    hass.states.async_set("binary_sensor.car_cable", "on", force_update=True)
    _limit_feedback(hass, controller.target_limit_percent)
    _fresh(coordinator, now, current_a=1)
    await controller.async_reconcile(now)

    assert controller.reconciliation.phase == "confirmed"
    assert not controller.daily_backfill_stop_pending, (
        controller.outside_target_active,
        controller.outside_control_active,
        controller.decision_phase,
        controller.target_current_a,
        controller.target_limit_percent,
    )
    assert controller.outside_control_active
    assert controller.daily_backfill_delivered_kwh == delivered
    assert calls == []
    saved = await controller._repository.store.async_load()
    assert saved["daily_backfill"]["stop_pending"] is False
    assert saved["daily_backfill"]["delivered_kwh"] == delivered


async def test_confirmed_old_baseline_can_handoff_to_qualified_ev_before_export(hass, freezer):
    freezer.move_to(NOW)
    calls = _services(hass)
    coordinator, controller = _case(
        hass, NOW, ev_protected_baseline_a=1, ev_before_export_enabled=False
    )
    _charging(hass, 1)
    await controller.async_reconcile(NOW)
    _limit_feedback(hass, controller.target_limit_percent)
    await controller.async_reconcile(NOW + timedelta(seconds=1))
    assert controller.reconciliation.phase == "confirmed"
    controller.daily_backfill_stop_pending = True
    controller.daily_backfill_stop_attempts = 1
    controller.daily_backfill_last_stop_at = NOW - timedelta(minutes=1)
    await controller._async_save(NOW + timedelta(seconds=1))
    coordinator.update_config_value("ev_before_export_enabled", True)
    now = NOW + timedelta(seconds=2)
    freezer.move_to(now)
    calls.clear()

    await controller.async_reconcile(now)

    assert not controller.daily_backfill_stop_pending
    assert controller.decision_phase == "ev_before_export_charging"
    assert controller.target_current_a == 8
    assert controller.outside_target_active
    assert any(
        data.get("entity_id") == "number.car_current" and data.get("value") == 8
        for _, _, data in calls
    )
