"""Reconfigure must merge form edits with newer persisted operator settings."""

from __future__ import annotations

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.const import DOMAIN

from .test_config_flow import _open_reconfigure_page, _schema_values
from .test_setup import ENTRY_DATA


async def _start(hass, *, data=None, options=None, setup=False):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Concurrent settings",
        version=ConfigFlow.VERSION,
        data={**ENTRY_DATA, **(data or {})},
        options=options or {},
    )
    entry.add_to_hass(hass)
    if setup:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        if data and "ev_charge_to_full_enabled" in data:
            await hass.services.async_call(
                "switch",
                "turn_on" if data["ev_charge_to_full_enabled"] else "turn_off",
                {"entity_id": "switch.home_energy_ev_charge_to_full"},
                blocking=True,
            )
            await hass.async_block_till_done()
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    return entry, flow


async def _edit(hass, result, page="aemo_monitor", **changes):
    result = await _open_reconfigure_page(hass, result, page)
    values = _schema_values(result["data_schema"])
    values.update(changes)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=values)
    assert result["type"] is FlowResultType.MENU
    return result


async def _apply(hass, result):
    result = await _open_reconfigure_page(hass, result, "review")
    values = {
        marker.schema: marker.default()
        for marker in result["data_schema"].schema
        if marker.default is not vol.UNDEFINED
    }
    values["apply_configuration"] = True
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input=values)


