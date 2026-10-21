"""Optional local connection commissioning is clearable and never activates control."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_RECONFIGURE

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.config_page_schema import build_page_schema
from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import CONF_EV_LOCAL_CONNECTION, DOMAIN
from tests.test_ev_capacity_configuration import _form_values, _open_car


def test_optional_mapping_default_does_not_infer_source_or_change_authority():
    original = ConfigFlow._apply_defaults({})
    before = deepcopy(original)
    assert CONF_EV_LOCAL_CONNECTION not in original
    runtime = RuntimeConfiguration.from_mapping(original)
    assert runtime.ev_connection.local_connection_entity is None
    selected = RuntimeConfiguration.from_mapping({
        **original, CONF_EV_LOCAL_CONNECTION: "binary_sensor.local_connection",
    })
    assert selected.ev_connection.local_connection_entity == "binary_sensor.local_connection"
    assert selected.automation == runtime.automation
    assert selected.ev_preferences == runtime.ev_preferences
    assert selected.electrical == runtime.electrical
    assert before == original
    schema = build_page_schema("charger", {CONF_EV_LOCAL_CONNECTION: "binary_sensor.saved"})
    markers = {m.schema: m for m in schema.schema}
    assert markers[CONF_EV_LOCAL_CONNECTION].default is vol.UNDEFINED
    assert markers[CONF_EV_LOCAL_CONNECTION].description["suggested_value"] == "binary_sensor.saved"
    assert CONF_EV_LOCAL_CONNECTION not in schema({})


@pytest.mark.parametrize("selected", [None, "binary_sensor.local_connection"])
async def test_native_reconfigure_draft_apply_and_clear_are_persistent(hass, monkeypatch, selected):
    reload = AsyncMock(return_value=True)
    monkeypatch.setattr(hass.config_entries, "async_reload", reload)
    entry, _ = await _open_car(hass, {CONF_EV_LOCAL_CONNECTION: "binary_sensor.saved"})
    before = deepcopy(dict(entry.data))
    opened = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    form = await hass.config_entries.flow.async_configure(
        opened["flow_id"], {"next_step_id": "reconfigure_charger"},
    )
    values = _form_values(form)
    values.pop(CONF_EV_LOCAL_CONNECTION, None)
    if selected:
        values[CONF_EV_LOCAL_CONNECTION] = selected
    result = await hass.config_entries.flow.async_configure(form["flow_id"], values)
    assert not result.get("errors")
    assert entry.data == before
    review = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"next_step_id": "reconfigure_review"},
    )
    applied = await hass.config_entries.flow.async_configure(
        review["flow_id"], {"sign_conventions_verified": True, "apply_configuration": True},
    )
    await hass.async_block_till_done()
    assert applied["reason"] == "reconfigure_successful"
    reload.assert_awaited_once_with(entry.entry_id)
    assert entry.data[CONF_EV_LOCAL_CONNECTION] == selected
    original = RuntimeConfiguration.from_mapping(before)
    current = RuntimeConfiguration.from_mapping(entry.data)
    assert current.automation == original.automation
    assert current.ev_preferences == original.ev_preferences
    reopened = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    form = await hass.config_entries.flow.async_configure(
        reopened["flow_id"], {"next_step_id": "reconfigure_charger"},
    )
    marker = next(m for m in form["data_schema"].schema if m.schema == CONF_EV_LOCAL_CONNECTION)
    assert marker.default is vol.UNDEFINED
    assert (marker.description or {}).get("suggested_value") == selected
