"""Tests for the explicitly commissioned FoxESS controller."""

from __future__ import annotations

from datetime import UTC, datetime, time
from types import SimpleNamespace

from homeassistant.const import EVENT_CALL_SERVICE

from custom_components.home_energy_orchestrator.active import ActiveFoxessController
from custom_components.home_energy_orchestrator.active_ev import ActiveEvController
from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_BONUS_WINDOW_START,
    CONF_DISCHARGE_EFFICIENCY_PERCENT,
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_EV_CHARGE_LIMIT,
    CONF_EV_CHARGE_SWITCH,
    CONF_EV_CURRENT_LIMIT,
    CONF_EV_MAX_CURRENT,
    CONF_EV_MIN_CURRENT,
    CONF_EV_PHASE_COUNT,
    CONF_EV_PROTECTED_BASELINE_A,
    CONF_EV_SOC,
    CONF_EV_VOLTAGE,
    CONF_EXPORT_ALLOWANCE_KWH,
    CONF_EXPORT_DISCHARGE_POWER_KW,
    CONF_FORCE_DISCHARGE_FINISH,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_FREE_CHARGE_START,
    CONF_INVERTER_CAPACITY,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_REHEARSAL_MODE,
    CONF_SERVICE_IMPORT_LIMIT_A,
    FOXESS_CONTROL_OWNER_CLOUD,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from custom_components.home_energy_orchestrator.planner.export_session import (
    ExportSessionState,
)


def _coordinator(**config):
    values = {
        CONF_AUTOMATIC_CONTROL_ENABLED: False,
        CONF_FOXESS_CONTROL_OWNER: FOXESS_CONTROL_OWNER_MODBUS,
        CONF_EV_AUTOMATIC_CONTROL_ENABLED: False,
        CONF_REHEARSAL_MODE: True,
        CONF_FOXESS_WORK_MODE: "select.foxess_mode",
        CONF_FOXESS_FORCE_CHARGE_POWER: "number.foxess_charge",
        CONF_FOXESS_FORCE_DISCHARGE_POWER: "number.foxess_discharge",
        CONF_INVERTER_CHARGE_LIMIT_KW: 15.0,
        **config,
    }
    return SimpleNamespace(
        config=values,
        snapshot=SimpleNamespace(
            battery_soc=60.0,
            battery_capacity_kwh=38.0,
            battery_floor_percent=10.0,
            grid_power_kw=0.0,
            house_load_kw=0.0,
            ev_soc=60.0,
        ),
        data=SimpleNamespace(
            grid_import_kw=0.0,
            free_window_import_kwh=0.0,
            available_after_reserve_kwh=0.0,
        ),
        free_charge_plan=SimpleNamespace(target_charge_power_kw=5.0),
        free_charge_completion=SimpleNamespace(action="continue"),
        _free_window_hours_remaining=lambda _now: 1.0,
        _power=lambda _entity: 0.0,
        _configured_time=lambda _key, default: time.fromisoformat(default),
        _bonus_window_active=lambda _now: False,
        learning_remaining_kwh=4.0,
        zerohero_export=SimpleNamespace(imported_kwh=0.0),
    )


