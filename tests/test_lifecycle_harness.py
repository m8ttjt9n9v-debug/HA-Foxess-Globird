"""System-level lifecycle characterization tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.core import ServiceRegistry
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN
from tests.helpers.lifecycle import LifecycleHarness
from tests.test_setup import ENTRY_DATA


def _register_foxess_services(harness: LifecycleHarness, monkeypatch) -> None:
    async def noop(_call) -> None:
        return None

    async def no_wait(_seconds) -> None:
        return None

    original_async_call = ServiceRegistry.async_call

    async def record_call(
        registry,
        domain,
        service,
        service_data=None,
        blocking=False,
        context=None,
        target=None,
        return_response=False,
    ):
        if (domain, service) in {
            ("number", "set_value"),
            ("select", "select_option"),
        }:
            payload = dict(service_data or {})
            payload.update(target or {})
            harness.record_service_call(domain, service, payload)
        return await original_async_call(
            registry,
            domain,
            service,
            service_data,
            blocking,
            context,
            target,
            return_response,
        )

    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep",
        no_wait,
    )
    monkeypatch.setattr(ServiceRegistry, "async_call", record_call)
    harness.hass.services.async_register("number", "set_value", noop)
    harness.hass.services.async_register("select", "select_option", noop)


def _register_ev_services(harness: LifecycleHarness, monkeypatch) -> None:
    async def noop(_call) -> None:
        return None

    original_async_call = ServiceRegistry.async_call

    async def record_call(
        registry,
        domain,
        service,
        service_data=None,
        blocking=False,
        context=None,
        target=None,
        return_response=False,
    ):
        if (domain, service) in {
            ("number", "set_value"),
            ("switch", "turn_on"),
            ("switch", "turn_off"),
        }:
            payload = dict(service_data or {})
            payload.update(target or {})
            harness.record_service_call(domain, service, payload)
        return await original_async_call(
            registry,
            domain,
            service,
            service_data,
            blocking,
            context,
            target,
            return_response,
        )

    monkeypatch.setattr(ServiceRegistry, "async_call", record_call)
    harness.hass.services.async_register("number", "set_value", noop)
    harness.hass.services.async_register("switch", "turn_on", noop)
    harness.hass.services.async_register("switch", "turn_off", noop)


async def _seed_foxess_states(harness: LifecycleHarness, battery_soc: float) -> None:
    await harness.set_state(
        "sensor.test_battery_soc", battery_soc, {"unit_of_measurement": "%"}
    )
    await harness.set_state(
        "sensor.test_grid_power", "0", {"unit_of_measurement": "kW"}
    )
    await harness.set_state(
        "sensor.test_house_load", "0.8", {"unit_of_measurement": "kW"}
    )
    await harness.set_state(
        "select.test_work_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    await harness.set_state(
        "number.test_force_charge",
        "0",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "number.test_force_discharge",
        "0",
        {"unit_of_measurement": "kW", "max": 10},
    )


async def _seed_ev_states(
    harness: LifecycleHarness,
    *,
    soc: float,
    actual_current: float,
    requested_current: float,
    stored_energy: float,
    house_load: float,
    site_current: float,
) -> None:
    await harness.set_state(
        "sensor.test_house_load", house_load, {"unit_of_measurement": "kW"}
    )
    await harness.set_state(
        "sensor.test_site_current", site_current, {"unit_of_measurement": "A"}
    )
    await harness.set_state("sensor.test_ev_soc", soc, {"unit_of_measurement": "%"})
    await harness.set_state("device_tracker.test_ev", "home")
    await harness.set_state("binary_sensor.test_ev_cable", "on")
    await harness.set_state("sensor.test_ev_charging", "charging")
    await harness.set_state(
        "sensor.test_ev_actual_current",
        actual_current,
        {"unit_of_measurement": "A"},
    )
    await harness.set_state(
        "sensor.test_ev_energy", stored_energy, {"unit_of_measurement": "kWh"}
    )
    await harness.set_state(
        "number.test_ev_current",
        requested_current,
        {"min": 1, "max": 16, "step": 1, "unit_of_measurement": "A"},
    )
    await harness.set_state(
        "number.test_ev_limit", "90", {"min": 50, "max": 100, "step": 1}
    )
    await harness.set_state("switch.test_ev_charge", "on")


def _active_entry_data(**overrides) -> dict[str, object]:
    return {
        **ENTRY_DATA,
        "foxess_control_owner": "local_modbus",
        "automatic_control_enabled": True,
        "rehearsal_mode": False,
        "sign_conventions_verified": True,
        "foxess_work_mode_entity": "select.test_work_mode",
        "foxess_force_charge_power_entity": "number.test_force_charge",
        "foxess_force_discharge_power_entity": "number.test_force_discharge",
        **overrides,
    }


def _ev_entry_data(**overrides) -> dict[str, object]:
    return _active_entry_data(
        **{
            "automatic_control_enabled": False,
            "foxess_control_owner": "foxcloud_scheduler",
            "ev_automatic_control_enabled": True,
            "ev_control_commissioned": True,
            "ev_soc_entity": "sensor.test_ev_soc",
            "ev_at_home_entity": "device_tracker.test_ev",
            "ev_cable_connected_entity": "binary_sensor.test_ev_cable",
            "ev_charging_state_entity": "sensor.test_ev_charging",
            "ev_actual_current_entity": "sensor.test_ev_actual_current",
            "ev_stored_energy_entity": "sensor.test_ev_energy",
            "ev_current_limit_entity": "number.test_ev_current",
            "ev_charge_limit_entity": "number.test_ev_limit",
            "ev_charge_switch_entity": "switch.test_ev_charge",
            "ev_location_mode": "auto",
            "ev_free_window_priority": "ev",
            "ev_free_window_charge_limit_percent": 90.0,
            "ev_free_window_minimum_current_a": 1.0,
            "ev_free_window_settle_minutes": 0.0,
            "ev_allowance_guard_enabled": True,
            "ev_allowance_safety_margin_kwh": 0.0,
            "ev_protected_baseline_a": 0.0,
            "ev_max_current": 16.0,
            "ev_voltage": 230.0,
            "ev_phase_count": 3,
            "house_load_includes_ev": True,
            "site_phase_count": 3,
            "site_grid_current_entity": "sensor.test_site_current",
            "service_import_limit_a": 80.0,
            "site_grid_headroom_current_a": 1.0,
            "daily_free_allowance_kwh": 50.0,
            "free_charge_window_start": "12:00:00",
            "free_charge_window_end": "15:00:00",
            **overrides,
        }
    )


async def _apply_reconfiguration(
    hass,
    entry: MockConfigEntry,
    data: dict[str, object],
    *,
    name: str,
) -> None:
    """Submit the complete reconfigure flow and wait for its reload."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        data={"name": name, **data},
    )
    if result["type"] is FlowResultType.FORM:
        assert result["step_id"] == "confirm_schedule"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"confirm_schedule": True}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()


