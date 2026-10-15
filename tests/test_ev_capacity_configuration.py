"""Explicit capacity configuration preserves legacy behavior and staged apply."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.config_page_schema import build_page_schema
from custom_components.home_energy_orchestrator.configuration import (
    EvCapacitySettings,
    RuntimeConfiguration,
)
from custom_components.home_energy_orchestrator.const import (
    CONF_EV_CAPACITY_ENTITY,
    CONF_EV_CAPACITY_FALLBACK_KWH,
    CONF_EV_CAPACITY_SOURCE,
    CONF_EV_STORED_ENERGY,
    DOMAIN,
    EV_CAPACITY_SOURCES,
)
from custom_components.home_energy_orchestrator.field_catalogue import FIELD_KEYS_BY_PAGE
from scripts.config_field_contract import TRANSLATION_PATH

from .test_setup import ENTRY_DATA


@pytest.fixture
def entry_reload(hass, monkeypatch):
    """Observe Apply's scheduled reload without starting unrelated controllers."""
    reload = AsyncMock(return_value=True)
    monkeypatch.setattr(hass.config_entries, "async_reload", reload)
    return reload


def test_legacy_snapshot_is_available_without_new_keys_or_enabled_requests():
    before = RuntimeConfiguration.from_mapping(ENTRY_DATA)
    assert before.ev_capacity == EvCapacitySettings("legacy_ratio", None, None)
    for source in EV_CAPACITY_SOURCES:
        after = RuntimeConfiguration.from_mapping(
            {
                **ENTRY_DATA,
                CONF_EV_CAPACITY_SOURCE: source,
                CONF_EV_CAPACITY_ENTITY: "sensor.car_capacity",
                CONF_EV_CAPACITY_FALLBACK_KWH: 75,
            }
        )
        assert after.ev_capacity == EvCapacitySettings(source, "sensor.car_capacity", 75.0)
        assert after.automation == before.automation
        assert after.electrical == before.electrical
        assert after.telemetry == before.telemetry
        assert after.ev_preferences == before.ev_preferences
    defaults = ConfigFlow._apply_defaults({})
    assert defaults[CONF_EV_CAPACITY_SOURCE] == "legacy_ratio"
    assert defaults[CONF_EV_CAPACITY_FALLBACK_KWH] == 0
    assert CONF_EV_CAPACITY_ENTITY not in defaults


@pytest.mark.parametrize(
    "value", [None, "", 0, 0.0, False, True, float("nan"), float("inf"), -1, 1001]
)
def test_runtime_never_turns_unset_or_invalid_fallback_into_capacity(value):
    assert (
        RuntimeConfiguration.from_mapping(
            {CONF_EV_CAPACITY_FALLBACK_KWH: value}
        ).ev_capacity.fallback_kwh
        is None
    )


@pytest.mark.parametrize("value", [1, 75.4, 1000, "82.5"])
def test_positive_commissioned_fallback_is_parsed_without_inference(value):
    assert RuntimeConfiguration.from_mapping(
        {CONF_EV_CAPACITY_FALLBACK_KWH: value}
    ).ev_capacity.fallback_kwh == float(value)


@pytest.mark.parametrize("source", [None, True, "auto", "unknown", {}])
def test_invalid_source_does_not_silently_revert_to_legacy(source):
    selected = RuntimeConfiguration.from_mapping({CONF_EV_CAPACITY_SOURCE: source}).ev_capacity
    assert selected.source != "legacy_ratio"
    assert EvCapacitySettings.validate_mapping({CONF_EV_CAPACITY_SOURCE: source}) == {
        CONF_EV_CAPACITY_SOURCE: "invalid_ev_capacity_source"
    }


@pytest.mark.parametrize(
    "value", [True, False, -1, 1001, float("nan"), float("inf"), "bad", 10**1000]
)
def test_validation_and_schema_reject_invalid_numeric_fallback(value):
    assert EvCapacitySettings.validate_mapping({CONF_EV_CAPACITY_FALLBACK_KWH: value}) == {
        CONF_EV_CAPACITY_FALLBACK_KWH: "invalid_ev_capacity_fallback"
    }
    schema = build_page_schema("car", {})
    with pytest.raises(vol.Invalid):
        schema({CONF_EV_CAPACITY_FALLBACK_KWH: value})


