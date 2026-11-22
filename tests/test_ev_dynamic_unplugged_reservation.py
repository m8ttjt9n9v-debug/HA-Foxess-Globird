"""Online unplugged planning uses a bounded measurement, separate from handoff."""

from datetime import timedelta

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.ev_current_measurement import (
    measure_ev_current,
    measure_ev_soc,
)
from custom_components.home_energy_orchestrator.planner.foxess_export_policy import (
    evaluate_foxess_export_policy,
)
from tests.test_ev_backfill_timing import _fresh
from tests.test_ev_dynamic_reservation_outage import _publish_current_modbus
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

AGE_SETTING = "ev_reservation_unplugged_soc_max_age_minutes"
LOCAL_CABLE = "binary_sensor.local_ev_connected"


def _stamp(rig, age_seconds):
    rig.provider.data["charge_state_timestamp"] = (
        rig.now - timedelta(seconds=age_seconds)
    ).timestamp() * 1000


@pytest.mark.parametrize("home", [False, True])
@pytest.mark.parametrize("price", [False, True])
@pytest.mark.parametrize("soc,reserved", [(35, 3.6), (53, 0)])
async def test_online_unplugged_reserves_the_shortfall_without_blanking_sellable(
    hass, freezer, home, price, soc, reserved,
):
    rig = await _rig(hass, freezer)
    _publish_vehicle(hass, rig, soc=soc, home=home, connected=False)
    _stamp(rig, 450)
    budget = _budget(rig)
    assert budget.valid
    assert budget.requested_reservation_kwh == pytest.approx(reserved)
    assert budget.exportable_kwh == pytest.approx(19 - reserved)
    policy = evaluate_foxess_export_policy(_context(hass, rig, price=price))
    assert policy.eligible
    assert policy.protected_ev_kwh == pytest.approx(reserved)
    assert policy.export_plan.sellable_energy_kwh > 0
    assert not rig.controller.dynamic_topup_requested(rig.now)
    assert rig.fox._ev_before_export_handoff_ready(rig.now)
    assert rig.fox.ev_export_handoff_reason == "vehicle_disconnected"
    feedback = rig.controller._capture_feedback()
    assert measure_ev_soc(hass, feedback, now=rig.now, max_age_seconds=90) is None
    assert not measure_ev_current(hass, feedback, now=rig.now, max_age_seconds=90).valid


@pytest.mark.parametrize("age,valid", [
    (-0.001, False), (90, True), (90.001, True),
    (5399.999, True), (5400, True), (5400.001, False), (30 * 86400, False),
])
async def test_default_unplugged_age_uses_original_frame_even_after_ha_republish(
    hass, freezer, age, valid,
):
    rig = await _rig(hass, freezer)
    _publish_vehicle(hass, rig, home=False, connected=False)
    _stamp(rig, age)
    assert hass.states.get("sensor.car_soc").last_reported == rig.now
    budget = _budget(rig)
    assert budget.valid is valid
    protection = rig.controller.daily_backfill_protection_kwh(rig.now)
    assert protection == (pytest.approx(3.6) if valid else None)


@pytest.mark.parametrize("age_minutes,age_seconds,valid", [
    (0, 90, True), (0, 90.001, False), (5, 300, True), (5, 300.001, False),
])
async def test_unplugged_setting_changes_only_the_longer_age(
    hass, freezer, age_minutes, age_seconds, valid,
):
    rig = await _rig(hass, freezer)
    _publish_vehicle(hass, rig, home=True, connected=False)
    _stamp(rig, age_seconds)
    rig.coordinator.update_config_value(AGE_SETTING, age_minutes)
    assert _budget(rig).valid is valid


@pytest.mark.parametrize("age,valid", [(90, True), (90.001, False)])
async def test_online_connected_vehicle_keeps_the_strict_soc_age(hass, freezer, age, valid):
    rig = await _rig(hass, freezer)
    _publish_vehicle(hass, rig, home=True, connected=True)
    _stamp(rig, age)
    assert _budget(rig).valid is valid


async def test_retained_amps_in_a_disconnected_frame_are_not_live_current(hass, freezer):
    rig = await _rig(hass, freezer)
    _publish_vehicle(hass, rig, home=False, connected=False, actual=2)
    _stamp(rig, 450)
    assert _budget(rig).requested_reservation_kwh == pytest.approx(3.6)
    feedback = rig.controller._capture_feedback()
    assert not measure_ev_current(hass, feedback, now=rig.now, max_age_seconds=90).valid


