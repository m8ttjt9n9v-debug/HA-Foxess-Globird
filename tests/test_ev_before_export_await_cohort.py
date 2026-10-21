"""Budget checks must observe one current cohort after awaited checkpoints."""

import asyncio
from datetime import timedelta

import pytest

from custom_components.home_energy_orchestrator.ev_active import _CYCLE_FEEDBACK
from custom_components.home_energy_orchestrator.ev_observation_adapter import (
    capture_ev_feedback,
    ev_observation_entity_map,
)
from tests.test_ev_backfill_timing import _charging, _fresh, _services
from tests.test_ev_before_export_source_clocks import _native
from tests.test_ev_before_export_source_clocks import (
    native_provider_cleanup as native_provider_cleanup,
)
from tests.test_ev_before_export_source_clocks import (
    utc_clock as utc_clock,
)


def _running(hass, freezer):
    rig = _native(hass, freezer, old_seconds=0)
    _charging(hass)
    limit = hass.states.get("number.car_limit")
    hass.states.async_set(limit.entity_id, "50", dict(limit.attributes))
    rig.provider.data.update({
        "charge_state_charging_state": "Charging",
        "charge_state_charger_actual_current": 8,
        "charge_state_charge_current_request": 8,
        "charge_state_charge_limit_soc": 50,
        "charge_state_timestamp": (rig.now - timedelta(seconds=2)).timestamp() * 1000,
    })
    _fresh(rig.coordinator, rig.now, current_a=8)
    return rig


@pytest.mark.parametrize("publication", ["native_clock", "native_value", "electrical"])
async def test_healthy_publication_during_checkpoint_does_not_create_stop_duty(
    hass, freezer, monkeypatch, publication,
):
    rig = _running(hass, freezer)
    calls = _services(hass)
    original_save = rig.controller._async_save
    published = False

    async def save_with_publication(at=None):
        nonlocal published
        if not published:
            published = True
            await asyncio.sleep(0)
            later = rig.now + timedelta(seconds=1)
            freezer.move_to(later)
            if publication == "native_clock":
                rig.provider.data = {
                    **rig.provider.data,
                    "charge_state_timestamp": later.timestamp() * 1000,
                }
            elif publication == "native_value":
                # The vehicle measured before cycle start but published during
                # storage. Both native and HA values belong to the new frame.
                rig.provider.data = {
                    **rig.provider.data,
                    "charge_state_timestamp": (
                        rig.now - timedelta(seconds=1)
                    ).timestamp() * 1000,
                    "charge_state_charger_actual_current": 7,
                }
                hass.states.async_set(
                    "sensor.car_actual_current", "7", {"unit_of_measurement": "A"},
                )
            else:
                _fresh(rig.coordinator, later, current_a=8)
        await original_save(at)

    monkeypatch.setattr(rig.controller, "_async_save", save_with_publication)
    await rig.controller.async_reconcile(rig.now)

    assert published
    assert rig.controller.decision_phase == "ev_before_export_charging"
    assert rig.controller.target_current_a == 8
    assert not rig.controller.daily_backfill_stop_pending
    assert not any(call[:2] == ("switch", "turn_off") for call in calls)


@pytest.mark.parametrize("fault", [
    "future_native", "future_electrical", "native_mismatch", "expired_native",
    "failed_native", "optimistic_native",
])
async def test_post_checkpoint_current_evidence_still_rejects_real_faults(
    hass, freezer, monkeypatch, fault,
):
    rig = _running(hass, freezer)
    calls = _services(hass)
    original_save = rig.controller._async_save
    published = False

    async def save_with_fault(at=None):
        nonlocal published
        if not published:
            published = True
            await asyncio.sleep(0)
            later = rig.now + timedelta(seconds=1)
            freezer.move_to(later)
            if fault == "future_native":
                rig.provider.data["charge_state_timestamp"] = (
                    later + timedelta(seconds=1)
                ).timestamp() * 1000
            elif fault == "future_electrical":
                _fresh(rig.coordinator, later + timedelta(seconds=1), current_a=8)
            elif fault == "native_mismatch":
                rig.provider.data["charge_state_charger_actual_current"] = 7
            elif fault == "expired_native":
                rig.provider.data["charge_state_timestamp"] = (
                    later - timedelta(seconds=91)
                ).timestamp() * 1000
            elif fault == "failed_native":
                rig.provider.last_update_success = False
            else:
                rig.provider.data["charge_state_charging_state"] = True
        await original_save(at)

    monkeypatch.setattr(rig.controller, "_async_save", save_with_fault)
    await rig.controller.async_reconcile(rig.now)

    assert rig.controller.decision_phase == "ev_before_export_energy_unavailable"
    assert rig.controller.target_current_a == 0
    assert rig.controller.daily_backfill_stop_pending
    assert any(call[:2] == ("switch", "turn_off") for call in calls)


