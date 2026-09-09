from __future__ import annotations

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_EV_BEFORE_EXPORT_ENABLED,
    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
    CONF_FOXESS_CONTROL_OWNER,
    DEFAULT_AUTOMATIC_CHARGE_ENABLED,
    DEFAULT_EV_BEFORE_EXPORT_ENABLED,
    DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
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


async def test_user_form_prefills_unambiguous_foxess_and_tessie_entities(hass):
    foxess = MockConfigEntry(domain="foxess_modbus")
    foxess.add_to_hass(hass)
    tessie = MockConfigEntry(domain="tessie")
    tessie.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "foxess_modbus",
        "battery_soc",
        suggested_object_id="battery_soc",
        config_entry=foxess,
    )
    registry.async_get_or_create(
        "sensor",
        "foxess_modbus",
        "grid_ct",
        suggested_object_id="grid_ct",
        config_entry=foxess,
    )
    registry.async_get_or_create(
        "sensor",
        "tessie",
        "car_battery_level",
        suggested_object_id="jns_x_battery_level",
        config_entry=tessie,
    )
    registry.async_get_or_create(
        "number",
        "tessie",
        "car_charge_current",
        suggested_object_id="jns_x_charge_current",
        config_entry=tessie,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    markers = {
        marker.schema: marker
        for marker in result["data_schema"].schema
        if hasattr(marker, "schema")
    }
    assert "ev_charge_to_full_entity" not in markers
    assert markers["battery_soc_entity"].default() == "sensor.battery_soc"
    assert markers["grid_power_entity"].default() == "sensor.grid_ct"
    assert markers["ev_soc_entity"].default() == "sensor.jns_x_battery_level"
    assert (
        markers["ev_current_limit_entity"].default()
        == "number.jns_x_charge_current"
    )


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


async def test_user_flow_defaults_legacy_automatic_charge_to_disabled(hass):
    legacy_data = {
        key: value for key, value in ENTRY_DATA.items() if key != CONF_AUTOMATIC_CHARGE_ENABLED
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Legacy charge site", **legacy_data},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_AUTOMATIC_CHARGE_ENABLED] is DEFAULT_AUTOMATIC_CHARGE_ENABLED


async def test_user_flow_defaults_legacy_ev_before_export_to_disabled(hass):
    legacy_data = {
        key: value
        for key, value in ENTRY_DATA.items()
        if key not in {CONF_EV_BEFORE_EXPORT_ENABLED, CONF_EV_BEFORE_EXPORT_SOC_TARGET}
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Legacy priority site", **legacy_data},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_EV_BEFORE_EXPORT_ENABLED] is DEFAULT_EV_BEFORE_EXPORT_ENABLED
    assert (
        result["data"][CONF_EV_BEFORE_EXPORT_SOC_TARGET]
        == DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET
    )


async def test_daily_backfill_is_allowed_with_foxcloud_when_fully_configured(hass):
    data = {
        **ENTRY_DATA,
        "foxess_control_owner": "foxcloud_scheduler",
        "ev_daily_backfill_energy_kwh": 5,
        "ev_daily_ready_time": "08:00:00",
        "ev_outside_inverter_percent": 30,
        "inverter_discharge_limit_kw": 15,
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Cloud EV Site", **data},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_daily_backfill_fails_closed_without_an_outside_power_cap(hass):
    data = {
        **ENTRY_DATA,
        "ev_daily_backfill_energy_kwh": 5,
        "ev_outside_inverter_percent": 0,
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Invalid Daily Backfill", **data},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_daily_ev_backfill"


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
    assert result["data"]["ev_current_limit_entity"] == "number.car_current"
    assert result["data"]["ev_charge_switch_entity"] == "switch.car_charge"
    removed = {
        "ev_charger_profile",
        "free_charge_full_battery_import_threshold_kwh",
        "bonus_load_following_percent",
    }
    assert not removed & result["data"].keys()


async def test_ev_commissioning_requires_complete_explicit_mapping(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Incomplete EV",
            **ENTRY_DATA,
            "service_import_limit_a": 63,
            "ev_control_commissioned": True,
            "ev_soc_entity": "sensor.car_soc",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "incomplete_ev_mapping"}


async def test_ev_commissioning_accepts_complete_explicit_mapping(hass):
    mappings = {
        "ev_soc_entity": "sensor.car_soc",
        "ev_at_home_entity": "device_tracker.car",
        "ev_cable_connected_entity": "binary_sensor.car_cable",
        "ev_charging_state_entity": "sensor.car_charging",
        "ev_actual_current_entity": "sensor.car_current",
        "ev_stored_energy_entity": "sensor.car_energy",
        "ev_current_limit_entity": "number.car_current",
        "ev_charge_limit_entity": "number.car_limit",
        "ev_charge_switch_entity": "switch.car_charge",
    }
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Commissioned EV",
            **ENTRY_DATA,
            **mappings,
            "service_import_limit_a": 63,
            "ev_control_commissioned": True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert {key: result["data"][key] for key in mappings} == mappings


async def test_outside_ev_policies_require_local_modbus_ownership(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Cloud-owned outside policy",
            **ENTRY_DATA,
            "ev_pre_free_backfill_enabled": True,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "outside_ev_policy_requires_local_modbus"}


async def test_solar_spill_requires_signed_battery_power_mapping(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Incomplete solar spill",
            **ENTRY_DATA,
            "foxess_control_owner": "local_modbus",
            "ev_solar_spill_enabled": True,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {
        "base": "solar_spill_battery_power_mapping_required"
    }


async def test_split_battery_mapping_must_be_complete(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Partial split battery",
            **ENTRY_DATA,
            "battery_charge_power_entity": "sensor.battery_charge",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "incomplete_split_battery_mapping"}


async def test_solar_spill_accepts_complete_split_battery_mapping(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Split battery solar spill",
            **ENTRY_DATA,
            "foxess_control_owner": "local_modbus",
            "ev_solar_spill_enabled": True,
            "battery_charge_power_entity": "sensor.battery_charge",
            "battery_discharge_power_entity": "sensor.battery_discharge",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_smart_socket_commissioning_requires_switch_and_physical_limit(hass):
    mappings = {
        "ev_soc_entity": "sensor.car_soc",
        "ev_at_home_entity": "device_tracker.car",
        "ev_cable_connected_entity": "binary_sensor.car_cable",
        "ev_charging_state_entity": "sensor.car_charging",
        "ev_actual_current_entity": "sensor.car_current",
        "ev_stored_energy_entity": "sensor.car_energy",
        "ev_current_limit_entity": "number.car_current",
        "ev_charge_limit_entity": "number.car_limit",
        "ev_charge_switch_entity": "switch.car_charge",
    }
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Smart socket incomplete",
            **ENTRY_DATA,
            **mappings,
            "service_import_limit_a": 63,
            "ev_control_commissioned": True,
            "ev_charge_path": "smart_socket",
            "ev_smart_socket_current_limit_a": 10,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "incomplete_smart_socket_mapping"}

    accepted = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Smart socket commissioned",
            **ENTRY_DATA,
            **mappings,
            "service_import_limit_a": 63,
            "ev_control_commissioned": True,
            "ev_charge_path": "smart_socket",
            "ev_smart_socket_entity": "switch.car_socket",
            "ev_smart_socket_current_limit_a": 10,
        },
    )
    assert accepted["type"] is FlowResultType.CREATE_ENTRY
    assert accepted["data"]["ev_smart_socket_entity"] == "switch.car_socket"


async def test_multiphase_ev_commissioning_requires_controlling_current_mapping(hass):
    mappings = {
        "ev_soc_entity": "sensor.car_soc",
        "ev_at_home_entity": "device_tracker.car",
        "ev_cable_connected_entity": "binary_sensor.car_cable",
        "ev_charging_state_entity": "sensor.car_charging",
        "ev_actual_current_entity": "sensor.car_current",
        "ev_stored_energy_entity": "sensor.car_energy",
        "ev_current_limit_entity": "number.car_current",
        "ev_charge_limit_entity": "number.car_limit",
        "ev_charge_switch_entity": "switch.car_charge",
    }
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Multiphase EV",
            **ENTRY_DATA,
            **mappings,
            "site_phase_count": 3,
            "service_import_limit_a": 80,
            "ev_control_commissioned": True,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "multiphase_current_mapping_required"}

    accepted = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Multiphase EV mapped",
            **ENTRY_DATA,
            **mappings,
            "site_phase_count": 3,
            "service_import_limit_a": 80,
            "site_grid_current_entity": "sensor.most_loaded_phase_current",
            "ev_control_commissioned": True,
        },
    )
    assert accepted["type"] is FlowResultType.CREATE_ENTRY


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


async def test_user_flow_rejects_overlapping_charge_and_export_sessions(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            "name": "Overlapping control windows",
            **ENTRY_DATA,
            "free_charge_window_start": "20:00:00",
            "free_charge_window_end": "22:00:00",
            "bonus_window_start": "18:00:00",
            "force_discharge_finish": "21:01:00",
            "automatic_charge_enabled": True,
            "automatic_export_enabled": True,
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


async def test_reconfigure_resets_sign_verification_when_a_source_changes(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Verified Site",
        version=2,
        data={**ENTRY_DATA, "sign_conventions_verified": True},
    )
    entry.add_to_hass(hass)
    updated = {
        **ENTRY_DATA,
        "grid_power_entity": "sensor.replacement_grid",
        "sign_conventions_verified": True,
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        data={"name": "Verified Site", **updated},
    )

    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    assert entry.data["grid_power_entity"] == "sensor.replacement_grid"
    assert entry.data["sign_conventions_verified"] is False
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_preserves_hidden_legacy_charge_to_full_mapping(hass):
    legacy_data = {
        key: value
        for key, value in ENTRY_DATA.items()
        if key != "ev_charge_to_full_enabled"
    }
    legacy_data["ev_charge_to_full_entity"] = "input_boolean.old_charge_to_full"
    entry = MockConfigEntry(domain=DOMAIN, title="Legacy Site", data=legacy_data)
    entry.add_to_hass(hass)

    submitted_data = {
        key: value
        for key, value in legacy_data.items()
        if key != "ev_charge_to_full_entity"
    }
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        data={"name": "Legacy Site", **submitted_data},
    )

    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    assert entry.data["ev_charge_to_full_entity"] == "input_boolean.old_charge_to_full"
    assert "ev_charge_to_full_enabled" not in entry.data
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_suggests_replacement_for_stale_mapping(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Old Test Site",
        data={**ENTRY_DATA, "battery_soc_entity": "sensor.removed_test_battery"},
    )
    entry.add_to_hass(hass)
    foxess = MockConfigEntry(domain="foxess_modbus")
    foxess.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor",
        "foxess_modbus",
        "battery_soc",
        suggested_object_id="battery_soc",
        config_entry=foxess,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )

    markers = {
        marker.schema: marker
        for marker in result["data_schema"].schema
        if hasattr(marker, "schema")
    }
    assert markers["battery_soc_entity"].default() == "sensor.battery_soc"


async def test_reconfigure_never_replaces_registered_existing_mapping(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Existing Site",
        data={**ENTRY_DATA, "battery_soc_entity": "sensor.custom_battery_soc"},
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "template",
        "custom_battery_soc",
        suggested_object_id="custom_battery_soc",
    )
    foxess = MockConfigEntry(domain="foxess_modbus")
    foxess.add_to_hass(hass)
    registry.async_get_or_create(
        "sensor",
        "foxess_modbus",
        "battery_soc",
        suggested_object_id="battery_soc",
        config_entry=foxess,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )

    markers = {
        marker.schema: marker
        for marker in result["data_schema"].schema
        if hasattr(marker, "schema")
    }
    assert markers["battery_soc_entity"].default() == "sensor.custom_battery_soc"