async def test_controller_is_inert_when_automatic_control_is_disabled(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    controller = ActiveFoxessController(hass, _coordinator())

    await controller.async_reconcile()

    assert calls == []


async def test_cloud_scheduler_owner_blocks_all_modbus_automation_writes(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    controller = ActiveFoxessController(
        hass,
        _coordinator(
            **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_EXPORT_ENABLED: True,
            CONF_FOXESS_CONTROL_OWNER: FOXESS_CONTROL_OWNER_CLOUD,
                CONF_REHEARSAL_MODE: False,
            }
        ),
    )

    await controller.async_reconcile()

    assert controller.gate_status == "foxcloud_scheduler_owner"
    assert controller.last_reason == "foxcloud_scheduler_owns_inverter"
    assert calls == []


async def test_rehearsal_mode_is_an_absolute_no_write_gate(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    controller = ActiveFoxessController(
        hass,
        _coordinator(**{CONF_AUTOMATIC_CONTROL_ENABLED: True}),
    )

    await controller.async_reconcile()

    assert calls == []


async def test_commissioned_controller_executes_bounded_charge_plan(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def noop(_call):
        return None

    hass.services.async_register("number", "set_value", noop)
    hass.services.async_register("select", "select_option", noop)
    hass.states.async_set("select.foxess_mode", "Self Use")
    hass.states.async_set("number.foxess_charge", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("number.foxess_discharge", "0", {"unit_of_measurement": "kW"})
    controller = ActiveFoxessController(
        hass,
        _coordinator(
            **{
                CONF_AUTOMATIC_CONTROL_ENABLED: True,
                CONF_REHEARSAL_MODE: False,
            }
        ),
    )

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert [(event.data["domain"], event.data["service"]) for event in calls] == [
        ("number", "set_value"),
        ("select", "select_option"),
    ]
    assert calls[0].data["service_data"]["value"] == 5.0
    assert calls[1].data["service_data"]["option"] == "Force Charge"


async def test_cutoff_restores_self_use_even_when_battery_is_not_full(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def noop(_call):
        return None

    hass.services.async_register("number", "set_value", noop)
    hass.services.async_register("select", "select_option", noop)
    hass.states.async_set("select.foxess_mode", "Force Charge")
    hass.states.async_set("number.foxess_charge", "15", {"unit_of_measurement": "kW"})
    hass.states.async_set("number.foxess_discharge", "0", {"unit_of_measurement": "kW"})
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
        }
    )
    coordinator.snapshot.battery_soc = 80.0
    coordinator.free_charge_plan = SimpleNamespace(target_charge_power_kw=0.0)
    coordinator.free_charge_completion = SimpleNamespace(action="self_use")
    controller = ActiveFoxessController(hass, coordinator)

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert [(event.data["domain"], event.data["service"]) for event in calls] == [
        ("select", "select_option"),
        ("number", "set_value"),
    ]
    assert calls[0].data["service_data"]["option"] == "Self Use"
    assert calls[1].data["service_data"]["value"] == 0.0


async def test_mangerton_export_starts_at_latest_start_and_latches(hass, monkeypatch):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def noop(_call):
        return None

    async def no_wait(_seconds):
        return None

    hass.services.async_register("number", "set_value", noop)
    hass.services.async_register("select", "select_option", noop)
    hass.states.async_set(
        "select.foxess_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    hass.states.async_set("number.foxess_charge", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set(
        "number.foxess_discharge",
        "0",
        {"unit_of_measurement": "kW", "max": 15},
    )
    now = datetime(2026, 9, 5, 19, 31, tzinfo=UTC)
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now", lambda: now
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep", no_wait
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_EXPORT_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_INVERTER_DISCHARGE_LIMIT_KW: 15.0,
            CONF_EXPORT_DISCHARGE_POWER_KW: 10.0,
            CONF_EXPORT_ALLOWANCE_KWH: 15.0,
            CONF_DISCHARGE_EFFICIENCY_PERCENT: 95.0,
            CONF_BONUS_WINDOW_START: "18:00:00",
            CONF_FORCE_DISCHARGE_FINISH: "21:01:00",
            CONF_FREE_CHARGE_START: "12:01:00",
        }
    )
    coordinator.data.available_after_reserve_kwh = 30.0
    controller = ActiveFoxessController(hass, coordinator)

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert controller.export_planned_start == now
    assert controller.export_session.phase == "starting"
    assert controller.export_session.requested_power_kw == 10.0
    assert [(event.data["domain"], event.data["service"]) for event in calls] == [
        ("number", "set_value"),
        ("select", "select_option"),
    ]
    assert calls[0].data["service_data"]["value"] == 10.0
    assert calls[1].data["service_data"]["option"] == "Force Discharge"

    hass.states.async_set(
        "select.foxess_mode",
        "Force Discharge",
        {"options": ["Self Use", "Force Discharge"]},
    )
    hass.states.async_set(
        "number.foxess_discharge", "10", {"unit_of_measurement": "kW", "max": 15}
    )
    coordinator.data.available_after_reserve_kwh = 0.0
    coordinator.learning_remaining_kwh = 99.0
    await controller.async_reconcile()
    assert controller.export_session.phase == "active"
    assert controller.export_session.requested_power_kw == 10.0
    assert len(calls) == 2


async def test_export_session_latch_round_trips_through_ha_storage(hass):
    coordinator = _coordinator()
    coordinator.entry_id = "persisted-export-test"
    first = ActiveFoxessController(hass, coordinator)
    first.export_session = ExportSessionState(
        "recovering", 8.5, 2, datetime(2026, 9, 5, 20, 0, tzinfo=UTC)
    )
    await first._export_store.async_save(first._export_state_payload())

    restored = ActiveFoxessController(hass, coordinator)
    await restored._async_load_export_session()

    assert restored.export_session == first.export_session


async def test_ev_controller_is_inert_in_rehearsal_mode(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_EV_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_EV_CURRENT_LIMIT: "number.tessy_charge_current",
            CONF_EV_CHARGE_SWITCH: "switch.tessy_charge",
        }
    )
    controller = ActiveEvController(hass, coordinator)

    await controller.async_reconcile()

    assert calls == []
    assert controller.gate_status == "rehearsal"


