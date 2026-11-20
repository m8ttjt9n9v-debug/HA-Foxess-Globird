"""Fast inverter readings must not refresh retained native vehicle measurements.

Synthetic native publishers and the real controller are used throughout.  A
requested-current acknowledgement is deliberately separate from a vehicle
actual-current measurement; no physical EV power is inferred from house load.
"""

import asyncio
from dataclasses import replace
from datetime import timedelta
from math import floor
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.home_energy_orchestrator.coordinator import EnergyCoordinator
from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.ev_current_measurement import measure_ev_current
from custom_components.home_energy_orchestrator.ev_observation_adapter import (
    capture_ev_feedback,
    ev_observation_entity_map,
)
from custom_components.home_energy_orchestrator.planner.export import ExportPlan
from custom_components.home_energy_orchestrator.telemetry import NormalizedSample, TelemetrySource
from tests.test_ev_backfill_timing import _fresh, _services
from tests.test_ev_before_export_charging import _above_baseline, _case, _now
from tests.test_ev_before_export_source_clocks import _native
from tests.test_ev_before_export_source_clocks import (
    native_provider_cleanup as native_provider_cleanup,
)
from tests.test_ev_before_export_source_clocks import utc_clock as utc_clock


def _morning(hass, freezer, *, spill=False):
    rig = _native(hass, freezer, old_seconds=0)
    for key, value in {
        "ev_before_export_enabled": False,
        "ev_morning_solar_enabled": not spill,
        "ev_solar_spill_enabled": spill,
        "ev_solar_spill_battery_soc_percent": 95,
        "ev_morning_solar_reserve_soc_percent": 20,
        "ev_pre_free_backfill_enabled": False,
        "configure_solar": True,
        "solar_power_entity": "sensor.solar",
        "free_charge_window_start": "17:00:00",
        "free_charge_window_end": "17:59:00",
    }.items():
        rig.coordinator.update_config_value(key, value)
    _modbus(hass, rig, rig.now)
    return rig


def _modbus(hass, rig, at, *, surplus=3.43, physical_current=0, grid=0):
    """Publish fast site power independently of retained Tessie current."""
    _fresh(rig.coordinator, at, grid_kw=grid)
    ev_kw = physical_current * 230 * 3 / 1000
    battery = surplus - ev_kw + grid

    def sample(entity, value):
        return NormalizedSample(value, "kW", (TelemetrySource(entity, value, "kW", at),),
                                "positive_charge", True, True, "ok")

    rig.coordinator.telemetry = replace(
        rig.coordinator.telemetry,
        battery_power=sample("sensor.battery_power", battery),
        solar_power=sample("sensor.solar", surplus + 0.2),
    )
    rig.coordinator.snapshot = replace(
        rig.coordinator.snapshot, battery_soc=99, grid_power_kw=grid,
        house_load_kw=ev_kw + 0.2,
    )
    for entity, value, unit in (
        ("sensor.site_battery_soc", 99, "%"),
        ("sensor.site_grid", grid, "kW"),
        ("sensor.battery_power", battery, "kW"),
        ("sensor.house", ev_kw + 0.2, "kW"),
        ("sensor.solar", surplus + 0.2, "kW"),
    ):
        hass.states.async_set(entity, str(value), {"unit_of_measurement": unit}, force_update=True)
    hass.states.async_set("device_tracker.car", "home", force_update=True)


def _vehicle(hass, rig, at, *, actual, requested, limit=90, charging=True):
    """One genuine native measurement, not an optimistic command cache update."""
    rig.provider.data.update({
        "charge_state_timestamp": at.timestamp() * 1000,
        "charge_state_charger_actual_current": actual,
        "charge_state_charge_current_request": requested,
        "charge_state_charge_limit_soc": limit,
        "charge_state_charging_state": "Charging" if charging else "Stopped",
    })
    for entity, value in (
        ("sensor.car_actual_current", actual),
        ("number.car_current", requested),
        ("number.car_limit", limit),
    ):
        old = hass.states.get(entity)
        hass.states.async_set(entity, str(value), dict(old.attributes), force_update=True)
    hass.states.async_set("sensor.car_charging", "charging" if charging else "stopped",
                          force_update=True)
    hass.states.async_set("switch.car_charge", "on" if charging else "off", force_update=True)


