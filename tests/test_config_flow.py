from __future__ import annotations

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.const import (
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_EV_CHARGE_LIMIT,
    CONF_EV_CHARGE_SWITCH,
    CONF_EV_CURRENT_LIMIT,
    CONF_EV_SOC,
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


async def test_user_flow_defaults_legacy_ev_control_gate_to_disabled(hass):
    legacy_data = {
        key: value
        for key, value in ENTRY_DATA.items()
        if key != CONF_EV_AUTOMATIC_CONTROL_ENABLED
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Legacy EV Site", **legacy_data},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_EV_AUTOMATIC_CONTROL_ENABLED] is False


async def test_user_flow_preserves_explicit_future_actuator_mappings(hass):
    mappings = {
        "foxess_work_mode_entity": "select.foxess_work_mode",
        "foxess_force_charge_power_entity": "number.foxess_force_charge_power",
        "foxess_force_discharge_power_entity": "number.foxess_force_discharge_power",
        "ev_charge_limit_entity": "number.tessie_charge_limit",
        "ev_current_limit_entity": "number.tessie_charge_current",
        "ev_charge_switch_entity": "switch.tessie_charge",
    }
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Mapped Site", **ENTRY_DATA, **mappings},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert {key: result["data"][key] for key in mappings} == mappings


async def test_entity_suggestions_find_common_tessie_entities(hass):
    hass.states.async_set(
        "sensor.tessy_battery_level", "59", {"friendly_name": "Tessy Battery level"}
    )
    hass.states.async_set(
        "number.tessy_charge_limit", "71", {"friendly_name": "Tessy Charge limit"}
    )
    hass.states.async_set(
        "number.tessy_charge_current", "16", {"friendly_name": "Tessy Charge current"}
    )
    hass.states.async_set("switch.tessy_charge", "off", {"friendly_name": "Tessy Charge"})
    flow = ConfigFlow()
    flow.hass = hass

    assert flow._suggest_entity(CONF_EV_SOC) == "sensor.tessy_battery_level"
    assert flow._suggest_entity(CONF_EV_CHARGE_LIMIT) == "number.tessy_charge_limit"
    assert flow._suggest_entity(CONF_EV_CURRENT_LIMIT) == "number.tessy_charge_current"
    assert flow._suggest_entity(CONF_EV_CHARGE_SWITCH) == "switch.tessy_charge"


async def test_entity_suggestions_leave_ambiguous_matches_blank(hass):
    hass.states.async_set("number.tessy_ev_charge_current", "16")
    hass.states.async_set("number.tessy_car_charge_current", "16")
    flow = ConfigFlow()
    flow.hass = hass

    assert flow._suggest_entity(CONF_EV_CURRENT_LIMIT) is None


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


async def test_user_flow_rejects_partial_ev_mapping(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Partial EV",
            **ENTRY_DATA,
            "ev_charge_limit_entity": "number.tessie_charge_limit",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "incomplete_ev_mapping"}


async def test_user_flow_rejects_unsafe_limits(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Test Site", **ENTRY_DATA, "inverter_capacity_kw": -1},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_site_limits"}


async def test_user_flow_rejects_invalid_load_following_rate(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Test Site", **ENTRY_DATA, "bonus_load_following_percent": 101},
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