async def test_export_protects_only_configured_connected_ev_baseline(hass):
    hass.states.async_set("device_tracker.tessy_location", "home")
    hass.states.async_set(
        "sensor.tessy_charger_current",
        "0",
        {"friendly_name": "Tessy Charger current"},
    )
    hass.states.async_set(
        "binary_sensor.tessy_charge_cable",
        "on",
        {"friendly_name": "Tessy Charge cable"},
    )
    controller = ActiveEvController(
        hass,
        _coordinator(
            **{
                CONF_EV_PROTECTED_BASELINE_A: 1.0,
                CONF_EV_VOLTAGE: 230.0,
                CONF_EV_PHASE_COUNT: 1,
            }
        ),
    )

    assert controller.protected_keepalive_energy_kwh(15) == 3.45

    hass.states.async_set("binary_sensor.tessy_charge_cable", "off")
    assert controller.protected_keepalive_energy_kwh(15) == 0.0


async def test_ev_controller_is_inert_when_only_foxess_control_is_enabled(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_EV_AUTOMATIC_CONTROL_ENABLED: False,
            CONF_REHEARSAL_MODE: False,
            CONF_EV_CURRENT_LIMIT: "number.tessy_charge_current",
            CONF_EV_CHARGE_SWITCH: "switch.tessy_charge",
        }
    )
    controller = ActiveEvController(hass, coordinator)

    await controller.async_reconcile()

    assert controller.gate_status == "disabled"
    assert controller.last_reason == "automatic_ev_control_disabled"
    assert calls == []


async def test_ev_controller_adjusts_mapped_current_only_when_commissioned(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def noop(_call):
        return None

    hass.services.async_register("number", "set_value", noop)
    hass.states.async_set("device_tracker.tessy_location", "home")
    # Tessie's entity advertises 32 A, but the commissioned charger profile is
    # 16 A and must remain the physical authority.
    hass.states.async_set("number.tessy_charge_current", "16", {"min": 0, "max": 32, "step": 1})
    hass.states.async_set("switch.tessy_charge", "on")
    hass.states.async_set(
        "sensor.tessy_charger_current", "16", {"friendly_name": "Tessy Charger current"}
    )
    hass.states.async_set(
        "binary_sensor.tessy_charge_cable", "on", {"friendly_name": "Tessy Charge cable"}
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: False,
            CONF_EV_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_EV_SOC: "sensor.tessy_battery_level",
            CONF_EV_CURRENT_LIMIT: "number.tessy_charge_current",
            CONF_EV_CHARGE_SWITCH: "switch.tessy_charge",
            CONF_EV_MAX_CURRENT: 16.0,
            CONF_EV_MIN_CURRENT: 6.0,
            CONF_EV_PHASE_COUNT: 1,
            CONF_EV_VOLTAGE: 230.0,
            CONF_INVERTER_CAPACITY: 10.0,
            CONF_SERVICE_IMPORT_LIMIT_A: 32.0,
        }
    )
    coordinator.snapshot.ev_soc = 60.0
    coordinator.snapshot.grid_power_kw = 8.0
    controller = ActiveEvController(hass, coordinator)

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert controller.gate_status == "ready"
    assert [(event.data["domain"], event.data["service"]) for event in calls] == [
        ("number", "set_value")
    ]
    assert calls[0].data["service_data"]["value"] == 12.0