def _asleep_unplugged(hass, rig, measured_at):
    """Publish a real unplugged frame whose clock can age while the car sleeps."""
    _vehicle(hass, rig, measured_at, actual=0, requested=6, charging=False)
    rig.provider.data.update({
        "state": "asleep",
        "charge_state_charging_state": "Disconnected",
        "charge_state_conn_charge_cable": "<invalid>",
        "charge_state_charge_enable_request": True,
    })
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("sensor.car_charging", "disconnected")


def _house_learner(hass, rig, **changes):
    config = {**rig.coordinator.config, "house_load_includes_ev": True, **changes}
    coordinator = EnergyCoordinator(hass, config, "native-learning-idle-test")
    coordinator.snapshot = replace(rig.coordinator.snapshot, house_load_kw=6)
    return coordinator


async def test_fully_generic_fresh_physical_feedback_preserves_existing_top_up_permission(
    hass, freezer,
):
    # This separate controller has explicitly generic mappings, not one half
    # of a native pair. Retain the canonical generic contract independently.
    now = _now(16)
    freezer.move_to(now)
    _, controller = _case(hass, now)
    calls = _services(hass)
    await controller.async_reconcile(now)
    assert controller.decision_phase == "ev_before_export_charging"
    assert controller.target_current_a == 8
    assert _above_baseline(calls)


@pytest.mark.parametrize("fault", [
    "expired", "future", "missing_timestamp", "invalid_timestamp", "offline",
    "publisher_failed", "missing_actual", "actual_mismatch", "restored_actual",
])
@pytest.mark.parametrize("spill", [False, True])
async def test_fresh_modbus_does_not_authorize_morning_solar_from_invalid_native_current(
    hass, freezer, fault, spill,
):
    rig = _morning(hass, freezer, spill=spill)
    calls = _services(hass)
    if fault in {"expired", "future"}:
        rig.provider.data["charge_state_timestamp"] = (
            rig.now + timedelta(seconds=-91 if fault == "expired" else 1)
        ).timestamp() * 1000
    elif fault == "missing_timestamp":
        rig.provider.data.pop("charge_state_timestamp")
    elif fault == "invalid_timestamp":
        rig.provider.data["charge_state_timestamp"] = True
    elif fault == "offline":
        rig.provider.data["state"] = "asleep"
    elif fault == "publisher_failed":
        rig.provider.last_update_success = False
    elif fault == "missing_actual":
        hass.states.async_remove("sensor.car_actual_current")
    elif fault == "actual_mismatch":
        rig.provider.data["charge_state_charger_actual_current"] = 4
    elif fault == "restored_actual":
        hass.states.async_set("sensor.car_actual_current", "0", {
            "unit_of_measurement": "A", "restored": True,
        })
    await rig.controller.async_reconcile(rig.now)
    assert not _above_baseline(calls)
    assert rig.controller.target_current_a in {None, 0}


async def test_genuine_unchanged_native_current_does_not_require_ha_value_republication(
    hass, freezer,
):
    rig = _morning(hass, freezer)
    calls = _services(hass)
    actual = hass.states.get("sensor.car_actual_current")
    later = rig.now + timedelta(seconds=91)
    freezer.move_to(later)
    _modbus(hass, rig, later)
    # Only the existing native frame's measurement advances, not the unchanged
    # HA actual-current entity's own report clock.
    rig.provider.data["charge_state_timestamp"] = later.timestamp() * 1000
    await rig.controller.async_reconcile(later)
    assert rig.controller.target_current_a == 4
    assert _above_baseline(calls)
    assert hass.states.get(actual.entity_id).last_reported == actual.last_reported


@pytest.mark.parametrize("restart", [False, True])
async def test_expired_vehicle_frame_with_fast_modbus_withdraws_owned_morning_current(
    hass, freezer, restart,
):
    rig = _morning(hass, freezer)
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.target_current_a == 4
    _vehicle(hass, rig, rig.now, actual=4, requested=4)
    await rig.controller._async_save(rig.now)
    later = rig.now + timedelta(seconds=91)
    freezer.move_to(later)
    _modbus(hass, rig, later, physical_current=4)
    if restart:
        rig.controller = ActiveEvController(hass, rig.coordinator)
        rig.coordinator.ev_controller = rig.controller
        await rig.controller._async_restore()
    before = len(calls)
    await rig.controller.async_reconcile(later)
    assert rig.controller.target_current_a == 0
    assert not _above_baseline(calls[before:])
    assert any(call[:2] == ("switch", "turn_off") for call in calls[before:])


