"""Retained export recovery through actual HA setup, storage and service calls.

The fake actuator replaces only the physical inverter. Feed-in First mimics
the FoxESS Modbus base-mode fallback after its forced overlay is lost; it is
not a new export permission or a fabricated cloud-event identity.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.home_energy_orchestrator.const import DOMAIN
from custom_components.home_energy_orchestrator.foxess_adapter import FoxessServiceAdapter
from custom_components.home_energy_orchestrator.planner.foxess import FoxessCommand
from tests.helpers.lifecycle import LifecycleHarness
from tests.test_setup import ENTRY_DATA

NOW = datetime(2026, 9, 5, 20, tzinfo=UTC)
MODE = "select.test_work_mode"
CHARGE = "number.test_force_charge"
DISCHARGE = "number.test_force_discharge"
POWER = 7.5


@pytest.fixture
async def export_fallback(hass, monkeypatch, freezer):
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to(NOW)
    harness = LifecycleHarness(hass)
    calls = []
    entries = []
    await async_setup_component(hass, "number", {})
    await async_setup_component(hass, "select", {})

    async def apply(call):
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            entity = entity[0]
        value = call.data.get("value", call.data.get("option"))
        calls.append((entity, value))
        state = hass.states.get(entity)
        hass.states.async_set(entity, str(value), dict(state.attributes), force_update=True)

    hass.services.async_register("number", "set_value", apply)
    hass.services.async_register("select", "select_option", apply)
    original = FoxessServiceAdapter._async_execute_command

    async def without_physical_delay(adapter, command):
        await original(adapter, FoxessCommand(command.action, command.value))

    monkeypatch.setattr(FoxessServiceAdapter, "_async_execute_command", without_physical_delay)

    async def setup(*, phase="recovering", mode="Feed-in First", overrides=None, journal=True):
        for entity, value, unit in [
            ("sensor.test_battery_soc", 80, "%"),
            ("sensor.test_grid_power", 0, "kW"),
            ("sensor.test_house_load", 0.8, "kW"),
        ]:
            hass.states.async_set(entity, str(value), {"unit_of_measurement": unit})
        hass.states.async_set(
            MODE,
            mode,
            {
                "options": [
                    "Self Use",
                    "Feed-in First",
                    "Back-up",
                    "Force Charge",
                    "Force Discharge",
                ],
            },
        )
        for entity, value in [(CHARGE, 0), (DISCHARGE, POWER)]:
            hass.states.async_set(
                entity,
                str(value),
                {
                    "unit_of_measurement": "kW",
                    "min": 0,
                    "max": 10,
                    "step": 0.001,
                },
            )
        entry = MockConfigEntry(
            domain=DOMAIN,
            version=6,
            data={
                **ENTRY_DATA,
                "configure_ev": False,
                "configure_solar": False,
                "battery_capacity_kwh": 40,
                "house_learning_fallback_kwh": 4,
                "automatic_control_enabled": True,
                "automatic_export_enabled": True,
                "foxess_control_owner": "local_modbus",
                "rehearsal_mode": False,
                "sign_conventions_verified": True,
                "foxess_work_mode_entity": MODE,
                "foxess_force_charge_power_entity": CHARGE,
                "foxess_force_discharge_power_entity": DISCHARGE,
                "inverter_discharge_limit_kw": 9,
                "inverter_charge_limit_kw": 9,
                "automatic_export_limit_kwh": 20,
                **(overrides or {}),
            },
        )
        entry.add_to_hass(hass)
        entries.append(entry)
        if journal:
            await harness.save_store(
                f"{DOMAIN}.{entry.entry_id}.export_session",
                {
                    "phase": phase,
                    "requested_power_kw": POWER,
                    "attempts": 0,
                    "last_command_at": None,
                },
            )
        await harness.setup(entry)
        return entry

    try:
        yield harness, setup, calls
    finally:
        for entry in entries:
            if entry.state is ConfigEntryState.LOADED:
                await harness.unload(entry)
        harness.close()


@pytest.mark.parametrize("phase", ["starting", "active", "recovering"])
@pytest.mark.parametrize("phase_count", [1, 3])
async def test_retained_export_resumes_from_fallback_without_new_power_budget(
    export_fallback,
    phase,
    phase_count,
):
    harness, setup, calls = export_fallback
    entry = await setup(phase=phase, overrides={"site_phase_count": phase_count})
    active = entry.runtime_data.active_controller
    assert calls == [(MODE, "Force Discharge")], (
        dt_util.now(),
        active._export_bounds(dt_util.now()),
        active.last_reason,
        entry.data["automatic_export_enabled"],
    )
    assert active.export_session.requested_power_kw == POWER
    assert active.export_session.phase == "starting"
    assert active.ownership_status == "verified_session"
    await active.async_reconcile()
    assert active.export_session.phase == "active"
    assert calls == [(MODE, "Force Discharge")]
    stored = await harness.load_store(f"{DOMAIN}.{entry.entry_id}.export_session")
    assert stored["phase"] == "active" and stored["requested_power_kw"] == POWER
    assert entry.data["inverter_discharge_limit_kw"] == 9


async def test_periodic_recovery_after_reload_and_unavailable_startup_feedback(
    export_fallback,
    freezer,
):
    harness, setup, calls = export_fallback
    entry = await setup(mode="unavailable")
    assert not calls
    assert entry.runtime_data.active_controller.export_session.phase == "recovering"
    await harness.unload(entry)
    attributes = {"options": ["Self Use", "Feed-in First", "Force Discharge", "Force Charge"]}
    await harness.set_state(MODE, "Feed-in First", attributes)
    await harness.setup(entry)
    active = entry.runtime_data.active_controller
    assert calls == [(MODE, "Force Discharge")]
    await active.async_reconcile()
    assert active.export_session.phase == "active"
    calls.clear()
    # Recreate Modbus's fallback while the integration's stored export is active.
    await harness.unload(entry)
    await harness.set_state(MODE, "Feed-in First", attributes)
    original_settings = dict(entry.data)
    await harness.setup(entry)
    # Preserve the existing retry spacing; restart does not reset the last command.
    assert not calls
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(harness.hass, dt_util.utcnow())
    await harness.hass.async_block_till_done(wait_background_tasks=True)
    assert calls == [(MODE, "Force Discharge")]
    calls.clear()
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(harness.hass, dt_util.utcnow())
    await harness.hass.async_block_till_done(wait_background_tasks=True)
    assert not calls
    assert entry.runtime_data.active_controller.export_session.phase == "active"
    assert dict(entry.data) == original_settings


@pytest.mark.parametrize("reason", ["window_ended", "export_disabled", "ev_priority"])
@pytest.mark.parametrize("phase", ["starting", "active", "stopping", "recovering"])
async def test_owned_fallback_cleans_up_instead_of_restarting_when_permission_ends(
    export_fallback,
    freezer,
    reason,
    phase,
):
    harness, setup, calls = export_fallback
    overrides = {}
    if reason == "window_ended":
        freezer.move_to(NOW.replace(hour=21, minute=1))
    elif reason == "export_disabled":
        overrides["automatic_export_enabled"] = False
    else:
        overrides.update(ev_before_export_enabled=True, ev_before_export_soc_target_percent=50)
    entry = await setup(phase=phase, overrides=overrides)
    active = entry.runtime_data.active_controller
    assert calls == [(MODE, "Self Use"), (DISCHARGE, 0)]
    assert active.export_session.phase == "stopping"
    await active.async_reconcile()
    assert active.export_session.phase == "idle"
    assert not any(value == "Force Discharge" for _, value in calls)


@pytest.mark.parametrize(
    "overrides",
    [
        {"automatic_control_enabled": False},
        {"rehearsal_mode": True},
        {"foxess_control_owner": "foxcloud_scheduler"},
        {"foxess_control_owner": "observer_only"},
        {"sign_conventions_verified": False},
        {"foxess_force_discharge_power_entity": ""},
    ],
)
async def test_fallback_recovery_cannot_bypass_an_absolute_write_gate(export_fallback, overrides):
    _, setup, calls = export_fallback
    entry = await setup(overrides=overrides)
    assert not calls
    assert entry.runtime_data.active_controller.export_session.phase == "recovering"


@pytest.mark.parametrize("entity", [MODE, CHARGE, DISCHARGE])
async def test_unavailable_actuator_feedback_cannot_reassert_fallback(export_fallback, entity):
    harness, setup, calls = export_fallback
    entry = await setup(overrides={"rehearsal_mode": True})
    await harness.unload(entry)
    await harness.set_unavailable(entity)
    harness.hass.config_entries.async_update_entry(
        entry, data={**entry.data, "rehearsal_mode": False}
    )
    await harness.setup(entry)
    assert not calls
    assert entry.runtime_data.active_controller.export_session.phase == "recovering"


@pytest.mark.parametrize("journal", [False, True])
async def test_feed_in_first_without_an_unfinished_export_is_left_alone(export_fallback, journal):
    _, setup, calls = export_fallback
    entry = await setup(phase="idle", journal=journal)
    assert not calls
    assert entry.runtime_data.active_controller.last_reason in [
        "ownership_unknown",
        "external_forced_mode",
    ]
    assert entry.runtime_data.active_controller.export_session.phase == "idle"


async def test_manual_stop_still_relinquishes_the_recovered_export(export_fallback):
    harness, setup, calls = export_fallback
    entry = await setup()
    active = entry.runtime_data.active_controller
    result = await active.manual.async_request("self_use")
    assert result["hold"] and result["command_confirmed"]
    assert active.export_session.phase == "idle"
    calls.clear()
    await harness.set_state(
        MODE,
        "Feed-in First",
        {
            "options": ["Self Use", "Feed-in First", "Force Charge", "Force Discharge"],
        },
    )
    await active.async_reconcile()
    assert not any(value == "Force Discharge" for _, value in calls)
    assert active.manual.is_active


async def test_corrupt_persisted_export_cannot_adopt_feed_in_first(export_fallback):
    _, setup, calls = export_fallback
    entry = await setup(phase="invalid_phase")
    assert not calls
    assert entry.runtime_data.active_controller.export_session.phase == "idle"
    assert entry.runtime_data.active_controller.last_reason == "ownership_unknown"
