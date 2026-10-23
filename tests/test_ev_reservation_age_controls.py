"""Sleeping-SoC planning age shares one wizard/native value, not command freshness."""

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform, entity_registry

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.config_page_schema import iter_page_schema_fields
from custom_components.home_energy_orchestrator.configuration import (
    RuntimeConfiguration,
    valid_ev_reservation_soc_max_age_hours,
)
from custom_components.home_energy_orchestrator.const import (
    CONF_EV_RESERVATION_SOC_MAX_AGE_HOURS as KEY,
)
from custom_components.home_energy_orchestrator.const import (
    CONF_EV_TELEMETRY_MAX_AGE_SECONDS as FAST_KEY,
)
from custom_components.home_energy_orchestrator.const import (
    DEFAULT_EV_RESERVATION_SOC_MAX_AGE_HOURS as DEFAULT,
)
from custom_components.home_energy_orchestrator.const import (
    DEFAULT_EV_TELEMETRY_MAX_AGE_SECONDS as FAST_DEFAULT,
)
from custom_components.home_energy_orchestrator.const import (
    DOMAIN,
)

from .test_config_flow import _open_reconfigure_page, _schema_values
from .test_ev_backfill_controls import _setup
from .test_reconfigure_concurrency import _apply
from .test_setup import ENTRY_DATA

ENTITY = "number.home_energy_ev_reservation_soc_max_age_hours"
VALID = (0.025, 0.05, 1.0, 24.0, 47.975, 48.0)
INVALID = (None, True, False, -1, 0, 0.024, 0.026, 48.025, "bad", float("nan"), float("inf"))