@pytest.mark.parametrize("initial", [False, True])
async def test_paged_aemo_reconfigure_keeps_newer_full_request_after_actual_reload(hass, initial):
    entry, flow = await _start(hass, data={"ev_charge_to_full_enabled": initial}, setup=True)
    assert entry.data["ev_charge_to_full_enabled"] is initial
    flow = await _edit(hass, flow, aemo_export_threshold_per_kwh=4.0)
    await hass.services.async_call(
        "switch",
        "turn_off" if initial else "turn_on",
        {"entity_id": "switch.home_energy_ev_charge_to_full"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.data["ev_charge_to_full_enabled"] is not initial

    result = await _apply(hass, flow)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data["ev_charge_to_full_enabled"] is not initial
    assert hass.states.get("switch.home_energy_ev_charge_to_full").state == (
        "off" if initial else "on"
    )
    assert entry.runtime_data.runtime_config.ev_preferences.charge_to_full_enabled is not initial
    assert entry.data["aemo_export_threshold_per_kwh"] == 4.0
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("initial", [False, True])
async def test_full_request_changed_after_review_is_preserved(hass, initial):
    entry, flow = await _start(hass, data={"ev_charge_to_full_enabled": initial}, setup=True)
    flow = await _edit(hass, flow, aemo_export_threshold_per_kwh=4.0)
    flow = await _open_reconfigure_page(hass, flow, "review")
    await hass.services.async_call(
        "switch",
        "turn_off" if initial else "turn_on",
        {"entity_id": "switch.home_energy_ev_charge_to_full"},
        blocking=True,
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        user_input={"apply_configuration": True, "sign_conventions_verified": False},
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data["ev_charge_to_full_enabled"] is not initial
    assert entry.runtime_data.runtime_config.ev_preferences.charge_to_full_enabled is not initial
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("key", "initial", "latest"),
    [
        ("automatic_control_enabled", False, True),
        ("automatic_charge_enabled", False, True),
        ("automatic_export_enabled", False, True),
        ("ev_automatic_control_enabled", False, True),
        ("ev_before_export_enabled", False, True),
        ("ev_morning_solar_enabled", False, True),
        ("ev_solar_spill_enabled", False, True),
        ("ev_pre_free_backfill_enabled", False, True),
        ("ev_allowance_guard_enabled", True, False),
        ("ev_smart_socket_power_switching", False, True),
        ("rehearsal_mode", True, False),
        ("aemo_monitor_enabled", False, True),
        ("critical_event_sell_enabled", False, True),
        ("house_occupancy_mode", "auto", "away"),
        ("ev_before_export_soc_target_percent", 40.0, 75.0),
        ("ev_morning_solar_reserve_soc_percent", 20.0, 35.0),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
async def test_unrelated_form_preserves_every_newer_dashboard_setting(
    hass, monkeypatch, key, initial, latest, reverse
):
    if reverse:
        initial, latest = latest, initial
    reloads = []
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", reloads.append)
    entry, flow = await _start(
        hass,
        data={
            "foxess_control_owner": "local_modbus",
            "battery_power_entity": "sensor.signed_battery",
            "solar_power_entity": "sensor.solar",
            "inverter_discharge_limit_kw": 10.0,
            "ev_outside_inverter_percent": 50.0,
            "aemo_region": "NSW1",
            "aemo_monitor_enabled": True,
            key: initial,
        },
    )
    flow = await _edit(hass, flow, aemo_export_threshold_per_kwh=4.0)
    hass.config_entries.async_update_entry(entry, data={**entry.data, key: latest})
    result = await _apply(hass, flow)
    if result.get("step_id") == "confirm_schedule":
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"confirm_schedule": True}
        )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[key] == latest
    assert entry.data["aemo_export_threshold_per_kwh"] == 4.0
    assert entry.data["ev_min_current"] == ENTRY_DATA["ev_min_current"]
    assert entry.data["ev_max_current"] == ENTRY_DATA["ev_max_current"]
    assert reloads == [entry.entry_id]


async def test_unvisited_optional_suggestion_is_not_a_configuration_edit(hass, monkeypatch):
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", lambda _: None)
    monkeypatch.setattr(
        ConfigFlow,
        "_discovery_defaults",
        lambda _: {"battery_power_entity": "sensor.suggested_battery"},
    )
    entry, flow = await _start(hass)
    flow = await _edit(hass, flow, aemo_export_threshold_per_kwh=4.0)
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    assert "battery_power_entity" not in entry.data


async def test_submitting_optional_suggestion_accepts_it(hass, monkeypatch):
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", lambda _: None)
    monkeypatch.setattr(
        ConfigFlow,
        "_discovery_defaults",
        lambda _: {"battery_power_entity": "sensor.suggested_battery"},
    )
    entry, flow = await _start(hass)
    flow = await _edit(hass, flow, "battery")
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["battery_power_entity"] == "sensor.suggested_battery"


async def test_effective_options_are_shown_and_only_edited_override_is_removed(hass, monkeypatch):
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", lambda _: None)
    entry, flow = await _start(
        hass,
        options={
            "aemo_export_threshold_per_kwh": 5.0,
            "aemo_import_threshold_per_kwh": -0.2,
            "ev_charge_to_full_enabled": False,
            "house_learning_fallback_kwh": 19.0,
            "future_unrelated_setting": "retained",
        },
    )
    flow = await _open_reconfigure_page(hass, flow, "aemo_monitor")
    markers = {marker.schema: marker for marker in flow["data_schema"].schema}
    assert markers["aemo_export_threshold_per_kwh"].default() == 5.0
    assert markers["aemo_import_threshold_per_kwh"].description["suggested_value"] == -0.2
    values = _schema_values(flow["data_schema"])
    values.pop("aemo_import_threshold_per_kwh")
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input=values)
    latest_options = {
        **entry.options,
        "ev_charge_to_full_enabled": True,
        "house_learning_fallback_kwh": 21.0,
    }
    hass.config_entries.async_update_entry(entry, options=latest_options)
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["aemo_import_threshold_per_kwh"] is None
    assert "aemo_import_threshold_per_kwh" not in entry.options
    assert entry.options == {
        key: value
        for key, value in latest_options.items()
        if key != "aemo_import_threshold_per_kwh"
    }
    assert entry.data["ev_charge_to_full_enabled"] is True
    assert entry.data["house_learning_fallback_kwh"] == 21.0


@pytest.mark.parametrize("same_value", [False, True])
async def test_same_field_concurrent_change_requires_reopening_unless_values_agree(
    hass, monkeypatch, same_value
):
    reloads = []
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", reloads.append)
    entry, flow = await _start(hass)
    flow = await _edit(hass, flow, aemo_export_threshold_per_kwh=4.0)
    latest = 4.0 if same_value else 5.0
    hass.config_entries.async_update_entry(entry, options={"aemo_export_threshold_per_kwh": latest})
    result = await _open_reconfigure_page(hass, flow, "review")
    if same_value:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"apply_configuration": True, "sign_conventions_verified": False},
        )
        assert result["reason"] == "reconfigure_successful"
        assert entry.data["aemo_export_threshold_per_kwh"] == 4.0
        assert "aemo_export_threshold_per_kwh" not in entry.options
        assert reloads == [entry.entry_id]
    else:
        assert result["reason"] == "reconfigure_conflict"
        assert entry.options["aemo_export_threshold_per_kwh"] == 5.0
        assert "aemo_export_threshold_per_kwh" not in entry.data
        assert reloads == []


