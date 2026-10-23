"""The wizard and native timing selector share one preserved saved choice."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform, entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.config_page_schema import iter_page_schema_fields
from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import DOMAIN
from custom_components.home_energy_orchestrator.ev_backfill_settings import backfill_timing_error

from .test_config_flow import _open_reconfigure_page, _schema_values
from .test_reconfigure_concurrency import _apply
from .test_setup import ENTRY_DATA

KEY = "ev_pre_free_backfill_timing"
ENTITY = "select.home_energy_ev_backfill_timing"
CHOICES = ["conservative", "ready_by", "when_connected"]
ENABLED = {
    "configure_ev": True,
    "ev_pre_free_backfill_enabled": True,
    "foxess_control_owner": "local_modbus",
    "ev_daily_ready_time": "07:00:00",
    "ev_outside_inverter_percent": 50,
    "inverter_discharge_limit_kw": 15,
}


async def _setup(hass, *, data=None, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Backfill timing", version=ConfigFlow.VERSION,
        data={**ENTRY_DATA, **(data or {})}, options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def _set(hass, choice):
    await hass.services.async_call(
        "select", "select_option", {"entity_id": ENTITY, "option": choice}, blocking=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize("choice", CHOICES)
async def test_native_service_persists_one_key_and_only_reconciles_existing_ev(
    hass, monkeypatch, choice,
):
    entry = await _setup(hass, data=ENABLED)
    owner = entry.runtime_data
    original = dict(entry.data)
    ev, battery = AsyncMock(), AsyncMock()
    monkeypatch.setattr(owner.ev_controller, "async_reconcile", ev)
    monkeypatch.setattr(owner.active_controller, "async_reconcile", battery)
    assert hass.states.get(ENTITY).attributes["options"] == CHOICES
    await _set(hass, choice)
    assert dict(entry.data) == {**original, KEY: choice}
    assert owner.runtime_config.ev_policy.pre_free_backfill_timing == choice
    assert hass.states.get(ENTITY).state == choice
    assert entry.runtime_data is owner
    ev.assert_awaited_once()
    battery.assert_not_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("choice", CHOICES)
async def test_native_choice_overrides_only_matching_option_and_survives_reload(hass, choice):
    entry = await _setup(hass, options={KEY: "conservative", "reserve_kwh": 4})
    await _set(hass, choice)
    assert KEY not in entry.options
    assert entry.options["reserve_kwh"] == 4
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(ENTITY).state == choice
    schema = ConfigFlow()._page_schema("ev_policies", dict(entry.data))
    markers = {marker.schema: marker for marker, _ in iter_page_schema_fields(schema)}
    assert markers[KEY].default() == choice
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("choice", CHOICES)
async def test_setup_accepts_additional_timing_without_enabling_any_control(hass, choice):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER},
        data={"name": "Backfill settings", **ENTRY_DATA, KEY: choice},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][KEY] == choice
    assert result["data"]["ev_automatic_control_enabled"] is False
    assert result["data"]["ev_pre_free_backfill_enabled"] is False


@pytest.mark.parametrize("choice", CHOICES)
async def test_wizard_reconfiguration_commits_same_native_value_only_at_apply(hass, choice):
    entry = await _setup(hass, data={"configure_ev": True, KEY: "ready_by"})
    before = dict(entry.data)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    flow = await _open_reconfigure_page(hass, flow, "ev_policies")
    values = _schema_values(flow["data_schema"])
    values[KEY] = choice
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input=values)
    assert dict(entry.data) == before
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(ENTITY).state == choice
    assert entry.data["ev_pre_free_backfill_enabled"] is False
    assert entry.data["ev_automatic_control_enabled"] is False
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_unrelated_open_reconfigure_preserves_newer_dashboard_timing(hass):
    entry = await _setup(hass)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    flow = await _open_reconfigure_page(hass, flow, "aemo_monitor")
    values = _schema_values(flow["data_schema"])
    values["aemo_export_threshold_per_kwh"] = 4
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input=values)
    await _set(hass, "when_connected")
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[KEY] == "when_connected"
    assert hass.states.get(ENTITY).state == "when_connected"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("invalid", ["soon", "Ready by", "", None, 1])
async def test_unknown_native_choice_cannot_change_config(hass, invalid):
    entry = await _setup(hass)
    entity = next(
        platform.entities[ENTITY]
        for platform in entity_platform.async_get_platforms(hass, DOMAIN)
        if ENTITY in platform.entities
    )
    before = dict(entry.data), dict(entry.options)
    with pytest.raises(HomeAssistantError):
        await entity.async_select_option(invalid)
    assert (dict(entry.data), dict(entry.options)) == before
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(("changes", "expected"), [
    ({"ev_charge_path": "smart_socket"}, "when_connected_requires_direct_evse"),
    ({"ev_outside_inverter_percent": 0}, "invalid_ready_by_ev_backfill"),
    ({"inverter_discharge_limit_kw": 0}, "invalid_ready_by_ev_backfill"),
    ({"ev_daily_ready_time": "00:00:00"}, "invalid_ready_by_ev_backfill"),
    ({"ev_daily_ready_time": "12:01:00"}, "invalid_ready_by_ev_backfill"),
    ({"foxess_control_owner": "foxcloud_scheduler"}, "outside_ev_policy_requires_local_modbus"),
    ({"force_discharge_finish": "12:01:00"}, "invalid_when_connected_ev_backfill"),
    ({"force_discharge_finish": "08:00:00"}, "invalid_when_connected_ev_backfill"),
    ({"bonus_window_end": "06:00:00", "force_discharge_offset_minutes": 61},
     "invalid_when_connected_ev_backfill"),
])
async def test_same_cross_field_rejection_without_mutation_on_native_surface(
    hass, changes, expected,
):
    entry = await _setup(hass, data={**ENABLED, **changes})
    config = {**entry.data, KEY: "when_connected"}
    assert backfill_timing_error(RuntimeConfiguration.from_mapping(config)) == expected
    before = dict(entry.data), dict(entry.options)
    with pytest.raises(HomeAssistantError):
        await _set(hass, "when_connected")
    assert (dict(entry.data), dict(entry.options)) == before
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_configuration_without_evidence_or_with_lock_cannot_emit_hardware_commands(hass):
    entry = await _setup(hass, data={
        **ENABLED, "ev_automatic_control_enabled": True,
        "ev_control_commissioned": True, "rehearsal_mode": True,
    })
    calls = []
    assert hass.states.get("switch.home_energy_safety_lock").state == "on"
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    await _set(hass, "when_connected")
    assert hass.states.get(ENTITY).state == "when_connected"
    assert len(calls) == 1
    assert calls[0].data["domain"] == "select"
    assert calls[0].data["service_data"]["entity_id"] == ENTITY
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(("changes", "expected"), [
    ({}, None),
    ({"ev_outside_inverter_percent": 0}, "invalid_ready_by_ev_backfill"),
    ({"inverter_discharge_limit_kw": 0}, "invalid_ready_by_ev_backfill"),
    ({"ev_daily_ready_time": "00:00:00"}, "invalid_ready_by_ev_backfill"),
    ({"ev_daily_ready_time": "12:01:00"}, "invalid_ready_by_ev_backfill"),
    ({"bonus_window_end": "06:00:00", "force_discharge_offset_minutes": 61},
     "invalid_when_connected_ev_backfill"),
    ({"bonus_window_end": "12:00:00", "force_discharge_offset_minutes": 1},
     "invalid_when_connected_ev_backfill"),
])
async def test_actual_wizard_applies_same_when_connected_enabled_checks(hass, changes, expected):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER},
        data={"name": "Prompt timing", **ENTRY_DATA, **ENABLED, KEY: "when_connected", **changes},
    )
    if expected is None:
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][KEY] == "when_connected"
    else:
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": expected}


async def test_registered_select_rename_survives_reload(hass):
    entry = await _setup(hass)
    registry = entity_registry.async_get(hass)
    registry.async_update_entity(ENTITY, new_entity_id="select.my_backfill", name="My timing")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("select.my_backfill").state == "ready_by"
    assert hass.states.get(ENTITY) is None
    assert await hass.config_entries.async_unload(entry.entry_id)


REARM_KEY = "ev_surplus_rearm_energy_kwh"
REARM_ENTITY = "number.home_energy_ev_surplus_rearm_energy"


async def _set_rearm(hass, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": REARM_ENTITY, "value": value}, blocking=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize("value", [0.0, 0.01, 0.1, 1.23, 5.0])
async def test_rearm_margin_native_shared_value_options_and_reload(hass, monkeypatch, value):
    entry = await _setup(hass, options={REARM_KEY: 0.2, "reserve_kwh": 4})
    owner = entry.runtime_data
    ev, battery = AsyncMock(), AsyncMock()
    monkeypatch.setattr(owner.ev_controller, "async_reconcile", ev)
    monkeypatch.setattr(owner.active_controller, "async_reconcile", battery)
    before = dict(entry.data)
    await _set_rearm(hass, value)
    assert dict(entry.data) == {**before, REARM_KEY: value}
    assert entry.options == {"reserve_kwh": 4}
    assert owner.runtime_config.ev_numbers.value(REARM_KEY, -1) == value
    assert hass.states.get(REARM_ENTITY).state == str(value)
    ev.assert_awaited_once()
    battery.assert_not_awaited()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(REARM_ENTITY).state == str(value)
    fields = {
        marker.schema: marker for marker, _ in iter_page_schema_fields(
            ConfigFlow()._page_schema("ev_policies", dict(entry.data))
        )
    }
    assert fields[REARM_KEY].default() == value
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("invalid", [True, None, float("nan"), float("inf"), -0.01, 5.01, 0.001])
async def test_invalid_rearm_margin_rejected_by_native_wizard_and_saved_snapshot(hass, invalid):
    entry = await _setup(hass)
    entity = next(
        platform.entities[REARM_ENTITY]
        for platform in entity_platform.async_get_platforms(hass, DOMAIN)
        if REARM_ENTITY in platform.entities
    )
    before = dict(entry.data), dict(entry.options)
    with pytest.raises(HomeAssistantError, match="restart margin"):
        await entity.async_set_native_value(invalid)
    assert (dict(entry.data), dict(entry.options)) == before
    flow = ConfigFlow()
    data = flow._apply_defaults({**ENTRY_DATA, REARM_KEY: invalid})
    assert flow._validate_input(data) == {REARM_KEY: "invalid_site_limits"}
    assert flow._page_limit_error("ev_policies", data) == {REARM_KEY: "invalid_site_limits"}
    assert RuntimeConfiguration.from_mapping(data).ev_numbers.value(REARM_KEY, -1) > 5
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_rearm_margin_defaults_and_renamed_native_entity_preserved(hass):
    entry = await _setup(hass)
    assert entry.runtime_data.runtime_config.ev_numbers.value(REARM_KEY, -1) == 0.1
    assert REARM_KEY not in entry.data
    registry = entity_registry.async_get(hass)
    registry.async_update_entity(REARM_ENTITY, new_entity_id="number.my_restart_margin")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("number.my_restart_margin").state == "0.1"
    assert hass.states.get(REARM_ENTITY) is None
    assert entry.data["ev_automatic_control_enabled"] is False
    assert entry.data["ev_pre_free_backfill_enabled"] is False
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_rearm_margin_wizard_and_native_control_agree_without_enabling_policy(hass):
    entry = await _setup(hass, data={"configure_ev": True})
    before = dict(entry.data)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    flow = await _open_reconfigure_page(hass, flow, "ev_policies")
    values = _schema_values(flow["data_schema"])
    assert values[REARM_KEY] == 0.1
    values[REARM_KEY] = 0.25
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input=values)
    assert dict(entry.data) == before
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[REARM_KEY] == 0.25
    assert hass.states.get(REARM_ENTITY).state == "0.25"
    assert entry.data["ev_automatic_control_enabled"] is False
    assert entry.data["ev_pre_free_backfill_enabled"] is False
    assert await hass.config_entries.async_unload(entry.entry_id)
