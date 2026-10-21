"""EV-before-export runtime, protected-energy and physical-handoff regressions.

All observations are local synthetic states. No helper under test is mocked and
no provider, vehicle, inverter or live installation is contacted.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.planner.charge_session import ChargeSessionState
from custom_components.home_energy_orchestrator.planner.export import ExportPlan
from custom_components.home_energy_orchestrator.planner.export_session import ExportSessionState
from tests.test_ev_backfill_timing import _charging, _fresh, _services, _site
from tests.test_zerohero_active import _loaded_controller


@pytest.fixture(autouse=True)
def utc_clock(monkeypatch):
    """Synthetic tariff times and adapter rechecks must share one timezone."""
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime.now(UTC),
    )


def _now(hour=18, minute=10):
    return datetime(2026, 9, 7, hour, minute, tzinfo=UTC)


def _foxess(hass, *, mode="Self Use", charge=0, discharge=0):
    hass.states.async_set(
        "select.foxess_mode",
        mode,
        {"options": ["Self Use", "Force Charge", "Force Discharge"]},
    )
    for entity, value in (("number.foxess_charge", charge), ("number.foxess_discharge", discharge)):
        hass.states.async_set(
            entity, str(value), {"min": 0, "max": 15, "step": 0.1, "unit_of_measurement": "kW"}
        )


def _case(hass, now, **changes):
    config = dict(
        ev_before_export_enabled=True,
        ev_before_export_soc_target_percent=30,
        ev_before_export_soc_buffer_percent=0,  # Characterise the pre-buffer policy.
        ev_pre_free_backfill_enabled=False,
        ev_pre_free_backfill_timing="conservative",
        ev_morning_solar_enabled=False,
        ev_solar_spill_enabled=False,
        ev_daily_backfill_energy_kwh=0,
        ev_protected_baseline_a=0,
        ev_capacity_source="configured",
        ev_capacity_fallback_kwh=60,
        foxess_work_mode_entity="select.foxess_mode",
        foxess_force_charge_power_entity="number.foxess_charge",
        foxess_force_discharge_power_entity="number.foxess_discharge",
        grid_power_entity="sensor.site_grid",
        battery_power_entity="sensor.battery_power",
        house_load_entity="sensor.house",
        battery_soc_entity="sensor.site_battery_soc",
        automatic_export_enabled=True,
        automatic_charge_enabled=False,
        bonus_window_start="18:00:00",
        bonus_window_end="21:00:00",
        force_discharge_finish="21:01:00",
        automatic_export_limit_kwh=30,
        configure_solar=False,
    )
    config.update(changes)
    coordinator, controller = _site(hass, **config)
    coordinator.ev_controller = controller
    coordinator.snapshot = replace(
        coordinator.snapshot,
        ev_soc=25,
        grid_power_kw=0,
        house_load_kw=0.2,
    )
    coordinator.data = SimpleNamespace(
        available_after_reserve_kwh=24,
        daily_export_kwh=0,
        paid_export_kwh=0,
        free_energy_remaining_kwh=50,
    )
    coordinator.zerohero_export = SimpleNamespace(imported_kwh=0)
    coordinator._free_window_hours_remaining = lambda at: (
        controller._free_window(at)[2] if controller._free_window(at)[0] else 0
    )
    coordinator.manual_test = SimpleNamespace(
        is_active=False, active_kind=None, storage_status="valid"
    )
    coordinator.active_controller.charge_session = ChargeSessionState()
    coordinator.active_controller.export_protected_ev_kwh = 0
    coordinator.active_controller.manual = SimpleNamespace(is_active=False)
    _foxess(hass)
    _fresh(coordinator, now)
    hass.states.async_set("sensor.site_grid", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.battery_power", "-0.2", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.house", "0.2", {"unit_of_measurement": "kW"})
    return coordinator, controller


def _above_baseline(calls, baseline=0):
    return [
        call
        for call in calls
        if call[0:2] == ("number", "set_value")
        and call[2].get("entity_id") == "number.car_current"
        and call[2].get("value", 0) > baseline
    ]


@pytest.mark.parametrize("hour", [0, 5, 10, 16, 18, 22])
async def test_spare_energy_top_up_does_not_wait_for_solar_or_a_deadline(hass, freezer, hour):
    now = _now(hour)
    freezer.move_to(now)
    calls = _services(hass)
    _, controller = _case(hass, now)
    await controller.async_reconcile(now)
    assert controller.decision_phase == "ev_before_export_charging"
    assert controller.target_current_a == 8  # 40% of 15 kW / (230 V * 3), rounded down.
    assert ("switch", "turn_on", {"entity_id": "switch.car_charge"}) in calls
    assert not controller.daily_backfill_active
    assert not controller.pre_free_session.active


async def test_paid_export_cap_is_not_an_ev_spare_energy_cap(hass, freezer):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now)
    coordinator.active_controller.export_plan = ExportPlan(19, 0, 0, "no_protected_energy")
    coordinator.data.daily_export_kwh = 30
    coordinator.data.paid_export_kwh = 30
    await controller.async_reconcile(now)
    assert controller.decision_phase == "ev_before_export_charging"
    assert _above_baseline(calls)


@pytest.mark.parametrize("baseline", [0, 1])
async def test_disabled_option_does_not_create_a_new_charging_owner(hass, freezer, baseline):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    _, controller = _case(
        hass, now, ev_before_export_enabled=False, ev_protected_baseline_a=baseline
    )
    await controller.async_reconcile(now)
    assert controller.decision_phase != "ev_before_export_charging"
    assert not _above_baseline(calls, baseline)


@pytest.mark.parametrize("soc", [30, 31, 90])
async def test_equal_or_above_threshold_does_not_start_the_top_up(hass, freezer, soc):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    _, controller = _case(hass, now)
    hass.states.async_set("sensor.car_soc", str(soc), {"unit_of_measurement": "%"})
    await controller.async_reconcile(now)
    assert controller.decision_phase != "ev_before_export_charging"
    assert not _above_baseline(calls)


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"ev_phase_count": 1, "site_phase_count": 1, "ev_max_current": 15}, 15),
        ({"ev_phase_count": 3, "ev_outside_inverter_percent": 25}, 5),
        (
            {
                "ev_phase_count": 3,
                "inverter_discharge_limit_kw": 6,
                "ev_outside_inverter_percent": 50,
            },
            4,
        ),
    ],
)
async def test_total_current_respects_connector_and_inverter_percentage(
    hass, freezer, changes, expected
):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    _, controller = _case(hass, now, **changes)
    await controller.async_reconcile(now)
    assert controller.decision_phase == "ev_before_export_charging"
    assert controller.target_current_a == expected


@pytest.mark.parametrize(
    "failure",
    [
        "sellable_zero",
        "plan_missing",
        "protected_missing",
        "available_missing",
        "house_stale",
        "grid_stale",
        "battery_stale",
        "grid_import",
        "force_charge",
        "force_discharge",
        "charge_target",
        "discharge_target",
        "export_session",
        "charge_session",
        "manual",
        "diagnostic",
    ],
)
async def test_failed_authority_cannot_start_top_up_or_fall_into_pre_free_battery(
    hass, freezer, failure
):
    now = _now(10, 59)
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now, ev_pre_free_backfill_enabled=True)
    if failure == "sellable_zero":
        coordinator.active_controller.export_plan = ExportPlan(0, 0, 0, "no_protected_energy")
    elif failure == "plan_missing":
        coordinator.active_controller.export_plan = None
    elif failure == "protected_missing":
        coordinator.learning_remaining_kwh = None
    elif failure == "available_missing":
        coordinator.data.available_after_reserve_kwh = None
    elif failure.endswith("_stale"):
        field = {
            "house_stale": "house_load",
            "grid_stale": "grid_power",
            "battery_stale": "battery_power",
        }[failure]
        sample = getattr(coordinator.telemetry, field)
        stale = replace(
            sample,
            fresh=False,
            reason="stale",
            sources=tuple(
                replace(source, updated_at=now - timedelta(seconds=180))
                for source in sample.sources
            ),
        )
        coordinator.telemetry = replace(coordinator.telemetry, **{field: stale})
    elif failure == "grid_import":
        _fresh(coordinator, now, grid_kw=2)
    elif failure in {"force_charge", "force_discharge"}:
        _foxess(hass, mode="Force Charge" if failure == "force_charge" else "Force Discharge")
    elif failure == "charge_target":
        _foxess(hass, charge=3)
    elif failure == "discharge_target":
        _foxess(hass, discharge=3)
    elif failure == "export_session":
        coordinator.active_controller.export_session = ExportSessionState("stopping", 10)
    elif failure == "charge_session":
        coordinator.active_controller.charge_session = ChargeSessionState("active", 10)
    elif failure == "manual":
        coordinator.active_controller.manual.is_active = True
    elif failure == "diagnostic":
        coordinator.manual_test.is_active = True
    await controller.async_reconcile(now)
    assert controller.decision_phase != "ev_before_export_charging"
    assert not _above_baseline(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize(
    "changes",
    [
        {"ev_automatic_control_enabled": False},
        {"rehearsal_mode": True},
        {"sign_conventions_verified": False},
        {"foxess_control_owner": "foxcloud_scheduler"},
    ],
)
async def test_closed_write_gates_never_start_an_ev(hass, freezer, changes):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    _, controller = _case(hass, now, **changes)
    await controller.async_reconcile(now)
    assert not _above_baseline(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("baseline", [0, 1])
async def test_live_budget_exhaustion_withdraws_top_up_on_the_next_cycle(hass, freezer, baseline):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now, ev_protected_baseline_a=baseline)
    await controller.async_reconcile(now)
    assert controller.decision_phase == "ev_before_export_charging"
    now += timedelta(seconds=30)
    freezer.move_to(now)
    _charging(hass, 8)
    _fresh(coordinator, now, current_a=8)
    coordinator.active_controller.export_plan = ExportPlan(0, 0, 0, "no_protected_energy")
    calls.clear()
    await controller.async_reconcile(now)
    assert controller.target_current_a <= baseline
    if baseline == 0:
        assert any(call[:2] == ("switch", "turn_off") for call in calls)
    else:
        assert _above_baseline(calls, 0)
        assert not _above_baseline(calls, baseline)


async def test_top_up_does_not_activate_or_credit_the_waiting_daily_allocation(hass, freezer):
    now = _now(1)
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _case(hass, now, ev_daily_backfill_energy_kwh=2)
    await controller.async_reconcile(now)
    assert controller.decision_phase == "ev_before_export_charging"
    assert not controller.daily_backfill_active
    before = controller.daily_backfill_delivered_kwh
    now += timedelta(seconds=30)
    freezer.move_to(now)
    _charging(hass, 8)
    _fresh(coordinator, now, current_a=8)
    await controller.async_reconcile(now)
    assert not controller.daily_backfill_active
    assert controller.daily_backfill_delivered_kwh == before


async def test_free_window_keeps_its_independent_priority(hass, freezer):
    now = _now(12, 2)
    freezer.move_to(now)
    _services(hass)
    _, controller = _case(hass, now)
    await controller.async_reconcile(now)
    assert controller.policy_route.route == "free_window"
    assert controller.decision_phase != "ev_before_export_charging"


async def test_full_request_keeps_its_explicit_paid_override(hass, freezer):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    _, controller = _case(hass, now, ev_charge_to_full_enabled=True)
    await controller.async_reconcile(now)
    assert controller.decision_phase == "charge_to_full_paid_grid_override"
    assert controller.target_current_a == 16


@pytest.mark.parametrize("soc", [20, 19])
async def test_outside_battery_reserve_is_still_inclusive(hass, freezer, soc):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now)
    hass.states.async_set("sensor.site_battery_soc", str(soc), {"unit_of_measurement": "%"})
    coordinator.snapshot = replace(coordinator.snapshot, battery_soc=soc)
    await controller.async_reconcile(now)
    assert not _above_baseline(calls)
    assert controller.decision_phase != "ev_before_export_charging"


async def test_disconnect_and_reconnect_replans_without_commands_while_away(hass, freezer):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now)
    await controller.async_reconcile(now)
    now += timedelta(seconds=30)
    freezer.move_to(now)
    hass.states.async_set("device_tracker.car", "not_home")
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("sensor.car_charging", "disconnected")
    hass.states.async_set("switch.car_charge", "off")
    _fresh(coordinator, now)
    calls.clear()
    await controller.async_reconcile(now)
    assert calls == []
    now += timedelta(seconds=30)
    freezer.move_to(now)
    hass.states.async_set("device_tracker.car", "home")
    hass.states.async_set("binary_sensor.car_cable", "on")
    hass.states.async_set("sensor.car_charging", "stopped")
    _fresh(coordinator, now)
    await controller.async_reconcile(now)
    assert controller.decision_phase == "ev_before_export_charging"
    assert any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("ev_runs_first", [True, False])
async def test_export_waits_for_physical_baseline_after_threshold_crossing(
    hass, freezer, monkeypatch, ev_runs_first
):
    now = _now(20, 55)
    freezer.move_to(now)
    calls = _services(hass)

    async def record_mode(call):
        calls.append((call.domain, call.service, dict(call.data)))

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep",
        no_wait,
    )
    hass.services.async_register("select", "select_option", record_mode)
    coordinator, ev = _case(hass, now, ev_protected_baseline_a=1)
    await ev.async_reconcile(now)
    assert ev.decision_phase == "ev_before_export_charging"
    fox = _loaded_controller(hass, coordinator)
    coordinator.active_controller = fox
    now += timedelta(seconds=30)
    freezer.move_to(now)
    _charging(hass, 8)
    hass.states.async_set("sensor.car_soc", "30", {"unit_of_measurement": "%"})
    coordinator.snapshot = replace(coordinator.snapshot, ev_soc=30)
    _fresh(coordinator, now, current_a=8)
    calls.clear()
    if ev_runs_first:
        await ev.async_reconcile(now)
        await fox.async_reconcile()
    else:
        await fox.async_reconcile()
        await ev.async_reconcile(now)
    assert not any(call[2].get("option") == "Force Discharge" for call in calls)
    assert fox.export_session.phase == "idle"
    # A new EV process has no transient selected-stage flag. It must not make
    # physical 8 A disappear or permit the inverter to race its startup restore.
    coordinator.ev_controller = ActiveEvController(hass, coordinator)
    calls.clear()
    await fox.async_reconcile()
    assert not any(call[2].get("option") == "Force Discharge" for call in calls)
    assert fox.export_session.phase == "idle"
    # Prove that the preceding absence of export was not an ineligible plan:
    # after the EV actually reaches the protected baseline, the same evening
    # and protected energy permit the ordinary fixed-power export again.
    now += timedelta(seconds=30)
    freezer.move_to(now)
    _charging(hass, 1)
    _fresh(coordinator, now, current_a=1)
    calls.clear()
    await fox.async_reconcile()
    assert any(call[2].get("option") == "Force Discharge" for call in calls)


@pytest.mark.parametrize("soc", ["unknown", "nan", "101"])
async def test_invalid_vehicle_soc_is_not_permission_to_charge(hass, freezer, soc):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    _, controller = _case(hass, now)
    hass.states.async_set("sensor.car_soc", soc, {"unit_of_measurement": "%"})
    await controller.async_reconcile(now)
    assert not _above_baseline(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize(
    "failure",
    [
        "restored_limit",
        "wrong_current_unit",
        "actual_missing",
        "actual_negative",
        "stale_home",
        "stale_cable",
        "stale_limit",
        "future_home",
        "future_cable",
        "future_limit",
    ],
)
async def test_native_ev_cohort_must_be_valid_and_fresh(hass, freezer, failure):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now)
    if failure == "restored_limit":
        state = hass.states.get("number.car_limit")
        hass.states.async_set(state.entity_id, state.state, {**state.attributes, "restored": True})
    elif failure == "wrong_current_unit":
        state = hass.states.get("number.car_current")
        hass.states.async_set(
            state.entity_id,
            state.state,
            {**state.attributes, "unit_of_measurement": "kW"},
        )
    elif failure == "actual_missing":
        hass.states.async_remove("sensor.car_actual_current")
    elif failure == "actual_negative":
        hass.states.async_set("sensor.car_actual_current", "-1", {"unit_of_measurement": "A"})
    else:
        kind, name = failure.split("_")
        entity = {
            "home": "device_tracker.car",
            "cable": "binary_sensor.car_cable",
            "limit": "number.car_limit",
        }[name]
        if kind == "future":
            state = hass.states.get(entity)
            freezer.move_to(now + timedelta(seconds=91))
            hass.states.async_set(entity, state.state, dict(state.attributes), force_update=True)
            freezer.move_to(now)
        else:
            now += timedelta(seconds=91)
            freezer.move_to(now)
            for state in hass.states.async_all():
                if state.entity_id != entity:
                    hass.states.async_set(
                        state.entity_id,
                        state.state,
                        dict(state.attributes),
                        force_update=True,
                    )
            _fresh(coordinator, now)
    await controller.async_reconcile(now)
    assert not _above_baseline(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("loss", ["battery_cutoff", "policy_off", "house_source", "budget"])
async def test_authority_is_rechecked_after_each_awaited_positive_command(hass, freezer, loss):
    now = _now()
    freezer.move_to(now)
    coordinator, controller = _case(hass, now, ev_outside_battery_reserve_percent=75)
    calls = []

    async def record_and_remove_permission(call):
        calls.append((call.domain, call.service, dict(call.data)))
        if call.data.get("entity_id") != "number.car_limit":
            return
        if loss == "battery_cutoff":
            hass.states.async_set("sensor.site_battery_soc", "74", {"unit_of_measurement": "%"})
            coordinator.snapshot = replace(coordinator.snapshot, battery_soc=74)
        elif loss == "policy_off":
            coordinator.update_config_value("ev_before_export_enabled", False)
        elif loss == "house_source":
            coordinator.telemetry = replace(
                coordinator.telemetry,
                house_load=replace(coordinator.telemetry.house_load, fresh=False),
            )
        else:
            coordinator.active_controller.export_plan = ExportPlan(0, 0, 0, "no_protected_energy")

    hass.services.async_register("number", "set_value", record_and_remove_permission)
    hass.services.async_register("switch", "turn_on", record_and_remove_permission)
    hass.services.async_register("switch", "turn_off", record_and_remove_permission)
    await controller.async_reconcile(now)
    assert calls
    assert calls[0][2]["entity_id"] == "number.car_limit"
    assert not _above_baseline(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


async def test_live_keepalive_protection_overrules_older_zero_cached_reservation(hass, freezer):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now, ev_protected_baseline_a=1)
    coordinator.data.available_after_reserve_kwh = 3
    coordinator.learning_remaining_kwh = 0
    coordinator.active_controller.export_protected_ev_kwh = 0
    coordinator.active_controller.export_plan = ExportPlan(10, 10, 1, "ready")
    await controller.async_reconcile(now)
    assert controller.target_current_a <= 1
    assert not _above_baseline(calls, 1)


async def test_opt_in_does_not_add_unstoppable_smart_socket_top_up(hass, freezer):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    _, controller = _case(
        hass,
        now,
        ev_charge_path="smart_socket",
        ev_smart_socket_entity="switch.car_socket",
        ev_smart_socket_current_limit_a=10,
        ev_smart_socket_settle_seconds=0,
    )
    hass.states.async_set("switch.car_socket", "on")
    await controller.async_reconcile(now)
    assert controller.decision_phase != "ev_before_export_charging"
    assert not _above_baseline(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


async def test_restored_top_up_at_met_target_reduces_instead_of_resuming(hass, freezer):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, original = _case(hass, now)
    await original.async_reconcile(now)
    assert original.decision_phase == "ev_before_export_charging"
    await original._async_save(now)
    now += timedelta(seconds=30)
    freezer.move_to(now)
    _charging(hass, 8)
    _fresh(coordinator, now, current_a=8)
    hass.states.async_set("sensor.car_soc", "30", {"unit_of_measurement": "%"})
    restored = ActiveEvController(hass, coordinator)
    coordinator.ev_controller = restored
    await restored._async_restore()
    calls.clear()
    await restored.async_reconcile(now)
    assert restored.target_current_a == 0
    assert not _above_baseline(calls)
    assert any(call[:2] == ("switch", "turn_off") for call in calls)


async def test_restored_top_up_waits_through_unplug_and_resumes_only_freshly_connected(
    hass, freezer
):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, original = _case(hass, now)
    await original.async_reconcile(now)
    await original._async_save(now)
    restored = ActiveEvController(hass, coordinator)
    coordinator.ev_controller = restored
    await restored._async_restore()
    now += timedelta(seconds=30)
    freezer.move_to(now)
    hass.states.async_set("device_tracker.car", "not_home")
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("sensor.car_charging", "disconnected")
    hass.states.async_set("switch.car_charge", "off")
    _fresh(coordinator, now)
    calls.clear()
    await restored.async_reconcile(now)
    assert calls == []
    now += timedelta(seconds=30)
    freezer.move_to(now)
    hass.states.async_set("device_tracker.car", "home")
    hass.states.async_set("binary_sensor.car_cable", "on")
    hass.states.async_set("sensor.car_charging", "stopped")
    _fresh(coordinator, now)
    await restored.async_reconcile(now)
    assert restored.decision_phase == "ev_before_export_charging"
    assert any(call[:2] == ("switch", "turn_on") for call in calls)


async def test_restored_top_up_cannot_bypass_safety_lock_or_lost_source(hass, freezer):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, original = _case(hass, now)
    await original.async_reconcile(now)
    await original._async_save(now)
    restored = ActiveEvController(hass, coordinator)
    coordinator.ev_controller = restored
    await restored._async_restore()
    now += timedelta(seconds=30)
    freezer.move_to(now)
    _fresh(coordinator, now)
    coordinator.update_config_value("rehearsal_mode", True)
    calls.clear()
    await restored.async_reconcile(now)
    assert calls == []
    coordinator.update_config_value("rehearsal_mode", False)
    coordinator.telemetry = replace(
        coordinator.telemetry,
        house_load=replace(coordinator.telemetry.house_load, fresh=False),
    )
    await restored.async_reconcile(now)
    assert not _above_baseline(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("stored", ["unavailable", "-2", "0"])
async def test_lost_legacy_capacity_returns_an_owned_topup_to_stop(hass, freezer, stored):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _case(hass, now)
    await controller.async_reconcile(now)
    now += timedelta(seconds=30)
    freezer.move_to(now)
    _charging(hass, 8)
    _fresh(coordinator, now, current_a=8)
    coordinator.update_config_value("ev_capacity_source", "legacy_ratio")
    hass.states.async_set("sensor.car_energy", stored, {"unit_of_measurement": "kWh"})
    calls.clear()
    await controller.async_reconcile(now)
    assert controller.target_current_a == 0
    assert not _above_baseline(calls)
    assert any(call[:2] == ("switch", "turn_off") for call in calls)


async def test_topup_never_writes_before_its_ownership_is_saved(hass, freezer, monkeypatch):
    from unittest.mock import AsyncMock

    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    _, controller = _case(hass, now)
    monkeypatch.setattr(
        controller, "_async_save", AsyncMock(side_effect=OSError("disk unavailable")),
    )
    with pytest.raises(OSError, match="disk unavailable"):
        await controller.async_reconcile(now)
    assert calls == []


@pytest.mark.parametrize("target,soc,soft", [(95, 90, 90), (80, 75, 75)])
async def test_before_export_target_cannot_bypass_lower_normal_ceiling(
    hass, freezer, target, soc, soft,
):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    _, controller = _case(
        hass, now, ev_before_export_soc_target_percent=target,
        ev_free_window_charge_limit_percent=soft,
    )
    hass.states.async_set("sensor.car_soc", str(soc), {"unit_of_measurement": "%"})
    await controller.async_reconcile(now)
    assert controller.decision_phase == "ev_before_export_normal_soc_limit"
    assert not _above_baseline(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)