async def test_same_field_conflict_after_review_does_not_apply_any_draft(hass, monkeypatch):
    reloads = []
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", reloads.append)
    entry, flow = await _start(hass)
    flow = await _edit(hass, flow, aemo_export_threshold_per_kwh=4.0)
    flow = await _open_reconfigure_page(hass, flow, "review")
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "aemo_export_threshold_per_kwh": 5.0}
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        user_input={"apply_configuration": True, "sign_conventions_verified": False},
    )
    assert result["reason"] == "reconfigure_conflict"
    assert entry.data["aemo_export_threshold_per_kwh"] == 5.0
    assert reloads == []


@pytest.mark.parametrize("initial", [False, True])
async def test_final_schedule_confirmation_reads_latest_full_without_baking_intermediate_value(
    hass, monkeypatch, initial
):
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", lambda _: None)
    entry, flow = await _start(
        hass,
        data={"automatic_charge_enabled": True, "ev_charge_to_full_enabled": initial},
    )
    flow = await _edit(hass, flow, aemo_export_threshold_per_kwh=4.0)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "ev_charge_to_full_enabled": not initial}
    )
    flow = await _apply(hass, flow)
    assert flow["step_id"] == "confirm_schedule"
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, "ev_charge_to_full_enabled": initial},
        options={"house_learning_fallback_kwh": 23.0},
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], user_input={"confirm_schedule": True}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["ev_charge_to_full_enabled"] is initial
    assert entry.options["house_learning_fallback_kwh"] == 23.0
    assert entry.data["aemo_export_threshold_per_kwh"] == 4.0
    assert entry.data["free_charge_schedule_confirmed"] is True


@pytest.mark.parametrize("field", ["grid_power_entity", "free_charge_window_start"])
async def test_schedule_confirmation_cannot_attest_changed_sources_or_times(
    hass, monkeypatch, field
):
    reloads = []
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", reloads.append)
    entry, flow = await _start(hass, data={"automatic_charge_enabled": True})
    flow = await _edit(hass, flow, aemo_export_threshold_per_kwh=4.0)
    flow = await _apply(hass, flow)
    assert flow["step_id"] == "confirm_schedule"
    latest = "sensor.new_grid" if field == "grid_power_entity" else "11:30:00"
    hass.config_entries.async_update_entry(entry, data={**entry.data, field: latest})
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], user_input={"confirm_schedule": True}
    )
    assert result["reason"] == "reconfigure_conflict"
    assert entry.data[field] == latest
    assert "aemo_export_threshold_per_kwh" not in entry.data
    assert reloads == []


async def test_review_does_not_reuse_sign_confirmation_after_concurrent_mapping_change(
    hass, monkeypatch
):
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", lambda _: None)
    entry, flow = await _start(hass, data={"sign_conventions_verified": True})
    flow = await _edit(hass, flow, aemo_export_threshold_per_kwh=4.0)
    flow = await _open_reconfigure_page(hass, flow, "review")
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            "grid_power_entity": "sensor.new_grid",
            "sign_conventions_verified": False,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        user_input={"apply_configuration": True, "sign_conventions_verified": True},
    )
    assert result["reason"] == "reconfigure_conflict"
    assert entry.data["sign_conventions_verified"] is False
    assert "aemo_export_threshold_per_kwh" not in entry.data