def test_three_appended_fields_have_translated_defaults_and_clearable_optional_values():
    assert FIELD_KEYS_BY_PAGE["car"][-3:] == (
        CONF_EV_CAPACITY_SOURCE,
        CONF_EV_CAPACITY_ENTITY,
        CONF_EV_CAPACITY_FALLBACK_KWH,
    )
    schema = build_page_schema(
        "car", {CONF_EV_CAPACITY_ENTITY: "sensor.saved_capacity", CONF_EV_CAPACITY_FALLBACK_KWH: 80}
    )
    markers = {marker.schema: marker for marker in schema.schema}
    assert markers[CONF_EV_CAPACITY_SOURCE].default() == "legacy_ratio"
    for key in (CONF_EV_CAPACITY_ENTITY, CONF_EV_CAPACITY_FALLBACK_KWH):
        assert markers[key].default is vol.UNDEFINED
        assert "suggested_value" in markers[key].description
    assert CONF_EV_CAPACITY_ENTITY not in schema({})
    assert CONF_EV_CAPACITY_FALLBACK_KWH not in schema({})
    translations = json.loads(TRANSLATION_PATH.read_text())
    steps = translations["config"]["step"]
    assert steps["car"]["data"] == steps["reconfigure_car"]["data"]
    assert steps["car"]["data_description"] == steps["reconfigure_car"]["data_description"]
    assert set(translations["selector"]["ev_capacity_source"]["options"]) == set(
        EV_CAPACITY_SOURCES
    )
    assert "not verified usable" in steps["car"]["data_description"][CONF_EV_CAPACITY_SOURCE]
    assert "ignores the new fallback" in steps["car"]["data_description"][CONF_EV_CAPACITY_SOURCE]


@pytest.mark.parametrize(
    "data,expected",
    [
        (
            {CONF_EV_CAPACITY_SOURCE: "configured"},
            {CONF_EV_CAPACITY_FALLBACK_KWH: "ev_capacity_fallback_required"},
        ),
        (
            {CONF_EV_CAPACITY_SOURCE: "configured", CONF_EV_CAPACITY_FALLBACK_KWH: 0},
            {CONF_EV_CAPACITY_FALLBACK_KWH: "ev_capacity_fallback_required"},
        ),
        (
            {CONF_EV_CAPACITY_SOURCE: "mapped_entity"},
            {CONF_EV_CAPACITY_ENTITY: "ev_capacity_mapping_required"},
        ),
        ({CONF_EV_CAPACITY_SOURCE: "tessie"}, {"ev_soc_entity": "ev_capacity_soc_required"}),
        ({CONF_EV_CAPACITY_SOURCE: "mapped_entity", CONF_EV_CAPACITY_FALLBACK_KWH: 75}, {}),
        (
            {CONF_EV_CAPACITY_SOURCE: "mapped_entity", CONF_EV_CAPACITY_ENTITY: "sensor.capacity"},
            {},
        ),
        ({CONF_EV_CAPACITY_SOURCE: "tessie", "ev_soc_entity": "sensor.explicit_soc"}, {}),
    ],
)
def test_source_requirements_are_explicit_and_do_not_guess_a_provider(data, expected):
    assert EvCapacitySettings.validate_mapping(data) == expected


@pytest.mark.parametrize("unit", ["Wh", "kWh"])
async def test_explicit_energy_sensor_units_are_accepted_when_temporarily_unavailable(hass, unit):
    flow = ConfigFlow()
    flow.hass = hass
    hass.states.async_set("sensor.capacity", "unavailable", {"unit_of_measurement": unit})
    assert (
        flow._validate_ev_capacity(
            {CONF_EV_CAPACITY_SOURCE: "mapped_entity", CONF_EV_CAPACITY_ENTITY: "sensor.capacity"}
        )
        == {}
    )


