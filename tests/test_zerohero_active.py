"""Tests for the ported Working Single Phase Pilot Site ZEROHERO controller."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.const import EVENT_CALL_SERVICE

from custom_components.home_energy_orchestrator.active import ActiveFoxessController
from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_AUTOMATIC_EXPORT_LIMIT_KWH,
    CONF_BATTERY_FREE_WINDOW_TARGET,
    CONF_BONUS_WINDOW_END,
    CONF_BONUS_WINDOW_START,
    CONF_DISCHARGE_EFFICIENCY_PERCENT,
    CONF_EV_AT_HOME,
    CONF_EV_BEFORE_EXPORT_ENABLED,
    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
    CONF_EV_CABLE_CONNECTED,
    CONF_EV_CONTROL_COMMISSIONED,
    CONF_EV_PHASE_COUNT,
    CONF_EV_PROTECTED_BASELINE_A,
    CONF_EV_VOLTAGE,
    CONF_EXPORT_ALLOWANCE_KWH,
    CONF_EXPORT_DISCHARGE_POWER_KW,
    CONF_FORCE_DISCHARGE_FINISH,
    CONF_FORCE_DISCHARGE_OFFSET_MINUTES,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_FREE_CHARGE_END,
    CONF_FREE_CHARGE_SCHEDULE_CONFIRMED,
    CONF_FREE_CHARGE_START,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_REHEARSAL_MODE,
    CONF_SIGN_CONVENTIONS_VERIFIED,
    FOXESS_CONTROL_OWNER_CLOUD,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from custom_components.home_energy_orchestrator.planner.charge_session import (
    ChargeSessionState,
)
from custom_components.home_energy_orchestrator.planner.export_session import (
    ExportSessionState,
)


def _coordinator(**config):
    values = {
        CONF_AUTOMATIC_CONTROL_ENABLED: False,
        CONF_AUTOMATIC_CHARGE_ENABLED: False,
        CONF_FREE_CHARGE_SCHEDULE_CONFIRMED: True,
        CONF_FOXESS_CONTROL_OWNER: FOXESS_CONTROL_OWNER_MODBUS,
        CONF_REHEARSAL_MODE: True,
        CONF_SIGN_CONVENTIONS_VERIFIED: True,
        CONF_FOXESS_WORK_MODE: "select.foxess_mode",
        CONF_FOXESS_FORCE_CHARGE_POWER: "number.foxess_charge",
        CONF_FOXESS_FORCE_DISCHARGE_POWER: "number.foxess_discharge",
        CONF_INVERTER_CHARGE_LIMIT_KW: 15.0,
        **config,
    }
    def free_window_hours_remaining(now):
        start = time.fromisoformat(str(values.get(CONF_FREE_CHARGE_START, "12:01:00")))
        end = time.fromisoformat(str(values.get(CONF_FREE_CHARGE_END, "14:59:00")))
        current = now.timetz().replace(tzinfo=None)
        if start < end:
            if not start <= current < end:
                return 0.0
            finish = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
        else:
            if end <= current < start:
                return 0.0
            finish = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
            if current >= start:
                finish += timedelta(days=1)
        return max((finish - now).total_seconds() / 3600, 0.0)

    return SimpleNamespace(
        config=values,
        runtime_config=RuntimeConfiguration.from_mapping(values),
        snapshot=SimpleNamespace(battery_soc=60.0),
        data=SimpleNamespace(
            available_after_reserve_kwh=0.0,
            free_energy_remaining_kwh=50.0,
        ),
        _configured_time=lambda key, default: time.fromisoformat(
            str(values.get(key, default))
        ),
        _free_window_hours_remaining=free_window_hours_remaining,
        learning_remaining_kwh=4.0,
        zerohero_export=SimpleNamespace(imported_kwh=0.0),
    )


@pytest.mark.parametrize(
    ("overrides", "expected_gate", "expected_reason"),
    [
        (
            {CONF_FOXESS_CONTROL_OWNER: FOXESS_CONTROL_OWNER_CLOUD},
            "foxcloud_scheduler_owner",
            "foxcloud_scheduler_owns_inverter",
        ),
        (
            {CONF_FOXESS_CONTROL_OWNER: "observer_only"},
            "observer_owner",
            "foxess_observer_owner",
        ),
        (
            {CONF_AUTOMATIC_CONTROL_ENABLED: False},
            "disabled",
            "automatic_control_disabled",
        ),
        (
            {CONF_REHEARSAL_MODE: True},
            "rehearsal",
            "rehearsal_mode",
        ),
        (
            {CONF_SIGN_CONVENTIONS_VERIFIED: False},
            "sign_conventions_unverified",
            "sign_conventions_unverified",
        ),
        (
            {CONF_FOXESS_FORCE_DISCHARGE_POWER: ""},
            "blocked_incomplete_mapping",
            "incomplete_foxess_mapping",
        ),
    ],
)
async def test_active_gate_precedence_is_a_no_write_contract(
    hass,
    overrides: dict[str, object],
    expected_gate: str,
    expected_reason: str,
) -> None:
    """Characterize the exact absolute-gate outcome before typed migration."""
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    controller = _loaded_controller(
        hass,
        _coordinator(
            **{
                CONF_AUTOMATIC_CONTROL_ENABLED: True,
                CONF_REHEARSAL_MODE: False,
                CONF_SIGN_CONVENTIONS_VERIFIED: True,
                **overrides,
            }
        ),
    )

    await controller.async_reconcile()

    assert controller.gate_status == expected_gate
    assert controller.last_reason == expected_reason
    assert controller.writes_performed == 0
    assert calls == []


def _loaded_controller(hass, coordinator):
    """Construct a controller with explicit valid unit-test storage evidence."""
    coordinator.manual_test = SimpleNamespace(
        is_active=False,
        active_kind=None,
        storage_status="valid",
    )
    controller = ActiveFoxessController(hass, coordinator)
    controller._charge_storage_status = "valid"  # noqa: SLF001
    controller._export_storage_status = "valid"  # noqa: SLF001
    return controller


async def test_controller_is_inert_when_automatic_control_is_disabled(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    controller = _loaded_controller(hass, _coordinator())

    await controller.async_reconcile()

    assert calls == []


async def test_cloud_scheduler_owner_blocks_all_modbus_automation_writes(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    controller = _loaded_controller(
        hass,
        _coordinator(
            **{
                CONF_AUTOMATIC_CONTROL_ENABLED: True,
                CONF_AUTOMATIC_CHARGE_ENABLED: True,
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
    controller = _loaded_controller(
        hass,
        _coordinator(
            **{
                CONF_AUTOMATIC_CONTROL_ENABLED: True,
                CONF_AUTOMATIC_CHARGE_ENABLED: True,
            }
        ),
    )

    await controller.async_reconcile()

    assert calls == []


async def test_unverified_signs_block_modbus_automation(hass):
    controller = _loaded_controller(
        hass,
        _coordinator(
            **{
                CONF_AUTOMATIC_CONTROL_ENABLED: True,
                CONF_AUTOMATIC_CHARGE_ENABLED: True,
                CONF_REHEARSAL_MODE: False,
                CONF_SIGN_CONVENTIONS_VERIFIED: False,
            }
        ),
    )

    await controller.async_reconcile()

    assert controller.gate_status == "sign_conventions_unverified"
    assert controller.last_reason == "sign_conventions_unverified"
    assert controller.writes_performed == 0


async def test_master_gate_alone_cannot_write_at_midnight(hass, monkeypatch):
    """The master gate cannot schedule a charge without its independent opt-in."""
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
    controller = _loaded_controller(
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

    assert controller.last_reason == "no_automatic_foxess_policy_active"
    assert controller.export_session.phase == "idle"
    assert calls == []


async def test_unconfirmed_charge_schedule_is_an_absolute_no_start_gate(
    hass, monkeypatch
):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    hass.states.async_set(
        "select.foxess_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    hass.states.async_set(
        "number.foxess_charge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime(2026, 9, 10, 12, 30, tzinfo=UTC),
    )
    controller = _loaded_controller(
        hass,
        _coordinator(
            **{
                CONF_AUTOMATIC_CONTROL_ENABLED: True,
                CONF_AUTOMATIC_CHARGE_ENABLED: True,
                CONF_FREE_CHARGE_SCHEDULE_CONFIRMED: False,
                CONF_REHEARSAL_MODE: False,
            }
        ),
    )

    await controller.async_reconcile()

    assert controller.charge_session.phase == "idle"
    assert controller.last_reason == "charge_schedule_unconfirmed"
    assert calls == []


async def test_pilot_site_export_starts_at_latest_start_and_latches(hass, monkeypatch):
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
    now = datetime(2026, 9, 5, 20, 2, tzinfo=UTC)
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
            CONF_INVERTER_DISCHARGE_LIMIT_KW: 20.0,
            CONF_EXPORT_DISCHARGE_POWER_KW: 10.0,
            CONF_AUTOMATIC_EXPORT_LIMIT_KWH: 15.0,
            CONF_EXPORT_ALLOWANCE_KWH: 15.0,
            CONF_DISCHARGE_EFFICIENCY_PERCENT: 95.0,
            CONF_BONUS_WINDOW_START: "18:00:00",
            CONF_FORCE_DISCHARGE_FINISH: "21:01:00",
            CONF_FREE_CHARGE_START: "12:01:00",
        }
    )
    coordinator.data.available_after_reserve_kwh = 30.0
    controller = _loaded_controller(hass, coordinator)

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert controller.export_planned_start == datetime(2026, 9, 5, 20, 1, tzinfo=UTC)
    assert controller.export_session.phase == "starting"
    # The legacy 10 kW preference is intentionally ignored. The controller
    # requests the commissioned inverter/actuator maximum so house load cannot
    # consume artificially reserved discharge headroom.
    assert controller.export_session.requested_power_kw == 15.0
    assert sorted(
        (event.data["domain"], event.data["service"]) for event in calls
    ) == [
        ("number", "set_value"),
        ("select", "select_option"),
    ]

    hass.states.async_set(
        "select.foxess_mode",
        "Force Discharge",
        {"options": ["Self Use", "Force Discharge"]},
    )
    hass.states.async_set(
        "number.foxess_discharge", "15", {"unit_of_measurement": "kW", "max": 15}
    )
    coordinator.data.available_after_reserve_kwh = 0.0
    coordinator.learning_remaining_kwh = 99.0
    await controller.async_reconcile()
    assert controller.export_session.phase == "active"
    assert len(calls) == 2


def test_zerohero_finish_offset_wraps_midnight(hass):
    coordinator = _coordinator(
        **{
            CONF_BONUS_WINDOW_START: "22:00:00",
            CONF_BONUS_WINDOW_END: "23:59:00",
            CONF_FORCE_DISCHARGE_OFFSET_MINUTES: 5.0,
        }
    )
    controller = _loaded_controller(hass, coordinator)

    start, finish = controller._export_bounds(  # noqa: SLF001
        datetime(2026, 9, 5, 23, 0, tzinfo=UTC)
    )
    assert start == datetime(2026, 9, 5, 22, 0, tzinfo=UTC)
    assert finish == datetime(2026, 9, 6, 0, 4, tzinfo=UTC)

    start, finish = controller._export_bounds(  # noqa: SLF001
        datetime(2026, 9, 6, 0, 2, tzinfo=UTC)
    )
    assert start == datetime(2026, 9, 5, 22, 0, tzinfo=UTC)
    assert finish == datetime(2026, 9, 6, 0, 4, tzinfo=UTC)


async def test_automatic_export_cap_is_independent_of_boosted_tariff_cap(
    hass, monkeypatch
):
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
    now = datetime(2026, 9, 5, 19, 45, tzinfo=UTC)
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
            CONF_AUTOMATIC_EXPORT_LIMIT_KWH: 20.0,
            CONF_EXPORT_ALLOWANCE_KWH: 15.0,
            CONF_DISCHARGE_EFFICIENCY_PERCENT: 100.0,
            CONF_BONUS_WINDOW_START: "18:00:00",
            CONF_FORCE_DISCHARGE_FINISH: "21:01:00",
            CONF_FREE_CHARGE_START: "12:01:00",
        }
    )
    coordinator.data.available_after_reserve_kwh = 30.0
    controller = _loaded_controller(hass, coordinator)

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert controller.automatic_export_remaining_kwh == 20.0
    assert controller.export_plan is not None
    assert controller.export_plan.sellable_energy_kwh == 26.0
    assert controller.export_plan.planned_export_energy_kwh == 20.0
    assert controller.export_plan.planned_duration_h == 1.333
    assert controller.export_planned_start == datetime(
        2026, 9, 5, 19, 41, 1, 200000, tzinfo=UTC
    )
    assert controller.export_session.phase == "starting"
    assert sorted(
        (event.data["domain"], event.data["service"]) for event in calls
    ) == [
        ("number", "set_value"),
        ("select", "select_option"),
    ]


async def test_ev_before_export_prevents_new_session_below_target(hass, monkeypatch):
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
    now = datetime(2026, 9, 5, 19, 31, tzinfo=UTC)
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now", lambda: now
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_EXPORT_ENABLED: True,
            CONF_EV_BEFORE_EXPORT_ENABLED: True,
            CONF_EV_BEFORE_EXPORT_SOC_TARGET: 40.0,
            CONF_REHEARSAL_MODE: False,
            CONF_INVERTER_DISCHARGE_LIMIT_KW: 15.0,
            CONF_EXPORT_DISCHARGE_POWER_KW: 10.0,
            CONF_EXPORT_ALLOWANCE_KWH: 15.0,
            CONF_DISCHARGE_EFFICIENCY_PERCENT: 95.0,
            CONF_BONUS_WINDOW_START: "18:00:00",
            CONF_FORCE_DISCHARGE_FINISH: "21:01:00",
        }
    )
    coordinator.snapshot.ev_soc = 25.0
    coordinator.data.available_after_reserve_kwh = 30.0
    controller = _loaded_controller(hass, coordinator)

    await controller.async_reconcile()

    assert controller.export_session.phase == "idle"
    assert controller.export_effective_enabled is False
    assert controller.ev_before_export_decision.reason == "ev_below_target"
    assert calls == []


async def test_ev_before_export_stops_active_heo_export_below_target(hass, monkeypatch):
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
        "Force Discharge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    hass.states.async_set("number.foxess_charge", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set(
        "number.foxess_discharge", "10", {"unit_of_measurement": "kW", "max": 15}
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime(2026, 9, 5, 19, 31, tzinfo=UTC),
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep", no_wait
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_EXPORT_ENABLED: True,
            CONF_EV_BEFORE_EXPORT_ENABLED: True,
            CONF_EV_BEFORE_EXPORT_SOC_TARGET: 40.0,
            CONF_REHEARSAL_MODE: False,
            CONF_INVERTER_DISCHARGE_LIMIT_KW: 15.0,
            CONF_EXPORT_DISCHARGE_POWER_KW: 10.0,
        }
    )
    coordinator.snapshot.ev_soc = 25.0
    controller = _loaded_controller(hass, coordinator)
    controller.export_session = ExportSessionState("active", 10.0, 0)

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert controller.export_session.phase == "stopping"
    assert controller.ev_before_export_decision.reason == "ev_below_target"
    assert {(event.data["domain"], event.data["service"]) for event in calls} == {
        ("select", "select_option"),
        ("number", "set_value"),
    }
    assert any(
        event.data["service_data"].get("option") == "Self Use" for event in calls
    )
    assert any(event.data["service_data"].get("value") == 0.0 for event in calls)


async def test_export_session_latch_round_trips_through_ha_storage(hass):
    coordinator = _coordinator()
    coordinator.entry_id = "persisted-export-test"
    first = _loaded_controller(hass, coordinator)
    first.export_session = ExportSessionState(
        "recovering", 8.5, 2, datetime(2026, 9, 5, 20, 0, tzinfo=UTC)
    )
    await first._export_store.async_save(first._export_state_payload())

    restored = _loaded_controller(hass, coordinator)
    await restored._async_load_export_session()

    assert restored.export_session == first.export_session


async def test_export_protects_only_explicit_connected_ev_baseline(hass):
    hass.states.async_set("device_tracker.car", "home")
    hass.states.async_set("binary_sensor.car_cable", "on")
    controller = _loaded_controller(
        hass,
        _coordinator(
            **{
                CONF_EV_CONTROL_COMMISSIONED: True,
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
    controller = _loaded_controller(
        hass,
        _coordinator(
            **{
                CONF_EV_CONTROL_COMMISSIONED: True,
                CONF_EV_PROTECTED_BASELINE_A: 1.0,
            }
        ),
    )

    assert controller._protected_keepalive_energy_kwh(15) is None


async def test_battery_only_site_ignores_retained_ev_baseline(hass):
    controller = _loaded_controller(
        hass,
        _coordinator(
            **{
                CONF_EV_CONTROL_COMMISSIONED: False,
                CONF_EV_PROTECTED_BASELINE_A: 1.0,
            }
        ),
    )

    assert controller._protected_keepalive_energy_kwh(15) == 0.0


async def test_local_modbus_free_charge_starts_at_noon_boundary(hass, monkeypatch):
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
    hass.states.async_set(
        "number.foxess_charge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime(2026, 9, 10, 12, 1, tzinfo=UTC),
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep", no_wait
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_CHARGE_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_FREE_CHARGE_START: "12:01:00",
            CONF_FREE_CHARGE_END: "14:59:00",
            CONF_BATTERY_FREE_WINDOW_TARGET: 100.0,
            CONF_INVERTER_CHARGE_LIMIT_KW: 15.0,
        }
    )
    coordinator.snapshot.battery_soc = 20.0
    controller = _loaded_controller(hass, coordinator)

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert controller.charge_session == ChargeSessionState(
        "starting",
        15.0,
        1,
        datetime(2026, 9, 10, 12, 1, tzinfo=UTC),
    )
    assert controller.last_actions == ("set_charge_power", "select_mode")
    assert {
        (event.data["domain"], event.data["service"]) for event in calls
    } == {("number", "set_value"), ("select", "select_option")}


async def test_local_modbus_charge_cannot_misread_noon_as_midnight(hass, monkeypatch):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    hass.states.async_set(
        "select.foxess_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    hass.states.async_set(
        "number.foxess_charge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime(2026, 9, 10, 0, 1, tzinfo=UTC),
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_CHARGE_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_FREE_CHARGE_START: "12:01:00",
            CONF_FREE_CHARGE_END: "14:59:00",
            CONF_INVERTER_CHARGE_LIMIT_KW: 15.0,
        }
    )
    controller = _loaded_controller(hass, coordinator)

    await controller.async_reconcile()

    assert controller.charge_session.phase == "idle"
    assert controller.last_reason == "no_automatic_foxess_policy_active"
    assert calls == []


async def test_free_charge_does_not_start_without_fresh_soc(hass, monkeypatch):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    hass.states.async_set(
        "select.foxess_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    hass.states.async_set(
        "number.foxess_charge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime(2026, 9, 10, 12, 30, tzinfo=UTC),
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_CHARGE_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_INVERTER_CHARGE_LIMIT_KW: 15.0,
        }
    )
    coordinator.snapshot.battery_soc = None
    controller = _loaded_controller(hass, coordinator)

    await controller.async_reconcile()

    assert controller.charge_session.phase == "idle"
    assert calls == []


async def test_runtime_blocks_overlapping_enabled_charge_and_export_windows(
    hass, monkeypatch
):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    hass.states.async_set(
        "select.foxess_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    hass.states.async_set(
        "number.foxess_charge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime(2026, 9, 10, 20, 30, tzinfo=UTC),
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_CHARGE_ENABLED: True,
            CONF_AUTOMATIC_EXPORT_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_FREE_CHARGE_START: "20:00:00",
            CONF_FREE_CHARGE_END: "22:00:00",
            CONF_BONUS_WINDOW_START: "18:00:00",
            CONF_FORCE_DISCHARGE_FINISH: "21:01:00",
            CONF_INVERTER_CHARGE_LIMIT_KW: 15.0,
            CONF_INVERTER_DISCHARGE_LIMIT_KW: 15.0,
        }
    )
    coordinator.snapshot.battery_soc = 20.0
    controller = _loaded_controller(hass, coordinator)

    await controller.async_reconcile()

    assert controller.last_reason == "configured_control_windows_overlap"
    assert controller.charge_session.phase == "idle"
    assert controller.export_session.phase == "idle"
    assert calls == []


async def test_free_charge_requires_below_target_soc_and_live_force_charge_option(
    hass, monkeypatch
):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    hass.states.async_set(
        "select.foxess_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge"]},
    )
    hass.states.async_set(
        "number.foxess_charge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime(2026, 9, 10, 12, 30, tzinfo=UTC),
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_CHARGE_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_BATTERY_FREE_WINDOW_TARGET: 90.0,
            CONF_INVERTER_CHARGE_LIMIT_KW: 15.0,
        }
    )
    coordinator.snapshot.battery_soc = 90.0
    controller = _loaded_controller(hass, coordinator)

    await controller.async_reconcile()
    assert calls == []

    coordinator.snapshot.battery_soc = 20.0
    await controller.async_reconcile()
    assert controller.charge_session.phase == "idle"
    assert controller.last_reason == "charge_source_unavailable"
    assert calls == []


async def test_free_charge_does_not_adopt_an_unlatched_forced_mode(hass, monkeypatch):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    hass.states.async_set(
        "select.foxess_mode",
        "Force Charge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    hass.states.async_set(
        "number.foxess_charge", "15", {"unit_of_measurement": "kW", "max": 15}
    )
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 15}
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime(2026, 9, 10, 12, 30, tzinfo=UTC),
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_CHARGE_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_INVERTER_CHARGE_LIMIT_KW: 15.0,
        }
    )
    coordinator.snapshot.battery_soc = 20.0
    controller = _loaded_controller(hass, coordinator)

    await controller.async_reconcile()

    assert controller.charge_session.phase == "idle"
    assert controller.last_reason == "external_forced_mode"
    assert controller.ownership_status == "verified_external_owner"
    assert calls == []


async def test_latched_free_charge_restores_self_use_after_window(hass, monkeypatch):
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
        "Force Charge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    hass.states.async_set(
        "number.foxess_charge", "10", {"unit_of_measurement": "kW", "max": 10}
    )
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 10}
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime(2026, 9, 10, 15, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep", no_wait
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_CHARGE_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_INVERTER_CHARGE_LIMIT_KW: 10.0,
        }
    )
    controller = _loaded_controller(hass, coordinator)
    controller.charge_session = ChargeSessionState("active", 10.0, 0)

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert controller.charge_session.phase == "stopping"
    assert {(event.data["domain"], event.data["service"]) for event in calls} == {
        ("select", "select_option"),
        ("number", "set_value"),
    }
    assert any(
        event.data["service_data"].get("option") == "Self Use" for event in calls
    )
    assert any(event.data["service_data"].get("value") == 0.0 for event in calls)


async def test_charge_session_latch_round_trips_through_ha_storage(hass):
    coordinator = _coordinator()
    coordinator.entry_id = "persisted-charge-test"
    first = _loaded_controller(hass, coordinator)
    first.charge_session = ChargeSessionState(
        "recovering", 8.5, 2, datetime(2026, 9, 10, 13, 0, tzinfo=UTC)
    )
    await first._charge_store.async_save(first._charge_state_payload())

    restored = _loaded_controller(hass, coordinator)
    await restored._async_load_charge_session()

    assert restored.charge_session == first.charge_session


async def test_completed_charge_session_round_trips_through_ha_storage(hass):
    coordinator = _coordinator()
    coordinator.entry_id = "persisted-completed-charge-test"
    first = _loaded_controller(hass, coordinator)
    first.charge_session = ChargeSessionState("completed", 8.0, 0, None)
    await first._charge_store.async_save(first._charge_state_payload())

    restored = _loaded_controller(hass, coordinator)
    await restored._async_load_charge_session()

    assert restored.charge_session == first.charge_session


async def test_active_free_charge_restarts_from_self_use_while_still_eligible(
    hass, monkeypatch
):
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
    hass.states.async_set(
        "number.foxess_charge", "0", {"unit_of_measurement": "kW", "max": 10}
    )
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 10}
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime(2026, 9, 10, 12, 46, tzinfo=UTC),
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep",
        no_wait,
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_CHARGE_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_INVERTER_CHARGE_LIMIT_KW: 10.0,
        }
    )
    coordinator.snapshot.battery_soc = 96.0
    controller = _loaded_controller(hass, coordinator)
    controller.charge_session = ChargeSessionState("active", 10.0, 0)

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert controller.charge_session == ChargeSessionState(
        "starting", 10.0, 1, datetime(2026, 9, 10, 12, 46, tzinfo=UTC)
    )
    assert controller.charge_power_target_kw == 10.0
    assert controller.last_reason == "charge_start_requested"
    assert controller.last_actions == ("set_charge_power", "select_mode")
    assert {
        (event.data["domain"], event.data["service"]) for event in calls
    } == {("number", "set_value"), ("select", "select_option")}


async def test_free_charge_does_not_start_after_allowance_is_exhausted(
    hass, monkeypatch
):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    hass.states.async_set(
        "select.foxess_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    hass.states.async_set(
        "number.foxess_charge", "0", {"unit_of_measurement": "kW", "max": 10}
    )
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 10}
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime(2026, 9, 10, 12, 46, tzinfo=UTC),
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_CHARGE_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_INVERTER_CHARGE_LIMIT_KW: 10.0,
        }
    )
    coordinator.snapshot.battery_soc = 20.0
    coordinator.data.free_energy_remaining_kwh = 0.0
    controller = _loaded_controller(hass, coordinator)

    await controller.async_reconcile()

    assert controller.charge_session.phase == "idle"
    assert controller.last_reason == "charge_allowance_exhausted"
    assert calls == []


async def test_active_free_charge_restores_self_use_when_allowance_is_exhausted(
    hass, monkeypatch
):
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
        "Force Charge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    hass.states.async_set(
        "number.foxess_charge", "8", {"unit_of_measurement": "kW", "max": 8}
    )
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 8}
    )
    now = datetime(2026, 9, 10, 13, 31, tzinfo=UTC)
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now", lambda: now
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep",
        no_wait,
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_CHARGE_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_INVERTER_CHARGE_LIMIT_KW: 8.0,
        }
    )
    coordinator.snapshot.battery_soc = 96.0
    coordinator.data.free_energy_remaining_kwh = 0.0
    controller = _loaded_controller(hass, coordinator)
    controller.charge_session = ChargeSessionState("active", 8.0, 0)

    await controller.async_reconcile()
    await hass.async_block_till_done()

    assert controller.charge_session == ChargeSessionState("stopping", 8.0, 1, now)
    assert controller.last_actions == ("select_mode", "set_charge_power")
    assert {
        (event.data["domain"], event.data["service"]) for event in calls
    } == {("number", "set_value"), ("select", "select_option")}


async def test_persisted_active_charge_restarts_after_ha_restart_feedback_settles(
    hass, monkeypatch
):
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
    hass.states.async_set(
        "number.foxess_charge", "0", {"unit_of_measurement": "kW", "max": 8}
    )
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 8}
    )
    now = datetime(2026, 9, 10, 13, 31, tzinfo=UTC)
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now", lambda: now
    )
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep",
        no_wait,
    )
    coordinator = _coordinator(
        **{
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_CHARGE_ENABLED: True,
            CONF_REHEARSAL_MODE: False,
            CONF_INVERTER_CHARGE_LIMIT_KW: 8.0,
        }
    )
    coordinator.entry_id = "restart-during-free-window"
    coordinator.snapshot.battery_soc = 96.0
    before_restart = _loaded_controller(hass, coordinator)
    before_restart.charge_session = ChargeSessionState(
        "active", 8.0, 0, now - timedelta(minutes=45)
    )
    await before_restart._charge_store.async_save(  # noqa: SLF001
        before_restart._charge_state_payload()  # noqa: SLF001
    )

    restored = _loaded_controller(hass, coordinator)
    await restored._async_load_charge_session()  # noqa: SLF001
    await restored.async_reconcile()
    await hass.async_block_till_done()

    assert restored.charge_session == ChargeSessionState("starting", 8.0, 1, now)
    assert restored.last_actions == ("set_charge_power", "select_mode")
    assert {
        (event.data["domain"], event.data["service"]) for event in calls
    } == {("number", "set_value"), ("select", "select_option")}


async def test_latched_charge_marks_recovering_when_feedback_is_unavailable(hass):
    hass.states.async_set(
        "select.foxess_mode",
        "unavailable",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    hass.states.async_set(
        "number.foxess_charge", "10", {"unit_of_measurement": "kW", "max": 10}
    )
    hass.states.async_set(
        "number.foxess_discharge", "0", {"unit_of_measurement": "kW", "max": 10}
    )
    controller = _loaded_controller(
        hass,
        _coordinator(
            **{
                CONF_AUTOMATIC_CONTROL_ENABLED: True,
                CONF_AUTOMATIC_CHARGE_ENABLED: True,
                CONF_REHEARSAL_MODE: False,
            }
        ),
    )
    controller.charge_session = ChargeSessionState("active", 10.0, 0)

    await controller.async_reconcile()

    assert controller.charge_session.phase == "recovering"
    assert controller.last_reason == "foxess_feedback_unavailable"