async def test_one_page_compatibility_rebases_again_after_schedule_delay(hass, monkeypatch):
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", lambda _: None)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="One-page client",
        version=ConfigFlow.VERSION,
        data={**ENTRY_DATA, "ev_charge_to_full_enabled": True},
        options={"house_learning_fallback_kwh": 21.0},
    )
    entry.add_to_hass(hass)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        data={
            **ENTRY_DATA,
            "name": "One-page client",
            "automatic_charge_enabled": True,
            "house_learning_fallback_kwh": 21.0,
        },
    )
    assert flow["step_id"] == "confirm_schedule"
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, "ev_charge_to_full_enabled": False},
        options={"house_learning_fallback_kwh": 24.0},
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], user_input={"confirm_schedule": True}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["ev_charge_to_full_enabled"] is False
    assert entry.options["house_learning_fallback_kwh"] == 24.0
    assert entry.data["automatic_charge_enabled"] is True


async def test_one_page_client_can_edit_current_fields_and_clear_option_override(hass, monkeypatch):
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", lambda _: None)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="One-page client",
        version=ConfigFlow.VERSION,
        data={**ENTRY_DATA, "ev_charge_to_full_enabled": True},
        options={"aemo_import_threshold_per_kwh": -0.2},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        data={
            **ENTRY_DATA,
            "name": "One-page client",
            "aemo_export_threshold_per_kwh": 4.0,
            "aemo_import_threshold_per_kwh": None,
        },
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["aemo_export_threshold_per_kwh"] == 4.0
    assert entry.data["aemo_import_threshold_per_kwh"] is None
    assert "aemo_import_threshold_per_kwh" not in entry.options
    assert entry.data["ev_charge_to_full_enabled"] is True


async def test_rebased_settings_are_validated_again_at_final_confirmation(hass, monkeypatch):
    reloads = []
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", reloads.append)
    entry, flow = await _start(hass, data={"automatic_charge_enabled": True})
    flow = await _edit(hass, flow, aemo_export_threshold_per_kwh=4.0)
    flow = await _apply(hass, flow)
    assert flow["step_id"] == "confirm_schedule"
    hass.config_entries.async_update_entry(entry, options={"foxess_control_owner": "invalid_owner"})
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], user_input={"confirm_schedule": True}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_conflict"
    assert "aemo_export_threshold_per_kwh" not in entry.data
    assert entry.options["foxess_control_owner"] == "invalid_owner"
    assert entry.data["free_charge_schedule_confirmed"] is False
    assert reloads == []


async def test_explicit_capability_removal_still_closes_dependent_requests(hass, monkeypatch):
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", lambda _: None)
    entry, flow = await _start(
        hass,
        data={
            "configure_ev": True,
            "ev_automatic_control_enabled": True,
            "ev_before_export_enabled": True,
        },
    )
    flow = await _edit(hass, flow, "site", configure_ev=False)
    result = await _apply(hass, flow)
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["configure_ev"] is False
    assert entry.data["ev_automatic_control_enabled"] is False
    assert entry.data["ev_before_export_enabled"] is False


async def test_explicit_optional_clear_conflicting_with_newer_mapping_aborts(hass, monkeypatch):
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", lambda _: None)
    entry, flow = await _start(hass, data={"aemo_import_threshold_per_kwh": -0.2})
    flow = await _open_reconfigure_page(hass, flow, "aemo_monitor")
    values = _schema_values(flow["data_schema"])
    values.pop("aemo_import_threshold_per_kwh")
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input=values)
    hass.config_entries.async_update_entry(entry, options={"aemo_import_threshold_per_kwh": -0.3})
    result = await _open_reconfigure_page(hass, flow, "review")
    assert result["reason"] == "reconfigure_conflict"
    assert entry.data["aemo_import_threshold_per_kwh"] == -0.2
    assert entry.options["aemo_import_threshold_per_kwh"] == -0.3
