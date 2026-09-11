from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.models import SiteSnapshot
from custom_components.home_energy_orchestrator.planner.ev import (
    SmartSocketRecoveryState,
)
from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    PreFreeSessionState,
)
from custom_components.home_energy_orchestrator.planner.export import ExportPlan
from custom_components.home_energy_orchestrator.planner.export_session import (
    ExportSessionState,
)
from custom_components.home_energy_orchestrator.telemetry import (
    NormalizedSample,
    NormalizedTelemetry,
    TelemetrySource,
    unavailable_sample,
)


def _controller_config(**changes):
    config = {
        "battery_soc_entity": "sensor.site_battery_soc",
        "automatic_control_enabled": False,
        "foxess_control_owner": "foxcloud_scheduler",
        "ev_automatic_control_enabled": True,
        "ev_control_commissioned": True,
        "rehearsal_mode": False,
        "sign_conventions_verified": True,
        "ev_soc_entity": "sensor.car_soc",
        "ev_at_home_entity": "device_tracker.car",
        "ev_cable_connected_entity": "binary_sensor.car_cable",
        "ev_charging_state_entity": "sensor.car_charging",
        "ev_actual_current_entity": "sensor.car_actual_current",
        "ev_stored_energy_entity": "sensor.car_energy",
        "ev_current_limit_entity": "number.car_current",
        "ev_charge_limit_entity": "number.car_limit",
        "ev_charge_switch_entity": "switch.car_charge",
        "ev_location_mode": "auto",
        "ev_free_window_priority": "ev",
        "ev_free_window_charge_limit_percent": 90,
        "ev_free_window_minimum_current_a": 1,
        "ev_free_window_settle_minutes": 5,
        "ev_direct_limit_headroom_percent": 2,
        "ev_charge_efficiency_percent": 90,
        "ev_allowance_guard_enabled": False,
        "ev_protected_baseline_a": 0,
        "ev_max_current": 16,
        "ev_voltage": 230,
        "ev_phase_count": 1,
        "house_load_includes_ev": False,
        "site_phase_count": 1,
        "service_import_limit_a": 63,
        "site_grid_headroom_current_a": 1,
        "free_charge_window_start": "12:01:00",
        "free_charge_window_end": "14:59:00",
    }
    config.update(changes)
    return config


def _coordinator(config):
    observed_at = datetime(2026, 9, 7, 12, 1, tzinfo=UTC)
    grid_source = TelemetrySource("sensor.site_grid", 10, "kW", observed_at)
    grid = NormalizedSample(10, "kW", (grid_source,), "positive_import", True, True, "ok")
    return SimpleNamespace(
        config=config,
        entry_id="ev-runtime-test",
        snapshot=SiteSnapshot(
            battery_soc=20,
            battery_capacity_kwh=40,
            battery_floor_percent=10,
            reserve_kwh=0,
            grid_power_kw=10,
            house_load_kw=2,
            site_phase_count=int(config["site_phase_count"]),
            service_import_limit_a=63,
        ),
        telemetry=NormalizedTelemetry(
            grid_power=grid,
            battery_power=unavailable_sample(
                unit="kW", positive_direction="positive_charge", reason="not_configured"
            ),
            solar_power=unavailable_sample(
                unit="kW", positive_direction="generation_positive", reason="not_configured"
            ),
            house_load=unavailable_sample(
                unit="kW", positive_direction="positive_consumption", reason="not_configured"
            ),
            site_grid_current=(
                NormalizedSample(
                    10 * 1000 / 230,
                    "A",
                    (grid_source,),
                    "positive_import",
                    True,
                    True,
                    "derived_from_grid_power",
                )
                if int(config["site_phase_count"]) == 1
                else unavailable_sample(
                    unit="A",
                    positive_direction="positive_import",
                    reason="source_unavailable",
                )
            ),
        ),
        free_window_import=SimpleNamespace(last_at=None, imported_kwh=0),
        _configured_time=lambda key, default: time.fromisoformat(str(config.get(key, default))),
        async_update_listeners=lambda: None,
    )


def _set_power_telemetry(coordinator, hass: HomeAssistant, *, grid_kw, battery_kw):
    observed_at = hass.states.get("sensor.site_grid").last_updated
    coordinator.telemetry = NormalizedTelemetry(
        grid_power=NormalizedSample(
            grid_kw,
            "kW",
            (TelemetrySource("sensor.site_grid", grid_kw, "kW", observed_at),),
            "positive_import",
            True,
            True,
            "ok",
        ),
        battery_power=NormalizedSample(
            battery_kw,
            "kW",
            (TelemetrySource("sensor.battery_power", battery_kw, "kW", observed_at),),
            "positive_charge",
            True,
            True,
            "ok",
        ),
        solar_power=coordinator.telemetry.solar_power,
        house_load=coordinator.telemetry.house_load,
        site_grid_current=coordinator.telemetry.site_grid_current,
    )


