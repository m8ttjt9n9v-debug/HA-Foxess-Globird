"""Reconfiguration preserves raw saved values, not only effective defaults."""

from __future__ import annotations

from copy import deepcopy

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.const import DOMAIN

from .test_config_flow import _open_reconfigure_page, _schema_values
from .test_setup import ENTRY_DATA

ABSENT_POLICY_DEFAULTS = {
    "ev_before_export_soc_buffer_percent",
    "ev_solar_soak_battery_soc_percent",
    "ev_solar_soak_average_minutes",
    "ev_solar_soak_adjustment_minutes",
}


def _sparse_data():
    data = deepcopy(ENTRY_DATA)
    for key in ABSENT_POLICY_DEFAULTS:
        data.pop(key, None)
    return data


def _flow(hass, monkeypatch, *, options=None):
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", lambda _: None)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Sparse configuration",
        version=ConfigFlow.VERSION,
        data=_sparse_data(),
        options=options or {},
    )
    entry.add_to_hass(hass)
    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    return entry, flow


@pytest.mark.parametrize("mapping", ["sensor", "binary_sensor"])
def test_commit_keeps_unedited_absent_defaults_absent(hass, monkeypatch, mapping):
    entry, flow = _flow(hass, monkeypatch)
    before = dict(entry.data)
    key = "battery_power_entity" if mapping == "sensor" else "ev_local_connection_entity"
    pending = {**flow._current_reconfigure_data(entry), key: f"{mapping}.new_input"}
    assert ABSENT_POLICY_DEFAULTS <= pending.keys()

    result = flow._commit_reconfigure(pending, {key})

    assert result["reason"] == "reconfigure_successful"
    assert dict(entry.data) == {**before, key: f"{mapping}.new_input"}
    assert ABSENT_POLICY_DEFAULTS.isdisjoint(entry.data)


def test_commit_removes_only_edited_option_without_baking_other_options(hass, monkeypatch):
    options = {
        "aemo_export_threshold_per_kwh": 5.0,
        "house_learning_fallback_kwh": 23.0,
        "ev_charge_to_full_enabled": True,
        "future_option": "keep",
    }
    entry, flow = _flow(hass, monkeypatch, options=options)
    before = dict(entry.data)
    pending = {**flow._current_reconfigure_data(entry), "aemo_export_threshold_per_kwh": 4.0}

    flow._commit_reconfigure(pending, {"aemo_export_threshold_per_kwh"})

    assert dict(entry.data) == {**before, "aemo_export_threshold_per_kwh": 4.0}
    assert dict(entry.options) == {
        key: value for key, value in options.items() if key != "aemo_export_threshold_per_kwh"
    }
    assert entry.data["ev_charge_to_full_enabled"] is False
    assert entry.options["ev_charge_to_full_enabled"] is True
    assert ABSENT_POLICY_DEFAULTS.isdisjoint(entry.data)


def test_commit_explicit_clear_and_title_keep_raw_legacy_keys(hass, monkeypatch):
    entry, flow = _flow(hass, monkeypatch)
    legacy = {"ev_charger_profile": "older_profile", "future_setting": {"keep": True}}
    hass.config_entries.async_update_entry(entry, data={**entry.data, **legacy})
    before = dict(entry.data)
    pending = {
        **flow._current_reconfigure_data(entry),
        CONF_NAME: "Renamed configuration",
        "battery_power_entity": None,
    }

    flow._commit_reconfigure(pending, {CONF_NAME, "battery_power_entity"})

    assert entry.title == "Renamed configuration"
    assert dict(entry.data) == {**before, "battery_power_entity": None}
    assert CONF_NAME not in entry.data
    assert ABSENT_POLICY_DEFAULTS.isdisjoint(entry.data)


async def test_legacy_one_page_update_adds_no_unedited_policy_defaults(hass, monkeypatch):
    entry, _ = _flow(hass, monkeypatch)
    before = dict(entry.data)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        data={
            **ENTRY_DATA,
            CONF_NAME: entry.title,
            "aemo_export_threshold_per_kwh": 4.0,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert dict(entry.data) == {**before, "aemo_export_threshold_per_kwh": 4.0}
    assert ABSENT_POLICY_DEFAULTS.isdisjoint(entry.data)


async def test_conflict_after_sparse_draft_still_commits_nothing(hass, monkeypatch):
    entry, _ = _flow(hass, monkeypatch)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    flow = await _open_reconfigure_page(hass, flow, "aemo_monitor")
    values = _schema_values(flow["data_schema"])
    values["aemo_export_threshold_per_kwh"] = 4.0
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input=values)
    hass.config_entries.async_update_entry(
        entry, options={"aemo_export_threshold_per_kwh": 5.0}
    )
    before = dict(entry.data)

    result = await _open_reconfigure_page(hass, flow, "review")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_conflict"
    assert dict(entry.data) == before
    assert dict(entry.options) == {"aemo_export_threshold_per_kwh": 5.0}
    assert ABSENT_POLICY_DEFAULTS.isdisjoint(entry.data)