async def test_fresh_numeric_lag_and_catchup_never_substitute_command_or_house_power(
    hass, freezer,
):
    rig = _morning(hass, freezer)
    _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.target_current_a == 4
    # Command acknowledgements arrive before actual current catches up. The
    # new native measurement truthfully reports zero, while fast Modbus already
    # includes 4 A EV demand. No controller delay/new power estimate is assumed.
    for seconds, actual, requested, physical, expected_kw in (
        (30, 0, 4, 4, 0),
        (60, 4, 4, 4, 2.76),
        (90, 4, 2, 2, 2.76),
        (120, 2, 2, 2, 1.38),
    ):
        at = rig.now + timedelta(seconds=seconds)
        freezer.move_to(at)
        _vehicle(hass, rig, at, actual=actual, requested=requested)
        _modbus(hass, rig, at, physical_current=physical)
        await rig.controller.async_reconcile(at)
        measured = rig.controller._measured_ev_telemetry(at)
        assert rig.controller.actual_current_a == actual
        assert measured.telemetry_valid
        assert measured.ev_power_kw == pytest.approx(expected_kw)
        assert measured.ev_power_kw != pytest.approx(physical * 0.69) or actual == physical
        assert measured.ev_power_kw + measured.battery_charge_kw == pytest.approx(
            3.43 + (actual - physical) * 0.69
        )


@pytest.mark.parametrize("allowance", [False, True])
async def test_expired_native_current_is_not_free_window_average_or_house_subtraction(
    hass, freezer, allowance,
):
    rig = _morning(hass, freezer)
    _services(hass)
    for key, value in {
        "free_charge_window_start": "16:00:00",
        "ev_free_window_priority": "house_battery",
        "ev_free_window_settle_minutes": 0,
        "ev_allowance_guard_enabled": allowance,
        "house_load_includes_ev": True,
    }.items():
        rig.coordinator.update_config_value(key, value)
    _vehicle(hass, rig, rig.now, actual=4, requested=4)
    _modbus(hass, rig, rig.now, physical_current=4)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.actual_current_a == 4
    later = rig.now + timedelta(seconds=91)
    freezer.move_to(later)
    _modbus(hass, rig, later, physical_current=4)
    await rig.controller.async_reconcile(later)
    assert rig.controller.actual_current_a is None
    assert not rig.controller.ev_average.result(later).source_value_valid
    if allowance:
        # No forecast/subtraction planner remains. An unknown allowance counter
        # takes the ordinary route, without making expired native current valid.
        assert rig.controller.allowance_phase == "outside_free_window"
        assert rig.controller.allowance_house_load_kw is None
        assert rig.controller.allowance_ev_power_kw is None


@pytest.mark.parametrize("fault", ["service", "battery_reserve", "ev_limit"])
async def test_fresh_delayed_current_does_not_postpone_immediate_protection(
    hass, freezer, fault,
):
    rig = _morning(hass, freezer)
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.target_current_a == 4
    later = rig.now + timedelta(seconds=30)
    freezer.move_to(later)
    # Legitimate new native frame still says 0 A during a ramp to requested4 A.
    _vehicle(hass, rig, later, actual=0, requested=4)
    # Without the independent fault this still reconstructs6 A and the solar
    # cadence would retain its existing4 A, so zero cannot be caused by lag alone.
    _modbus(hass, rig, later, physical_current=4, surplus=6.9)
    if fault == "service":
        rig.coordinator.telemetry = replace(
            rig.coordinator.telemetry,
            site_grid_current=replace(rig.coordinator.telemetry.site_grid_current, value=100),
        )
    elif fault == "battery_reserve":
        hass.states.async_set("sensor.site_battery_soc", "19", {"unit_of_measurement": "%"})
        rig.coordinator.snapshot = replace(rig.coordinator.snapshot, battery_soc=19)
    elif fault == "ev_limit":
        hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
        rig.provider.data["charge_state_usable_battery_level"] = 90
    before = len(calls)
    await rig.controller.async_reconcile(later)
    assert rig.controller.target_current_a == 0
    assert any(call[:2] == ("switch", "turn_off") for call in calls[before:])


