"""Tests for the explicitly commissioned FoxESS controller."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.const import EVENT_CALL_SERVICE

from custom_components.home_energy_orchestrator.active import ActiveFoxessController
from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_REHEARSAL_MODE,
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
        snapshot=SimpleNamespace(battery_soc=60.0, battery_floor_percent=10.0),
        data=SimpleNamespace(grid_import_kw=0.0),
        free_charge_plan=SimpleNamespace(target_charge_power_kw=5.0),
        free_charge_completion=SimpleNamespace(action="continue"),
        _free_window_hours_remaining=lambda _now: 1.0,
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