def _set_ev_states(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.site_battery_soc", "20", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.car_soc", "40", {"unit_of_measurement": "%"})
    hass.states.async_set("device_tracker.car", "home")
    hass.states.async_set("binary_sensor.car_cable", "on")
    hass.states.async_set("sensor.car_charging", "stopped")
    hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "A"})
    hass.states.async_set("sensor.car_energy", "30", {"unit_of_measurement": "kWh"})
    hass.states.async_set(
        "number.car_current",
        "6",
        {"min": 1, "max": 16, "step": 1, "unit_of_measurement": "A"},
    )
    hass.states.async_set("number.car_limit", "80", {"min": 50, "max": 100, "step": 1})
    hass.states.async_set("switch.car_charge", "off")


def test_allowance_does_not_cycle_when_whole_house_meter_includes_ev(
    hass: HomeAssistant,
) -> None:
    config = _controller_config(
        ev_phase_count=3,
        site_phase_count=3,
        ev_allowance_guard_enabled=True,
        daily_free_allowance_kwh=50,
        house_load_includes_ev=True,
    )
    coordinator = _coordinator(config)
    coordinator.free_window_import = SimpleNamespace(
        last_at=datetime(2026, 9, 7, 12, 30, tzinfo=UTC), imported_kwh=25
    )
    controller = ActiveEvController(hass, coordinator)
    hass.states.async_set("sensor.car_energy", "5", {"unit_of_measurement": "kWh"})
    hass.states.async_set("sensor.car_charging", "charging")

    hass.states.async_set("sensor.car_actual_current", "16", {"unit_of_measurement": "A"})
    high_snapshot = replace(coordinator.snapshot, battery_soc=100, house_load_kw=12)
    high = controller._allowance_target(  # noqa: SLF001
        16, 1, 1, 1, 60, 50, 2, high_snapshot
    )
    hass.states.async_set("sensor.car_actual_current", "1", {"unit_of_measurement": "A"})
    low_snapshot = replace(coordinator.snapshot, battery_soc=100, house_load_kw=1.65)
    low = controller._allowance_target(  # noqa: SLF001
        16, 1, 1, 1, 60, 50, 2, low_snapshot
    )

    assert high is not None and high.current_a == 16
    assert low is not None and low.current_a == 16
    assert high.phase == low.phase == "allowance_not_constraining"
    assert controller.allowance_house_load_kw == 0.96


def test_pilot_house_load_excluding_ev_is_not_subtracted_again(
    hass: HomeAssistant,
) -> None:
    config = _controller_config(
        ev_phase_count=3,
        site_phase_count=3,
        ev_allowance_guard_enabled=True,
        daily_free_allowance_kwh=50,
        house_load_includes_ev=False,
    )
    coordinator = _coordinator(config)
    coordinator.free_window_import = SimpleNamespace(
        last_at=datetime(2026, 9, 7, 12, 30, tzinfo=UTC), imported_kwh=25
    )
    controller = ActiveEvController(hass, coordinator)
    hass.states.async_set("sensor.car_energy", "5", {"unit_of_measurement": "kWh"})
    hass.states.async_set("sensor.car_charging", "charging")
    hass.states.async_set("sensor.car_actual_current", "16", {"unit_of_measurement": "A"})

    snapshot = replace(coordinator.snapshot, battery_soc=100, house_load_kw=12)
    decision = controller._allowance_target(  # noqa: SLF001
        16, 1, 1, 1, 60, 50, 2, snapshot
    )

    assert decision is not None and decision.current_a == 1
    assert decision.phase == "allowance_below_charger_minimum"
    assert controller.allowance_house_load_kw == 12