@pytest.mark.freeze_time("2026-09-17 01:00:00+00:00")
async def test_observer_public_state_is_equivalent_after_reload(hass) -> None:
    """A reload with identical evidence must not change public truth or write."""
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.test_house_load", "0.8", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(domain=DOMAIN, title="Lifecycle baseline", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    harness = LifecycleHarness(hass)

    await harness.setup(entry)
    public_entities = {
        "sensor.home_energy_status",
        "sensor.home_energy_fleet_summary",
        "sensor.home_energy_battery_soc",
        "sensor.home_energy_grid_power",
        "sensor.home_energy_house_load",
        "switch.home_energy_safety_lock",
    }
    before = harness.states(public_entities, ignored_attributes=frozenset({"last_update"}))
    assert harness.service_calls == ()

    await harness.reload(entry)
    after = harness.states(public_entities, ignored_attributes=frozenset({"last_update"}))

    assert after == before
    assert harness.service_calls == ()
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_battery_telemetry_recovers_after_delay_outage_and_reload(hass) -> None:
    """Canonical battery power survives delay fallback and recovers after outage."""
    harness = LifecycleHarness(hass)
    await _seed_foxess_states(harness, 60)
    now = datetime.now(UTC)
    await harness.set_state(
        "sensor.test_battery_charge",
        "9.713",
        {"unit_of_measurement": "kW"},
    )
    hass.states.async_set(
        "sensor.test_battery_discharge",
        "0",
        {"unit_of_measurement": "kW"},
        timestamp=(now - timedelta(minutes=10)).timestamp(),
    )
    await harness.set_state(
        "sensor.test_signed_battery",
        "-9.713",
        {"unit_of_measurement": "kW"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Battery telemetry recovery",
        version=6,
        data=_active_entry_data(
            automatic_control_enabled=False,
            battery_power_entity="sensor.test_signed_battery",
            battery_power_positive_direction="positive_discharge",
            battery_charge_power_entity="sensor.test_battery_charge",
            battery_discharge_power_entity="sensor.test_battery_discharge",
        ),
    )
    entry.add_to_hass(hass)

    await harness.setup(entry)

    battery = hass.states.get("sensor.home_energy_battery_power")
    assert battery is not None
    assert battery.state == "9.713"
    assert battery.attributes["reason"] == "signed_fallback_pair_stale"
    healthy_states = harness.states(
        {
            "sensor.home_energy_battery_soc",
            "sensor.home_energy_grid_power",
            "sensor.home_energy_house_load",
        },
        ignored_attributes=frozenset({"last_update"}),
    )

    await harness.set_unavailable("sensor.test_battery_discharge")

    battery = hass.states.get("sensor.home_energy_battery_power")
    assert battery is not None
    assert battery.state == "unknown"
    assert battery.attributes["reason"] == "discharge_source_unavailable"
    assert harness.states(
        {
            "sensor.home_energy_battery_soc",
            "sensor.home_energy_grid_power",
            "sensor.home_energy_house_load",
        },
        ignored_attributes=frozenset({"last_update"}),
    ) == healthy_states

    await harness.reload(entry)

    battery = hass.states.get("sensor.home_energy_battery_power")
    assert battery is not None
    assert battery.state == "unknown"
    assert battery.attributes["reason"] == "discharge_source_unavailable"
    assert harness.service_calls == ()

    await harness.set_state(
        "sensor.test_battery_discharge",
        "0",
        {"unit_of_measurement": "kW"},
    )

    battery = hass.states.get("sensor.home_energy_battery_power")
    assert battery is not None
    assert battery.state == "9.713"
    assert battery.attributes["reason"] == "ok"
    assert len(battery.attributes["sources"]) == 2
    assert harness.service_calls == ()
    await harness.unload(entry)
    harness.close()


@pytest.mark.freeze_time("2026-09-17 12:30:00+00:00")
async def test_ev_allowance_target_does_not_cycle_with_inclusive_house_load(
    hass, monkeypatch
) -> None:
    """Alternating EV feedback must not make an inclusive meter flap 1 ↔ 16 A."""
    harness = LifecycleHarness(hass)
    _register_ev_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 100)
    await _seed_ev_states(
        harness,
        soc=40,
        actual_current=16,
        requested_current=16,
        stored_energy=5,
        house_load=12,
        site_current=38,
    )
    now = [datetime(2026, 9, 17, 12, 30, tzinfo=UTC)]
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.ev_active.dt_util.now",
        lambda: now[0],
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="EV inclusive-meter anti-cycling",
        version=6,
        data=_ev_entry_data(),
    )
    entry.add_to_hass(hass)
    await harness.save_store(
        f"home_energy_orchestrator.{entry.entry_id}.free_window_import",
        {
            "date": now[0].date().isoformat(),
            "imported_kwh": 25.0,
            "last_at": now[0].isoformat(),
            "last_import_kw": 10.0,
        },
    )

    await harness.setup(entry)

    controller = entry.runtime_data.ev_controller
    assert controller.target_current_a == 16
    harness.clear_service_calls()
    for index, actual_current in enumerate((1, 16, 1, 16), start=1):
        now[0] = datetime(2026, 9, 17, 12, 30, tzinfo=UTC) + timedelta(
            minutes=3 * index,
            seconds=index,
        )
        high = actual_current == 16
        await harness.set_state(
            "sensor.test_ev_actual_current",
            str(actual_current),
            {"unit_of_measurement": "A"},
            observed_at=now[0],
        )
        await harness.set_state(
            "sensor.test_house_load",
            "12" if high else "1.65",
            {"unit_of_measurement": "kW"},
            observed_at=now[0],
        )
        await harness.set_state(
            "sensor.test_site_current",
            "38" if high else "5",
            {"unit_of_measurement": "A"},
            observed_at=now[0],
        )
        await controller.async_reconcile(now[0])
        entry.runtime_data.async_update_listeners()
        await hass.async_block_till_done()

        target = hass.states.get("sensor.home_energy_ev_current_target")
        requested = hass.states.get("sensor.home_energy_ev_requested_current")
        actual = hass.states.get("sensor.home_energy_ev_actual_current")
        assert target is not None and target.state == "16.0"
        assert requested is not None and requested.state == "16.0"
        assert actual is not None and actual.state == f"{float(actual_current):.1f}"
        assert controller.allowance_house_load_kw == pytest.approx(0.96, abs=0.001)

    assert harness.service_calls == ()
    assert controller.target_current_a == 16
    assert controller.reconciliation.phase == "confirmed"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("switch", "turn_on")
    hass.services.async_remove("switch", "turn_off")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 06:30:00+00:00")