async def test_import_reduction_is_immediate_despite_fresh_actual_current_lag(hass, freezer):
    rig = _morning(hass, freezer)
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.target_current_a == 4
    later = rig.now + timedelta(seconds=30)
    freezer.move_to(later)
    _vehicle(hass, rig, later, actual=3, requested=4)
    _modbus(hass, rig, later, physical_current=4, surplus=3.43, grid=2)
    # Actual3 A plus fresh battery/grid reconstructs2.74 kW, i.e.3 A. Import
    # must bypass the ordinary ten-minute solar adjustment hold for that drop.
    await rig.controller.async_reconcile(later)
    assert rig.controller.target_current_a == 3
    assert rig.controller.actual_current_a == 3
    assert ("number", "set_value", {"entity_id": "number.car_current", "value": 3}) in calls


async def test_morning_to_free_uses_free_authority_not_expired_solar_owner(hass, freezer):
    rig = _morning(hass, freezer)
    rig.coordinator.update_config_value("free_charge_window_start", "16:11:00")
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.target_current_a == 4
    _vehicle(hass, rig, rig.now, actual=4, requested=4)
    later = rig.now + timedelta(seconds=91)
    freezer.move_to(later)
    _modbus(hass, rig, later, physical_current=4)
    before = len(calls)
    await rig.controller.async_reconcile(later)
    assert rig.controller.policy_route.route == "free_window"
    assert rig.controller.decision_phase == "ev_priority_maximum"
    assert rig.controller.target_current_a == 16
    assert rig.controller.actual_current_a is None
    assert not any(call[:2] == ("switch", "turn_off") for call in calls[before:])


@pytest.mark.parametrize("pre_free", [False, True])
@pytest.mark.parametrize("actual", [0, 3, 4])
@pytest.mark.parametrize("service_current", [77.999, 78, 78.001, 79, 80, 80.001])
async def test_morning_target_obeys_current_service_envelope_at_supported_boundaries(
    hass, freezer, pre_free, actual, service_current,
):
    rig = _morning(hass, freezer)
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.target_current_a == 4
    later = rig.now + timedelta(seconds=30)
    freezer.move_to(later)
    _vehicle(hass, rig, later, actual=actual, requested=4)
    _modbus(hass, rig, later, physical_current=4, surplus=6.9)
    rig.coordinator.telemetry = replace(
        rig.coordinator.telemetry,
        site_grid_current=replace(
            rig.coordinator.telemetry.site_grid_current, value=service_current,
        ),
    )
    rig.coordinator.update_config_value("ev_pre_free_backfill_enabled", pre_free)
    # The optional pre-free policy has no battery allocation. Its solar-only
    # successor must obey the same cap as standalone morning capture.
    rig.coordinator.active_controller.export_plan = ExportPlan(0, 0, 0, "no_protected_energy")
    before = len(calls)
    await rig.controller.async_reconcile(later)
    expected = min(4, floor(max(80 - 1 - service_current + actual, 0)))
    assert rig.controller.target_current_a == expected
    assert rig.controller.actual_current_a == actual
    assert not rig.controller.pre_free_session.active
    if expected == 0:
        assert any(call[:2] == ("switch", "turn_off") for call in calls[before:])
    elif expected < 4:
        assert ("number", "set_value", {
            "entity_id": "number.car_current", "value": expected,
        }) in calls[before:]