async def test_ev_runtime_writes_tessie_but_not_foxess_when_cloud_owns_inverter(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def set_number(call):
        entity = call.data["entity_id"]
        old = hass.states.get(entity)
        assert old is not None
        hass.states.async_set(entity, str(call.data["value"]), old.attributes)

    async def start_charge(_call):
        hass.states.async_set("switch.car_charge", "on")

    hass.services.async_register("number", "set_value", set_number)
    hass.services.async_register("switch", "turn_on", start_charge)
    controller = ActiveEvController(hass, _coordinator(_controller_config()))

    await controller.async_reconcile(datetime(2026, 9, 7, 12, 1, tzinfo=UTC))
    await hass.async_block_till_done()

    assert controller.target_current_a == 16
    assert controller.requested_current_a == 6
    assert controller.applied_limit_percent == 80
    assert controller.actual_current_a == 0
    assert controller.last_actions == (
        "set_charge_limit",
        "set_charge_current",
        "start_charging",
    )
    assert controller.writes_performed == 3
    assert {event.data["domain"] for event in calls} == {"number", "switch"}


async def test_transient_tessie_max_bounds_transport_then_catches_up(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set(
        "number.car_current",
        "6",
        {"min": 1, "max": 6, "step": 1, "unit_of_measurement": "A"},
    )
    written_currents = []

    async def set_number(call):
        if call.data["entity_id"] == "number.car_current":
            written_currents.append(call.data["value"])

    async def accept(_call):
        return None

    hass.services.async_register("number", "set_value", set_number)
    hass.services.async_register("switch", "turn_on", accept)
    controller = ActiveEvController(hass, _coordinator(_controller_config()))
    start = datetime(2026, 9, 7, 12, 1, tzinfo=UTC)

    await controller.async_reconcile(start)
    assert controller.target_current_a == 16
    assert written_currents == []

    hass.states.async_set(
        "number.car_current",
        "6",
        {"min": 1, "max": 16, "step": 1, "unit_of_measurement": "A"},
    )
    await controller.async_reconcile(start + timedelta(seconds=30))

    assert controller.target_current_a == 16
    assert written_currents == [16]


async def test_safety_lock_calculates_rehearsal_plan_without_writing(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    controller = ActiveEvController(hass, _coordinator(_controller_config(rehearsal_mode=True)))

    await controller.async_reconcile(datetime(2026, 9, 7, 12, 1, tzinfo=UTC))

    assert controller.gate_status == "safety_locked"
    assert controller.target_current_a == 16
    assert controller.target_limit_percent == 90
    assert controller.last_actions == (
        "would_set_charge_limit",
        "would_set_charge_current",
        "would_start_charging",
    )
    assert controller.last_reason == "rehearsal_direct_path_ready"
    assert controller.reconciliation.attempts == 0
    assert controller.writes_performed == 0
    assert calls == []


async def test_ev_runtime_only_applies_general_limit_outside_free_window(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def accept(_call):
        return None

    hass.services.async_register("number", "set_value", accept)
    controller = ActiveEvController(hass, _coordinator(_controller_config()))

    start = datetime(2026, 9, 7, 0, 1, tzinfo=UTC)
    await controller.async_reconcile(start)
    await controller.async_reconcile(start + timedelta(seconds=30))
    await hass.async_block_till_done()

    assert controller.last_reason == "outside_window_general_limit_awaiting_feedback"
    assert controller.last_actions == ()
    assert len(calls) == 1
    assert calls[0].data["service_data"]["entity_id"] == "number.car_limit"


async def test_cloud_owner_blocks_opted_in_outside_window_stages(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def accept(_call):
        return None

    hass.services.async_register("number", "set_value", accept)
    controller = ActiveEvController(
        hass,
        _coordinator(
            _controller_config(
                ev_solar_spill_enabled=True,
                ev_pre_free_backfill_enabled=True,
            )
        ),
    )

    await controller.async_reconcile(datetime(2026, 9, 7, 0, 1, tzinfo=UTC))
    await hass.async_block_till_done()

    assert controller.last_reason == "general_limit"
    assert controller.last_actions == ("set_charge_limit",)
    assert len(calls) == 1


@pytest.mark.freeze_time("2026-09-07 00:01:00+00:00")
async def test_solar_spill_runtime_ports_measured_surplus_to_tessie(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set("sensor.site_grid", "-2", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.battery_power", "0.5", {"unit_of_measurement": "kW"})
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def accept(_call):
        return None

    hass.services.async_register("number", "set_value", accept)
    hass.services.async_register("switch", "turn_on", accept)
    coordinator = _coordinator(
        _controller_config(
            foxess_control_owner="local_modbus",
            ev_solar_spill_enabled=True,
            battery_power_entity="sensor.battery_power",
            battery_power_positive_direction="positive_charge",
            grid_power_entity="sensor.site_grid",
            grid_power_positive_direction="positive_import",
            bonus_window_start="21:00:00",
            bonus_window_end="22:00:00",
        )
    )
    _set_power_telemetry(coordinator, hass, grid_kw=-2, battery_kw=0.5)
    coordinator.snapshot = replace(coordinator.snapshot, battery_soc=100)
    hass.states.async_set("sensor.site_battery_soc", "100", {"unit_of_measurement": "%"})
    controller = ActiveEvController(hass, coordinator)
    soc_state = hass.states.get("sensor.site_battery_soc")
    assert soc_state is not None
    now = soc_state.last_updated

    await controller.async_reconcile(now)
    await hass.async_block_till_done()

    assert controller.solar_spill.phase == "solar_spill"
    assert controller.solar_spill.reconstructed_surplus_kw == 2.5
    assert controller.target_current_a == 10
    assert controller.outside_control_active is True
    assert {event.data["domain"] for event in calls} == {"number", "switch"}


@pytest.mark.freeze_time("2026-09-07 00:01:00+00:00")
async def test_opted_in_outside_policy_restores_baseline_after_reconnect(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set(
        "number.car_current",
        "10",
        {"min": 0, "max": 16, "step": 1, "unit_of_measurement": "A"},
    )
    hass.states.async_set("switch.car_charge", "on")
    hass.states.async_set("sensor.site_grid", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.battery_power", "0", {"unit_of_measurement": "kW"})
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def accept(_call):
        return None

    hass.services.async_register("number", "set_value", accept)
    coordinator = _coordinator(
        _controller_config(
            foxess_control_owner="local_modbus",
            ev_solar_spill_enabled=True,
            ev_protected_baseline_a=1,
            battery_power_entity="sensor.battery_power",
            grid_power_entity="sensor.site_grid",
            bonus_window_start="21:00:00",
            bonus_window_end="22:00:00",
        )
    )
    _set_power_telemetry(coordinator, hass, grid_kw=0, battery_kw=0)
    controller = ActiveEvController(hass, coordinator)
    battery_state = hass.states.get("sensor.battery_power")
    assert battery_state is not None

    await controller.async_reconcile(battery_state.last_updated)
    await hass.async_block_till_done()

    assert controller.solar_spill.phase == "battery_not_full"
    assert controller.target_current_a == 1
    assert controller.decision_phase == "protected_baseline"
    assert controller.outside_control_active is True
    current_calls = [
        event
        for event in calls
        if event.data["domain"] == "number" and event.data["service_data"].get("value") == 1
    ]
    assert len(current_calls) == 1


async def test_pre_free_runtime_latches_latest_start_and_uses_export_budget(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)

    async def accept(_call):
        return None

    hass.services.async_register("number", "set_value", accept)
    hass.services.async_register("switch", "turn_on", accept)
    coordinator = _coordinator(
        _controller_config(
            foxess_control_owner="local_modbus",
            ev_pre_free_backfill_enabled=True,
            ev_protected_baseline_a=1,
            force_discharge_finish="09:00:00",
        )
    )
    coordinator.active_controller = SimpleNamespace(
        export_plan=ExportPlan(5, 5, 5 / 3.45, "ready"),
        export_session=ExportSessionState(),
    )
    controller = ActiveEvController(hass, coordinator)
    now = datetime(2026, 9, 7, 10, 40, tzinfo=UTC)

    await controller.async_reconcile(now)

    assert controller.pre_free_session.active is True
    assert controller.pre_free_phase == "started"
    assert controller.pre_free_session.frozen_start == datetime(2026, 9, 7, 10, 34, tzinfo=UTC)
    assert controller.pre_free_plan is not None
    assert controller.pre_free_plan.planned_energy_kwh == 5
    assert controller.pre_free_plan.planned_start == controller.pre_free_session.frozen_start
    assert controller.target_current_a == 16
    assert controller.decision_phase == "pre_free_or_solar_spill"


async def test_daily_ready_backfill_runs_with_foxcloud_owner_and_never_writes_foxess(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def accept(_call):
        return None

    hass.services.async_register("number", "set_value", accept)
    hass.services.async_register("switch", "turn_on", accept)
    coordinator = _coordinator(
        _controller_config(
            foxess_control_owner="foxcloud_scheduler",
            ev_daily_backfill_energy_kwh=5,
            ev_daily_ready_time="08:00:00",
            ev_outside_inverter_percent=30,
            ev_backfill_buffer_minutes=0,
            inverter_discharge_limit_kw=15,
            ev_phase_count=3,
        )
    )
    coordinator.data = SimpleNamespace(available_after_reserve_kwh=14)
    coordinator.learning_remaining_kwh = 3
    controller = ActiveEvController(hass, coordinator)

    await controller.async_reconcile(datetime(2026, 9, 7, 6, 30, tzinfo=UTC))

    assert controller.daily_backfill_active is True
    assert controller.daily_backfill_plan is not None
    assert controller.daily_backfill_plan.current_ceiling_a == 6
    assert controller.target_current_a == 6
    assert controller.decision_phase == "daily_ready_backfill"
    assert all(event.data["domain"] in {"number", "switch"} for event in calls)
    assert not any(event.data["domain"] == "foxess_modbus" for event in calls)


async def test_charge_to_full_starts_immediately_outside_free_and_bypasses_normal_cap(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)

    async def accept(_call):
        return None

    hass.services.async_register("number", "set_value", accept)
    hass.services.async_register("switch", "turn_on", accept)
    coordinator = _coordinator(
        _controller_config(
            ev_charge_to_full_enabled=True,
            ev_daily_backfill_energy_kwh=5,
            ev_daily_ready_time="08:00:00",
            ev_outside_inverter_percent=10,
            inverter_discharge_limit_kw=15,
        )
    )
    controller = ActiveEvController(hass, coordinator)

    await controller.async_reconcile(datetime(2026, 9, 7, 18, 0, tzinfo=UTC))

    assert controller.target_current_a == 16
    assert controller.target_limit_percent == 100
    assert controller.decision_phase == "charge_to_full_paid_grid_override"
    assert controller.last_actions == (
        "set_charge_limit",
        "set_charge_current",
        "start_charging",
    )


async def test_charge_to_full_clears_and_stops_at_full_soc(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set("sensor.car_soc", "100", {"unit_of_measurement": "%"})
    hass.states.async_set("switch.car_charge", "on")
    config = _controller_config(ev_charge_to_full_enabled=True)
    entry = MockConfigEntry(
        domain="home_energy_orchestrator",
        data=config,
    )
    entry.add_to_hass(hass)
    coordinator = _coordinator(config)
    coordinator.entry_id = entry.entry_id
    stopped = []

    async def stop(call):
        stopped.append(call.data["entity_id"])

    hass.services.async_register("switch", "turn_off", stop)
    controller = ActiveEvController(hass, coordinator)

    await controller.async_reconcile(datetime(2026, 9, 7, 18, 0, tzinfo=UTC))

    assert entry.data["ev_charge_to_full_enabled"] is False
    assert controller._charge_to_full_requested() is False  # noqa: SLF001
    assert controller.last_actions == ("stop_charging",)
    assert stopped == ["switch.car_charge"]


async def test_daily_policy_does_not_stop_unowned_evening_charging(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set("switch.car_charge", "on")
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    coordinator = _coordinator(
        _controller_config(
            ev_daily_backfill_energy_kwh=5,
            ev_daily_ready_time="08:00:00",
            ev_outside_inverter_percent=30,
            inverter_discharge_limit_kw=15,
        )
    )
    coordinator.data = SimpleNamespace(available_after_reserve_kwh=14)
    coordinator.learning_remaining_kwh = 3
    controller = ActiveEvController(hass, coordinator)

    await controller.async_reconcile(datetime(2026, 9, 7, 18, 0, tzinfo=UTC))

    assert controller.daily_backfill_plan is not None
    assert controller.daily_backfill_plan.phase == "before_planning_window"
    assert controller.last_actions == ()
    assert calls == []


async def test_daily_policy_stops_its_owned_session_at_frozen_energy_target(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set("switch.car_charge", "on")
    stopped = []

    async def stop(call):
        stopped.append(call.data["entity_id"])

    hass.services.async_register("switch", "turn_off", stop)
    coordinator = _coordinator(
        _controller_config(
            ev_daily_backfill_energy_kwh=5,
            ev_daily_ready_time="08:00:00",
            ev_outside_inverter_percent=30,
            inverter_discharge_limit_kw=15,
        )
    )
    coordinator.data = SimpleNamespace(available_after_reserve_kwh=14)
    coordinator.learning_remaining_kwh = 3
    controller = ActiveEvController(hass, coordinator)
    controller.daily_backfill_cycle_ready_at = datetime(2026, 9, 7, 8, tzinfo=UTC)
    controller.daily_backfill_active = True
    controller.daily_backfill_delivered_kwh = 2
    controller.daily_backfill_session_start_delivered_kwh = 1
    controller.daily_backfill_session_target_kwh = 1
    controller.daily_backfill_frozen_start = datetime(2026, 9, 7, 5, tzinfo=UTC)

    await controller.async_reconcile(datetime(2026, 9, 7, 6, 30, tzinfo=UTC))

    assert controller.daily_backfill_active is False
    assert controller.last_actions == ("stop_charging",)
    assert stopped == ["switch.car_charge"]


async def test_daily_backfill_cycle_and_delivered_energy_survive_restart(
    hass: HomeAssistant,
) -> None:
    coordinator = _coordinator(
        _controller_config(
            ev_daily_backfill_energy_kwh=5,
            ev_daily_ready_time="08:00:00",
            ev_outside_inverter_percent=30,
            inverter_discharge_limit_kw=15,
        )
    )
    first = ActiveEvController(hass, coordinator)
    first.daily_backfill_cycle_ready_at = datetime(2026, 9, 7, 8, tzinfo=UTC)
    first.daily_backfill_delivered_kwh = 2.25
    first.daily_backfill_active = True
    first.daily_backfill_session_target_kwh = 4
    first.daily_backfill_session_start_delivered_kwh = 1
    first.daily_backfill_frozen_start = datetime(2026, 9, 7, 5, tzinfo=UTC)
    first.daily_backfill_stop_pending = True
    first.daily_backfill_stop_attempts = 2
    first.daily_backfill_last_stop_at = datetime(2026, 9, 7, 5, 59, tzinfo=UTC)
    await first._async_save(datetime(2026, 9, 7, 6, tzinfo=UTC))  # noqa: SLF001

    restored = ActiveEvController(hass, coordinator)
    await restored._async_restore()  # noqa: SLF001

    assert restored.daily_backfill_delivered_kwh == 2.25
    assert restored.daily_backfill_active is True
    assert restored.daily_backfill_session_target_kwh == 4
    assert restored.daily_backfill_frozen_start == datetime(2026, 9, 7, 5, tzinfo=UTC)
    assert restored.daily_backfill_stop_pending is True
    assert restored.daily_backfill_stop_attempts == 2
    assert restored.daily_backfill_last_stop_at == datetime(2026, 9, 7, 5, 59, tzinfo=UTC)


def test_evening_export_protects_next_mornings_ready_cycle(
    hass: HomeAssistant,
) -> None:
    coordinator = _coordinator(
        _controller_config(
            ev_daily_backfill_energy_kwh=5,
            ev_daily_ready_time="08:00:00",
            ev_outside_inverter_percent=30,
            inverter_discharge_limit_kw=15,
        )
    )
    controller = ActiveEvController(hass, coordinator)
    controller.daily_backfill_cycle_ready_at = datetime(2026, 9, 8, 8, tzinfo=UTC)
    controller.daily_backfill_delivered_kwh = 1.5

    assert controller.daily_backfill_protection_kwh(datetime(2026, 9, 7, 18, tzinfo=UTC)) == 3.5


async def test_pre_free_phase_and_cleanup_ownership_survive_restart(
    hass: HomeAssistant,
) -> None:
    coordinator = _coordinator(
        _controller_config(
            foxess_control_owner="local_modbus",
            ev_pre_free_backfill_enabled=True,
        )
    )
    first = ActiveEvController(hass, coordinator)
    frozen = datetime(2026, 9, 6, 9, 30, tzinfo=UTC)
    first.pre_free_session = PreFreeSessionState(True, frozen)
    first.outside_control_active = True
    await first._async_save(datetime(2026, 9, 6, 10, 0, tzinfo=UTC))  # noqa: SLF001

    restored = ActiveEvController(hass, coordinator)
    await restored._async_restore()  # noqa: SLF001

    assert restored.pre_free_session == PreFreeSessionState(True, frozen)
    assert restored.outside_control_active is True


async def test_multiphase_runtime_is_blocked_without_explicit_current_mapping(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    controller = ActiveEvController(hass, _coordinator(_controller_config(site_phase_count=3)))

    await controller.async_reconcile(datetime(2026, 9, 7, 12, 1, tzinfo=UTC))

    assert controller.gate_status == "multiphase_current_mapping_required"
    assert controller.writes_performed == 0


async def test_multiphase_runtime_blocks_when_mapped_current_is_unavailable(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    controller = ActiveEvController(
        hass,
        _coordinator(
            _controller_config(
                site_phase_count=3,
                site_grid_current_entity="sensor.most_loaded_phase_current",
            )
        ),
    )

    await controller.async_reconcile(datetime(2026, 9, 7, 12, 1, tzinfo=UTC))

    assert controller.gate_status == "ready"
    assert controller.last_reason == "multiphase_current_feedback_unavailable"
    assert controller.writes_performed == 0


async def test_smart_socket_runtime_respects_connector_settle_time(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set("switch.car_socket", "on")
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    controller = ActiveEvController(
        hass,
        _coordinator(
            _controller_config(
                ev_charge_path="smart_socket",
                ev_smart_socket_entity="switch.car_socket",
                ev_smart_socket_current_limit_a=10,
            )
        ),
    )

    await controller.async_reconcile(datetime(2026, 9, 7, 12, 1, tzinfo=UTC))

    assert controller.gate_status == "ready"
    assert controller.last_reason == "smart_socket_settling"
    assert controller.writes_performed == 0
    assert calls == []


@pytest.mark.freeze_time("2026-09-07 12:01:00+00:00")
async def test_smart_socket_runtime_preserves_pilot_command_order(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set("switch.car_socket", "off")
    actions = []

    async def set_number(call):
        actions.append(("set_charge_current", call.data["value"]))
        old = hass.states.get("number.car_current")
        assert old is not None
        hass.states.async_set("number.car_current", str(call.data["value"]), old.attributes)

    async def turn_on(call):
        entity = call.data["entity_id"]
        if entity == "switch.car_socket":
            actions.append(("turn_on_smart_socket", None))
            hass.states.async_set(entity, "on")
        else:
            actions.append(("start_charging", None))
            hass.states.async_set(entity, "on")

    hass.services.async_register("number", "set_value", set_number)
    hass.services.async_register("switch", "turn_on", turn_on)
    controller = ActiveEvController(
        hass,
        _coordinator(
            _controller_config(
                ev_charge_path="smart_socket",
                ev_smart_socket_entity="switch.car_socket",
                ev_smart_socket_current_limit_a=10,
            )
        ),
    )
    start = datetime(2026, 9, 7, 12, 1, tzinfo=UTC)

    await controller.async_reconcile(start)
    assert actions == [
        ("set_charge_current", 10),
        ("turn_on_smart_socket", None),
    ]

    await controller.async_reconcile(start + timedelta(seconds=10))
    assert controller.last_reason == "smart_socket_settling"
    assert actions[-1] == ("turn_on_smart_socket", None)

    await controller.async_reconcile(start + timedelta(seconds=16))
    assert actions[-1] == ("start_charging", None)
    assert [action for action, _value in actions] == [
        "set_charge_current",
        "turn_on_smart_socket",
        "start_charging",
    ]


@pytest.mark.freeze_time("2026-09-07 00:01:00+00:00")
async def test_smart_socket_runtime_turns_off_disconnected_socket_outside_window(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set("sensor.car_charging", "disconnected")
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("switch.car_socket", "on")
    calls = []

    async def turn_off(call):
        calls.append(call.data["entity_id"])
        hass.states.async_set("switch.car_socket", "off")

    hass.services.async_register("switch", "turn_off", turn_off)
    controller = ActiveEvController(
        hass,
        _coordinator(
            _controller_config(
                ev_charge_path="smart_socket",
                ev_smart_socket_entity="switch.car_socket",
                ev_smart_socket_current_limit_a=10,
            )
        ),
    )

    await controller.async_reconcile(datetime(2026, 9, 7, 0, 1, tzinfo=UTC))

    assert calls == ["switch.car_socket"]
    assert controller.last_actions == ("turn_off_smart_socket",)
    assert controller.last_reason == "smart_socket_no_charge_command"


@pytest.mark.freeze_time("2026-09-07 12:01:00+00:00")
async def test_smart_socket_recovery_safety_lock_never_latches_or_writes(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set("sensor.car_charging", "no_power")
    hass.states.async_set("switch.car_socket", "on")
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    controller = ActiveEvController(
        hass,
        _coordinator(
            _controller_config(
                rehearsal_mode=True,
                ev_charge_path="smart_socket",
                ev_smart_socket_entity="switch.car_socket",
                ev_smart_socket_current_limit_a=10,
            )
        ),
    )

    await controller.async_reconcile(datetime(2026, 9, 7, 12, 3, tzinfo=UTC))

    assert controller.smart_recovery == SmartSocketRecoveryState()
    assert controller.last_actions == ("would_set_charge_current",)
    assert controller.last_reason == "rehearsal_recovery_current_staged"
    assert calls == []


async def test_direct_path_rearms_persisted_smart_socket_recovery_without_telemetry(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set("sensor.car_charging", "unavailable")
    controller = ActiveEvController(
        hass,
        _coordinator(_controller_config(rehearsal_mode=True)),
    )
    controller.smart_recovery = SmartSocketRecoveryState(
        attempted=True,
        phase="fault",
        phase_started_at=datetime(2026, 9, 7, 0, 0, tzinfo=UTC),
        recovery_current_a=10,
    )

    await controller.async_reconcile(datetime(2026, 9, 7, 12, 1, tzinfo=UTC))

    assert controller.smart_recovery == SmartSocketRecoveryState()


@pytest.mark.freeze_time("2026-09-07 12:01:00+00:00")
async def test_smart_socket_recovery_runtime_is_ordered_and_restart_latched(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set("sensor.car_charging", "no_power")
    hass.states.async_set("switch.car_socket", "on")
    actions = []

    async def set_number(call):
        actions.append("set_charge_current")
        old = hass.states.get("number.car_current")
        assert old is not None
        hass.states.async_set("number.car_current", str(call.data["value"]), old.attributes)

    async def turn_off(call):
        actions.append("turn_off_smart_socket")
        hass.states.async_set(call.data["entity_id"], "off")

    async def turn_on(call):
        entity = call.data["entity_id"]
        if entity == "switch.car_socket":
            actions.append("turn_on_smart_socket")
            hass.states.async_set(entity, "on")
        else:
            actions.append("start_charging")
            hass.states.async_set(entity, "on")

    hass.services.async_register("number", "set_value", set_number)
    hass.services.async_register("switch", "turn_off", turn_off)
    hass.services.async_register("switch", "turn_on", turn_on)
    coordinator = _coordinator(
        _controller_config(
            ev_charge_path="smart_socket",
            ev_smart_socket_entity="switch.car_socket",
            ev_smart_socket_current_limit_a=10,
        )
    )
    controller = ActiveEvController(hass, coordinator)
    start = datetime(2026, 9, 7, 12, 3, tzinfo=UTC)

    await controller.async_reconcile(start)
    await controller.async_reconcile(start + timedelta(seconds=1))
    await controller.async_reconcile(start + timedelta(seconds=2))
    await controller.async_reconcile(start + timedelta(seconds=32))
    await controller.async_reconcile(start + timedelta(seconds=33))
    await controller.async_reconcile(start + timedelta(seconds=53))

    assert actions == [
        "set_charge_current",
        "turn_off_smart_socket",
        "turn_on_smart_socket",
        "start_charging",
    ]
    assert controller.smart_recovery.phase == "confirming_charging"

    hass.states.async_set(
        "sensor.car_charging",
        "charging",
        timestamp=(start + timedelta(seconds=54)).timestamp(),
    )
    await controller.async_reconcile(start + timedelta(seconds=54))
    assert controller.smart_recovery.phase == "recovered"

    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.ev_active.dt_util.now",
        lambda: start + timedelta(seconds=54),
    )
    restored = ActiveEvController(hass, coordinator)
    await restored._async_restore()  # noqa: SLF001
    assert restored.smart_recovery.phase == "recovered"

    hass.states.async_set(
        "sensor.car_charging",
        "no_power",
        timestamp=(start + timedelta(seconds=55)).timestamp(),
    )
    await restored.async_reconcile(start + timedelta(seconds=55))
    assert restored.smart_recovery.phase == "recovered"
    assert actions.count("turn_off_smart_socket") == 1


async def test_runtime_does_not_flap_forever_when_feedback_never_changes(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def ignore(_call):
        return None

    hass.services.async_register("number", "set_value", ignore)
    hass.services.async_register("switch", "turn_on", ignore)
    controller = ActiveEvController(hass, _coordinator(_controller_config()))
    start = datetime(2026, 9, 7, 12, 1, tzinfo=UTC)

    for offset in (0, 30, 60, 90, 120):
        await controller.async_reconcile(start + timedelta(seconds=offset))
    await hass.async_block_till_done()

    assert len(calls) == 9
    assert controller.writes_performed == 9
    assert controller.reconciliation.attempts == 3
    assert controller.reconciliation.phase == "fault_maximum_attempts"
    assert controller.last_reason == "maximum_attempts_reached"


async def test_runtime_fails_closed_when_vehicle_soc_is_unavailable(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set("sensor.car_soc", "unavailable")
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    controller = ActiveEvController(hass, _coordinator(_controller_config()))

    await controller.async_reconcile(datetime(2026, 9, 7, 12, 1, tzinfo=UTC))

    assert controller.last_reason == "ev_soc_unavailable"
    assert calls == []


async def test_daily_driving_snapshot_survives_restart_and_ignores_missed_days(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _controller_config(ev_lifetime_energy_entity="sensor.car_lifetime")
    coordinator = _coordinator(config)
    first = ActiveEvController(hass, coordinator)
    hass.states.async_set("sensor.car_lifetime", "1000", {"unit_of_measurement": "kWh"})
    first_at = datetime(2026, 9, 7, 12, 1, tzinfo=UTC)
    await first._async_snapshot_driving(first_at)  # noqa: SLF001

    hass.states.async_set("sensor.car_lifetime", "1018.5", {"unit_of_measurement": "kWh"})
    second_at = first_at + timedelta(days=1)
    await first._async_snapshot_driving(second_at)  # noqa: SLF001
    assert first.daily_driving_energy_kwh == 18.5
    assert [sample.energy_kwh for sample in first.driving_history.samples] == [18.5]

    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.ev_active.dt_util.now",
        lambda: second_at,
    )
    restored = ActiveEvController(hass, coordinator)
    await restored._async_restore()  # noqa: SLF001
    assert restored.driving_snapshot == first.driving_snapshot
    assert [sample.energy_kwh for sample in restored.driving_history.samples] == [18.5]

    hass.states.async_set("sensor.car_lifetime", "1050", {"unit_of_measurement": "kWh"})
    await restored._async_snapshot_driving(second_at + timedelta(days=2))  # noqa: SLF001
    assert restored.daily_driving_energy_kwh is None
    assert [sample.energy_kwh for sample in restored.driving_history.samples] == [18.5]


async def test_outside_cleanup_uses_pilot_general_limit_fallback(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)

    async def accept(_call):
        return None

    hass.services.async_register("number", "set_value", accept)
    coordinator = _coordinator(
        _controller_config(
            foxess_control_owner="local_modbus",
            ev_solar_spill_enabled=True,
            ev_protected_baseline_a=1,
        )
    )
    controller = ActiveEvController(hass, coordinator)
    controller.outside_control_active = True

    await controller.async_reconcile(datetime(2026, 9, 7, 0, 1, tzinfo=UTC))

    assert controller.learned_charge_limit is not None
    assert controller.learned_charge_limit.mode == "learning_full_window_fallback"
    assert controller.learned_charge_limit.limit_percent == 76
    assert controller.target_limit_percent == 76
