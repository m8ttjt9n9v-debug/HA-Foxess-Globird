"""Tests for the preview-first FoxESS commissioning test surface."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.const import EVENT_CALL_SERVICE

from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_REHEARSAL_MODE,
    FOXESS_CONTROL_OWNER_CLOUD,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from custom_components.home_energy_orchestrator.manual_test import (
    ManualTestController,
    ManualTestError,
)
from custom_components.home_energy_orchestrator.planner.manual_test import (
    estimate_charge,
    estimate_discharge,
)


def test_charge_preview_uses_free_allowance_before_balance_rate() -> None:
    estimate = estimate_charge(
        10.0,
        60.0,
        free_window_active=True,
        free_energy_remaining_kwh=4.0,
        offpeak_rate=0.0,
        offpeak_balance_rate=0.308,
        current_rate=0.594,
    )

    assert estimate.energy_kwh == 10.0
    assert estimate.amount == 1.85
    assert estimate.direction == "cost"


def test_discharge_preview_reports_explicit_export_earning() -> None:
    estimate = estimate_discharge(7.4, 30.0, export_rate=0.10)

    assert estimate.energy_kwh == 3.7
    assert estimate.amount == 0.37
    assert estimate.direction == "earning"


def _coordinator(**config):
    free_window_hours = config.pop("free_window_hours", 1.0)
    values = {
        CONF_AUTOMATIC_CONTROL_ENABLED: True,
        CONF_FOXESS_CONTROL_OWNER: FOXESS_CONTROL_OWNER_MODBUS,
        CONF_REHEARSAL_MODE: False,
        CONF_FOXESS_WORK_MODE: "select.foxess_mode",
        CONF_FOXESS_FORCE_CHARGE_POWER: "number.foxess_charge",
        CONF_FOXESS_FORCE_DISCHARGE_POWER: "number.foxess_discharge",
        CONF_INVERTER_CHARGE_LIMIT_KW: 15.0,
        CONF_INVERTER_DISCHARGE_LIMIT_KW: 15.0,
        **config,
    }
    return SimpleNamespace(
        config=values,
        snapshot=SimpleNamespace(battery_soc=70.0, battery_floor_percent=10.0),
        data=SimpleNamespace(free_energy_remaining_kwh=49.0),
        _free_window_hours_remaining=lambda _now: free_window_hours,
        _configured_time=lambda _key, default: __import__("datetime").time.fromisoformat(default),
        async_update_listeners=lambda: None,
    )


async def test_controller_requires_rehearsal_off(hass) -> None:
    coordinator = _coordinator(**{CONF_REHEARSAL_MODE: True})
    controller = ManualTestController(hass, coordinator)

    with pytest.raises(ManualTestError, match="Rehearsal mode"):
        await controller.async_start("charge", 1.0, 1.0)


async def test_controller_blocks_diagnostic_when_cloud_scheduler_owns_inverter(hass) -> None:
    coordinator = _coordinator(
        **{CONF_FOXESS_CONTROL_OWNER: FOXESS_CONTROL_OWNER_CLOUD}
    )
    controller = ManualTestController(hass, coordinator)

    with pytest.raises(ManualTestError, match="Local Modbus"):
        await controller.async_start("charge", 1.0, 1.0)


async def test_controller_blocks_charge_outside_free_window(hass) -> None:
    coordinator = _coordinator(free_window_hours=0.0)
    controller = ManualTestController(hass, coordinator)

    hass.states.async_set("select.foxess_mode", "Self Use")
    hass.states.async_set("number.foxess_charge", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("number.foxess_discharge", "0", {"unit_of_measurement": "kW"})

    with pytest.raises(ManualTestError, match="outside the free window"):
        await controller.async_start("charge", 1.0, 1.0)


async def test_controller_blocks_charge_when_battery_is_full(hass) -> None:
    coordinator = _coordinator()
    coordinator.snapshot.battery_soc = 100.0
    controller = ManualTestController(hass, coordinator)

    with pytest.raises(ManualTestError, match="already at 100%"):
        await controller.async_start("charge", 1.0, 1.0)


async def test_controller_starts_and_stops_a_timed_test(hass) -> None:
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def noop(_call):
        return None

    hass.services.async_register("number", "set_value", noop)
    hass.services.async_register("select", "select_option", noop)
    hass.states.async_set("select.foxess_mode", "Self Use")
    hass.states.async_set("number.foxess_charge", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("number.foxess_discharge", "0", {"unit_of_measurement": "kW"})

    coordinator = _coordinator()
    controller = ManualTestController(hass, coordinator)
    await controller.async_start("charge", 2.0, 1.0)
    await hass.async_block_till_done()

    assert controller.status == "active_charge"
    assert [(event.data["domain"], event.data["service"]) for event in calls] == [
        ("number", "set_value"),
        ("select", "select_option"),
    ]
    assert calls[0].data["service_data"]["value"] == 2.0
    assert calls[1].data["service_data"]["option"] == "Force Charge"

    # Simulate the inverter's feedback after accepting the request before
    # asking the controller to restore normal operation.
    hass.states.async_set("select.foxess_mode", "Force Charge")
    hass.states.async_set("number.foxess_charge", "2", {"unit_of_measurement": "kW"})
    await controller.async_stop()
    await hass.async_block_till_done()
    assert controller.status == "idle"
    assert any(
        event.data["service"] == "select_option"
        and event.data["service_data"]["option"] == "Self Use"
        for event in calls
    )


async def test_stop_clears_targets_when_feedback_disappears(hass) -> None:
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    async def noop(_call):
        return None

    hass.services.async_register("number", "set_value", noop)
    hass.services.async_register("select", "select_option", noop)
    coordinator = _coordinator()
    controller = ManualTestController(hass, coordinator)
    controller.active_kind = "discharge"

    await controller.async_stop("feedback_lost")
    await hass.async_block_till_done()

    assert controller.status == "idle"
    assert [(event.data["domain"], event.data["service"]) for event in calls] == [
        ("select", "select_option"),
        ("number", "set_value"),
        ("number", "set_value"),
    ]
    assert calls[0].data["service_data"]["option"] == "Self Use"
    assert all(call.data["service_data"]["value"] == 0.0 for call in calls[1:])