@pytest.mark.parametrize("unit", [None, "W", "kW", "%", "MWh"])
async def test_capacity_sensor_cannot_be_a_power_or_unqualified_unit(hass, unit):
    flow = ConfigFlow()
    flow.hass = hass
    hass.states.async_set("sensor.capacity", "80", {"unit_of_measurement": unit})
    assert flow._validate_ev_capacity({CONF_EV_CAPACITY_ENTITY: "sensor.capacity"}) == {
        CONF_EV_CAPACITY_ENTITY: "invalid_ev_capacity_unit"
    }


@pytest.mark.parametrize(
    "source,extra,complete",
    [
        ("legacy_ratio", {}, False),
        ("legacy_ratio", {CONF_EV_CAPACITY_FALLBACK_KWH: 75}, False),
        ("mapped_entity", {CONF_EV_CAPACITY_ENTITY: "sensor.capacity"}, True),
        ("mapped_entity", {CONF_EV_CAPACITY_FALLBACK_KWH: 75}, True),
        ("configured", {CONF_EV_CAPACITY_FALLBACK_KWH: 75}, True),
        ("tessie", {}, True),
    ],
)
async def test_selected_source_only_replaces_legacy_capacity_mapping_slot(
    hass, source, extra, complete
):
    flow = ConfigFlow()
    flow.hass = hass
    mappings = {
        "ev_soc_entity": "sensor.fixture_soc",
        "ev_at_home_entity": "device_tracker.fixture",
        "ev_cable_connected_entity": "binary_sensor.fixture_cable",
        "ev_charging_state_entity": "sensor.fixture_charging",
        "ev_actual_current_entity": "sensor.fixture_current",
        "ev_current_limit_entity": "number.fixture_current",
        "ev_charge_limit_entity": "number.fixture_limit",
        "ev_charge_switch_entity": "switch.fixture_charging",
    }
    data = flow._apply_defaults(
        {
            **ENTRY_DATA,
            **mappings,
            "name": "Capacity fixture",
            "service_import_limit_a": 40,
            "configure_ev": True,
            "ev_control_commissioned": True,
            CONF_EV_STORED_ENERGY: None,
            CONF_EV_CAPACITY_SOURCE: source,
            **extra,
        }
    )
    assert RuntimeConfiguration.from_mapping(data).ev_required_mapping_complete is complete
    assert (flow._validate_input(data) == {}) is complete


def _form_values(form):
    values = {}
    for marker in form["data_schema"].schema:
        key = marker.schema
        if key in ENTRY_DATA:
            values[key] = ENTRY_DATA[key]
        elif marker.description and "suggested_value" in marker.description:
            values[key] = marker.description["suggested_value"]
        elif marker.default is not vol.UNDEFINED:
            values[key] = marker.default()
    return values


async def _open_car(hass, changes):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Capacity fixture",
        version=6,
        data={
            **ENTRY_DATA,
            "configure_ev": True,
            "automatic_charge_enabled": False,
            "sign_conventions_verified": True,
            **changes,
        },
    )
    entry.add_to_hass(hass)
    opened = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    form = await hass.config_entries.flow.async_configure(
        opened["flow_id"], {"next_step_id": "reconfigure_car"}
    )
    return entry, form


async def test_reconfigure_selection_is_draft_only_and_preserves_failed_values(hass):
    entry, form = await _open_car(hass, {})
    before = dict(entry.data)
    values = {**_form_values(form), CONF_EV_CAPACITY_SOURCE: "mapped_entity"}
    values.pop(CONF_EV_CAPACITY_ENTITY, None)
    values.pop(CONF_EV_CAPACITY_FALLBACK_KWH, None)
    rejected = await hass.config_entries.flow.async_configure(form["flow_id"], values)
    assert rejected["errors"] == {CONF_EV_CAPACITY_ENTITY: "ev_capacity_mapping_required"}
    markers = {marker.schema: marker for marker in rejected["data_schema"].schema}
    assert markers[CONF_EV_CAPACITY_SOURCE].default() == "mapped_entity"
    values[CONF_EV_CAPACITY_FALLBACK_KWH] = 75
    accepted = await hass.config_entries.flow.async_configure(form["flow_id"], values)
    assert accepted["type"] is FlowResultType.MENU
    assert entry.data == before


