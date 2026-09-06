from __future__ import annotations

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_FOXESS_CONTROL_OWNER,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DOMAIN,
)

from .test_setup import ENTRY_DATA


async def test_user_flow_creates_a_config_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Test Site", **ENTRY_DATA},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Site"
    assert result["data"] == ENTRY_DATA


async def test_user_flow_defaults_existing_single_phase_ev_configuration(hass):
    data_without_phase = {
        key: value for key, value in ENTRY_DATA.items() if key != "ev_phase_count"
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Legacy Site", **data_without_phase},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["ev_phase_count"] == 1


async def test_user_flow_defaults_legacy_foxess_owner_to_observer(hass):
    legacy_data = {
        key: value for key, value in ENTRY_DATA.items() if key != CONF_FOXESS_CONTROL_OWNER
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Legacy FoxESS Site", **legacy_data},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_FOXESS_CONTROL_OWNER] == DEFAULT_FOXESS_CONTROL_OWNER


async def test_user_flow_defaults_legacy_automatic_export_to_disabled(hass):
    legacy_data = {
        key: value for key, value in ENTRY_DATA.items() if key != CONF_AUTOMATIC_EXPORT_ENABLED
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Legacy export site", **legacy_data},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_AUTOMATIC_EXPORT_ENABLED] is False


async def test_user_flow_defaults_legacy_ev_control_to_disabled(hass):
    legacy_data = {
        key: value
        for key, value in ENTRY_DATA.items()
        if key != CONF_EV_AUTOMATIC_CONTROL_ENABLED
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Legacy EV site", **legacy_data},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_EV_AUTOMATIC_CONTROL_ENABLED] is False


async def test_user_flow_removes_obsolete_rewritten_controller_fields(hass):
    legacy_fields = {
        "ev_current_limit_entity": "number.car_current",
        "ev_charge_switch_entity": "switch.car_charge",
        "ev_charger_profile": "single_phase_32a",
        "free_charge_full_battery_import_threshold_kwh": 49.0,
        "bonus_load_following_percent": 20.0,
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Legacy rewritten site", **ENTRY_DATA, **legacy_fields},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert not legacy_fields.keys() & result["data"].keys()


async def test_user_flow_preserves_explicit_foxess_actuator_mappings(hass):
    mappings = {
        "foxess_work_mode_entity": "select.foxess_work_mode",
        "foxess_force_charge_power_entity": "number.foxess_force_charge_power",
        "foxess_force_discharge_power_entity": "number.foxess_force_discharge_power",
    }
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Mapped Site", **ENTRY_DATA, **mappings},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert {key: result["data"][key] for key in mappings} == mappings


async def test_user_flow_rejects_partial_foxess_mapping(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Partial FoxESS",
            **ENTRY_DATA,
            "foxess_work_mode_entity": "select.foxess_work_mode",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "incomplete_foxess_mapping"}


async def test_user_flow_rejects_unsafe_limits(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Test Site", **ENTRY_DATA, "ev_phase_count": 0},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_site_limits"}


async def test_user_flow_accepts_configured_phase_counts_without_a_profile_table(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Explicit topology",
            **ENTRY_DATA,
            "site_phase_count": 2,
            "ev_phase_count": 2,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["site_phase_count"] == 2
    assert result["data"]["ev_phase_count"] == 2


async def test_user_flow_rejects_fractional_phase_counts(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Invalid topology", **ENTRY_DATA, "site_phase_count": 1.5},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_site_limits"}


async def test_user_flow_rejects_invalid_learning_schedule(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Test Site",
            **ENTRY_DATA,
            "free_charge_window_start": "12:00:00",
            "free_charge_window_end": "12:00:00",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_schedule"}


async def test_user_flow_rejects_negative_learning_fallback(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Test Site", **ENTRY_DATA, "house_learning_fallback_kwh": -1},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_schedule"}


async def test_reconfigure_updates_and_reloads_an_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Original Site", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    updated_data = {**ENTRY_DATA, "battery_capacity_kwh": 25.0}
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        data={"name": "Updated Site", **updated_data},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.title == "Updated Site"
    assert entry.data == updated_data
    assert await hass.config_entries.async_unload(entry.entry_id)