async def test_ev_controller_does_not_change_current_when_vehicle_is_away(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def noop(_call):
        return None

    hass.services.async_register("number", "set_value", noop)
    hass.states.async_set("device_tracker.tessy_location", "not_home")
    hass.states.async_set("number.tessy_charge_current", "16", {"min": 0, "max": 16, "step": 1})
    hass.states.async_set("switch.tessy_charge", "on")
    hass.states.async_set(
        "sensor.tessy_charger_current", "16", {"friendly_name": "Tessy Charger current"}
    )
    hass.states.async_set(
        "binary_sensor.tessy_charge_cable", "on", {"friendly_name": "Tessy Charge cable"}
    )
    coordinator = _coordinator(
        **{
            CONF_EV_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_EV_CURRENT_LIMIT: "number.tessy_charge_current",
            CONF_EV_CHARGE_SWITCH: "switch.tessy_charge",
        }
    )
    controller = ActiveEvController(hass, coordinator)

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert controller.last_reason == "away"
    assert calls == []


async def test_ev_controller_starts_a_mapped_session_when_target_is_not_reached(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def noop(_call):
        return None

    hass.services.async_register("number", "set_value", noop)
    hass.services.async_register("switch", "turn_on", noop)
    hass.states.async_set("device_tracker.tessy_location", "home")
    hass.states.async_set("number.tessy_charge_current", "10", {"min": 0, "max": 16, "step": 1})
    hass.states.async_set("number.tessy_charge_limit", "80")
    hass.states.async_set("switch.tessy_charge", "off")
    hass.states.async_set(
        "sensor.tessy_charger_current", "0", {"friendly_name": "Tessy Charger current"}
    )
    hass.states.async_set(
        "binary_sensor.tessy_charge_cable", "on", {"friendly_name": "Tessy Charge cable"}
    )
    coordinator = _coordinator(
        **{
            CONF_EV_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_EV_CHARGE_LIMIT: "number.tessy_charge_limit",
            CONF_EV_CURRENT_LIMIT: "number.tessy_charge_current",
            CONF_EV_CHARGE_SWITCH: "switch.tessy_charge",
        }
    )
    coordinator.snapshot.ev_soc = 40.0
    controller = ActiveEvController(hass, coordinator)

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert [(event.data["domain"], event.data["service"]) for event in calls] == [
        ("number", "set_value"),
        ("switch", "turn_on"),
    ]
    assert controller._session_started is True


async def test_ev_controller_stops_only_a_session_it_started_at_target(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def noop(_call):
        return None

    hass.services.async_register("switch", "turn_off", noop)
    hass.states.async_set("device_tracker.tessy_location", "home")
    hass.states.async_set("number.tessy_charge_current", "10", {"min": 0, "max": 16, "step": 1})
    hass.states.async_set("number.tessy_charge_limit", "80")
    hass.states.async_set("switch.tessy_charge", "on")
    hass.states.async_set(
        "sensor.tessy_charger_current", "10", {"friendly_name": "Tessy Charger current"}
    )
    hass.states.async_set(
        "binary_sensor.tessy_charge_cable", "on", {"friendly_name": "Tessy Charge cable"}
    )
    coordinator = _coordinator(
        **{
            CONF_EV_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_EV_CHARGE_LIMIT: "number.tessy_charge_limit",
            CONF_EV_CURRENT_LIMIT: "number.tessy_charge_current",
            CONF_EV_CHARGE_SWITCH: "switch.tessy_charge",
        }
    )
    coordinator.snapshot.ev_soc = 80.0
    controller = ActiveEvController(hass, coordinator)
    controller._session_started = True

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert [(event.data["domain"], event.data["service"]) for event in calls] == [
        ("switch", "turn_off")
    ]
    assert controller.last_reason == "target_reached"


async def test_ev_controller_stops_owned_session_at_allowance_cutoff(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def noop(_call):
        return None

    hass.services.async_register("switch", "turn_off", noop)
    hass.states.async_set("device_tracker.tessy_location", "home")
    hass.states.async_set("number.tessy_charge_current", "16", {"min": 0, "max": 16})
    hass.states.async_set("number.tessy_charge_limit", "80")
    hass.states.async_set("switch.tessy_charge", "on")
    hass.states.async_set(
        "sensor.tessy_charger_current", "16", {"friendly_name": "Tessy Charger current"}
    )
    hass.states.async_set(
        "binary_sensor.tessy_charge_cable", "on", {"friendly_name": "Tessy Charge cable"}
    )
    coordinator = _coordinator(
        **{
            CONF_EV_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_EV_CHARGE_LIMIT: "number.tessy_charge_limit",
            CONF_EV_CURRENT_LIMIT: "number.tessy_charge_current",
            CONF_EV_CHARGE_SWITCH: "switch.tessy_charge",
        }
    )
    coordinator.data.free_window_import_kwh = 49.0
    controller = ActiveEvController(hass, coordinator)
    controller._session_started = True

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert [(event.data["domain"], event.data["service"]) for event in calls] == [
        ("switch", "turn_off")
    ]
    assert controller.last_reason == "free_allowance_cutoff_reached"


async def test_ev_controller_does_not_stop_unowned_session_at_cutoff(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    hass.states.async_set("device_tracker.tessy_location", "home")
    hass.states.async_set("number.tessy_charge_current", "16", {"min": 0, "max": 16})
    hass.states.async_set("switch.tessy_charge", "on")
    hass.states.async_set(
        "sensor.tessy_charger_current", "16", {"friendly_name": "Tessy Charger current"}
    )
    hass.states.async_set(
        "binary_sensor.tessy_charge_cable", "on", {"friendly_name": "Tessy Charge cable"}
    )
    coordinator = _coordinator(
        **{
            CONF_EV_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_EV_CURRENT_LIMIT: "number.tessy_charge_current",
            CONF_EV_CHARGE_SWITCH: "switch.tessy_charge",
        }
    )
    coordinator.data.free_window_import_kwh = 49.0
    controller = ActiveEvController(hass, coordinator)

    await controller.async_reconcile()

    assert calls == []
    assert controller.last_reason == "free_allowance_cutoff_reached"