async def test_clearing_optional_capacity_fields_persists_only_after_review_and_apply(
    hass, entry_reload
):
    entry, form = await _open_car(
        hass,
        {
            CONF_EV_CAPACITY_SOURCE: "mapped_entity",
            CONF_EV_CAPACITY_ENTITY: "sensor.saved_capacity",
            CONF_EV_CAPACITY_FALLBACK_KWH: 80,
        },
    )
    before = dict(entry.data)
    values = {**_form_values(form), CONF_EV_CAPACITY_SOURCE: "legacy_ratio"}
    values.pop(CONF_EV_CAPACITY_ENTITY, None)
    values.pop(CONF_EV_CAPACITY_FALLBACK_KWH, None)
    accepted = await hass.config_entries.flow.async_configure(form["flow_id"], values)
    assert accepted["type"] is FlowResultType.MENU
    assert entry.data == before
    review = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"next_step_id": "reconfigure_review"}
    )
    applied = await hass.config_entries.flow.async_configure(
        review["flow_id"], {"sign_conventions_verified": True, "apply_configuration": True}
    )
    await hass.async_block_till_done()
    entry_reload.assert_awaited_once_with(entry.entry_id)
    assert applied["type"] is FlowResultType.ABORT
    assert applied["reason"] == "reconfigure_successful"
    assert entry.data[CONF_EV_CAPACITY_SOURCE] == "legacy_ratio"
    assert entry.data[CONF_EV_CAPACITY_ENTITY] is None
    assert entry.data[CONF_EV_CAPACITY_FALLBACK_KWH] is None
    for key in (
        "automatic_control_enabled",
        "ev_automatic_control_enabled",
        "rehearsal_mode",
        "sign_conventions_verified",
    ):
        assert entry.data[key] == before[key]


async def test_configured_capacity_selection_persists_without_enabling_any_request(
    hass, entry_reload
):
    entry, form = await _open_car(hass, {})
    before = dict(entry.data)
    values = {
        **_form_values(form),
        CONF_EV_CAPACITY_SOURCE: "configured",
        CONF_EV_CAPACITY_FALLBACK_KWH: 75,
    }
    selected = await hass.config_entries.flow.async_configure(form["flow_id"], values)
    assert selected["type"] is FlowResultType.MENU
    assert entry.data == before
    review = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"next_step_id": "reconfigure_review"}
    )
    applied = await hass.config_entries.flow.async_configure(
        review["flow_id"], {"sign_conventions_verified": True, "apply_configuration": True}
    )
    await hass.async_block_till_done()
    entry_reload.assert_awaited_once_with(entry.entry_id)
    assert applied["reason"] == "reconfigure_successful"
    assert RuntimeConfiguration.from_mapping(entry.data).ev_capacity == EvCapacitySettings(
        "configured", None, 75.0
    )
    for key in (
        "automatic_control_enabled",
        "automatic_charge_enabled",
        "automatic_export_enabled",
        "ev_automatic_control_enabled",
        "rehearsal_mode",
        "sign_conventions_verified",
    ):
        assert entry.data[key] == before[key]


async def test_ev_disabled_skips_retained_capacity_source_requirements(hass):
    flow = ConfigFlow()
    flow.hass = hass
    candidate = flow._capability_safe_data(
        flow._apply_defaults(
            {
                **ENTRY_DATA,
                "name": "Capacity fixture",
                "configure_ev": False,
                CONF_EV_CAPACITY_SOURCE: "configured",
                CONF_EV_CAPACITY_FALLBACK_KWH: 0,
            }
        )
    )
    assert flow._validate_input(candidate) == {}
