"""Ready-by surplus charging through the actual EV runtime and persistence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    PreFreeSessionState,
)
from custom_components.home_energy_orchestrator.planner.export import ExportPlan
from custom_components.home_energy_orchestrator.planner.export_session import ExportSessionState
from custom_components.home_energy_orchestrator.telemetry import NormalizedSample, TelemetrySource
from tests.test_ev_active import _controller_config, _coordinator, _set_ev_states


def _at(hour=5, minute=0, second=0):
    return datetime(2026, 9, 7, hour, minute, second, tzinfo=UTC)


def _fresh(coordinator, now, *, grid_kw=0, current_a=0):
    """Provide coherent inverter evidence without assuming a cloud feedback ramp."""

    def sample(entity, value, unit, direction):
        return NormalizedSample(
            value,
            unit,
            (TelemetrySource(entity, value, unit, now),),
            direction,
            True,
            True,
            "ok",
        )

    coordinator.telemetry = replace(
        coordinator.telemetry,
        grid_power=sample("sensor.site_grid", grid_kw, "kW", "positive_import"),
        battery_power=sample(
            "sensor.battery_power", -0.2 - current_a * 0.69, "kW", "positive_charge"
        ),
        house_load=sample("sensor.house", 0.2, "kW", "positive_consumption"),
        site_grid_current=sample("sensor.phase_current", 0, "A", "positive_import"),
    )


def _site(hass: HomeAssistant, **changes):
    _set_ev_states(hass)
    hass.states.async_set("sensor.site_battery_soc", "80", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.car_soc", "25", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.car_energy", "15", {"unit_of_measurement": "kWh"})
    config = _controller_config(
        foxess_control_owner="local_modbus",
        automatic_control_enabled=True,
        ev_pre_free_backfill_enabled=True,
        ev_pre_free_backfill_timing="ready_by",
        ev_daily_backfill_energy_kwh=0,
        ev_daily_ready_time="08:00:00",
        ev_outside_battery_reserve_percent=20,
        ev_outside_inverter_percent=40,
        inverter_discharge_limit_kw=15,
        discharge_efficiency_percent=100,
        ev_phase_count=3,
        site_phase_count=3,
        site_grid_current_entity="sensor.phase_current",
        service_import_limit_a=80,
    )
    config.update(changes)
    if config.get("ev_pre_free_backfill_timing") is None:
        config.pop("ev_pre_free_backfill_timing", None)
    coordinator = _coordinator(config)
    coordinator.data = SimpleNamespace(available_after_reserve_kwh=24)
    coordinator.learning_remaining_kwh = 5
    coordinator.snapshot = replace(coordinator.snapshot, battery_soc=80)
    coordinator.active_controller.export_plan = ExportPlan(19, 19, 1, "ready")
    _fresh(coordinator, _at())
    return coordinator, ActiveEvController(hass, coordinator)


def _services(hass):
    calls = []

    async def record(call):
        calls.append((call.domain, call.service, dict(call.data)))

    hass.services.async_register("number", "set_value", record)
    hass.services.async_register("switch", "turn_on", record)
    hass.services.async_register("switch", "turn_off", record)
    return calls


def _charging(hass, current=8):
    hass.states.async_set("switch.car_charge", "on")
    hass.states.async_set("sensor.car_charging", "charging")
    hass.states.async_set("sensor.car_actual_current", str(current), {"unit_of_measurement": "A"})
    hass.states.async_set(
        "number.car_current",
        str(current),
        {"min": 1, "max": 16, "step": 1, "unit_of_measurement": "A"},
    )
    hass.states.async_set("number.car_limit", "90", {"min": 50, "max": 100, "step": 1})


async def test_zero_quota_ready_by_starts_overnight_without_reserving_evening_energy(hass):
    calls = _services(hass)
    coordinator, controller = _site(hass)
    _fresh(coordinator, _at(4))
    await controller.async_reconcile(_at(4))
    assert not controller.daily_backfill_active
    assert controller.daily_backfill_plan.planned_energy_kwh == 19
    assert controller.daily_backfill_plan.planned_start.hour == 4
    assert controller.daily_backfill_plan.planned_start.minute == 33
    assert calls == []

    _fresh(coordinator, _at(4, 40))
    await controller.async_reconcile(_at(4, 40))
    assert controller.daily_backfill_active
    assert controller.target_current_a == 8
    assert controller.decision_phase == "daily_ready_backfill"
    assert controller.daily_backfill_protection_kwh(_at(4, 40)) == 0
    assert controller.pre_free_phase == "ready_by_selected"
    assert not controller.pre_free_session.active
    assert calls[-1][:2] == ("switch", "turn_on")
    assert all(domain in {"number", "switch"} for domain, _, _ in calls)


async def test_conservative_preserves_free_window_deadline_and_zero_quota_disabled(hass):
    calls = _services(hass)
    coordinator, controller = _site(hass, ev_pre_free_backfill_timing="conservative")
    await controller.async_reconcile(_at())
    assert not controller.daily_backfill_active
    assert controller.daily_backfill_plan is None
    assert controller.pre_free_phase == "waiting_latest_start"
    assert controller.pre_free_plan.planned_start.hour == 8
    assert calls == []


async def test_legacy_enabled_backfill_adopts_ready_by_without_changing_other_switches(hass):
    calls = _services(hass)
    coordinator, controller = _site(hass, ev_pre_free_backfill_timing=None)
    assert "ev_pre_free_backfill_timing" not in coordinator.config
    await controller.async_reconcile(_at())
    assert controller.daily_backfill_active
    assert controller.target_current_a == 8
    assert controller.daily_backfill_protection_kwh(_at()) == 0
    assert calls[-1][:2] == ("switch", "turn_on")
    assert coordinator.config["ev_pre_free_backfill_enabled"] is True


async def test_disabled_backfill_stays_disabled_when_ready_by_becomes_default(hass):
    calls = _services(hass)
    coordinator, controller = _site(
        hass, ev_pre_free_backfill_timing=None, ev_pre_free_backfill_enabled=False
    )
    await controller.async_reconcile(_at())
    assert not controller.daily_backfill_active
    assert controller.pre_free_phase == "disabled"
    # The existing learned SoC limit may update without authorising charging.
    assert all(
        domain == "number"
        and service == "set_value"
        and data["entity_id"] == "number.car_limit"
        for domain, service, data in calls
    )
    assert coordinator.config["ev_pre_free_backfill_enabled"] is False


async def test_observer_upgrade_preserves_disabled_session_state_without_writing(hass):
    calls = _services(hass)
    coordinator, controller = _site(
        hass, ev_automatic_control_enabled=False, ev_pre_free_backfill_enabled=False
    )
    controller.daily_backfill_active = True
    controller.daily_backfill_frozen_start = _at(4)
    controller.daily_backfill_cycle_ready_at = _at(8)
    controller.daily_backfill_session_target_kwh = 8.5
    controller.daily_backfill_delivered_kwh = 3.25
    controller.daily_backfill_stop_pending = True
    controller.daily_backfill_stop_attempts = 2
    await controller.async_reconcile(_at())
    assert controller.daily_backfill_active
    assert controller.daily_backfill_session_target_kwh == 8.5
    assert controller.daily_backfill_delivered_kwh == 3.25
    assert controller.daily_backfill_frozen_start == _at(4)
    assert controller.daily_backfill_stop_attempts == 2
    assert calls == []


async def test_ready_deadline_stops_and_never_falls_back_to_late_pre_free(hass):
    calls = _services(hass)
    coordinator, controller = _site(hass)
    await controller.async_reconcile(_at())
    _charging(hass)
    _fresh(coordinator, _at(8), current_a=8)
    await controller.async_reconcile(_at(8))
    assert not controller.daily_backfill_active
    assert not controller.pre_free_session.active
    assert controller.target_current_a == 0
    assert calls[-1][:2] == ("switch", "turn_off")
    assert controller.daily_backfill_plan.phase == "before_planning_window"

    _fresh(coordinator, _at(10), current_a=8)
    await controller.async_reconcile(_at(10))
    assert controller.pre_free_phase == "ready_by_selected"
    assert controller.target_current_a == 0
    assert not controller.daily_backfill_active


@pytest.mark.parametrize("baseline", [0, 1])
async def test_ready_by_hard_battery_cutoff_preserves_configured_baseline(hass, baseline):
    calls = _services(hass)
    coordinator, controller = _site(hass, ev_protected_baseline_a=baseline)
    await controller.async_reconcile(_at())
    _charging(hass)
    coordinator.snapshot = replace(coordinator.snapshot, battery_soc=20)
    _fresh(coordinator, _at(5, 1), current_a=8)
    await controller.async_reconcile(_at(5, 1))
    assert not controller.daily_backfill_active
    assert controller.target_current_a == baseline
    if baseline == 0:
        assert calls[-1][:2] == ("switch", "turn_off")
    else:
        assert calls[-1][:2] == ("number", "set_value")
        assert calls[-1][2]["value"] == 1
        assert not any(service == "turn_off" for _, service, _ in calls)


@pytest.mark.parametrize(
    "loss",
    [
        "house_budget",
        "available_energy",
        "stored_energy",
        "vehicle_soc",
        "current_metadata",
        "stale_grid",
        "stale_battery",
        "stale_house",
        "grid_import",
        "invalid_energy",
        "export_active",
        "owner_changed",
        "timing_changed",
        "disabled",
        "invalid_deadline",
        "phase_current",
        "phase_and_metadata",
    ],
)
async def test_lost_authority_stops_active_surplus_and_preserves_stop_backoff(hass, loss):
    calls = _services(hass)
    coordinator, controller = _site(hass)
    await controller.async_reconcile(_at())
    _charging(hass)
    now = _at(5, 1)
    _fresh(coordinator, now, current_a=8)
    if loss == "house_budget":
        coordinator.learning_remaining_kwh = None
    elif loss == "available_energy":
        coordinator.data.available_after_reserve_kwh = None
    elif loss == "stored_energy":
        hass.states.async_set("sensor.car_energy", "unavailable")
    elif loss == "vehicle_soc":
        hass.states.async_set("sensor.car_soc", "unavailable")
    elif loss == "current_metadata":
        hass.states.async_set("number.car_current", "unavailable")
    elif loss.startswith("stale_"):
        field = {
            "stale_grid": "grid_power",
            "stale_battery": "battery_power",
            "stale_house": "house_load",
        }[loss]
        old = getattr(coordinator.telemetry, field)
        coordinator.telemetry = replace(
            coordinator.telemetry,
            **{field: replace(old, fresh=False, value=None, reason="source_stale")},
        )
    elif loss == "grid_import":
        _fresh(coordinator, now, grid_kw=2, current_a=8)
    elif loss == "invalid_energy":
        coordinator.data.available_after_reserve_kwh = float("nan")
    elif loss == "export_active":
        coordinator.active_controller.export_session = ExportSessionState(phase="active")
    elif loss == "owner_changed":
        coordinator.update_config_value("foxess_control_owner", "foxcloud_scheduler")
    elif loss == "timing_changed":
        coordinator.update_config_value("ev_pre_free_backfill_timing", "conservative")
    elif loss == "disabled":
        coordinator.update_config_value("ev_pre_free_backfill_enabled", False)
    elif loss == "invalid_deadline":
        coordinator.update_config_value("ev_daily_ready_time", "13:00:00")
    elif loss in {"phase_current", "phase_and_metadata"}:
        coordinator.telemetry = replace(
            coordinator.telemetry,
            site_grid_current=replace(
                coordinator.telemetry.site_grid_current, value=None, valid=False, fresh=False
            ),
        )
        if loss == "phase_and_metadata":
            hass.states.async_set("number.car_current", "unavailable")

    await controller.async_reconcile(now)
    assert not controller.daily_backfill_active
    assert controller.target_current_a == 0
    assert calls[-1][:2] == ("switch", "turn_off")
    assert controller.daily_backfill_stop_attempts == 1
    count = len(calls)

    # The charger has not acknowledged stopping: preserve its retry interval.
    await controller.async_reconcile(now + timedelta(seconds=15))
    assert len(calls) == count
    assert controller.daily_backfill_stop_attempts == 1


async def test_ready_by_uses_configured_import_tolerance(hass):
    _services(hass)
    coordinator, controller = _site(hass, zero_import_threshold_kw=0.2)
    _fresh(coordinator, _at(), grid_kw=0.1)
    await controller.async_reconcile(_at())
    assert controller.daily_backfill_active
    _charging(hass)
    _fresh(coordinator, _at(5, 1), grid_kw=0.21, current_a=8)
    await controller.async_reconcile(_at(5, 1))
    assert not controller.daily_backfill_active
    assert controller.daily_backfill_hold_reason == "ready_by_grid_import"


@pytest.mark.parametrize("loss", ["vehicle_soc", "stored_energy", "grid_import", "phase_current"])
async def test_ready_by_lost_authority_keeps_one_amp_charger_alive(hass, loss):
    calls = _services(hass)
    coordinator, controller = _site(hass, ev_protected_baseline_a=1)
    await controller.async_reconcile(_at())
    _charging(hass)
    _fresh(coordinator, _at(5, 1), current_a=8)
    if loss == "vehicle_soc":
        hass.states.async_set("sensor.car_soc", "unavailable")
    elif loss == "stored_energy":
        hass.states.async_set("sensor.car_energy", "unavailable")
    elif loss == "grid_import":
        _fresh(coordinator, _at(5, 1), grid_kw=2, current_a=8)
    else:
        coordinator.telemetry = replace(
            coordinator.telemetry,
            site_grid_current=replace(
                coordinator.telemetry.site_grid_current, value=None, valid=False, fresh=False
            ),
        )
    await controller.async_reconcile(_at(5, 1))
    assert not controller.daily_backfill_active
    assert controller.target_current_a == 1
    assert calls[-1][:2] == ("number", "set_value")
    assert calls[-1][2]["value"] == 1
    assert not any(service == "turn_off" for _, service, _ in calls)


@pytest.mark.parametrize("minimum,step,expected", [(6, 1, 6), (0, 2, 2), (6, 4, 8)])
async def test_ready_by_failure_uses_representable_protected_baseline(
    hass, minimum, step, expected
):
    calls = _services(hass)
    coordinator, controller = _site(hass, ev_protected_baseline_a=1)
    await controller.async_reconcile(_at())
    _charging(hass, 16)
    hass.states.async_set(
        "number.car_current",
        "16",
        {"min": minimum, "max": 16, "step": step, "unit_of_measurement": "A"},
    )
    hass.states.async_set("sensor.car_soc", "unavailable")
    _fresh(coordinator, _at(5, 1), current_a=8)
    await controller.async_reconcile(_at(5, 1))
    assert controller.target_current_a == expected
    assert calls[-1][:2] == ("number", "set_value")
    assert calls[-1][2]["value"] == expected


async def test_unexpected_house_consumption_removes_budget_well_before_soc_cutoff(hass):
    calls = _services(hass)
    coordinator, controller = _site(hass)
    await controller.async_reconcile(_at())
    _charging(hass)
    _fresh(coordinator, _at(5, 1), current_a=8)
    coordinator.data.available_after_reserve_kwh = 7
    await controller.async_reconcile(_at(5, 1))
    assert controller.daily_backfill_active
    assert controller.daily_backfill_session_target_kwh < 3

    # Unexpected house use has consumed the surplus, although SoC is above20%.
    coordinator.data.available_after_reserve_kwh = 4
    _fresh(coordinator, _at(5, 2), current_a=8)
    await controller.async_reconcile(_at(5, 2))
    assert coordinator.snapshot.battery_soc == 80
    assert not controller.daily_backfill_active
    assert controller.daily_backfill_plan.phase == "protected_energy_unavailable"
    assert calls[-1][:2] == ("switch", "turn_off")


@pytest.mark.parametrize("remaining_battery_kwh,resumes_now", [(24, True), (12, False)])
async def test_house_surge_clearing_replans_and_can_resume_before_ready(
    hass, remaining_battery_kwh, resumes_now
):
    calls = _services(hass)
    coordinator, controller = _site(hass)
    await controller.async_reconcile(_at())
    _charging(hass)
    _fresh(coordinator, _at(5, 1), grid_kw=2, current_a=8)
    await controller.async_reconcile(_at(5, 1))
    assert not controller.daily_backfill_active
    assert calls[-1][:2] == ("switch", "turn_off")

    # The surge ends and stopping is acknowledged; Tessie retains its8A setting.
    hass.states.async_set("switch.car_charge", "off")
    hass.states.async_set("sensor.car_charging", "stopped")
    hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "A"})
    coordinator.data.available_after_reserve_kwh = remaining_battery_kwh
    _fresh(coordinator, _at(5, 2))
    count = len(calls)
    await controller.async_reconcile(_at(5, 2))
    assert controller.daily_backfill_active is resumes_now
    if resumes_now:
        assert controller.target_current_a == 8
        assert calls[-1][:2] == ("switch", "turn_on")
    else:
        assert len(calls) == count
        assert controller.daily_backfill_plan.phase == "waiting_latest_start"
        assert controller.daily_backfill_plan.planned_energy_kwh == 7
        _fresh(coordinator, _at(6, 50))
        await controller.async_reconcile(_at(6, 50))
        assert controller.daily_backfill_active
        assert controller.target_current_a == 8
        assert calls[-1][:2] == ("switch", "turn_on")


async def test_fixed_quota_and_ready_by_share_one_budget_and_delivery_ledger(hass):
    _services(hass)
    coordinator, controller = _site(hass, ev_daily_backfill_energy_kwh=3)
    await controller.async_reconcile(_at())
    assert controller.daily_backfill_plan.planned_energy_kwh == 19
    assert controller.daily_backfill_plan.discretionary_energy_kwh == 16
    assert controller.daily_backfill_protection_kwh(_at()) == 3
    _charging(hass)
    controller.daily_backfill_delivered_kwh = 2
    assert controller.daily_backfill_protection_kwh(_at(5, 1)) == 1
    coordinator.data.available_after_reserve_kwh = 20
    _fresh(coordinator, _at(5, 1), current_a=8)
    await controller.async_reconcile(_at(5, 1))
    assert controller.daily_backfill_plan.planned_energy_kwh == 15
    assert controller.daily_backfill_plan.remaining_allocation_kwh <= 1


async def test_late_plug_in_delivers_partial_energy_then_honours_same_day_deadline(hass):
    calls = _services(hass)
    coordinator, controller = _site(hass)
    _fresh(coordinator, _at(7, 55))
    await controller.async_reconcile(_at(7, 55))
    assert controller.daily_backfill_active
    assert not controller.daily_backfill_plan.achievable_by_ready
    _charging(hass)
    _fresh(coordinator, _at(8), current_a=8)
    await controller.async_reconcile(_at(8))
    assert not controller.daily_backfill_active
    assert calls[-1][:2] == ("switch", "turn_off")


async def test_after_ready_morning_solar_takes_over_then_free_window_uses_maximum(hass):
    _services(hass)
    coordinator, controller = _site(
        hass,
        solar_configured=True,
        ev_morning_solar_enabled=True,
        ev_morning_solar_reserve_soc_percent=20,
    )
    await controller.async_reconcile(_at())
    _charging(hass)
    _fresh(coordinator, _at(8), current_a=8)
    coordinator.telemetry = replace(
        coordinator.telemetry,
        battery_power=replace(coordinator.telemetry.battery_power, value=-2.72),
    )
    await controller.async_reconcile(_at(8))
    assert not controller.daily_backfill_active
    assert not controller.pre_free_session.active

    _charging(hass, 0)
    hass.states.async_set("switch.car_charge", "off")
    hass.states.async_set("sensor.car_charging", "stopped")
    _fresh(coordinator, _at(8, 10))
    coordinator.telemetry = replace(
        coordinator.telemetry,
        battery_power=replace(coordinator.telemetry.battery_power, value=2.8),
    )
    await controller.async_reconcile(_at(8, 10))
    assert controller.outside_stage_selection.stage == "morning_solar"
    assert controller.target_current_a == 4
    assert not controller.pre_free_session.active
    _fresh(coordinator, _at(12, 1))
    await controller.async_reconcile(_at(12, 1))
    assert controller.target_current_a == 16
    assert controller.decision_phase == "ev_priority_maximum"


async def test_ready_by_shrinks_live_budget_and_plans_only_to_normal_90_percent_cap(hass):
    _services(hass)
    coordinator, controller = _site(hass, ev_free_window_charge_limit_percent=100)
    hass.states.async_set("sensor.car_soc", "89", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.car_energy", "53.4", {"unit_of_measurement": "kWh"})
    _fresh(coordinator, _at(7, 55))
    await controller.async_reconcile(_at(7, 55))
    assert controller.daily_backfill_plan.planned_energy_kwh == pytest.approx(0.667, abs=0.001)
    assert controller.daily_backfill_active
    assert controller.target_limit_percent == 90
    _charging(hass)
    hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
    _fresh(coordinator, _at(7, 56), current_a=8)
    await controller.async_reconcile(_at(7, 56))
    assert not controller.daily_backfill_active
    assert controller.target_current_a == 0


async def test_ready_by_paid_override_has_separate_energy_ownership(hass):
    _services(hass)
    coordinator, controller = _site(hass)
    await controller.async_reconcile(_at())
    _charging(hass)
    controller.daily_backfill_delivered_kwh = 1.25
    coordinator.update_config_value("ev_charge_to_full_enabled", True)
    _fresh(coordinator, _at(5, 1), current_a=8)
    await controller.async_reconcile(_at(5, 1))
    assert not controller.daily_backfill_active
    assert controller.daily_backfill_delivered_kwh == 1.25
    assert controller.target_current_a == 16
    assert controller.target_limit_percent == 100

    _charging(hass, 16)
    _fresh(coordinator, _at(5, 2), current_a=16)
    await controller.async_reconcile(_at(5, 2))
    assert controller.daily_backfill_delivered_kwh == 1.25


async def test_ready_by_restart_retains_session_and_free_window_takes_ownership(hass):
    calls = _services(hass)
    coordinator, controller = _site(hass)
    await controller.async_reconcile(_at())
    _charging(hass)
    await controller._async_save(_at())
    restarted = ActiveEvController(hass, coordinator)
    await restarted._async_restore()
    assert restarted.daily_backfill_active
    assert restarted.daily_backfill_frozen_start == controller.daily_backfill_frozen_start
    _fresh(coordinator, _at(5, 1), current_a=8)
    await restarted.async_reconcile(_at(5, 1))
    assert restarted.daily_backfill_active
    assert restarted.target_current_a == 8

    # Also reject a stale conservative pre-free latch on mode takeover.
    restarted.pre_free_session = PreFreeSessionState(True, _at(4))
    _fresh(coordinator, _at(5, 2), current_a=8)
    await restarted.async_reconcile(_at(5, 2))
    assert not restarted.pre_free_session.active
    delivered = restarted.daily_backfill_delivered_kwh

    _fresh(coordinator, _at(12, 1), current_a=8)
    await restarted.async_reconcile(_at(12, 1))
    assert not restarted.daily_backfill_active
    assert not restarted.daily_backfill_stop_pending
    assert restarted.daily_backfill_delivered_kwh == delivered
    assert restarted.target_current_a == 16
    assert not any(service == "turn_off" for _, service, _ in calls)


@pytest.mark.parametrize("presence", ["away", "disconnected", "safety_lock"])
async def test_ready_by_never_starts_when_vehicle_or_control_is_ineligible(hass, presence):
    calls = _services(hass)
    coordinator, controller = _site(hass)
    if presence == "away":
        hass.states.async_set("device_tracker.car", "not_home")
    elif presence == "disconnected":
        hass.states.async_set("binary_sensor.car_cable", "off")
    else:
        coordinator.update_config_value("rehearsal_mode", True)
    await controller.async_reconcile(_at())
    assert calls == []
