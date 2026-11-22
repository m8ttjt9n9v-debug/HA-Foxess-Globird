"""Configured normal limits through Dynamic accounting and existing handoffs.

All provider frames and transport acknowledgements are synthetic. These cases
remove no source, electrical, energy or physical-handoff requirement.
"""

from datetime import timedelta

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.planner.ev_before_export import (
    EvBeforeExportRecovery,
)
from custom_components.home_energy_orchestrator.planner.export import ExportPlan
from custom_components.home_energy_orchestrator.planner.foxess_export_policy import (
    evaluate_foxess_export_policy,
)
from tests.test_ev_backfill_timing import _fresh
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
from tests.test_ev_dynamic_reservation_runtime import utc_clock as utc_clock


@pytest.mark.parametrize("normal_target", [80, 90, 95, 100])
@pytest.mark.parametrize("delta", [-1, 0, 0.001])
async def test_dynamic_reservation_clips_minimum_plus_buffer_to_configured_normal_limit(
    hass, freezer, normal_target, delta,
):
    rig = await _rig(
        hass, freezer, ev_free_window_charge_limit_percent=normal_target,
        ev_before_export_soc_target_percent=99, ev_before_export_soc_buffer_percent=2,
    )
    soc = min(normal_target + delta, 100)
    _publish_vehicle(hass, rig, soc=soc, home=False, connected=False)
    budget = _budget(rig)
    shortfall = 60 * max(normal_target - soc, 0) / 100
    assert budget.valid and budget.target_soc_percent == normal_target
    assert budget.requested_reservation_kwh == pytest.approx(shortfall)
    assert budget.protected_ev_kwh == pytest.approx(shortfall)
    assert budget.exportable_kwh == pytest.approx(19 - shortfall)
    assert budget.ev_available_kwh == 19
    policy = evaluate_foxess_export_policy(_context(hass, rig))
    assert policy.eligible
    assert policy.export_plan.sellable_energy_kwh == pytest.approx(19 - shortfall)
    assert not rig.controller.dynamic_topup_requested(rig.now)
    assert not rig.controller._charge_to_full_requested()


@pytest.mark.parametrize(
    "normal_target,minimum,buffer,target",
    [(80, 78, 3, 80), (90, 88, 3, 90), (95, 92, 2, 94),
     (100, 95, 2, 97), (100, 99, 2, 100)],
)
async def test_dynamic_minimum_buffer_and_normal_target_remain_separate_inputs(
    hass, freezer, normal_target, minimum, buffer, target,
):
    rig = await _rig(
        hass, freezer, ev_free_window_charge_limit_percent=normal_target,
        ev_before_export_soc_target_percent=minimum,
        ev_before_export_soc_buffer_percent=buffer,
    )
    _publish_vehicle(hass, rig, soc=75, home=False, connected=False)
    budget = _budget(rig)
    assert budget.valid and budget.target_soc_percent == target
    assert budget.requested_reservation_kwh == pytest.approx(60 * (target - 75) / 100)


@pytest.mark.parametrize("sleeping", [False, True])
async def test_normal_target_edits_recompute_dynamic_protection_without_retained_90_cap(
    hass, freezer, sleeping,
):
    rig = await _rig(
        hass, freezer, ev_before_export_soc_target_percent=94,
        ev_before_export_soc_buffer_percent=3,
    )
    _publish_vehicle(hass, rig, soc=91, home=False, connected=False)
    if sleeping:
        rig.provider.data.update({
            "state": "asleep",
            "charge_state_timestamp": (rig.now - timedelta(minutes=10)).timestamp() * 1000,
        })
    source_at = rig.provider.data["charge_state_timestamp"]
    for normal, expected_target, expected_reservation in [
        (80, 80, 0), (100, 97, 3.6), (90, 90, 0), (95, 95, 2.4), (100, 97, 3.6),
    ]:
        rig.coordinator.update_config_value("ev_free_window_charge_limit_percent", normal)
        budget = _budget(rig)
        assert budget.valid and budget.target_soc_percent == expected_target
        assert budget.requested_reservation_kwh == pytest.approx(expected_reservation)
        assert budget.exportable_kwh == pytest.approx(19 - expected_reservation)
        assert not rig.controller.dynamic_topup_requested(rig.now)
        assert not rig.controller._charge_to_full_requested()
        assert rig.provider.data["charge_state_timestamp"] == source_at
    assert rig.controller.writes_performed == 0


