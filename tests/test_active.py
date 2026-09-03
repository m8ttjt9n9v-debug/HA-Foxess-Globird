"""Tests for the explicitly commissioned FoxESS controller."""

from __future__ import annotations

from datetime import time
from types import SimpleNamespace

from homeassistant.const import EVENT_CALL_SERVICE

from custom_components.home_energy_orchestrator.active import ActiveFoxessController
from custom_components.home_energy_orchestrator.active_ev import ActiveEvController
from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_REHEARSAL_MODE,
    CONF_EV_CHARGE_SWITCH,
    CONF_EV_CURRENT_LIMIT,
    CONF_EV_SOC,
    CONF_EV_MAX_CURRENT,
    CONF_EV_MIN_CURRENT,
    CONF_EV_PHASE_COUNT,
    CONF_EV_VOLTAGE,
    CONF_INVERTER_CAPACITY,
    CONF_SERVICE_IMPORT_LIMIT_A,
)


def _coordinator(**config):
    values = {
        CONF_AUTOMATIC_CONTROL_ENABLED: False,
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
            battery_floor_percent=10.0,
            grid_power_kw=0.0,
            house_load_kw=0.0,
            ev_soc=60.0,
        ),
        data=SimpleNamespace(grid_import_kw=0.0, available_after_reserve_kwh=0.0),
        free_charge_plan=SimpleNamespace(target_charge_power_kw=5.0),
        free_charge_completion=SimpleNamespace(action="continue"),
        _free_window_hours_remaining=lambda _now: 1.0,
        _power=lambda _entity: 0.0,
        _configured_time=lambda _key, default: time.fromisoformat(default),
        _bonus_window_active=lambda _now: False,
    )


async def test_controller_is_inert_when_automatic_control_is_disabled(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    controller = ActiveFoxessController(hass, _coordinator())

    await controller.async_reconcile()

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


async def test_ev_controller_is_inert_in_rehearsal_mode(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_EV_CURRENT_LIMIT: "number.tessy_charge_current",
            CONF_EV_CHARGE_SWITCH: "switch.tessy_charge",
        }
    )
    controller = ActiveEvController(hass, coordinator)

    await controller.async_reconcile()

    assert calls == []
    assert controller.gate_status == "rehearsal"


async def test_ev_controller_adjusts_mapped_current_only_when_commissioned(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def noop(_call):
        return None

    hass.services.async_register("number", "set_value", noop)
    hass.states.async_set("device_tracker.tessy_location", "home")
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
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
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
    hass.states.async_set("sensor.tessy_charger_current", "16", {"friendly_name": "Tessy Charger current"})
    hass.states.async_set("binary_sensor.tessy_charge_cable", "on", {"friendly_name": "Tessy Charge cable"})
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
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