async def test_ev_outside_charge_stops_at_house_battery_floor(hass, monkeypatch) -> None:
    """Automatic EV charging yields at the battery floor without paid import."""
    harness = LifecycleHarness(hass)
    _register_ev_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 10)
    await _seed_ev_states(
        harness,
        soc=95,
        actual_current=6,
        requested_current=6,
        stored_energy=70,
        house_load=5,
        site_current=10,
    )
    now = [datetime(2026, 9, 17, 6, 30, tzinfo=UTC)]
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.ev_active.dt_util.now",
        lambda: now[0],
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Protected house battery floor",
        version=6,
        data=_ev_entry_data(
            foxess_control_owner="local_modbus",
            battery_floor_percent=10.0,
            ev_daily_backfill_energy_kwh=2.0,
            ev_daily_ready_time="08:00:00",
            ev_outside_inverter_percent=30.0,
            inverter_discharge_limit_kw=15.0,
        ),
    )
    entry.add_to_hass(hass)

    await harness.setup(entry)

    controller = entry.runtime_data.ev_controller
    assert controller.decision_phase == "battery_floor_reached"
    assert controller.target_current_a == 0
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()
    assert [
        (call.domain, call.service, call.service_data)
        for call in harness.service_calls
    ] == [
        (
            "switch",
            "turn_off",
            {"entity_id": "switch.test_ev_charge"},
        )
    ]
    target = hass.states.get("sensor.home_energy_ev_current_target")
    grid_import = hass.states.get("sensor.home_energy_grid_import")
    assert target is not None and target.state == "0.0"
    assert grid_import is not None and grid_import.state == "0.0"

    now[0] += timedelta(seconds=1)
    await harness.set_state(
        "sensor.test_ev_actual_current",
        "0",
        {"unit_of_measurement": "A"},
        observed_at=now[0],
    )
    await harness.set_state(
        "sensor.test_ev_charging", "stopped", observed_at=now[0]
    )
    await harness.set_state("switch.test_ev_charge", "off", observed_at=now[0])
    harness.clear_service_calls()

    await harness.reload(entry)

    controller = entry.runtime_data.ev_controller
    assert controller.decision_phase == "battery_floor_reached"
    assert controller.target_current_a == 0
    assert harness.service_calls == ()
    assert hass.states.get("sensor.home_energy_grid_import").state == "0.0"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("switch", "turn_on")
    hass.services.async_remove("switch", "turn_off")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_safety_lock_blocks_all_commands_across_reload(hass) -> None:
    """Requested automation cannot write before or after a locked reload."""
    harness = LifecycleHarness(hass)
    await harness.set_state(
        "sensor.test_battery_soc", "50", {"unit_of_measurement": "%"}
    )
    await harness.set_state(
        "sensor.test_grid_power", "0", {"unit_of_measurement": "kW"}
    )
    await harness.set_state(
        "sensor.test_house_load", "0.8", {"unit_of_measurement": "kW"}
    )
    await harness.set_state("select.test_work_mode", "Self Use")
    await harness.set_state("number.test_force_charge", "0")
    await harness.set_state("number.test_force_discharge", "0")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Locked lifecycle baseline",
        data={
            **ENTRY_DATA,
            "foxess_control_owner": "local_modbus",
            "automatic_control_enabled": True,
            "automatic_charge_enabled": True,
            "automatic_export_enabled": True,
            "rehearsal_mode": True,
            "sign_conventions_verified": True,
            "free_charge_schedule_confirmed": True,
            "inverter_charge_limit_kw": 10.0,
            "inverter_discharge_limit_kw": 10.0,
            "foxess_work_mode_entity": "select.test_work_mode",
            "foxess_force_charge_power_entity": "number.test_force_charge",
            "foxess_force_discharge_power_entity": "number.test_force_discharge",
        },
    )
    entry.add_to_hass(hass)

    await harness.setup(entry)
    before = harness.states(
        {
            "sensor.home_energy_status",
            "sensor.home_energy_free_charge_completion",
            "sensor.home_energy_zerohero_export_status",
            "switch.home_energy_safety_lock",
        }
    )
    status = hass.states.get("sensor.home_energy_status")
    assert status is not None
    assert status.attributes["control_gate"] == "rehearsal"
    assert harness.service_calls == ()

    await harness.reload(entry)
    after = harness.states(
        {
            "sensor.home_energy_status",
            "sensor.home_energy_free_charge_completion",
            "sensor.home_energy_zerohero_export_status",
            "switch.home_energy_safety_lock",
        }
    )

    assert after == before
    status = hass.states.get("sensor.home_energy_status")
    assert status is not None
    assert status.attributes["control_gate"] == "rehearsal"
    assert harness.service_calls == ()
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
@pytest.mark.parametrize("active_session", [False, True])
@pytest.mark.parametrize(
    ("gate_key", "blocked_value", "blocked_status"),
    [
        ("sign_conventions_verified", False, "sign_conventions_unverified"),
        ("foxess_control_owner", "observer_only", "observer_owner"),
    ],
)
async def test_owner_and_sign_gate_reconfiguration_is_atomic(
    hass,
    monkeypatch,
    active_session: bool,
    gate_key: str,
    blocked_value: bool | str,
    blocked_status: str,
) -> None:
    """Gate changes apply without writes or loss of persisted ownership."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 80 if active_session else 100)
    if active_session:
        await harness.set_state(
            "number.test_force_charge",
            "10",
            {"unit_of_measurement": "kW", "max": 10},
        )
        await harness.set_state(
            "select.test_work_mode",
            "Force Charge",
            {"options": ["Self Use", "Force Discharge", "Force Charge"]},
        )
    configured = _active_entry_data(
        automatic_charge_enabled=True,
        free_charge_schedule_confirmed=True,
        free_charge_window_start="00:00:00",
        free_charge_window_end="23:59:00",
        inverter_charge_limit_kw=10.0,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"{gate_key} {'active' if active_session else 'idle'}",
        version=6,
        data=configured,
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.charge_session"
    if active_session:
        await harness.save_store(
            store_key,
            {
                "phase": "active",
                "requested_power_kw": 10.0,
                "attempts": 0,
                "last_command_at": "2026-09-17T01:45:00+00:00",
            },
        )

    await harness.setup(entry)

    expected_phase = "active" if active_session else "idle"
    assert entry.runtime_data.active_controller.charge_session.phase == expected_phase
    assert harness.service_calls == ()

    await _apply_reconfiguration(
        hass,
        entry,
        {**configured, gate_key: blocked_value},
        name=f"{gate_key} blocked",
    )

    status = hass.states.get("sensor.home_energy_status")
    assert status is not None
    assert status.attributes["control_gate"] == blocked_status
    assert entry.runtime_data.active_controller.charge_session.phase == expected_phase
    assert harness.service_calls == ()
    if active_session:
        persisted = await harness.load_store(store_key)
        assert persisted is not None
        assert persisted["phase"] == "active"

    await _apply_reconfiguration(
        hass,
        entry,
        configured,
        name=f"{gate_key} restored",
    )

    status = hass.states.get("sensor.home_energy_status")
    assert status is not None
    assert status.attributes["control_gate"] == "ready"
    assert entry.runtime_data.active_controller.charge_session.phase == expected_phase
    assert harness.service_calls == ()
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_active_free_charge_is_reasserted_then_adopted_after_reload(
    hass, monkeypatch
) -> None:
    """A restart inside the free window resumes, then adopts confirmed feedback."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 50)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Restarted free charge",
        version=6,
        data=_active_entry_data(
            automatic_charge_enabled=True,
            free_charge_schedule_confirmed=True,
            free_charge_window_start="00:00:00",
            free_charge_window_end="23:59:00",
            inverter_charge_limit_kw=10.0,
        ),
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.charge_session"
    await harness.save_store(
        store_key,
        {
            "phase": "active",
            "requested_power_kw": 10.0,
            "attempts": 0,
            "last_command_at": "2026-09-17T01:45:00+00:00",
        },
    )

    await harness.setup(entry)

    observed_calls = [
        (call.domain, call.service, call.service_data)
        for call in harness.service_calls
    ]
    assert observed_calls == [
        (
            "number",
            "set_value",
            {"value": 10.0, "entity_id": "number.test_force_charge"},
        ),
        (
            "select",
            "select_option",
            {"option": "Force Charge", "entity_id": "select.test_work_mode"},
        ),
    ], entry.runtime_data.active_controller.last_reason
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()
    charge_state = hass.states.get("sensor.home_energy_free_charge_completion")
    assert charge_state is not None
    assert charge_state.state == "starting"
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "starting"
    await harness.set_state(
        "number.test_force_charge",
        "10",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Charge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )

    harness.clear_service_calls()
    await harness.reload(entry)

    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()
    charge_state = hass.states.get("sensor.home_energy_free_charge_completion")
    assert charge_state is not None
    assert charge_state.state == "active"
    assert harness.service_calls == ()
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "active"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_active_export_is_reasserted_then_adopted_after_reload(
    hass, monkeypatch
) -> None:
    """A retained export obligation survives setup and confirmed-feedback reload."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 100)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Restarted export",
        version=6,
        data=_active_entry_data(
            automatic_export_enabled=True,
            automatic_export_limit_kwh=25.0,
            bonus_window_start="00:00:00",
            bonus_window_end="23:58:00",
            force_discharge_offset_minutes=1.0,
            inverter_discharge_limit_kw=10.0,
            house_learning_fallback_kwh=0.0,
        ),
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.export_session"
    await harness.save_store(
        store_key,
        {
            "phase": "active",
            "requested_power_kw": 10.0,
            "attempts": 0,
            "last_command_at": "2026-09-17T01:45:00+00:00",
        },
    )

    await harness.setup(entry)

    observed_calls = [
        (call.domain, call.service, call.service_data)
        for call in harness.service_calls
    ]
    assert observed_calls == [
        (
            "number",
            "set_value",
            {"value": 10.0, "entity_id": "number.test_force_discharge"},
        ),
        (
            "select",
            "select_option",
            {"option": "Force Discharge", "entity_id": "select.test_work_mode"},
        ),
    ], entry.runtime_data.active_controller.last_reason
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()
    export_state = hass.states.get("sensor.home_energy_zerohero_export_status")
    assert export_state is not None
    assert export_state.state == "starting"
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "starting"
    await harness.set_state(
        "number.test_force_discharge",
        "10",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Discharge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )

    harness.clear_service_calls()
    await harness.reload(entry)

    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()
    export_state = hass.states.get("sensor.home_energy_zerohero_export_status")
    assert export_state is not None
    assert export_state.state == "active"
    assert harness.service_calls == ()
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "active"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_active_export_rejects_external_force_charge_across_reload(
    hass, monkeypatch
) -> None:
    """An owned export obligation must not adopt an external forced charge."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 100)
    await harness.set_state(
        "number.test_force_charge",
        "10",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Charge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Active export with external forced charge",
        version=6,
        data=_active_entry_data(
            automatic_export_enabled=True,
            automatic_export_limit_kwh=25.0,
            bonus_window_start="00:00:00",
            bonus_window_end="23:58:00",
            force_discharge_offset_minutes=1.0,
            inverter_discharge_limit_kw=10.0,
            house_learning_fallback_kwh=0.0,
        ),
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.export_session"
    await harness.save_store(
        store_key,
        {
            "phase": "active",
            "requested_power_kw": 10.0,
            "attempts": 0,
            "last_command_at": "2026-09-17T01:45:00+00:00",
        },
    )

    await harness.setup(entry)

    observed_calls = [
        (call.domain, call.service, call.service_data)
        for call in harness.service_calls
    ]
    assert observed_calls == [
        (
            "number",
            "set_value",
            {"value": 0.0, "entity_id": "number.test_force_charge"},
        ),
        (
            "number",
            "set_value",
            {"value": 10.0, "entity_id": "number.test_force_discharge"},
        ),
        (
            "select",
            "select_option",
            {"option": "Force Discharge", "entity_id": "select.test_work_mode"},
        ),
    ]
    controller = entry.runtime_data.active_controller
    assert controller.last_reason == "export_start_requested"
    assert controller.export_session.phase == "starting"
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "starting"

    await harness.set_state(
        "number.test_force_charge",
        "0",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "number.test_force_discharge",
        "10",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Discharge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    harness.clear_service_calls()

    await harness.reload(entry)

    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()
    export_state = hass.states.get("sensor.home_energy_zerohero_export_status")
    assert export_state is not None
    assert export_state.state == "active"
    assert harness.service_calls == ()
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "active"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_completed_charge_does_not_adopt_external_forced_mode_across_reload(
    hass, monkeypatch
) -> None:
    """A completed charge latch must not claim an unrelated forced mode."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 50)
    await harness.set_state(
        "number.test_force_discharge",
        "10",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Discharge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Completed charge with external forced mode",
        version=6,
        data=_active_entry_data(
            automatic_charge_enabled=True,
            free_charge_schedule_confirmed=True,
            free_charge_window_start="00:00:00",
            free_charge_window_end="23:59:00",
            inverter_charge_limit_kw=10.0,
        ),
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.charge_session"
    await harness.save_store(
        store_key,
        {
            "phase": "completed",
            "requested_power_kw": 10.0,
            "attempts": 0,
            "last_command_at": None,
        },
    )

    await harness.setup(entry)
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()

    charge_state = hass.states.get("sensor.home_energy_free_charge_completion")
    assert charge_state is not None
    assert charge_state.state == "completed"
    assert harness.service_calls == ()
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "completed"

    await harness.reload(entry)
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()

    charge_state = hass.states.get("sensor.home_energy_free_charge_completion")
    assert charge_state is not None
    assert charge_state.state == "completed"
    assert harness.service_calls == ()
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "completed"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_free_charge_exact_end_restores_self_use_and_clears_on_reload(
    hass, monkeypatch
) -> None:
    """The exact end boundary creates, persists and completes restoration."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 80)
    await harness.set_state(
        "number.test_force_charge",
        "10",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Charge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    now = [datetime(2026, 9, 17, 2, 30, tzinfo=UTC)]
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: now[0],
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Free charge end boundary",
        version=6,
        data=_active_entry_data(
            automatic_charge_enabled=True,
            free_charge_schedule_confirmed=True,
            free_charge_window_start="00:00:00",
            free_charge_window_end="23:59:00",
            inverter_charge_limit_kw=10.0,
        ),
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.charge_session"
    await harness.save_store(
        store_key,
        {
            "phase": "active",
            "requested_power_kw": 10.0,
            "attempts": 0,
            "last_command_at": "2026-09-17T02:00:00+00:00",
        },
    )

    await harness.setup(entry)
    assert harness.service_calls == ()

    now[0] = datetime(2026, 9, 17, 23, 59, tzinfo=UTC)
    await entry.runtime_data.active_controller.async_reconcile()
    await hass.async_block_till_done()

    observed_calls = [
        (call.domain, call.service, call.service_data)
        for call in harness.service_calls
    ]
    assert observed_calls == [
        (
            "select",
            "select_option",
            {"option": "Self Use", "entity_id": "select.test_work_mode"},
        ),
        (
            "number",
            "set_value",
            {"value": 0.0, "entity_id": "number.test_force_charge"},
        ),
    ]
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "stopping"
    await harness.set_state(
        "number.test_force_charge",
        "0",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )

    harness.clear_service_calls()
    await harness.reload(entry)

    assert harness.service_calls == ()
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "idle"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_active_charge_ownership_survives_unavailable_feedback_and_reload(
    hass, monkeypatch
) -> None:
    """Unavailable actuator feedback persists recovery instead of erasing ownership."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 80)
    await harness.set_state(
        "number.test_force_charge",
        "10",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Charge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Charge feedback recovery",
        version=6,
        data=_active_entry_data(
            automatic_charge_enabled=True,
            free_charge_schedule_confirmed=True,
            free_charge_window_start="00:00:00",
            free_charge_window_end="23:59:00",
            inverter_charge_limit_kw=10.0,
        ),
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.charge_session"
    await harness.save_store(
        store_key,
        {
            "phase": "active",
            "requested_power_kw": 10.0,
            "attempts": 0,
            "last_command_at": "2026-09-17T01:45:00+00:00",
        },
    )

    await harness.setup(entry)
    assert harness.service_calls == ()

    await harness.set_unavailable("select.test_work_mode")
    await entry.runtime_data.active_controller.async_reconcile()

    assert harness.service_calls == ()
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "recovering"

    await harness.set_state(
        "number.test_force_charge",
        "0",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    harness.clear_service_calls()
    await harness.reload(entry)

    observed_calls = [
        (call.domain, call.service, call.service_data)
        for call in harness.service_calls
    ]
    assert observed_calls == [
        (
            "number",
            "set_value",
            {"value": 10.0, "entity_id": "number.test_force_charge"},
        ),
        (
            "select",
            "select_option",
            {"option": "Force Charge", "entity_id": "select.test_work_mode"},
        ),
    ]
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "starting"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_active_charge_survives_applied_reconfiguration_without_duplicate_write(
    hass, monkeypatch
) -> None:
    """Applying unrelated config reloads without dropping or replaying ownership."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 80)
    await harness.set_state(
        "number.test_force_charge",
        "10",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Charge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    configured = _active_entry_data(
        automatic_charge_enabled=True,
        free_charge_schedule_confirmed=True,
        free_charge_window_start="00:00:00",
        free_charge_window_end="23:59:00",
        inverter_charge_limit_kw=10.0,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Active charge reconfigure",
        version=6,
        data=configured,
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.charge_session"
    await harness.save_store(
        store_key,
        {
            "phase": "active",
            "requested_power_kw": 10.0,
            "attempts": 0,
            "last_command_at": "2026-09-17T01:45:00+00:00",
        },
    )
    await harness.setup(entry)
    assert harness.service_calls == ()

    await _apply_reconfiguration(
        hass,
        entry,
        {**configured, "battery_capacity_kwh": 25.0},
        name="Active charge reconfigured",
    )

    assert entry.title == "Active charge reconfigured"
    assert entry.data["battery_capacity_kwh"] == 25.0
    assert harness.service_calls == ()
    assert entry.runtime_data.active_controller.charge_session.phase == "active"
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "active"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_active_export_survives_safety_lock_reconfiguration(
    hass, monkeypatch
) -> None:
    """Lock changes issue no commands and retain active export ownership."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 100)
    await harness.set_state(
        "number.test_force_discharge",
        "10",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Discharge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    configured = _active_entry_data(
        automatic_export_enabled=True,
        automatic_export_limit_kwh=25.0,
        bonus_window_start="00:00:00",
        bonus_window_end="23:58:00",
        force_discharge_offset_minutes=1.0,
        inverter_discharge_limit_kw=10.0,
        house_learning_fallback_kwh=0.0,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Active export reconfigure",
        version=6,
        data=configured,
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.export_session"
    await harness.save_store(
        store_key,
        {
            "phase": "active",
            "requested_power_kw": 10.0,
            "attempts": 0,
            "last_command_at": "2026-09-17T01:45:00+00:00",
        },
    )
    await harness.setup(entry)
    assert harness.service_calls == ()

    await _apply_reconfiguration(
        hass,
        entry,
        {**configured, "rehearsal_mode": True},
        name="Active export locked",
    )

    assert harness.service_calls == ()
    assert entry.runtime_data.active_controller.export_session.phase == "active"
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "active"
    status = hass.states.get("sensor.home_energy_status")
    assert status is not None
    assert status.attributes["control_gate"] == "rehearsal"

    await _apply_reconfiguration(
        hass,
        entry,
        configured,
        name="Active export unlocked",
    )

    assert harness.service_calls == ()
    assert entry.runtime_data.active_controller.export_session.phase == "active"
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "active"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
@pytest.mark.parametrize("direction", ["charge", "export"])
@pytest.mark.parametrize("phase", ["starting", "stopping", "recovering"])
async def test_inflight_session_phase_survives_unrelated_reconfiguration(
    hass, monkeypatch, direction: str, phase: str
) -> None:
    """Config reloads preserve every unfinished automatic-session obligation."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 80 if direction == "charge" else 100)
    enabled = phase != "stopping"
    if phase == "stopping":
        await harness.set_state(
            f"number.test_force_{direction}",
            "10",
            {"unit_of_measurement": "kW", "max": 10},
        )
        await harness.set_state(
            "select.test_work_mode",
            "Force Charge" if direction == "charge" else "Force Discharge",
            {"options": ["Self Use", "Force Discharge", "Force Charge"]},
        )
    elif phase == "recovering":
        await harness.set_unavailable("select.test_work_mode")

    if direction == "charge":
        configured = _active_entry_data(
            automatic_charge_enabled=enabled,
            free_charge_schedule_confirmed=True,
            free_charge_window_start="00:00:00",
            free_charge_window_end="23:59:00",
            inverter_charge_limit_kw=10.0,
        )
        store_suffix = "charge_session"
    else:
        configured = _active_entry_data(
            automatic_export_enabled=enabled,
            automatic_export_limit_kwh=25.0,
            bonus_window_start="00:00:00",
            bonus_window_end="23:58:00",
            force_discharge_offset_minutes=1.0,
            inverter_discharge_limit_kw=10.0,
            house_learning_fallback_kwh=0.0,
        )
        store_suffix = "export_session"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"{direction.title()} {phase} reconfigure",
        version=6,
        data=configured,
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.{store_suffix}"
    await harness.save_store(
        store_key,
        {
            "phase": phase,
            "requested_power_kw": 10.0,
            "attempts": 1,
            "last_command_at": "2026-09-17T02:29:50+00:00",
        },
    )

    await harness.setup(entry)

    controller = entry.runtime_data.active_controller
    session = (
        controller.charge_session
        if direction == "charge"
        else controller.export_session
    )
    assert session.phase == phase
    assert harness.service_calls == ()
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == phase

    await _apply_reconfiguration(
        hass,
        entry,
        {**configured, "battery_capacity_kwh": 25.0},
        name=f"{direction.title()} {phase} reconfigured",
    )

    controller = entry.runtime_data.active_controller
    session = (
        controller.charge_session
        if direction == "charge"
        else controller.export_session
    )
    assert entry.data["battery_capacity_kwh"] == 25.0
    assert session.phase == phase
    assert harness.service_calls == ()
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == phase
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 00:05:00+00:00")
@pytest.mark.parametrize("restart_at_each_phase", [False, True])
async def test_ordinary_day_has_restart_equivalent_command_obligations(
    hass, monkeypatch, restart_at_each_phase: bool
) -> None:
    """An ordinary charge/export day is invariant to phase-boundary reloads."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 50)
    now = [datetime(2026, 9, 17, 0, 5, tzinfo=UTC)]
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: now[0],
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=(
            "Ordinary day with phase reloads"
            if restart_at_each_phase
            else "Ordinary uninterrupted day"
        ),
        version=6,
        data=_active_entry_data(
            automatic_charge_enabled=True,
            automatic_export_enabled=True,
            automatic_export_limit_kwh=25.0,
            free_charge_schedule_confirmed=True,
            free_charge_window_start="00:00:00",
            free_charge_window_end="01:00:00",
            bonus_window_start="18:00:00",
            bonus_window_end="21:00:00",
            force_discharge_offset_minutes=1.0,
            battery_capacity_kwh=40.32,
            inverter_charge_limit_kw=10.0,
            inverter_discharge_limit_kw=10.0,
            house_learning_fallback_kwh=0.0,
        ),
    )
    entry.add_to_hass(hass)
    charge_store = f"home_energy_orchestrator.{entry.entry_id}.charge_session"
    export_store = f"home_energy_orchestrator.{entry.entry_id}.export_session"

    await harness.setup(entry)

    assert entry.runtime_data.active_controller.charge_session.phase == "starting"
    if restart_at_each_phase:
        await harness.reload(entry)
        assert entry.runtime_data.active_controller.charge_session.phase == "starting"

    await harness.set_state(
        "number.test_force_charge",
        "10",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Charge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    await entry.runtime_data.active_controller.async_reconcile()
    assert entry.runtime_data.active_controller.charge_session.phase == "active"
    if restart_at_each_phase:
        await harness.reload(entry)
        assert entry.runtime_data.active_controller.charge_session.phase == "active"

    now[0] = datetime(2026, 9, 17, 1, 0, tzinfo=UTC)
    await entry.runtime_data.active_controller.async_reconcile()
    assert entry.runtime_data.active_controller.charge_session.phase == "stopping"
    if restart_at_each_phase:
        await harness.reload(entry)
        assert entry.runtime_data.active_controller.charge_session.phase == "stopping"

    await harness.set_state(
        "number.test_force_charge",
        "0",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    await entry.runtime_data.active_controller.async_reconcile()
    assert entry.runtime_data.active_controller.charge_session.phase == "idle"

    now[0] = datetime(2026, 9, 17, 18, 45, tzinfo=UTC)
    await harness.set_state(
        "sensor.test_battery_soc", "100", {"unit_of_measurement": "%"}
    )
    await entry.runtime_data.active_controller.async_reconcile()
    controller = entry.runtime_data.active_controller
    assert controller.export_plan is not None
    assert controller.export_session.phase == "starting"
    if restart_at_each_phase:
        await harness.reload(entry)
        assert entry.runtime_data.active_controller.export_session.phase == "starting"

    await harness.set_state(
        "number.test_force_discharge",
        "10",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Discharge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    await entry.runtime_data.active_controller.async_reconcile()
    assert entry.runtime_data.active_controller.export_session.phase == "active"
    if restart_at_each_phase:
        await harness.reload(entry)
        assert entry.runtime_data.active_controller.export_session.phase == "active"

    now[0] = datetime(2026, 9, 17, 21, 1, tzinfo=UTC)
    await entry.runtime_data.active_controller.async_reconcile()
    assert entry.runtime_data.active_controller.export_session.phase == "stopping"
    if restart_at_each_phase:
        await harness.reload(entry)
        assert entry.runtime_data.active_controller.export_session.phase == "stopping"

    await harness.set_state(
        "number.test_force_discharge",
        "0",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    await entry.runtime_data.active_controller.async_reconcile()

    expected_calls = [
        (
            "number",
            "set_value",
            {"value": 10.0, "entity_id": "number.test_force_charge"},
        ),
        (
            "select",
            "select_option",
            {"option": "Force Charge", "entity_id": "select.test_work_mode"},
        ),
        (
            "select",
            "select_option",
            {"option": "Self Use", "entity_id": "select.test_work_mode"},
        ),
        (
            "number",
            "set_value",
            {"value": 0.0, "entity_id": "number.test_force_charge"},
        ),
        (
            "number",
            "set_value",
            {"value": 10.0, "entity_id": "number.test_force_discharge"},
        ),
        (
            "select",
            "select_option",
            {"option": "Force Discharge", "entity_id": "select.test_work_mode"},
        ),
        (
            "select",
            "select_option",
            {"option": "Self Use", "entity_id": "select.test_work_mode"},
        ),
        (
            "number",
            "set_value",
            {"value": 0.0, "entity_id": "number.test_force_discharge"},
        ),
    ]
    assert [
        (call.domain, call.service, call.service_data)
        for call in harness.service_calls
    ] == expected_calls
    assert entry.runtime_data.active_controller.charge_session.phase == "idle"
    assert entry.runtime_data.active_controller.export_session.phase == "idle"
    persisted_charge = await harness.load_store(charge_store)
    persisted_export = await harness.load_store(export_store)
    assert persisted_charge is not None
    assert persisted_export is not None
    assert persisted_charge["phase"] == "idle"
    assert persisted_export["phase"] == "idle"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 00:30:00+00:00")
async def test_export_cap_reconfiguration_keeps_sellable_energy_available(
    hass, monkeypatch
) -> None:
    """Changing 15 to 20 kWh updates the plan without invalidating inputs."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 100)
    configured = _active_entry_data(
        automatic_export_enabled=True,
        automatic_export_limit_kwh=15.0,
        export_allowance_kwh=15.0,
        battery_capacity_kwh=40.32,
        inverter_discharge_limit_kw=10.0,
        house_learning_fallback_kwh=0.0,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Export cap reconfigure",
        version=6,
        data=configured,
    )
    entry.add_to_hass(hass)
    await harness.setup(entry)
    controller = entry.runtime_data.active_controller
    assert controller.export_plan is not None, (
        controller.last_reason,
        controller.gate_status,
        entry.runtime_data.data.available_after_reserve_kwh,
        entry.runtime_data.learning_remaining_kwh,
        controller.automatic_export_remaining_kwh,
    )
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()

    sellable_entity = "sensor.home_energy_zerohero_sellable_energy"
    planned_entity = "sensor.home_energy_zerohero_planned_export_energy"
    sellable_before = hass.states.get(sellable_entity)
    planned_before = hass.states.get(planned_entity)
    assert sellable_before is not None
    assert planned_before is not None
    assert float(sellable_before.state) > 20.0
    assert planned_before.state == "15.0"
    assert harness.service_calls == ()

    await _apply_reconfiguration(
        hass,
        entry,
        {**configured, "automatic_export_limit_kwh": 20.0},
        name="Export cap reconfigured",
    )
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()

    sellable_after = hass.states.get(sellable_entity)
    planned_after = hass.states.get(planned_entity)
    assert sellable_after is not None
    assert planned_after is not None
    assert sellable_after.state == sellable_before.state
    assert planned_after.state == "20.0"
    assert entry.data["automatic_export_limit_kwh"] == 20.0
    assert entry.data["export_allowance_kwh"] == 15.0
    assert entry.data["sign_conventions_verified"] is True
    assert harness.service_calls == ()
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 00:30:00+00:00")
@pytest.mark.parametrize("entry_version", [3, 6])
async def test_battery_only_site_ignores_retained_ev_reservation_across_reload(
    hass, monkeypatch, entry_version: int
) -> None:
    """Clean and upgraded battery-only entries never reserve stale EV energy."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 100)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Battery-only v{entry_version}",
        version=entry_version,
        data=_active_entry_data(
            configure_ev=False,
            ev_control_commissioned=True,
            ev_protected_baseline_a=1.0,
            automatic_export_enabled=True,
            automatic_export_limit_kwh=25.0,
            battery_capacity_kwh=40.32,
            inverter_discharge_limit_kw=10.0,
            house_learning_fallback_kwh=0.0,
        ),
    )
    entry.add_to_hass(hass)

    await harness.setup(entry)

    controller = entry.runtime_data.active_controller
    assert entry.version == 6
    assert controller.export_protected_ev_kwh == 0.0
    assert controller.export_plan is not None
    assert controller.export_plan.planned_export_energy_kwh == 25.0
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()
    sellable = hass.states.get("sensor.home_energy_zerohero_sellable_energy")
    planned = hass.states.get("sensor.home_energy_zerohero_planned_export_energy")
    ev_status = hass.states.get("sensor.home_energy_ev_control_status")
    assert sellable is not None and sellable.state != "unknown"
    assert planned is not None and planned.state == "25.0"
    assert ev_status is not None and ev_status.state == "disabled"
    assert harness.service_calls == ()

    await harness.reload(entry)
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()

    controller = entry.runtime_data.active_controller
    assert controller.export_protected_ev_kwh == 0.0
    assert controller.export_plan is not None
    assert controller.export_plan.planned_export_energy_kwh == 25.0
    assert hass.states.get("sensor.home_energy_zerohero_planned_export_energy").state == "25.0"
    assert harness.service_calls == ()
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 10:00:00+00:00")
async def test_v5_scorecard_mapping_survives_upgrade_setup_and_reload(
    hass, monkeypatch
) -> None:
    """Discovered GloBird mappings populate Fleet actual/error across reload."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 60)
    globird = MockConfigEntry(domain="globird_ha")
    globird.add_to_hass(hass)
    registry = er.async_get(hass)
    cost = registry.async_get_or_create(
        "sensor",
        "globird_ha",
        "latest_daily_cost",
        suggested_object_id="globird_energy_latest_daily_cost",
        config_entry=globird,
    )
    status = registry.async_get_or_create(
        "sensor",
        "globird_ha",
        "zerohero_status",
        suggested_object_id="globird_energy_zerohero_status",
        config_entry=globird,
    )
    result_attributes = {
        "latest_available_day": "2026/09/16",
        "latest_available_day_complete": True,
    }
    await harness.set_state(cost.entity_id, "2.00", result_attributes)
    await harness.set_state(status.entity_id, "achieved", result_attributes)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Upgraded scorecard site",
        version=5,
        data=ENTRY_DATA,
    )
    entry.add_to_hass(hass)
    await harness.save_store(
        f"home_energy_orchestrator.{entry.entry_id}.forecast_feedback",
        {
            "current": {"date": "2026-09-17"},
            "export_realisation_fraction": 0.75,
            "learned_cost_bias": 0.0,
            "history": [
                {
                    "date": "2026-09-16",
                    "frozen_forecast_cost": 1.25,
                    "frozen_raw_forecast_cost": 1.25,
                }
            ],
        },
    )

    await harness.setup(entry)
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()

    assert entry.version == 6
    assert entry.data["globird_latest_daily_cost_entity"] == cost.entity_id
    assert entry.data["globird_zerohero_status_entity"] == status.entity_id
    fleet = hass.states.get("sensor.home_energy_fleet_summary")
    assert fleet is not None
    assert fleet.attributes["latest_actual_cost"] == 2.0
    assert fleet.attributes["forecast_error"] == 0.75
    assert fleet.attributes["latest_zerohero_status"] == "achieved"
    assert fleet.attributes["forecast_scorecard_status"] == "matched"
    assert harness.service_calls == ()

    await harness.reload(entry)
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()

    fleet = hass.states.get("sensor.home_energy_fleet_summary")
    assert fleet is not None
    assert fleet.attributes["latest_actual_cost"] == 2.0
    assert fleet.attributes["forecast_error"] == 0.75
    assert fleet.attributes["forecast_scorecard_status"] == "matched"
    assert harness.service_calls == ()
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_import_anchor_stays_zero_when_export_continues_after_reload(
    hass, monkeypatch
) -> None:
    """Import → export checkpoint prevents phantom import after reload."""
    harness = LifecycleHarness(hass)
    await harness.set_state(
        "sensor.test_battery_soc", "60", {"unit_of_measurement": "%"}
    )
    await harness.set_state(
        "sensor.test_house_load", "0.8", {"unit_of_measurement": "kW"}
    )
    await harness.set_state(
        "sensor.test_grid_power", "5", {"unit_of_measurement": "kW"}
    )
    now = [datetime(2026, 9, 17, 2, 30, tzinfo=UTC)]
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.coordinator.dt_util.now",
        lambda: now[0],
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Import anchor reload",
        version=6,
        data=ENTRY_DATA,
    )
    entry.add_to_hass(hass)
    await harness.setup(entry)

    now[0] = datetime(2026, 9, 17, 2, 30, 30, tzinfo=UTC)
    await harness.set_state(
        "sensor.test_grid_power", "5", {"unit_of_measurement": "kW"}
    )
    now[0] = datetime(2026, 9, 17, 2, 31, tzinfo=UTC)
    await harness.set_state(
        "sensor.test_grid_power", "-1", {"unit_of_measurement": "kW"}
    )

    before = hass.states.get("sensor.home_energy_daily_import")
    assert before is not None
    before_import_kwh = float(before.state)
    assert before_import_kwh > 0
    store_key = f"home_energy_orchestrator.{entry.entry_id}.daily_import"
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["last_import_kw"] == 0.0

    await harness.reload(entry)
    now[0] = datetime(2026, 9, 17, 2, 31, 30, tzinfo=UTC)
    await harness.set_state(
        "sensor.test_grid_power", "-1", {"unit_of_measurement": "kW"}
    )

    after = hass.states.get("sensor.home_energy_daily_import")
    assert after is not None
    assert float(after.state) == before_import_kwh
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["last_import_kw"] == 0.0
    assert harness.service_calls == ()
    await harness.unload(entry)
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_export_anchor_stays_zero_when_import_continues_after_reload(
    hass, monkeypatch
) -> None:
    """Export → import checkpoint prevents phantom export after reload."""
    harness = LifecycleHarness(hass)
    await harness.set_state(
        "sensor.test_battery_soc", "60", {"unit_of_measurement": "%"}
    )
    await harness.set_state(
        "sensor.test_house_load", "0.8", {"unit_of_measurement": "kW"}
    )
    await harness.set_state(
        "sensor.test_grid_power", "-5", {"unit_of_measurement": "kW"}
    )
    now = [datetime(2026, 9, 17, 2, 30, tzinfo=UTC)]
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.coordinator.dt_util.now",
        lambda: now[0],
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Export anchor reload",
        version=6,
        data=ENTRY_DATA,
    )
    entry.add_to_hass(hass)
    await harness.setup(entry)

    now[0] = datetime(2026, 9, 17, 2, 30, 30, tzinfo=UTC)
    await harness.set_state(
        "sensor.test_grid_power", "-5", {"unit_of_measurement": "kW"}
    )
    now[0] = datetime(2026, 9, 17, 2, 31, tzinfo=UTC)
    await harness.set_state(
        "sensor.test_grid_power", "1", {"unit_of_measurement": "kW"}
    )

    before = hass.states.get("sensor.home_energy_daily_export")
    assert before is not None
    before_export_kwh = float(before.state)
    assert before_export_kwh > 0
    store_key = f"home_energy_orchestrator.{entry.entry_id}.daily_export"
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["last_import_kw"] == 0.0

    await harness.reload(entry)
    now[0] = datetime(2026, 9, 17, 2, 31, 30, tzinfo=UTC)
    await harness.set_state(
        "sensor.test_grid_power", "1", {"unit_of_measurement": "kW"}
    )

    after = hass.states.get("sensor.home_energy_daily_export")
    assert after is not None
    assert float(after.state) == before_export_kwh
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["last_import_kw"] == 0.0
    assert harness.service_calls == ()
    await harness.unload(entry)
    harness.close()


@pytest.mark.freeze_time("2026-09-17 17:00:00+00:00")
async def test_gross_cost_stays_constant_during_continuous_export_across_reload(
    hass, monkeypatch
) -> None:
    """Zero import cannot make gross cost creep while export accumulates."""
    harness = LifecycleHarness(hass)
    await harness.set_state(
        "sensor.test_battery_soc", "80", {"unit_of_measurement": "%"}
    )
    await harness.set_state(
        "sensor.test_house_load", "0.8", {"unit_of_measurement": "kW"}
    )
    await harness.set_state(
        "sensor.test_grid_power", "-2", {"unit_of_measurement": "kW"}
    )
    now = [datetime(2026, 9, 17, 17, 0, tzinfo=UTC)]
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.coordinator.dt_util.now",
        lambda: now[0],
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Continuous export accounting",
        version=6,
        data={**ENTRY_DATA, "telemetry_max_age_seconds": 86_400.0},
    )
    entry.add_to_hass(hass)
    await harness.setup(entry)

    gross_entity = "sensor.home_energy_estimated_energy_cost"
    initial_gross = hass.states.get(gross_entity)
    assert initial_gross is not None
    observed_gross = [initial_gross.state]

    for index in range(1, 9):
        now[0] += timedelta(minutes=30)
        await harness.set_state(
            "sensor.test_grid_power", "-2", {"unit_of_measurement": "kW"}
        )
        if index == 4:
            await harness.reload(entry)
        gross = hass.states.get(gross_entity)
        assert gross is not None
        observed_gross.append(gross.state)

    daily_import = hass.states.get("sensor.home_energy_daily_import")
    daily_export = hass.states.get("sensor.home_energy_daily_export")
    assert daily_import is not None
    assert daily_export is not None
    assert daily_import.state == "0.0"
    assert float(daily_export.state) > 0
    assert observed_gross == [initial_gross.state] * 9
    assert harness.service_calls == ()
    await harness.unload(entry)
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_export_exact_end_restores_self_use_and_clears_on_reload(
    hass, monkeypatch
) -> None:
    """The exact export finish persists restoration until feedback confirms it."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 100)
    await harness.set_state(
        "number.test_force_discharge",
        "10",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Discharge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    now = [datetime(2026, 9, 17, 2, 30, tzinfo=UTC)]
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: now[0],
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Export end boundary",
        version=6,
        data=_active_entry_data(
            automatic_export_enabled=True,
            automatic_export_limit_kwh=25.0,
            bonus_window_start="00:00:00",
            bonus_window_end="23:58:00",
            force_discharge_offset_minutes=1.0,
            inverter_discharge_limit_kw=10.0,
            house_learning_fallback_kwh=0.0,
        ),
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.export_session"
    await harness.save_store(
        store_key,
        {
            "phase": "active",
            "requested_power_kw": 10.0,
            "attempts": 0,
            "last_command_at": "2026-09-17T02:00:00+00:00",
        },
    )

    await harness.setup(entry)
    assert harness.service_calls == ()

    now[0] = datetime(2026, 9, 17, 23, 59, tzinfo=UTC)
    await entry.runtime_data.active_controller.async_reconcile()
    await hass.async_block_till_done()

    observed_calls = [
        (call.domain, call.service, call.service_data)
        for call in harness.service_calls
    ]
    assert observed_calls == [
        (
            "select",
            "select_option",
            {"option": "Self Use", "entity_id": "select.test_work_mode"},
        ),
        (
            "number",
            "set_value",
            {"value": 0.0, "entity_id": "number.test_force_discharge"},
        ),
    ]
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "stopping"
    await harness.set_state(
        "number.test_force_discharge",
        "0",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )

    harness.clear_service_calls()
    await harness.reload(entry)

    assert harness.service_calls == ()
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "idle"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_active_export_ownership_survives_unavailable_feedback_and_reload(
    hass, monkeypatch
) -> None:
    """Unavailable export feedback retains the persisted recovery obligation."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 100)
    await harness.set_state(
        "number.test_force_discharge",
        "10",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Discharge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Export feedback recovery",
        version=6,
        data=_active_entry_data(
            automatic_export_enabled=True,
            automatic_export_limit_kwh=25.0,
            bonus_window_start="00:00:00",
            bonus_window_end="23:58:00",
            force_discharge_offset_minutes=1.0,
            inverter_discharge_limit_kw=10.0,
            house_learning_fallback_kwh=0.0,
        ),
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.export_session"
    await harness.save_store(
        store_key,
        {
            "phase": "active",
            "requested_power_kw": 10.0,
            "attempts": 0,
            "last_command_at": "2026-09-17T01:45:00+00:00",
        },
    )

    await harness.setup(entry)
    assert harness.service_calls == ()

    await harness.set_unavailable("select.test_work_mode")
    await entry.runtime_data.active_controller.async_reconcile()

    assert harness.service_calls == ()
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "recovering"

    await harness.set_state(
        "number.test_force_discharge",
        "0",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    harness.clear_service_calls()
    await harness.reload(entry)

    observed_calls = [
        (call.domain, call.service, call.service_data)
        for call in harness.service_calls
    ]
    assert observed_calls == [
        (
            "number",
            "set_value",
            {"value": 10.0, "entity_id": "number.test_force_discharge"},
        ),
        (
            "select",
            "select_option",
            {"option": "Force Discharge", "entity_id": "select.test_work_mode"},
        ),
    ]
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "starting"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_unfinished_manual_discharge_restores_and_clears_across_reload(
    hass, monkeypatch
) -> None:
    """Setup restores an unfinished diagnostic and reload confirms completion."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 80)
    await harness.set_state(
        "number.test_force_discharge",
        "8",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Discharge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Interrupted manual discharge",
        version=6,
        data=_active_entry_data(inverter_discharge_limit_kw=10.0),
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.manual_test"
    await harness.save_store(
        store_key,
        {
            "active_kind": "discharge",
            "phase": "running",
            "started_at": "2026-09-17T01:30:00+00:00",
            "ends_at": "2026-09-17T03:30:00+00:00",
            "restore_attempts": 0,
            "last_restore_at": None,
        },
    )

    await harness.setup(entry)

    observed_calls = [
        (call.domain, call.service, call.service_data)
        for call in harness.service_calls
    ]
    assert observed_calls == [
        (
            "select",
            "select_option",
            {"option": "Self Use", "entity_id": "select.test_work_mode"},
        ),
        (
            "number",
            "set_value",
            {"value": 0.0, "entity_id": "number.test_force_discharge"},
        ),
    ]
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()
    test_state = hass.states.get("sensor.home_energy_test_status")
    assert test_state is not None
    assert test_state.state == "stopping_discharge"
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "stopping"
    assert persisted["restore_attempts"] == 1

    await harness.set_state(
        "number.test_force_discharge",
        "0",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Self Use",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    harness.clear_service_calls()
    await harness.reload(entry)

    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()
    test_state = hass.states.get("sensor.home_energy_test_status")
    assert test_state is not None
    assert test_state.state == "idle"
    assert harness.service_calls == ()
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["active_kind"] is None
    assert persisted["phase"] == "idle"
    await harness.unload(entry)
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_safety_lock_blocks_persisted_manual_restore_on_setup_and_unload(
    hass, monkeypatch
) -> None:
    """Safety Lock blocks every write while retaining diagnostic ownership."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 80)
    await harness.set_state(
        "number.test_force_discharge",
        "8",
        {"unit_of_measurement": "kW", "max": 10},
    )
    await harness.set_state(
        "select.test_work_mode",
        "Force Discharge",
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Locked interrupted diagnostic",
        version=6,
        data=_active_entry_data(
            rehearsal_mode=True,
            inverter_discharge_limit_kw=10.0,
        ),
    )
    entry.add_to_hass(hass)
    store_key = f"home_energy_orchestrator.{entry.entry_id}.manual_test"
    await harness.save_store(
        store_key,
        {
            "active_kind": "discharge",
            "phase": "running",
            "started_at": "2026-09-17T01:30:00+00:00",
            "ends_at": "2026-09-17T03:30:00+00:00",
            "restore_attempts": 0,
            "last_restore_at": None,
        },
    )

    await harness.setup(entry)

    assert harness.service_calls == ()
    controller = entry.runtime_data.manual_test
    assert controller.phase == "stopping"
    assert controller.restore_attempts == 0
    assert controller.last_reason == "restore_blocked_safety_lock"
    persisted = await harness.load_store(store_key)
    assert persisted is not None
    assert persisted["phase"] == "stopping"
    assert persisted["restore_attempts"] == 0

    await harness.unload(entry)
    assert harness.service_calls == ()
    hass.services.async_remove("number", "set_value")
    hass.services.async_remove("select", "select_option")
    harness.close()
