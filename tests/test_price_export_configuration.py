"""Default-off price-export configuration and staged commissioning boundaries."""

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.configuration import (
    AemoMonitorConfiguration,
    RuntimeConfiguration,
)
from custom_components.home_energy_orchestrator.const import (
    AEMO_REGIONS,
    CONF_AEMO_EXPORT_THRESHOLD,
    CONF_AEMO_IMPORT_THRESHOLD,
    CONF_AEMO_MONITOR_ENABLED,
    CONF_AEMO_REGION,
    CONF_CRITICAL_EVENT_SELL_ENABLED,
    CONF_FOXESS_CONTROL_OWNER,
    DOMAIN,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from custom_components.home_energy_orchestrator.field_catalogue import FIELD_KEYS_BY_PAGE

from .test_setup import ENTRY_DATA


def test_legacy_defaults_are_off_without_inferred_region_or_consumption_rule():
    runtime = RuntimeConfiguration.from_mapping({})
    assert runtime.aemo_monitor == AemoMonitorConfiguration(False, None, 3.0, None)
    assert runtime.export.price_triggered_enabled is False
    assert not hasattr(runtime, "critical_events")
    defaults = ConfigFlow._apply_defaults({})
    assert defaults[CONF_AEMO_MONITOR_ENABLED] is False
    assert defaults[CONF_CRITICAL_EVENT_SELL_ENABLED] is False
    assert defaults[CONF_AEMO_EXPORT_THRESHOLD] == 3.0
    assert CONF_AEMO_REGION not in defaults
    assert CONF_AEMO_IMPORT_THRESHOLD not in defaults


@pytest.mark.parametrize("value", [None, 1, "true", "false", {}, []])
def test_malformed_saved_price_request_does_not_enable_export(value):
    assert not RuntimeConfiguration.from_mapping(
        {CONF_CRITICAL_EVENT_SELL_ENABLED: value}
    ).export.price_triggered_enabled


@pytest.mark.parametrize(
    "changes",
    [
        {CONF_AEMO_REGION: None},
        {CONF_AEMO_REGION: "NSW"},
        {CONF_AEMO_MONITOR_ENABLED: "false"},
        {CONF_AEMO_EXPORT_THRESHOLD: True},
        {CONF_AEMO_EXPORT_THRESHOLD: float("inf")},
        {CONF_AEMO_EXPORT_THRESHOLD: 0},
        {CONF_AEMO_IMPORT_THRESHOLD: float("nan")},
        {CONF_AEMO_IMPORT_THRESHOLD: True},
        {CONF_AEMO_IMPORT_THRESHOLD: 3},
    ],
)
def test_malformed_monitor_stays_inactive(changes):
    configuration = AemoMonitorConfiguration.from_mapping(
        {CONF_AEMO_MONITOR_ENABLED: True, CONF_AEMO_REGION: "NSW1", **changes}
    )
    assert configuration.enabled is False


@pytest.mark.parametrize("region", AEMO_REGIONS)
def test_explicit_region_and_threshold_are_independent_from_normal_limits(region):
    before = RuntimeConfiguration.from_mapping({})
    runtime = RuntimeConfiguration.from_mapping(
        {
            CONF_AEMO_MONITOR_ENABLED: True,
            CONF_AEMO_REGION: region,
            CONF_AEMO_EXPORT_THRESHOLD: 3.5,
            CONF_CRITICAL_EVENT_SELL_ENABLED: True,
        }
    )
    assert runtime.aemo_monitor.enabled
    assert runtime.aemo_monitor.region == region
    assert runtime.aemo_monitor.export_threshold_per_kwh == 3.5
    assert runtime.export.price_triggered_enabled
    assert runtime.export.automatic_limit_kwh == before.export.automatic_limit_kwh
    assert runtime.automation == before.automation
    assert runtime.electrical == before.electrical


def test_config_page_price_intent_requires_monitor_and_explicit_local_owner():
    assert ConfigFlow._validate_aemo_monitor({CONF_CRITICAL_EVENT_SELL_ENABLED: True}) == {
        CONF_CRITICAL_EVENT_SELL_ENABLED: "price_export_requires_monitor"
    }
    assert ConfigFlow._validate_aemo_monitor(
        {
            CONF_AEMO_MONITOR_ENABLED: True,
            CONF_AEMO_REGION: "NSW1",
            CONF_CRITICAL_EVENT_SELL_ENABLED: True,
        }
    ) == {CONF_CRITICAL_EVENT_SELL_ENABLED: "price_export_requires_local_modbus"}
    assert (
        ConfigFlow._validate_aemo_monitor(
            {
                CONF_AEMO_MONITOR_ENABLED: True,
                CONF_AEMO_REGION: "NSW1",
                CONF_CRITICAL_EVENT_SELL_ENABLED: True,
                CONF_FOXESS_CONTROL_OWNER: FOXESS_CONTROL_OWNER_MODBUS,
            }
        )
        == {}
    )


async def test_monitor_page_keeps_bad_draft_and_does_not_apply_before_review(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Test Site", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    prior = dict(entry.data)
    opened = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    assert "reconfigure_aemo_monitor" in opened["menu_options"]
    form = await hass.config_entries.flow.async_configure(
        opened["flow_id"], {"next_step_id": "reconfigure_aemo_monitor"}
    )
    assert form["type"] is FlowResultType.FORM
    assert (
        tuple(marker.schema for marker in form["data_schema"].schema)
        == (FIELD_KEYS_BY_PAGE["aemo_monitor"])
    )
    failed = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        {
            CONF_AEMO_MONITOR_ENABLED: True,
            CONF_AEMO_EXPORT_THRESHOLD: 3.25,
            CONF_CRITICAL_EVENT_SELL_ENABLED: False,
        },
    )
    assert failed["errors"] == {CONF_AEMO_REGION: "invalid_aemo_region"}
    assert entry.data == prior
    valid = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        {
            CONF_AEMO_MONITOR_ENABLED: True,
            CONF_AEMO_REGION: "QLD1",
            CONF_AEMO_EXPORT_THRESHOLD: 3.25,
            CONF_CRITICAL_EVENT_SELL_ENABLED: False,
        },
    )
    assert valid["type"] is FlowResultType.MENU
    assert entry.data == prior
