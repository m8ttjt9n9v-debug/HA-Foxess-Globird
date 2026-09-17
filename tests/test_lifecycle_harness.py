"""System-level lifecycle characterization tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN
from tests.helpers.lifecycle import LifecycleHarness
from tests.test_setup import ENTRY_DATA


def _register_foxess_services(hass, monkeypatch) -> None:
    async def noop(_call) -> None:
        return None

    async def no_wait(_seconds) -> None:
        return None

    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep",
        no_wait,
    )
    hass.services.async_register("number", "set_value", noop)
    hass.services.async_register("select", "select_option", noop)


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
async def test_active_free_charge_is_reasserted_then_adopted_after_reload(
    hass, monkeypatch
) -> None:
    """A restart inside the free window resumes, then adopts confirmed feedback."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(hass, monkeypatch)
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
    _register_foxess_services(hass, monkeypatch)
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
async def test_completed_charge_does_not_adopt_external_forced_mode_across_reload(
    hass, monkeypatch
) -> None:
    """A completed charge latch must not claim an unrelated forced mode."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(hass, monkeypatch)
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
    _register_foxess_services(hass, monkeypatch)
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
    _register_foxess_services(hass, monkeypatch)
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
    _register_foxess_services(hass, monkeypatch)
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

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        data={"name": "Active charge reconfigured", **configured, "battery_capacity_kwh": 25.0},
    )
    assert result["step_id"] == "confirm_schedule"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"confirm_schedule": True}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

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


@pytest.mark.freeze_time("2026-09-17 02:30:00+00:00")
async def test_export_exact_end_restores_self_use_and_clears_on_reload(
    hass, monkeypatch
) -> None:
    """The exact export finish persists restoration until feedback confirms it."""
    harness = LifecycleHarness(hass)
    _register_foxess_services(hass, monkeypatch)
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
    _register_foxess_services(hass, monkeypatch)
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
