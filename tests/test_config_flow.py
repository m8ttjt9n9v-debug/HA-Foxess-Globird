from __future__ import annotations

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN

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
