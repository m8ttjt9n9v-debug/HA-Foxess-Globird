from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace

from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import HomeAssistant

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.models import SiteSnapshot
from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    PreFreeSessionState,
)
from custom_components.home_energy_orchestrator.planner.export import ExportPlan
from custom_components.home_energy_orchestrator.planner.export_session import (
    ExportSessionState,
)


def _controller_config(**changes):
    config = {
        "battery_soc_entity": "sensor.site_battery_soc",
        "automatic_control_enabled": False,
        "foxess_control_owner": "foxcloud_scheduler",
        "ev_automatic_control_enabled": True,
        "ev_control_commissioned": True,
        "rehearsal_mode": False,
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
        "site_phase_count": 1,
        "service_import_limit_a": 63,
        "site_grid_headroom_current_a": 1,
        "free_charge_window_start": "12:01:00",
        "free_charge_window_end": "14:59:00",
    }
    config.update(changes)
    return config


def _coordinator(config):
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
        free_window_import=SimpleNamespace(last_at=None, imported_kwh=0),
        _configured_time=lambda key, default: time.fromisoformat(str(config.get(key, default))),
        async_update_listeners=lambda: None,
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


async def test_ev_runtime_never_stops_or_changes_direct_path_outside_free_window(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    controller = ActiveEvController(hass, _coordinator(_controller_config()))

    await controller.async_reconcile(datetime(2026, 9, 7, 0, 1, tzinfo=UTC))

    assert controller.last_reason == "outside_free_window_no_direct_write"
    assert calls == []


async def test_cloud_owner_blocks_opted_in_outside_window_stages(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
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

    assert controller.last_reason == "outside_free_window_no_direct_write"
    assert calls == []


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
            battery_charge_positive=True,
            grid_power_entity="sensor.site_grid",
            grid_import_positive=True,
            bonus_window_start="21:00:00",
            bonus_window_end="22:00:00",
        )
    )
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


async def test_opted_in_outside_policy_restores_baseline_after_reconnect(
    hass: HomeAssistant,
) -> None:
    _set_ev_states(hass)
    hass.states.async_set(
        "number.car_current",
        "10",
        {"min": 1, "max": 16, "step": 1, "unit_of_measurement": "A"},
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
    controller = ActiveEvController(hass, coordinator)
    battery_state = hass.states.get("sensor.battery_power")
    assert battery_state is not None

    await controller.async_reconcile(battery_state.last_updated)

    assert controller.solar_spill.phase == "battery_not_full"
    assert controller.target_current_a == 1
    assert controller.outside_control_active is True
    current_calls = [
        event
        for event in calls
        if event.data["domain"] == "number"
        and event.data["service_data"].get("value") == 1
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


async def test_smart_socket_selection_remains_non_writing_until_runtime_connected(
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
    assert controller.last_reason == "smart_socket_runtime_not_connected"
    assert controller.writes_performed == 0
    assert calls == []


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
