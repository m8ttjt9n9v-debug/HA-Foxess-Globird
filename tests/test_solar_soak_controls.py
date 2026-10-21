"""One canonical solar-soak configuration shared by wizard and native controls."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform, entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.config_page_schema import iter_page_schema_fields
from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import DOMAIN

from .test_config_flow import _open_reconfigure_page, _schema_values
from .test_reconfigure_concurrency import _apply
from .test_setup import ENTRY_DATA

SETTINGS = (
    ("ev_solar_soak_battery_soc_percent", "ev_solar_soak_battery_soc", 90.0, 85.0),
    ("ev_solar_soak_average_minutes", "ev_solar_soak_average_minutes", 5.0, 7.0),
    ("ev_solar_soak_adjustment_minutes", "ev_solar_soak_adjustment_minutes", 5.0, 3.0),
)


async def _setup(hass, *, data=None, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Solar controls", version=ConfigFlow.VERSION,
        data={**ENTRY_DATA, **(data or {})}, options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def _set(hass, name, value):
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": f"number.home_energy_{name}", "value": value}, blocking=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize(("key", "name", "default", "chosen"), SETTINGS)
async def test_actual_number_service_updates_shared_config_and_only_ev_reconciler(
    hass, monkeypatch, key, name, default, chosen,
):
    entry = await _setup(hass)
    owner = entry.runtime_data
    original = dict(entry.data)
    assert hass.states.get(f"number.home_energy_{name}").state == str(default)
    ev = AsyncMock()
    fox = AsyncMock()
    monkeypatch.setattr(owner.ev_controller, "async_reconcile", ev)
    monkeypatch.setattr(owner.active_controller, "async_reconcile", fox)
    await _set(hass, name, chosen)
    assert dict(entry.data) == {**original, key: chosen}
    assert owner.runtime_config.ev_numbers.value(key, -1) == chosen
    assert hass.states.get(f"number.home_energy_{name}").state == str(chosen)
    ev.assert_awaited_once()
    fox.assert_not_awaited()
    assert entry.runtime_data is owner  # No reload or duplicate controller.
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(("key", "name", "default", "chosen"), SETTINGS)
async def test_dashboard_option_override_survives_reload_and_wizard_reads_it(
    hass, key, name, default, chosen,
):
    entry = await _setup(hass, options={key: default, "reserve_kwh": 4.0})
    await _set(hass, name, chosen)
    assert key not in entry.options
    assert entry.options["reserve_kwh"] == 4.0
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(f"number.home_energy_{name}").state == str(chosen)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    # Default ENTRY_DATA has no commissioned EV; the public page itself still
    # reads the same persisted value if that capability is selected later.
    schema = ConfigFlow()._page_schema("ev_policies", dict(entry.data))
    fields = {marker.schema: marker for marker, _ in iter_page_schema_fields(schema)}
    assert fields[key].default() == chosen
    hass.config_entries.flow.async_abort(flow["flow_id"])
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(("key", "name", "default", "chosen"), SETTINGS)
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1, 101, 2.5])
async def test_invalid_native_number_write_is_rejected_without_any_config_change(
    hass, key, name, default, chosen, invalid,
):
    entry = await _setup(hass)
    original = dict(entry.data)
    entity_id = f"number.home_energy_{name}"
    entity = next(
        platform.entities[entity_id]
        for platform in entity_platform.async_get_platforms(hass, DOMAIN)
        if entity_id in platform.entities
    )
    with pytest.raises(HomeAssistantError, match="solar-soak"):
        await entity.async_set_native_value(invalid)
    assert dict(entry.data) == original
    assert entry.runtime_data.runtime_config.ev_numbers.value(key, -1) == default
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(("key", "name", "default", "chosen"), SETTINGS)
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1, 101, 2.5, True])
def test_flow_validates_all_new_numbers_before_saving(key, name, default, chosen, invalid):
    flow = ConfigFlow()
    data = flow._apply_defaults({**ENTRY_DATA, key: invalid})
    assert flow._validate_input(data) == {key: "invalid_site_limits"}
    assert flow._page_limit_error("ev_policies", data) == {key: "invalid_site_limits"}


@pytest.mark.parametrize(("key", "name", "default", "chosen"), SETTINGS)
async def test_operator_setting_remains_editable_with_no_telemetry_but_cannot_command_hardware(
    hass, key, name, default, chosen,
):
    entry = await _setup(hass, data={
        "ev_automatic_control_enabled": True, "ev_control_commissioned": True,
        "ev_solar_spill_enabled": True, "foxess_control_owner": "local_modbus",
    })
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    await _set(hass, name, chosen)
    assert hass.states.get(f"number.home_energy_{name}").state == str(chosen)
    assert entry.data[key] == chosen
    assert len(calls) == 1
    assert calls[0].data["service_data"]["entity_id"] == f"number.home_energy_{name}"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(("key", "name", "default", "chosen"), SETTINGS)
async def test_unrelated_open_reconfigure_draft_preserves_newer_dashboard_value(
    hass, monkeypatch, key, name, default, chosen,
):
    entry = await _setup(hass)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    flow = await _open_reconfigure_page(hass, flow, "aemo_monitor")
    values = _schema_values(flow["data_schema"])
    values["aemo_export_threshold_per_kwh"] = 4
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input=values)
    await _set(hass, name, chosen)
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[key] == chosen
    assert hass.states.get(f"number.home_energy_{name}").state == str(chosen)
    assert await hass.config_entries.async_unload(entry.entry_id)


def test_missing_controls_default_but_corrupt_floor_disables_buffering():
    values = RuntimeConfiguration.from_mapping(ENTRY_DATA).ev_numbers
    for key, _name, default, _chosen in SETTINGS:
        assert values.value(key, -1) == default
    for bad in (float("nan"), float("inf"), -1, 101, True, None, "nonsense", 2.5):
        values = RuntimeConfiguration.from_mapping({
            **ENTRY_DATA, "ev_solar_soak_battery_soc_percent": bad,
        }).ev_numbers
        assert values.value("ev_solar_soak_battery_soc_percent", -1) == 100


async def test_registered_solar_control_rename_survives_reload(hass):
    entry = await _setup(hass)
    registry = entity_registry.async_get(hass)
    registry.async_update_entity(
        "number.home_energy_ev_solar_soak_battery_soc",
        new_entity_id="number.my_buffer_floor", name="My buffer floor",
    )
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("number.my_buffer_floor").state == "90.0"
    assert hass.states.get("number.home_energy_ev_solar_soak_battery_soc") is None
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(("key", "name", "default", "chosen"), SETTINGS)
async def test_grouped_reconfigure_page_edits_native_number_from_same_saved_value(
    hass, key, name, default, chosen,
):
    entry = await _setup(hass, data={"configure_ev": True})
    before = dict(entry.data)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    flow = await _open_reconfigure_page(hass, flow, "ev_policies")
    values = _schema_values(flow["data_schema"])
    assert "solar_soak" in values
    values["solar_soak"][key] = chosen
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input=values)
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[key] == chosen
    assert entry.data["grid_power_entity"] == before["grid_power_entity"]
    assert entry.data["battery_soc_entity"] == before["battery_soc_entity"]
    assert hass.states.get(f"number.home_energy_{name}").state == str(chosen)
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(("key", "name", "default", "chosen"), SETTINGS)
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1, 101, 2.5])
async def test_invalid_actual_number_service_does_not_persist(
    hass, key, name, default, chosen, invalid,
):
    entry = await _setup(hass)
    before = dict(entry.data)
    with pytest.raises((HomeAssistantError, ValueError)):
        await _set(hass, name, invalid)
    assert dict(entry.data) == before
    assert entry.runtime_data.runtime_config.ev_numbers.value(key, -1) == default
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "key", ["ev_solar_soak_average_minutes", "ev_solar_soak_adjustment_minutes"]
)
@pytest.mark.parametrize("bad", [0, -1, 31, float("nan"), float("inf"), True, None, 2.5])
def test_corrupt_runtime_periods_keep_reviewed_bounded_default(key, bad):
    config = RuntimeConfiguration.from_mapping({**ENTRY_DATA, key: bad})
    assert config.ev_numbers.value(key, -1) == 5.0
