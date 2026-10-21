"""Buffered top-up handoff; no live devices or cloud APIs."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.foxess_adapter import FoxessEntityMap
from custom_components.home_energy_orchestrator.foxess_observation_adapter import (
    capture_foxess_feedback,
)
from custom_components.home_energy_orchestrator.planner.ev_before_export import (
    EvBeforeExportRecovery,
    advance_before_export_recovery,
    before_export_recovery_target,
    decide_ev_before_export,
)
from custom_components.home_energy_orchestrator.planner.ev_persistence import EvPersistenceState
from custom_components.home_energy_orchestrator.planner.foxess_export_policy import (
    evaluate_foxess_export_policy,
)
from tests.test_ev_backfill_timing import _charging, _fresh, _services
from tests.test_ev_before_export_charging import _case, _now
from tests.test_zerohero_active import _loaded_controller


@pytest.mark.parametrize(
    "soc,pending,expected",
    [
        (39, False, True),
        (40, True, True),
        (40.9, True, True),
        (41, True, False),
        (40, False, False),
        (39.9, False, True),
        (41, False, False),
    ],
)
def test_two_threshold_state_machine(soc, pending, expected):
    state = EvBeforeExportRecovery(pending, ("car",))
    result = advance_before_export_recovery(
        state,
        binding=("car",),
        soc=soc,
        minimum=40,
        release=41,
        connected=True,
    )
    assert result.pending is expected
    decision = decide_ev_before_export(
        enabled=True,
        ev_soc_percent=soc,
        target_soc_percent=40,
        recovery_target_soc_percent=41 if result.pending else None,
    )
    assert decision.export_allowed is (soc >= 40 and not expected)


@pytest.mark.parametrize(
    "minimum,buffer,soft,expected",
    [
        (40, 1, 90, 41),
        (40, 0, 90, 40),
        (40, 2, 40, 40),
        (89, 5, 90, 90),
        (99, 5, 100, 100),
        (95, 1, 90, 95),
    ],
)
def test_buffer_respects_normal_soc_ceiling(minimum, buffer, soft, expected):
    assert before_export_recovery_target(minimum, buffer, soft) == expected


async def _rig(hass, freezer):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(
        hass,
        now,
        ev_before_export_soc_target_percent=40,
        ev_before_export_soc_buffer_percent=1,
    )
    hass.states.async_set("sensor.car_soc", "39", {"unit_of_measurement": "%"})
    await controller.async_reconcile(now)
    return now, calls, coordinator, controller


async def test_topup_stays_active_at_minimum_then_releases_at_buffer(hass, freezer):
    now, calls, coordinator, controller = await _rig(hass, freezer)
    assert controller.before_export_release_target() == 41
    fox = _loaded_controller(hass, coordinator)
    for soc in (40, 40.9):
        now += timedelta(seconds=30)
        freezer.move_to(now)
        _fresh(coordinator, now)
        _charging(hass, 8)
        hass.states.async_set("sensor.car_soc", str(soc), {"unit_of_measurement": "%"})
        coordinator.snapshot = replace(coordinator.snapshot, ev_soc=soc)
        await controller.async_reconcile(now)
        assert controller.decision_phase == "ev_before_export_charging"
        assert 0 < controller.target_current_a <= 8
        assert controller._writes_still_authorized()
        context = fox._export_context(
            capture_foxess_feedback(
                hass,
                FoxessEntityMap(
                    "select.foxess_mode",
                    "number.foxess_charge",
                    "number.foxess_discharge",
                ),
            ),
            now,
        )
        assert context.before_export_recovery_target_percent == 41
        decision = evaluate_foxess_export_policy(context).before_export_decision
        assert not decision.export_allowed and decision.reason == "ev_buffer_topup"
    assert not any(call[:2] == ("switch", "turn_off") for call in calls)

    now += timedelta(seconds=30)
    freezer.move_to(now)
    _fresh(coordinator, now)
    hass.states.async_set("sensor.car_soc", "41", {"unit_of_measurement": "%"})
    await controller.async_reconcile(now)
    assert controller.before_export_release_target() is None
    assert not controller.before_export_recovery.pending
    assert controller.target_current_a == 0


async def test_restart_retains_pending_buffer_and_completed_cycle_does_not_rearm(hass, freezer):
    now, _, coordinator, controller = await _rig(hass, freezer)
    saved = await controller._repository.store.async_load()
    assert saved["before_export_recovery"]["pending"]
    replacement = ActiveEvController(hass, coordinator)
    await replacement._async_restore()
    assert replacement.before_export_release_target() == 41
    hass.states.async_set("sensor.car_soc", "41", {"unit_of_measurement": "%"})
    await replacement._async_update_before_export_recovery(now)
    restored = ActiveEvController(hass, coordinator)
    await restored._async_restore()
    hass.states.async_set("sensor.car_soc", "40", {"unit_of_measurement": "%"})
    await restored._async_update_before_export_recovery(now)
    assert restored.before_export_release_target() is None


async def test_export_positive_command_handoff_rechecks_pending_buffer(hass, freezer):
    now, _, coordinator, controller = await _rig(hass, freezer)
    fox = _loaded_controller(hass, coordinator)
    hass.states.async_set("sensor.car_soc", "40", {"unit_of_measurement": "%"})
    hass.states.async_set("switch.car_charge", "off")
    hass.states.async_set("sensor.car_charging", "stopped")
    hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "A"})
    assert controller.before_export_release_target() == 41
    assert not fox._ev_before_export_handoff_ready(now)


@pytest.mark.parametrize("fault", ["unavailable_soc", "stale", "restored"])
async def test_bad_or_old_completion_evidence_cannot_release_recovery(hass, freezer, fault):
    now, _, coordinator, controller = await _rig(hass, freezer)
    hass.states.async_set("sensor.car_soc", "41", {"unit_of_measurement": "%"})
    if fault == "unavailable_soc":
        hass.states.async_set("sensor.car_soc", "unavailable", {"unit_of_measurement": "%"})
    elif fault == "restored":
        hass.states.async_set(
            "sensor.car_soc", "41", {"unit_of_measurement": "%", "restored": True}
        )
    else:
        now += timedelta(seconds=91)
        freezer.move_to(now)
        _fresh(coordinator, now)
    await controller._async_update_before_export_recovery(now)
    assert controller.before_export_recovery.pending
    assert controller.before_export_release_target() == 41
    fox = _loaded_controller(hass, coordinator)
    assert not fox._ev_before_export_handoff_ready(now)


async def test_checkpoint_failure_cannot_release_export_or_issue_positive_commands(
    hass,
    freezer,
    monkeypatch,
):
    now, calls, _, controller = await _rig(hass, freezer)
    calls.clear()
    monkeypatch.setattr(controller, "_async_save", AsyncMock(side_effect=OSError("disk")))
    hass.states.async_set("sensor.car_soc", "41", {"unit_of_measurement": "%"})
    await controller._async_update_before_export_recovery(now)
    assert controller.before_export_recovery.pending
    assert not decide_ev_before_export(
        enabled=True,
        ev_soc_percent=41,
        target_soc_percent=40,
        recovery_target_soc_percent=controller.before_export_release_target(),
    ).export_allowed
    assert calls == []


async def test_export_cannot_observe_completion_before_its_checkpoint_finishes(
    hass, freezer, monkeypatch
):
    now, _, coordinator, controller = await _rig(hass, freezer)
    fox = _loaded_controller(hass, coordinator)
    hass.states.async_set("sensor.car_soc", "41", {"unit_of_measurement": "%"})
    hass.states.async_set("switch.car_charge", "off")
    hass.states.async_set("sensor.car_charging", "stopped")
    hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "A"})
    save = controller._async_save
    checked = []

    async def checkpoint(saved_at):
        assert not fox._ev_before_export_handoff_ready(now)
        checked.append(True)
        await save(saved_at)

    monkeypatch.setattr(controller, "_async_save", checkpoint)
    await controller._async_update_before_export_recovery(now)
    assert checked == [True]
    assert controller.before_export_release_target() is None
    assert fox._ev_before_export_handoff_ready(now)


async def test_cancelled_completion_checkpoint_retains_recovery(hass, freezer, monkeypatch):
    now, _, coordinator, controller = await _rig(hass, freezer)
    hass.states.async_set("sensor.car_soc", "41", {"unit_of_measurement": "%"})
    monkeypatch.setattr(controller, "_async_save", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await controller._async_update_before_export_recovery(now)
    assert controller.before_export_recovery.pending
    assert not controller._before_export_checkpoint_in_progress
    assert not _loaded_controller(hass, coordinator)._ev_before_export_handoff_ready(now)


async def test_failed_completion_checkpoint_does_not_block_zero_baseline_stop(
    hass,
    freezer,
    monkeypatch,
):
    now, calls, coordinator, controller = await _rig(hass, freezer)
    now += timedelta(seconds=61)
    freezer.move_to(now)
    _fresh(coordinator, now)
    _charging(hass, 8)
    hass.states.async_set("sensor.car_soc", "41", {"unit_of_measurement": "%"})
    monkeypatch.setattr(controller, "_async_save", AsyncMock(side_effect=OSError("disk")))
    calls.clear()
    with pytest.raises(OSError):  # The ordinary stop-attempt checkpoint still reports failure.
        await controller.async_reconcile(now)
    assert ("switch", "turn_off", {"entity_id": "switch.car_charge"}) in calls
    assert not any(c[:2] == ("switch", "turn_on") for c in calls)
    assert controller.before_export_recovery.pending


@pytest.mark.parametrize("fault", ["grid_import", "reserve", "empty_budget", "manual"])
async def test_buffer_does_not_bypass_existing_energy_or_ownership_limits(hass, freezer, fault):
    now, calls, coordinator, controller = await _rig(hass, freezer)
    now += timedelta(seconds=30)
    freezer.move_to(now)
    _fresh(coordinator, now)
    _charging(hass, 8)
    hass.states.async_set("sensor.car_soc", "40", {"unit_of_measurement": "%"})
    if fault == "grid_import":
        _fresh(coordinator, now, grid_kw=0.3)
    elif fault == "reserve":
        hass.states.async_set("sensor.site_battery_soc", "20", {"unit_of_measurement": "%"})
        coordinator.snapshot = replace(coordinator.snapshot, battery_soc=20)
    elif fault == "empty_budget":
        coordinator.data.available_after_reserve_kwh = 0
    else:
        coordinator.active_controller.manual.is_active = True
    calls.clear()
    await controller.async_reconcile(now)
    assert controller.before_export_recovery.pending
    assert controller.target_current_a == 0
    assert not any(c[:2] == ("switch", "turn_on") for c in calls)


async def test_buffer_keeps_total_outside_inverter_cap(hass, freezer):
    now, _, coordinator, controller = await _rig(hass, freezer)
    coordinator.update_config_value("ev_outside_inverter_percent", 10)
    now += timedelta(seconds=30)
    freezer.move_to(now)
    _fresh(coordinator, now)
    hass.states.async_set("sensor.car_soc", "40", {"unit_of_measurement": "%"})
    await controller.async_reconcile(now)
    assert controller.decision_phase == "ev_before_export_charging"
    assert 0 < controller.target_current_a <= 2


@pytest.mark.parametrize(
    "edit,value,expected",
    [
        ("ev_before_export_soc_buffer_percent", 2, 42),
        ("ev_before_export_soc_buffer_percent", 0, None),
        ("ev_before_export_soc_target_percent", 39, None),
        ("ev_before_export_soc_target_percent", 42, 43),
        ("ev_before_export_enabled", False, None),
    ],
)
async def test_setting_edits_recheck_current_intent(hass, freezer, edit, value, expected):
    now, _, coordinator, controller = await _rig(hass, freezer)
    hass.states.async_set("sensor.car_soc", "40", {"unit_of_measurement": "%"})
    coordinator.update_config_value(edit, value)
    await controller._async_update_before_export_recovery(now)
    assert controller.before_export_release_target() == expected


async def test_disconnect_retains_buffer_and_reconnect_can_resume(hass, freezer):
    now, _, coordinator, controller = await _rig(hass, freezer)
    hass.states.async_set("sensor.car_soc", "40", {"unit_of_measurement": "%"})
    hass.states.async_set("device_tracker.car", "not_home")
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("sensor.car_charging", "disconnected")
    await controller._async_update_before_export_recovery(now)
    assert controller.before_export_release_target() == 41
    hass.states.async_set("device_tracker.car", "home")
    hass.states.async_set("binary_sensor.car_cable", "on")
    hass.states.async_set("sensor.car_charging", "stopped")
    now += timedelta(seconds=30)
    freezer.move_to(now)
    _fresh(coordinator, now)
    await controller.async_reconcile(now)
    assert controller.decision_phase == "ev_before_export_charging"


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        [],
        {"pending": 1, "binding": ["car"]},
        {"pending": True, "binding": []},
        {"pending": True, "binding": [1]},
    ],
)
async def test_corrupt_recovery_does_not_clear_other_ownership_or_release_export(
    hass, freezer, bad
):
    now, _, _, controller = await _rig(hass, freezer)
    saved = await controller._repository.store.async_load()
    saved["before_export_recovery"] = bad
    decoded = EvPersistenceState.from_payload(saved, now)
    assert not decoded.before_export_recovery.valid
    assert decoded.reconciliation == controller.reconciliation
    assert decoded.outside_control_active == controller.outside_control_active
    next_state = advance_before_export_recovery(
        decoded.before_export_recovery,
        binding=("car",),
        soc=40,
        minimum=40,
        release=41,
        connected=True,
    )
    assert not next_state.valid


@pytest.mark.parametrize("owner", ["free", "full"])
async def test_explicit_free_and_full_priority_remains_independent(hass, freezer, owner):
    now = _now(12, 2) if owner == "free" else _now()
    freezer.move_to(now)
    _services(hass)
    _, controller = _case(
        hass,
        now,
        ev_before_export_soc_target_percent=40,
        ev_before_export_soc_buffer_percent=1,
        ev_charge_to_full_enabled=owner == "full",
    )
    hass.states.async_set("sensor.car_soc", "39", {"unit_of_measurement": "%"})
    await controller.async_reconcile(now)
    assert controller.decision_phase != "ev_before_export_charging"
    if owner == "free":
        assert controller.policy_route.route == "free_window"
    else:
        assert controller.decision_phase == "charge_to_full_paid_grid_override"