async def test_morning_positive_commands_recheck_vehicle_source_after_awaited_service(
    hass, freezer,
):
    rig = _morning(hass, freezer)
    calls = []

    async def accept(call):
        calls.append((call.domain, call.service, dict(call.data)))
        if call.data.get("entity_id") == "number.car_limit":
            rig.provider.last_update_success = False

    for domain, service in (("number", "set_value"), ("switch", "turn_on"),
                            ("switch", "turn_off")):
        hass.services.async_register(domain, service, accept)
    await rig.controller.async_reconcile(rig.now)
    assert calls and calls[0][2]["entity_id"] == "number.car_limit"
    assert not _above_baseline(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("change", ["provider_failed", "expired_during_save",
                                  "new_actual_frame", "unchanged_new_frame"])
async def test_matching_owned_solar_rechecks_measurement_after_checkpoint(
    hass, freezer, monkeypatch, change,
):
    rig = _morning(hass, freezer)
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.target_current_a == 4
    _vehicle(hass, rig, rig.now, actual=4, requested=4)
    _modbus(hass, rig, rig.now, physical_current=4)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.reconciliation.phase == "confirmed"
    at = rig.now + timedelta(seconds=30)
    freezer.move_to(at)
    _vehicle(hass, rig, at, actual=4, requested=4)
    _modbus(hass, rig, at, physical_current=4)
    original_save = rig.controller._async_save
    saved = False

    async def save_with_publication(when=None):
        nonlocal saved
        if not saved:
            saved = True
            await asyncio.sleep(0)
            later = at + timedelta(seconds=91 if change == "expired_during_save" else 1)
            freezer.move_to(later)
            if change == "provider_failed":
                rig.provider.last_update_success = False
            elif change in {"new_actual_frame", "unchanged_new_frame"}:
                _vehicle(hass, rig, later, actual=3 if change == "new_actual_frame" else 4,
                         requested=4)
            _modbus(hass, rig, later, physical_current=3 if change == "new_actual_frame" else 4)
        await original_save(when)

    monkeypatch.setattr(rig.controller, "_async_save", save_with_publication)
    before = len(calls)
    await rig.controller.async_reconcile(at)
    assert saved
    invalid = change in {"provider_failed", "expired_during_save"}
    assert rig.controller.target_current_a == (0 if invalid else 4)
    assert any(call[:2] == ("switch", "turn_off") for call in calls[before:]) is invalid
    if invalid:
        assert rig.controller.daily_backfill_stop_pending
        assert not _above_baseline(calls[before:])
    else:
        assert calls[before:] == []
        assert rig.controller._actual_ev_current_a() == (
            3 if change == "new_actual_frame" else 4, True,
        )


@pytest.mark.parametrize("change", [
    "service", "battery_negative", "battery_over_100", "battery_unknown",
    "vehicle_negative", "vehicle_over_100", "vehicle_unknown", "step_zero",
    "step_negative", "step_nan", "morning_reserve", "morning_threshold_edit",
    "morning_disabled", "morning_threshold_invalid", "boosted_spill",
])
async def test_solar_command_boundary_uses_live_valid_policy_and_electrical_envelope(
    hass, freezer, change,
):
    rig = _morning(hass, freezer, spill=change == "boosted_spill")
    if change == "morning_reserve":
        rig.coordinator.update_config_value("ev_morning_solar_reserve_soc_percent", 50)
    calls = []

    async def accept(call):
        calls.append((call.domain, call.service, dict(call.data)))
        if call.data.get("entity_id") != "number.car_limit":
            return
        if change == "service":
            rig.coordinator.telemetry = replace(
                rig.coordinator.telemetry,
                site_grid_current=replace(rig.coordinator.telemetry.site_grid_current, value=100),
            )
        elif change.startswith("battery_") or change in {"morning_reserve",
                                                        "morning_threshold_edit"}:
            value = {
                "battery_negative": "-1", "battery_over_100": "101",
                "battery_unknown": "unknown", "morning_reserve": "30",
                "morning_threshold_edit": "30",
            }[change]
            hass.states.async_set("sensor.site_battery_soc", value, {"unit_of_measurement": "%"})
            if change == "morning_threshold_edit":
                rig.coordinator.update_config_value("ev_morning_solar_reserve_soc_percent", 50)
        elif change.startswith("vehicle_"):
            hass.states.async_set("sensor.car_soc", {
                "vehicle_negative": "-1", "vehicle_over_100": "101",
                "vehicle_unknown": "unknown",
            }[change], {"unit_of_measurement": "%"})
        elif change.startswith("step_"):
            old = hass.states.get("number.car_current")
            hass.states.async_set(old.entity_id, old.state, {**old.attributes, "step": {
                "step_zero": 0, "step_negative": -1, "step_nan": float("nan"),
            }[change]})
        elif change == "morning_disabled":
            rig.coordinator.update_config_value("ev_morning_solar_enabled", False)
        elif change == "morning_threshold_invalid":
            rig.coordinator.update_config_value("ev_morning_solar_reserve_soc_percent", 101)
        elif change == "boosted_spill":
            rig.coordinator.update_config_value("bonus_window_start", "16:00:00")
            rig.coordinator.update_config_value("bonus_window_end", "16:59:00")

    for domain, service in (("number", "set_value"), ("switch", "turn_on"),
                            ("switch", "turn_off")):
        hass.services.async_register(domain, service, accept)
    await rig.controller.async_reconcile(rig.now)
    assert calls and calls[0][2]["entity_id"] == "number.car_limit"
    assert not _above_baseline(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("battery_soc,allowed", [(49.999, False), (50, True), (50.001, True)])
async def test_command_boundary_honors_selected_morning_reserve_not_lower_outside_floor(
    hass, freezer, battery_soc, allowed,
):
    rig = _morning(hass, freezer)
    rig.coordinator.update_config_value("ev_morning_solar_reserve_soc_percent", 50)
    assert rig.coordinator.config["ev_outside_battery_reserve_percent"] == 20
    calls = []

    async def accept(call):
        calls.append((call.domain, call.service, dict(call.data)))
        if call.data.get("entity_id") == "number.car_limit":
            hass.states.async_set("sensor.site_battery_soc", str(battery_soc),
                                  {"unit_of_measurement": "%"})

    for domain, service in (("number", "set_value"), ("switch", "turn_on"),
                            ("switch", "turn_off")):
        hass.services.async_register(domain, service, accept)
    await rig.controller.async_reconcile(rig.now)
    assert bool(_above_baseline(calls)) is allowed
    assert any(call[:2] == ("switch", "turn_on") for call in calls) is allowed


@pytest.mark.parametrize("phase_count", [1, 3])
@pytest.mark.parametrize("fault", [None, "expired", "asleep", "publisher_failed"])
async def test_house_learner_subtracts_only_the_shared_native_actual_measurement(
    hass, freezer, phase_count, fault,
):
    rig = _morning(hass, freezer)
    _vehicle(hass, rig, rig.now, actual=8, requested=8)
    config = {**rig.coordinator.config, "house_load_includes_ev": True,
              "ev_phase_count": phase_count, "site_phase_count": 3}
    coordinator = EnergyCoordinator(hass, config, "native-learning-current-test")
    coordinator.snapshot = replace(rig.coordinator.snapshot, house_load_kw=6)
    if fault == "expired":
        rig.provider.data["charge_state_timestamp"] -= 90_001
    elif fault == "asleep":
        rig.provider.data["state"] = "asleep"
    elif fault == "publisher_failed":
        rig.provider.last_update_success = False
    try:
        power = coordinator._state_qualified_ev_power_kw(rig.now)
        house = coordinator._protected_house_learning_power_kw(rig.now)
        if fault is not None:
            assert power is None and house is None
        else:
            assert power == pytest.approx(8 * 230 * phase_count / 1000)
            assert house == pytest.approx(6 - power)
    finally:
        coordinator.shutdown()


@pytest.mark.parametrize(("age_seconds", "max_hours", "accepted"), [
    (90, None, True),
    (12 * 3600, None, True),
    (24 * 3600, None, True),
    (24 * 3600 + 0.001, None, False),
    (-0.001, None, False),
    (2 * 3600, 2, True),
    (2 * 3600 + 0.001, 2, False),
    (90, 0, False),
])
async def test_house_learner_uses_only_bounded_asleep_disconnected_evidence(
    hass, freezer, age_seconds, max_hours, accepted,
):
    rig = _morning(hass, freezer)
    _asleep_unplugged(hass, rig, rig.now - timedelta(seconds=age_seconds))
    changes = {} if max_hours is None else {"ev_reservation_soc_max_age_hours": max_hours}
    coordinator = _house_learner(hass, rig, **changes)
    try:
        assert coordinator._protected_house_learning_power_kw(rig.now) == (
            6 if accepted else None
        )
        feedback = capture_ev_feedback(hass, ev_observation_entity_map(coordinator.runtime_config))
        assert not measure_ev_current(hass, feedback, now=rig.now, max_age_seconds=90).valid
    finally:
        coordinator.shutdown()


@pytest.mark.parametrize("state", ["Stopped", "Complete", "NoPower"])
async def test_house_learner_rejects_retained_plugged_zero_but_keeps_fresh_zero(
    hass, freezer, state,
):
    rig = _morning(hass, freezer)
    _vehicle(hass, rig, rig.now, actual=0, requested=6, charging=False)
    rig.provider.data["charge_state_charging_state"] = state
    reported_state = "no_power" if state == "NoPower" else state.lower()
    hass.states.async_set("sensor.car_charging", reported_state)
    coordinator = _house_learner(hass, rig)
    try:
        assert coordinator._protected_house_learning_power_kw(rig.now) == 6
        rig.provider.data["state"] = "asleep"
        assert coordinator._protected_house_learning_power_kw(rig.now) is None
    finally:
        coordinator.shutdown()


@pytest.mark.parametrize("fault", [
    "offline", "failed_provider", "missing_clock", "bool_current",
    "reconnected", "local_connection_on", "switch_on", "restored_cable",
    "restored_charging", "restored_current", "wrong_cable_binding",
])
async def test_house_learner_rejects_unsafe_asleep_disconnected_evidence(hass, freezer, fault):
    rig = _morning(hass, freezer)
    _asleep_unplugged(hass, rig, rig.now - timedelta(hours=2))
    data = rig.provider.data
    changes = {}
    if fault == "offline":
        data["state"] = "offline"
    elif fault == "failed_provider":
        rig.provider.last_update_success = False
    elif fault == "missing_clock":
        data.pop("charge_state_timestamp")
    elif fault == "bool_current":
        data["charge_state_charger_actual_current"] = False
    elif fault == "reconnected":
        hass.states.async_set("binary_sensor.car_cable", "on")
    elif fault == "local_connection_on":
        changes["ev_local_connection_entity"] = "binary_sensor.local_cable"
        hass.states.async_set("binary_sensor.local_cable", "on")
    elif fault == "switch_on":
        hass.states.async_set("switch.car_charge", "on")
    elif fault.startswith("restored_"):
        entity_id = {
            "restored_cable": "binary_sensor.car_cable",
            "restored_charging": "sensor.car_charging",
            "restored_current": "sensor.car_actual_current",
        }[fault]
        entity = hass.states.get(entity_id)
        hass.states.async_set(entity_id, entity.state, {**entity.attributes, "restored": True})
    elif fault == "wrong_cable_binding":
        er.async_get(hass).async_update_entity("binary_sensor.car_cable", device_id=None)
    coordinator = _house_learner(hass, rig, **changes)
    try:
        assert coordinator._protected_house_learning_power_kw(rig.now) is None
    finally:
        coordinator.shutdown()


@pytest.mark.parametrize("provider_state", ["online", "asleep"])
@pytest.mark.parametrize("retained_current", [0, 1, 3])
async def test_learning_unplugged_zero_ignores_retained_amps_without_granting_live_authority(
    hass, freezer, provider_state, retained_current,
):
    rig = _morning(hass, freezer)
    measured_at = rig.now - timedelta(hours=2)
    _asleep_unplugged(hass, rig, measured_at)
    rig.provider.data.update({
        "state": provider_state,
        "charge_state_charger_actual_current": retained_current,
    })
    hass.states.async_set(
        "sensor.car_actual_current", str(retained_current), {"unit_of_measurement": "A"},
    )
    # House learning has no reason to require a vehicle SoC when disconnected.
    hass.states.async_set("sensor.car_soc", "unavailable")
    coordinator = _house_learner(hass, rig)
    try:
        assert coordinator._protected_house_learning_power_kw(rig.now) == 6
        assert rig.provider.data["charge_state_timestamp"] == measured_at.timestamp() * 1000
        feedback = capture_ev_feedback(hass, ev_observation_entity_map(coordinator.runtime_config))
        assert not measure_ev_current(hass, feedback, now=rig.now, max_age_seconds=90).valid
        rig.provider.data["charge_state_timestamp"] = (
            rig.now - timedelta(hours=24, milliseconds=1)
        ).timestamp() * 1000
        assert coordinator._protected_house_learning_power_kw(rig.now) is None
    finally:
        coordinator.shutdown()


async def test_house_learner_completes_daily_cycle_with_asleep_unplugged_vehicle(
    hass, freezer, monkeypatch,
):
    rig = _morning(hass, freezer)
    start = rig.now.replace(hour=17, minute=0)
    freezer.move_to(start)
    _asleep_unplugged(hass, rig, start)
    coordinator = _house_learner(hass, rig)
    monkeypatch.setattr(coordinator, "_async_save_demand_state", AsyncMock())
    try:
        for minute in range(0, 24 * 60 + 1, 9):
            freezer.move_to(start + timedelta(minutes=minute))
            await coordinator._async_sample_house_load()
        (sample,) = coordinator.demand_history.samples
        assert sample.observed_at == start + timedelta(days=1)
        assert sample.energy_kwh == pytest.approx(6 * (24 - 59 / 60))
    finally:
        coordinator.shutdown()