@pytest.mark.parametrize("fault", [False, True])
async def test_fresh_budget_scope_always_restores_original_cycle_feedback(
    hass, freezer, fault,
):
    rig = _running(hass, freezer)
    original = capture_ev_feedback(hass, ev_observation_entity_map(rig.coordinator.runtime_config))
    later = rig.now + timedelta(seconds=1)
    freezer.move_to(later)
    rig.provider.data = {
        **rig.provider.data,
        "charge_state_timestamp": later.timestamp() * 1000,
        "charge_state_charger_actual_current": 7,
    }
    hass.states.async_set("sensor.car_actual_current", "7", {"unit_of_measurement": "A"})
    if fault:
        rig.provider.last_update_success = False
    token = _CYCLE_FEEDBACK.set(original)
    try:
        budget = rig.controller._before_export_energy_budget(rig.now)
        assert (budget is not None) is not fault
        assert _CYCLE_FEEDBACK.get() is original
        assert original.actual_current.current_a == 8
    finally:
        _CYCLE_FEEDBACK.reset(token)


async def test_checkpoint_crossing_free_start_cannot_add_outside_power(
    hass, freezer, monkeypatch,
):
    rig = _running(hass, freezer)
    rig.coordinator.update_config_value("free_charge_window_start", "16:10:01")
    rig.coordinator.update_config_value("free_charge_window_end", "17:00:00")
    calls = _services(hass)
    original_save = rig.controller._async_save
    published = False

    async def save_across_free_start(at=None):
        nonlocal published
        if not published:
            published = True
            await asyncio.sleep(0)
            freezer.move_to(rig.now + timedelta(seconds=1))
        await original_save(at)

    monkeypatch.setattr(rig.controller, "_async_save", save_across_free_start)
    await rig.controller.async_reconcile(rig.now)

    assert rig.controller.last_reason == "free_window_transition"
    assert calls == []


@pytest.mark.parametrize("maximum,expected", [(16, 8), (4, 4)])
async def test_checkpoint_new_current_request_is_reconciled_to_current_cap(
    hass, freezer, monkeypatch, maximum, expected,
):
    rig = _running(hass, freezer)
    calls = _services(hass)
    original_save = rig.controller._async_save
    published = False

    async def save_with_new_request(at=None):
        nonlocal published
        if not published:
            published = True
            await asyncio.sleep(0)
            rig.provider.data["charge_state_charge_current_request"] = 16
            current = hass.states.get("number.car_current")
            hass.states.async_set(
                current.entity_id, "16", {**current.attributes, "max": maximum},
            )
        await original_save(at)

    monkeypatch.setattr(rig.controller, "_async_save", save_with_new_request)
    await rig.controller.async_reconcile(rig.now)

    assert rig.controller.target_current_a == 8
    assert (
        "number", "set_value", {"entity_id": "number.car_current", "value": expected},
    ) in calls


@pytest.mark.parametrize("vehicle_soc", [25, 30])
async def test_fresh_outside_scope_restores_cycle_even_when_before_export_yields(
    hass, freezer, vehicle_soc,
):
    rig = _running(hass, freezer)
    original = capture_ev_feedback(hass, ev_observation_entity_map(rig.coordinator.runtime_config))
    rig.provider.data["charge_state_usable_battery_level"] = vehicle_soc
    hass.states.async_set("sensor.car_soc", str(vehicle_soc), {"unit_of_measurement": "%"})
    token = _CYCLE_FEEDBACK.set(original)
    try:
        rig.controller._calculate_outside_target(rig.now, original.direct_observation)
        assert _CYCLE_FEEDBACK.get() is original
        if vehicle_soc == 30:
            assert rig.controller.decision_phase != "ev_before_export_charging"
    finally:
        _CYCLE_FEEDBACK.reset(token)
