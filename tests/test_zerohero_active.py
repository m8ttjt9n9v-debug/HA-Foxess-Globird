"""Tests for the ported Mangerton ZEROHERO controller."""

from __future__ import annotations

from datetime import UTC, datetime, time
from types import SimpleNamespace

from homeassistant.const import EVENT_CALL_SERVICE

from custom_components.home_energy_orchestrator.active import ActiveFoxessController
from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_BONUS_WINDOW_START,
    CONF_DISCHARGE_EFFICIENCY_PERCENT,
    CONF_EV_AT_HOME,
    CONF_EV_CABLE_CONNECTED,
    CONF_EV_PHASE_COUNT,
    CONF_EV_PROTECTED_BASELINE_A,
    CONF_EV_VOLTAGE,
    CONF_EXPORT_ALLOWANCE_KWH,
    CONF_EXPORT_DISCHARGE_POWER_KW,
    CONF_FORCE_DISCHARGE_FINISH,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_FREE_CHARGE_START,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_REHEARSAL_MODE,
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
        CONF_REHEARSAL_MODE: True,
        CONF_FOXESS_WORK_MODE: "select.foxess_mode",
        CONF_FOXESS_FORCE_CHARGE_POWER: "number.foxess_charge",
        CONF_FOXESS_FORCE_DISCHARGE_POWER: "number.foxess_discharge",
        CONF_INVERTER_CHARGE_LIMIT_KW: 15.0,
        **config,
    }
    return SimpleNamespace(
        config=values,
        snapshot=SimpleNamespace(battery_soc=60.0),
        data=SimpleNamespace(available_after_reserve_kwh=0.0),
        _configured_time=lambda _key, default: time.fromisoformat(default),
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
        hass, _coordinator(**{CONF_AUTOMATIC_CONTROL_ENABLED: True})
    )

    await controller.async_reconcile()

    assert calls == []


async def test_master_gate_alone_cannot_write_at_midnight(hass, monkeypatch):
    """The removed free-charge reconciler must not survive behind the master gate."""
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    hass.states.async_set(
        "select.foxess_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    hass.states.async_set("number.foxess_charge", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime(2026, 9, 6, 0, 1, tzinfo=UTC),
    )
    controller = ActiveFoxessController(
        hass,
        _coordinator(
            **{
                CONF_AUTOMATIC_CONTROL_ENABLED: True,
                CONF_AUTOMATIC_EXPORT_ENABLED: False,
                CONF_REHEARSAL_MODE: False,
                CONF_INVERTER_DISCHARGE_LIMIT_KW: 15.0,
            }
        ),
    )

    await controller.async_reconcile()

    assert controller.last_reason == "zerohero_export_not_active"
    assert controller.export_session.phase == "idle"
    assert calls == []


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
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 15}
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


async def test_export_protects_only_explicit_connected_ev_baseline(hass):
    hass.states.async_set("device_tracker.car", "home")
    hass.states.async_set("binary_sensor.car_cable", "on")
    controller = ActiveFoxessController(
        hass,
        _coordinator(
            **{
                CONF_EV_PROTECTED_BASELINE_A: 1.0,
                CONF_EV_VOLTAGE: 230.0,
                CONF_EV_PHASE_COUNT: 1,
                CONF_EV_AT_HOME: "device_tracker.car",
                CONF_EV_CABLE_CONNECTED: "binary_sensor.car_cable",
            }
        ),
    )

    assert controller._protected_keepalive_energy_kwh(15) == 3.45
    hass.states.async_set("binary_sensor.car_cable", "off")
    assert controller._protected_keepalive_energy_kwh(15) == 0.0


async def test_nonzero_ev_baseline_fails_closed_without_explicit_evidence(hass):
    controller = ActiveFoxessController(
        hass, _coordinator(**{CONF_EV_PROTECTED_BASELINE_A: 1.0})
    )

    assert controller._protected_keepalive_energy_kwh(15) is None
