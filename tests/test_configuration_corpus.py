"""Sanitized configuration-corpus and complete draft-retention tests."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType, section

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.configuration import (
    RuntimeConfiguration,
)
from custom_components.home_energy_orchestrator.const import DOMAIN

from .test_setup import ENTRY_DATA


def _configuration_corpus() -> tuple[tuple[str, dict[str, object]], ...]:
    battery_only = {
        **ENTRY_DATA,
        "configure_solar": False,
        "configure_ev": False,
    }
    direct_ev = {
        **ENTRY_DATA,
        "configure_solar": True,
        "configure_ev": True,
        "solar_power_entity": "sensor.corpus_solar_power",
        "battery_power_entity": "sensor.corpus_battery_power",
        "service_import_limit_a": 63.0,
        "site_phase_count": 3,
        "site_grid_current_entity": "sensor.corpus_grid_current",
        "ev_control_commissioned": True,
        "ev_soc_entity": "sensor.corpus_ev_soc",
        "ev_at_home_entity": "binary_sensor.corpus_ev_home",
        "ev_cable_connected_entity": "binary_sensor.corpus_ev_cable",
        "ev_charging_state_entity": "sensor.corpus_ev_charging",
        "ev_actual_current_entity": "sensor.corpus_ev_current",
        "ev_stored_energy_entity": "sensor.corpus_ev_energy",
        "ev_current_limit_entity": "number.corpus_ev_current_limit",
        "ev_charge_limit_entity": "number.corpus_ev_charge_limit",
        "ev_charge_switch_entity": "switch.corpus_ev_charge",
        "foxess_control_owner": "local_modbus",
        "foxess_work_mode_entity": "select.corpus_work_mode",
        "foxess_force_charge_power_entity": "number.corpus_force_charge",
        "foxess_force_discharge_power_entity": "number.corpus_force_discharge",
        "inverter_charge_limit_kw": 10.0,
        "inverter_discharge_limit_kw": 10.0,
        "export_limit_kw": 5.0,
    }
    smart_socket_ev = {
        **direct_ev,
        "ev_charge_path": "smart_socket",
        "ev_smart_socket_entity": "switch.corpus_ev_socket",
        "ev_smart_socket_current_limit_a": 16.0,
        "ev_smart_socket_power_switching": True,
    }
    foxcloud_observer = {
        **battery_only,
        "foxess_control_owner": "foxcloud_scheduler",
        "globird_latest_daily_cost_entity": "sensor.corpus_daily_cost",
        "globird_zerohero_status_entity": "sensor.corpus_zerohero",
        "daily_import_entity": "sensor.corpus_daily_import",
    }
    legacy = {
        key: value
        for key, value in ENTRY_DATA.items()
        if key
        not in {
            "battery_power_positive_direction",
            "grid_power_positive_direction",
            "offpeak_export_rate_per_kwh",
            "force_discharge_offset_minutes",
            "automatic_export_limit_kwh",
            "ev_charge_to_full_enabled",
        }
    }
    legacy.update(
        {
            "battery_charge_positive": False,
            "grid_import_positive": True,
            "ev_charge_to_full_entity": "input_boolean.corpus_charge_to_full",
        }
    )
    return (
        ("battery_only", battery_only),
        ("direct_three_phase_ev", direct_ev),
        ("smart_socket_ev", smart_socket_ev),
        ("foxcloud_observer", foxcloud_observer),
        ("legacy", legacy),
    )


@pytest.mark.parametrize(("case_name", "data"), _configuration_corpus())
async def test_sanitized_configuration_corpus_round_trips_with_equivalent_meaning(
    hass,
    case_name: str,
    data: dict[str, object],
) -> None:
    payload = {
        "name": f"Corpus {case_name}",
        **data,
        "retained_unknown_extension": f"retain-{case_name}",
    }
    normalized = ConfigFlow._apply_defaults(dict(payload))  # noqa: SLF001
    expected_data = dict(normalized)
    expected_data.pop("name")
    expected_runtime = RuntimeConfiguration.from_mapping(expected_data)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data=dict(payload),
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    assert result["data"] == expected_data
    assert result["data"]["retained_unknown_extension"] == f"retain-{case_name}"
    assert ConfigFlow._apply_defaults(dict(result["data"])) == result["data"]  # noqa: SLF001
    assert RuntimeConfiguration.from_mapping(result["data"]) == expected_runtime


INVALID_PAGE_VALUES: tuple[tuple[str, str, object], ...] = (
    ("site", "name", ""),
    ("battery", "battery_floor_percent", -1),
    ("inverter", "inverter_charge_limit_kw", -1),
    ("grid", "site_phase_count", 0),
    ("tariff", "daily_charge", -1),
    ("house", "house_learning_fallback_kwh", -1),
    ("charger", "ev_voltage", 0),
    ("ev_policies", "ev_charge_efficiency_percent", 0),
    ("recovery", "ev_smart_recovery_no_power_seconds", 0),
    ("automation", "foxess_control_owner", "observer_only"),
)


def _displayed_values(
    result: Mapping[str, object],
    *,
    site_name: str,
) -> dict[str, object]:
    def schema_values(schema) -> dict[str, object]:
        values: dict[str, object] = {}
        for marker, validator in schema.schema.items():
            key = marker.schema
            if isinstance(validator, section):
                values[key] = schema_values(validator.schema)
            elif key in ENTRY_DATA:
                values[key] = ENTRY_DATA[key]
            elif marker.description and "suggested_value" in marker.description:
                values[key] = marker.description["suggested_value"]
            elif marker.default is not vol.UNDEFINED:
                values[key] = marker.default()
        return values

    values = schema_values(result["data_schema"])
    if result["step_id"] == "user":
        values.update(
            {
                "name": site_name,
                "configure_solar": True,
                "configure_ev": True,
            }
        )
    if result["step_id"] == "battery":
        values["battery_floor_percent"] = 13.0
    if result["step_id"] == "inverter":
        values.update(
            {
                "foxess_work_mode_entity": "select.retained_work_mode",
                "foxess_force_charge_power_entity": "number.retained_force_charge",
                "foxess_force_discharge_power_entity": "number.retained_force_discharge",
            }
        )
    if result["step_id"] == "solar":
        values["solar_power_entity"] = "sensor.retained_solar_power"
    if result["step_id"] == "car":
        values["ev_soc_entity"] = "sensor.retained_ev_soc"
    if result["step_id"] == "ev_policies":
        values["ev_pre_free_backfill_enabled"] = True
    if result["step_id"] == "automation":
        values["foxess_control_owner"] = "local_modbus"
    return values


@pytest.mark.parametrize(("invalid_page", "invalid_key", "invalid_value"), INVALID_PAGE_VALUES)
async def test_invalid_page_retains_complete_multi_page_draft(
    hass,
    invalid_page: str,
    invalid_key: str,
    invalid_value: object,
) -> None:
    site_name = f"Retained {invalid_page} draft"
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    invalid_submitted = False

    while result["step_id"] != "review":
        page = "site" if result["step_id"] == "user" else result["step_id"]
        valid_values = _displayed_values(result, site_name=site_name)
        if page == invalid_page:
            invalid_values = {**valid_values, invalid_key: invalid_value}
            rejected = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input=invalid_values
            )
            assert rejected["step_id"] == result["step_id"]
            assert rejected["errors"]
            markers = {
                marker.schema: marker for marker in rejected["data_schema"].schema
            }
            for key, value in invalid_values.items():
                if key in markers:
                    marker = markers[key]
                    if marker.default is not vol.UNDEFINED:
                        assert marker.default() == value
                    elif marker.description and "suggested_value" in marker.description:
                        assert marker.description["suggested_value"] == value
            result = rejected
            invalid_submitted = True
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=valid_values
        )

    assert invalid_submitted
    created = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"apply_configuration": True}
    )
    assert created["type"] is FlowResultType.CREATE_ENTRY, created
    assert created["title"] == site_name
    assert created["data"]["battery_floor_percent"] == 13.0
    assert created["data"]["solar_power_entity"] == "sensor.retained_solar_power"
    assert created["data"]["ev_soc_entity"] == "sensor.retained_ev_soc"
    assert created["data"]["sign_conventions_verified"] is False
