"""One persisted reservation choice without disabling existing EV protection."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform, entity_registry

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import DOMAIN

from .test_config_flow import _open_reconfigure_page, _schema_values
from .test_ev_backfill_controls import _setup
from .test_reconfigure_concurrency import _apply
from .test_setup import ENTRY_DATA

KEY = "ev_reservation_mode"
ENTITY = "select.home_energy_ev_reservation_mode"
MODES = ("fixed", "dynamic")


async def _set(hass, mode):
    await hass.services.async_call(
        "select", "select_option", {"entity_id": ENTITY, "option": mode}, blocking=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize("master", [False, True])
@pytest.mark.parametrize("mode", MODES)
async def test_native_service_changes_only_mode_and_reconciles_shared_protection(
    hass, monkeypatch, master, mode,
):
    entry = await _setup(hass, data={
        "ev_before_export_enabled": master, "ev_daily_backfill_energy_kwh": 4.5,
    })
    owner = entry.runtime_data
    before = dict(entry.data)
    calls = []

    async def refreshed():
        assert owner.runtime_config.ev_preferences.reservation_mode == mode
        calls.append("ledger")

    async def ev():
        calls.append("ev")

    async def export():
        calls.append("export")

    monkeypatch.setattr(owner, "async_request_refresh", refreshed)
    monkeypatch.setattr(owner.ev_controller, "async_reconcile", ev)
    monkeypatch.setattr(owner.active_controller, "async_reconcile", export)
    assert hass.states.get(ENTITY).state == "fixed"
    await _set(hass, mode)
    assert dict(entry.data) == {**before, KEY: mode}
    assert calls == ["ledger", "ev", "export"]
    assert entry.runtime_data is owner
    assert owner.runtime_config.ev_preferences.before_export_enabled is master
    assert entry.data["ev_daily_backfill_energy_kwh"] == 4.5
    assert hass.states.get(ENTITY).state == mode
    assert hass.states.get(ENTITY).attributes["options"] == list(MODES)
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("mode", MODES)
async def test_option_overlay_and_reload_preserve_one_mode_and_all_other_settings(hass, mode):
    entry = await _setup(hass, options={KEY: "dynamic", "reserve_kwh": 4.0})
    await _set(hass, mode)
    assert KEY not in entry.options
    assert entry.options == {"reserve_kwh": 4.0}
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(ENTITY).state == mode
    assert entry.runtime_data.runtime_config.ev_preferences.reservation_mode == mode
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("mode", MODES)
async def test_actual_wizard_accepts_mode_without_enabling_master_or_changing_fixed_energy(
    hass, mode,
):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER},
        data={"name": "Reservation", **ENTRY_DATA, KEY: mode, "ev_daily_backfill_energy_kwh": 0},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][KEY] == mode
    assert result["data"]["ev_daily_backfill_energy_kwh"] == 0
    assert result["data"]["ev_before_export_enabled"] is False
    assert result["data"]["ev_automatic_control_enabled"] is False


@pytest.mark.parametrize("invalid", ["automatic", "Dynamic", "", None, True, 1])
async def test_native_and_wizard_reject_unknown_mode_without_changing_intent(hass, invalid):
    entry = await _setup(hass, data={"ev_before_export_enabled": True})
    entity = next(
        platform.entities[ENTITY]
        for platform in entity_platform.async_get_platforms(hass, DOMAIN)
        if ENTITY in platform.entities
    )
    before = dict(entry.data), dict(entry.options)
    with pytest.raises(HomeAssistantError):
        await entity.async_select_option(invalid)
    assert (dict(entry.data), dict(entry.options)) == before
    flow = ConfigFlow()
    assert flow._validate_input(flow._apply_defaults({**ENTRY_DATA, KEY: invalid})) == {
        KEY: "invalid_ev_reservation_mode",
    }
    assert await hass.config_entries.async_unload(entry.entry_id)


def test_missing_mode_defaults_fixed_without_guessing_on_corrupt_saved_input():
    assert RuntimeConfiguration.from_mapping(ENTRY_DATA).ev_preferences.reservation_mode == "fixed"
    for bad in (None, True, "invalid", ""):
        assert RuntimeConfiguration.from_mapping({
            **ENTRY_DATA, KEY: bad,
        }).ev_preferences.reservation_mode not in MODES


@pytest.mark.parametrize("mode", MODES)
async def test_reconfigure_draft_commits_mode_only_at_review(hass, mode):
    entry = await _setup(hass, data={
        "configure_ev": True, "ev_before_export_enabled": True, KEY: "fixed",
    })
    before = dict(entry.data)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    flow = await _open_reconfigure_page(hass, flow, "ev_policies")
    values = _schema_values(flow["data_schema"])
    assert values[KEY] == "fixed"
    # The shared legacy fixture helper prefers ENTRY_DATA over displayed
    # defaults; retain this test's actual live master instead of submitting OFF.
    values["ev_before_export_enabled"] = True
    values[KEY] = mode
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input=values)
    assert dict(entry.data) == before
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[KEY] == mode and entry.data["ev_before_export_enabled"] is True
    assert hass.states.get(ENTITY).state == mode
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_unrelated_open_draft_keeps_newer_live_reservation_choice(hass):
    entry = await _setup(hass)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    flow = await _open_reconfigure_page(hass, flow, "aemo_monitor")
    values = _schema_values(flow["data_schema"])
    values["aemo_export_threshold_per_kwh"] = 4
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input=values)
    await _set(hass, "dynamic")
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[KEY] == "dynamic"
    assert hass.states.get(ENTITY).state == "dynamic"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_equal_concurrent_reservation_edit_is_idempotent(hass):
    entry = await _setup(hass, data={"configure_ev": True, KEY: "dynamic"})
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    flow = await _open_reconfigure_page(hass, flow, "ev_policies")
    values = _schema_values(flow["data_schema"])
    values[KEY] = "fixed"
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input=values)
    await _set(hass, "fixed")
    # Equal concurrent intent is safe, not a conflict or rewrite of the master.
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[KEY] == "fixed"
    assert entry.data["ev_before_export_enabled"] is False
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_renamed_entity_survives_reload(hass):
    entry = await _setup(hass)
    entity_registry.async_get(hass).async_update_entity(
        ENTITY, new_entity_id="select.owner_reservation", name="Owner reservation",
    )
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("select.owner_reservation").state == "fixed"
    assert hass.states.get(ENTITY) is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_setting_change_with_missing_sources_and_safety_lock_cannot_emit_device_command(hass):
    entry = await _setup(hass, data={
        "ev_before_export_enabled": True, "ev_automatic_control_enabled": True,
        "ev_control_commissioned": True, "rehearsal_mode": True,
    })
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    await _set(hass, "dynamic")
    assert len(calls) == 1
    assert calls[0].data["domain"] == "select"
    assert entry.data["ev_before_export_enabled"] is True
    assert entry.data["rehearsal_mode"] is True
    assert await hass.config_entries.async_unload(entry.entry_id)