@pytest.mark.parametrize("normal_target", [80, 90, 95, 100])
async def test_pending_dynamic_recovery_uses_same_configured_boundary_after_restart_and_return(
    hass, freezer, normal_target,
):
    rig = await _rig(
        hass, freezer, ev_free_window_charge_limit_percent=normal_target,
        ev_before_export_soc_target_percent=normal_target - 2,
        ev_before_export_soc_buffer_percent=2,
    )
    _publish_vehicle(hass, rig, soc=normal_target - 3, home=False, connected=False)
    rig.controller.before_export_recovery = EvBeforeExportRecovery(
        True, rig.controller._before_export_recovery_binding(),
    )
    assert _budget(rig).requested_reservation_kwh == pytest.approx(1.8)
    assert evaluate_foxess_export_policy(_context(hass, rig)).eligible
    await rig.controller._async_save(rig.now)
    restored = ActiveEvController(hass, rig.coordinator)
    rig.coordinator.ev_controller = restored
    await restored._async_restore()
    rig.controller = restored
    assert restored.before_export_recovery.pending
    assert _budget(rig).requested_reservation_kwh == pytest.approx(1.8)
    assert not restored.dynamic_topup_requested(rig.now)

    # Returning within the hysteresis band must retain the saved recovery
    # rather than consider the human minimum alone sufficient.
    _publish_vehicle(hass, rig, soc=normal_target - 1)
    assert restored.dynamic_topup_requested(rig.now)
    assert restored.before_export_release_target() == normal_target
    assert _budget(rig).requested_reservation_kwh == pytest.approx(0.6)
    assert not rig.fox._ev_before_export_handoff_ready(rig.now)

    # A newly measured boundary does not let read-only planning bypass the
    # restored recovery checkpoint, nor does it prove physical EV stop.
    _publish_vehicle(hass, rig, soc=normal_target, actual=8, charging=True)
    source_at = rig.provider.data["charge_state_timestamp"]
    assert rig.provider.data["charge_state_usable_battery_level"] == normal_target
    budget = _budget(rig)
    assert budget.target_soc_percent == normal_target
    assert budget.requested_reservation_kwh == 0
    assert restored.dynamic_topup_requested(rig.now)
    assert restored.before_export_recovery.pending
    assert restored.before_export_release_target() == normal_target
    saved = await restored._repository.store.async_load()
    assert saved["before_export_recovery"]["pending"] is True
    assert not rig.fox._ev_before_export_handoff_ready(rig.now)
    assert rig.provider.data["charge_state_timestamp"] == source_at

    # The existing measured transition must save logical completion first.
    # Its qualified SoC still cannot acknowledge the car's physical stop.
    await restored._async_update_before_export_recovery(rig.now)
    assert not restored.before_export_recovery.pending
    assert restored.before_export_release_target() is None
    saved = await restored._repository.store.async_load()
    assert saved["before_export_recovery"]["pending"] is False
    assert not restored.dynamic_topup_requested(rig.now)
    assert not rig.fox._ev_before_export_handoff_ready(rig.now)
    assert rig.provider.data["charge_state_timestamp"] == source_at
    _publish_vehicle(hass, rig, soc=normal_target, actual=0, charging=False)
    assert _budget(rig).target_soc_percent == normal_target
    assert _budget(rig).requested_reservation_kwh == 0
    assert rig.fox._ev_before_export_handoff_ready(rig.now)
    assert not restored._charge_to_full_requested()


@pytest.mark.parametrize("fault", [None, "budget", "provider"])
async def test_above_90_dynamic_topup_uses_existing_power_owner_and_withdraws_lost_authority(
    hass, freezer, monkeypatch, fault,
):
    rig = await _rig(
        hass, freezer, ev_free_window_charge_limit_percent=100,
        ev_before_export_soc_target_percent=95, ev_before_export_soc_buffer_percent=2,
    )
    calls = _services(hass, monkeypatch, rig)
    _publish_vehicle(hass, rig, soc=91)
    budget = _budget(rig)
    # Match the current export owner's published view of this same pool;
    # an absent export plan is correctly insufficient positive authority.
    rig.fox.export_plan = ExportPlan(
        budget.exportable_kwh, budget.exportable_kwh, 1, "ready",
    )
    rig.fox.export_protected_ev_kwh = budget.protected_ev_kwh
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.decision_phase == "ev_before_export_charging"
    assert rig.controller.target_limit_percent == 97
    assert 0 < rig.controller.target_current_a <= 8
    assert ("number.car_limit", 97) in calls
    assert ("switch.car_charge", "on") in calls
    assert not any(value == "Force Discharge" for _, value in calls)
    assert not rig.controller._charge_to_full_requested()
    if fault is None:
        return

    rig.now += timedelta(seconds=30)
    freezer.move_to(rig.now)
    _publish_vehicle(hass, rig, soc=91, actual=8, charging=True)
    _fresh(rig.coordinator, rig.now, current_a=8)
    if fault == "budget":
        rig.coordinator.data.available_after_reserve_kwh = 0
    else:
        rig.provider.last_update_success = False
    before = len(calls)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.target_current_a == 0
    assert not any(entity == "number.car_current" and value > 0
                   or entity == "switch.car_charge" and value == "on"
                   for entity, value in calls[before:])
    assert not rig.controller._charge_to_full_requested()