@pytest.mark.parametrize("native,mapped", [
    ({"state": "offline"}, {}),
    ({"charge_state_conn_charge_cable": "IEC"}, {}),
    ({"charge_state_conn_charge_cable": None}, {}),
    ({"charge_state_charging_state": "Stopped"}, {}),
    ({}, {"binary_sensor.car_cable": "on"}),
    ({}, {"binary_sensor.car_cable": "unknown"}),
    ({}, {"sensor.car_charging": "charging"}),
    ({}, {"sensor.car_charging": "unavailable"}),
    ({}, {"switch.car_charge": "on"}),
])
async def test_unplugged_extension_rejects_inconsistent_or_unknown_evidence(
    hass, freezer, native, mapped,
):
    rig = await _rig(hass, freezer)
    _publish_vehicle(hass, rig, home=False, connected=False)
    _stamp(rig, 91)
    assert _budget(rig).valid
    rig.provider.data.update(native)
    for entity, state in mapped.items():
        hass.states.async_set(entity, state, force_update=True)
    assert not _budget(rig).valid


@pytest.mark.parametrize("fault", ["failed_provider", "generic_cable", "wrong_cable_field"])
async def test_unplugged_extension_requires_healthy_exact_native_evidence(hass, freezer, fault):
    rig = await _rig(hass, freezer)
    _publish_vehicle(hass, rig, home=False, connected=False)
    _stamp(rig, 450)
    assert _budget(rig).valid
    registry = er.async_get(hass)
    if fault == "failed_provider":
        rig.provider.last_update_success = False
    elif fault == "generic_cable":
        registry.async_remove("binary_sensor.car_cable")
        hass.states.async_set("binary_sensor.car_cable", "off", force_update=True)
    else:
        registry.async_update_entity("binary_sensor.car_cable", new_unique_id="other-cable")
    assert not _budget(rig).valid


@pytest.mark.parametrize("withdraw", ["setting_disabled", "reconnected", "expired"])
async def test_unplugged_planning_leaves_export_handoff_and_ev_authority_separate(
    hass, freezer, monkeypatch, withdraw,
):
    rig = await _rig(hass, freezer, ev_local_connection_entity=LOCAL_CABLE)
    calls = _services(hass, monkeypatch, rig)
    _publish_vehicle(hass, rig, home=True, connected=False)
    original_stamp = rig.provider.data["charge_state_timestamp"]
    rig.now += timedelta(minutes=10)
    freezer.move_to(rig.now)
    _fresh(rig.coordinator, rig.now)
    _publish_current_modbus(rig)
    await rig.controller._async_save(rig.now)
    rig.controller = ActiveEvController(hass, rig.coordinator)
    rig.coordinator.ev_controller = rig.controller
    await rig.controller._async_restore()
    assert _budget(rig).requested_reservation_kwh == pytest.approx(3.6)
    assert rig.provider.data["charge_state_timestamp"] == original_stamp
    assert not rig.fox._ev_before_export_handoff_ready(rig.now)
    hass.states.async_set(LOCAL_CABLE, "off")
    await rig.fox.async_reconcile()
    assert rig.fox.ev_export_handoff_reason == "local_disconnected"
    assert any(value == "Force Discharge" for _, value in calls)
    calls.clear()

    if withdraw == "setting_disabled":
        rig.coordinator.update_config_value(AGE_SETTING, 0)
    elif withdraw == "reconnected":
        hass.states.async_set(LOCAL_CABLE, "on")
        hass.states.async_set("binary_sensor.car_cable", "on")
    else:
        # Shrink the ceiling to the exact age, then cross it without altering the frame.
        rig.coordinator.update_config_value(AGE_SETTING, 10)
        assert _budget(rig).valid
        rig.now += timedelta(milliseconds=1)
        freezer.move_to(rig.now)
        _fresh(rig.coordinator, rig.now)
        _publish_current_modbus(rig)
    assert not _budget(rig).valid
    await rig.fox.async_reconcile()
    await rig.controller.async_reconcile(rig.now)
    assert not rig.fox.export_effective_enabled
    assert ("select.foxess_mode", "Self Use") in calls
    assert not any(value == "Force Discharge" or entity == "switch.car_charge" and value == "on"
                   or entity == "number.car_current" and value > 0 for entity, value in calls)