async def _set(hass, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": ENTITY, "value": value}, blocking=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)


def test_missing_age_uses_default_and_never_rewrites_source_or_fast_telemetry():
    data = dict(ENTRY_DATA)
    runtime = RuntimeConfiguration.from_mapping(data)
    assert runtime.ev_numbers.value(KEY, -1) == DEFAULT == 24.0
    assert runtime.ev_numbers.value(FAST_KEY, -1) == FAST_DEFAULT == 90.0
    assert data == ENTRY_DATA and KEY not in data
    schema = ConfigFlow()._page_schema("ev_policies", ConfigFlow()._apply_defaults(data))
    fields = {
        marker.schema: (marker, validator)
        for marker, validator in iter_page_schema_fields(schema)
    }
    marker, selector = fields[KEY]
    assert marker.default() == DEFAULT
    assert selector.config == {
        "min": 0.025, "max": 48.0, "step": 0.025, "mode": "box", "unit_of_measurement": "h",
    }


@pytest.mark.parametrize("value", VALID)
def test_valid_age_boundary_values_share_setup_and_typed_configuration(value):
    assert valid_ev_reservation_soc_max_age_hours(value)
    flow = ConfigFlow()
    data = flow._apply_defaults({"name": "Planning age", **ENTRY_DATA, KEY: value})
    assert flow._validate_input(data) == {}
    assert RuntimeConfiguration.from_mapping(data).ev_numbers.value(KEY, -1) == value
    assert data[FAST_KEY] == FAST_DEFAULT


@pytest.mark.parametrize("value", INVALID)
def test_invalid_saved_and_setup_age_cannot_gain_default_authority(value):
    assert not valid_ev_reservation_soc_max_age_hours(value)
    flow = ConfigFlow()
    assert flow._validate_input(flow._apply_defaults({**ENTRY_DATA, KEY: value})) == {
        KEY: "invalid_site_limits",
    }
    runtime = RuntimeConfiguration.from_mapping({**ENTRY_DATA, KEY: value})
    assert runtime.ev_numbers.value(KEY, -1) == 0.0
    assert runtime.ev_numbers.value(FAST_KEY, -1) == FAST_DEFAULT


async def test_existing_entry_adds_native_control_without_saving_or_enabling(hass):
    entry = await _setup(hass)
    assert KEY not in entry.data and KEY not in entry.options
    number = hass.states.get(ENTITY)
    assert float(number.state) == DEFAULT
    assert number.attributes["unit_of_measurement"] == "h"
    assert number.attributes["min"] == 0.025 and number.attributes["max"] == 48.0
    assert number.attributes["step"] == 0.025
    assert number.attributes["mode"] == "box"
    assert entry.data["ev_automatic_control_enabled"] is False
    assert entry.runtime_data.runtime_config.ev_preferences.reservation_mode == "fixed"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("value", (0.025, 24.0, 48.0))
async def test_native_edit_persists_only_age_and_rechecks_existing_active_export_guard(
    hass, monkeypatch, value,
):
    entry = await _setup(hass, data={"ev_reservation_mode": "dynamic"})
    owner = entry.runtime_data
    before = dict(entry.data)
    calls = []
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    measurement = now - timedelta(hours=2)

    async def ledger():
        assert owner.runtime_config.ev_numbers.value(KEY, -1) == value
        calls.append("ledger")

    async def ev():
        calls.append("ev")

    async def active_export_guard():
        # Existing active work must see the newly shortened bound immediately;
        # the native control cannot retain an earlier in-memory 24-hour lease.
        bound = owner.runtime_config.ev_numbers.value(KEY, -1)
        assert ((now - measurement).total_seconds() <= bound * 3600) is (value >= 2)
        calls.append("export")

    monkeypatch.setattr(owner, "async_request_refresh", ledger)
    monkeypatch.setattr(owner.ev_controller, "async_reconcile", ev)
    monkeypatch.setattr(owner.active_controller, "async_reconcile", active_export_guard)
    await _set(hass, value)
    assert dict(entry.data) == {**before, KEY: value}
    assert owner.runtime_config.ev_numbers.value(FAST_KEY, -1) == FAST_DEFAULT
    assert calls == ["ledger", "ev", "export"]
    assert float(hass.states.get(ENTITY).state) == value
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("value", INVALID)
async def test_invalid_native_edit_preserves_all_settings(hass, value):
    entry = await _setup(hass)
    entity = next(
        platform.entities[ENTITY]
        for platform in entity_platform.async_get_platforms(hass, DOMAIN)
        if ENTITY in platform.entities
    )
    before = dict(entry.data), dict(entry.options)
    with pytest.raises(HomeAssistantError):
        await entity.async_set_native_value(value)
    assert (dict(entry.data), dict(entry.options)) == before
    assert float(hass.states.get(ENTITY).state) == DEFAULT
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_option_overlay_and_restart_preserve_only_one_saved_age(hass):
    entry = await _setup(hass, options={KEY: 48.0, "reserve_kwh": 4.0})
    assert float(hass.states.get(ENTITY).state) == 48.0
    await _set(hass, 12.0)
    assert entry.options == {"reserve_kwh": 4.0}
    assert entry.data[KEY] == 12.0
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert float(hass.states.get(ENTITY).state) == 12.0
    assert entry.runtime_data.runtime_config.ev_numbers.value(FAST_KEY, -1) == FAST_DEFAULT
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_flow_saves_age_without_selecting_dynamic_or_enabling_control(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER},
        data={"name": "Planning age", **ENTRY_DATA, KEY: 12.0},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][KEY] == 12.0
    assert result["data"]["ev_reservation_mode"] == "fixed"
    assert result["data"]["ev_automatic_control_enabled"] is False


async def test_reconfigure_age_commits_only_on_review(hass):
    entry = await _setup(hass, data={"configure_ev": True, KEY: 24.0})
    before = dict(entry.data)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    flow = await _open_reconfigure_page(hass, flow, "ev_policies")
    values = _schema_values(flow["data_schema"])
    assert values[KEY] == DEFAULT
    values[KEY] = 48.0
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input=values)
    assert dict(entry.data) == before
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[KEY] == 48.0
    assert float(hass.states.get(ENTITY).state) == 48.0
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_operator_entity_rename_survives_reload(hass):
    entry = await _setup(hass)
    entity_registry.async_get(hass).async_update_entity(
        ENTITY, new_entity_id="number.owner_soc_planning_age", name="Owner planning age",
    )
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert float(hass.states.get("number.owner_soc_planning_age").state) == DEFAULT
    assert hass.states.get(ENTITY) is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_missing_sources_and_safety_lock_edit_cannot_emit_device_command(hass):
    entry = await _setup(hass, data={
        "ev_before_export_enabled": True, "ev_automatic_control_enabled": True,
        "ev_control_commissioned": True, "rehearsal_mode": True,
    })
    events = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, events.append)
    await _set(hass, 48.0)
    assert len(events) == 1 and events[0].data["domain"] == "number"
    assert entry.data["rehearsal_mode"] is True
    assert entry.data["ev_before_export_enabled"] is True
    assert await hass.config_entries.async_unload(entry.entry_id)
