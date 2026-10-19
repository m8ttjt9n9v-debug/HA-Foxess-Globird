"""Optional native Amber input settings without changing legacy AEMO defaults."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.config_page_schema import build_page_schema
from custom_components.home_energy_orchestrator.configuration import (
    AemoMonitorConfiguration,
    RuntimeConfiguration,
)
from custom_components.home_energy_orchestrator.const import (
    AEMO_REGIONS,
    CONF_AEMO_MONITOR_ENABLED,
    CONF_AEMO_REGION,
    CONF_AMBER_PRICE_ENTITY,
    CONF_AMBER_PRICE_REGION,
    DOMAIN,
)
from custom_components.home_energy_orchestrator.field_catalogue import FIELD_SPECS_BY_KEY

from .test_setup import ENTRY_DATA

_PRICE_SENSOR = "sensor.selected_feed_in_price"
_BASE = {CONF_AEMO_MONITOR_ENABLED: True, CONF_AEMO_REGION: "NSW1"}
_AMBER = {CONF_AMBER_PRICE_ENTITY: _PRICE_SENSOR, CONF_AMBER_PRICE_REGION: "NSW1"}


def test_amber_defaults_preserve_all_old_positional_monitor_constructors():
    old = AemoMonitorConfiguration(True, "NSW1", 3.0, None)
    assert old.amber_price_entity is None
    assert old.amber_price_region is None
    assert AemoMonitorConfiguration.from_mapping(_BASE) == old
    runtime = RuntimeConfiguration.from_mapping({})
    assert runtime.aemo_monitor == AemoMonitorConfiguration(False, None, 3.0, None)


@pytest.mark.parametrize("region", AEMO_REGIONS)
def test_valid_explicit_amber_pair_is_retained_without_changing_other_policy(region):
    baseline = RuntimeConfiguration.from_mapping(_BASE)
    changed = RuntimeConfiguration.from_mapping(
        {**_BASE, CONF_AMBER_PRICE_ENTITY: _PRICE_SENSOR, CONF_AMBER_PRICE_REGION: region}
    )
    assert changed.aemo_monitor.enabled
    assert changed.aemo_monitor.amber_price_entity == _PRICE_SENSOR
    assert changed.aemo_monitor.amber_price_region == region
    assert changed.export == baseline.export
    assert changed.automation == baseline.automation
    assert changed.electrical == baseline.electrical


@pytest.mark.parametrize(
    ("changes", "field", "error"),
    [
        ({CONF_AMBER_PRICE_ENTITY: _PRICE_SENSOR}, CONF_AMBER_PRICE_REGION,
         "invalid_amber_price_region"),
        ({CONF_AMBER_PRICE_REGION: "NSW1"}, CONF_AMBER_PRICE_ENTITY,
         "invalid_amber_price_entity"),
        *[
            ({**_AMBER, CONF_AMBER_PRICE_ENTITY: value}, CONF_AMBER_PRICE_ENTITY,
             "invalid_amber_price_entity")
            for value in ("", True, 12, [], {}, "switch.price", "sensor.",
                          "sensor.price extra", "sensor.a/b", "sensor.Price")
        ],
        *[
            ({**_AMBER, CONF_AMBER_PRICE_REGION: value}, CONF_AMBER_PRICE_REGION,
             "invalid_amber_price_region")
            for value in (None, "", True, [], {}, "NSW", "nsw1", "WA1")
        ],
    ],
)
def test_bad_amber_pair_is_rejected_but_runtime_keeps_valid_aemo_fallback(changes, field, error):
    values = {**_BASE, **changes}
    assert AemoMonitorConfiguration.validate_mapping(values) == {field: error}
    runtime = AemoMonitorConfiguration.from_mapping(values)
    assert runtime.enabled
    assert runtime.region == "NSW1"
    assert runtime.export_threshold_per_kwh == 3.0
    assert runtime.amber_price_entity is None
    assert runtime.amber_price_region is None


def test_monitor_region_change_does_not_silently_rebind_amber_or_disable_aemo():
    values = {**_BASE, **_AMBER, CONF_AEMO_REGION: "QLD1"}
    assert AemoMonitorConfiguration.validate_mapping(values) == {}
    runtime = AemoMonitorConfiguration.from_mapping(values)
    assert runtime.enabled
    assert runtime.region == "QLD1"
    assert runtime.amber_price_region == "NSW1"
    assert runtime.amber_price_entity == _PRICE_SENSOR
    # The source resolver, not the account binding, must fall back on mismatch.


def test_cleared_optional_pair_does_not_reappear_as_schema_defaults():
    schema = build_page_schema("aemo_monitor", _AMBER)
    fields = {marker.schema: (marker, validator) for marker, validator in schema.schema.items()}
    for key in (CONF_AMBER_PRICE_ENTITY, CONF_AMBER_PRICE_REGION):
        marker, _ = fields[key]
        assert isinstance(marker, vol.Optional)
        assert marker.default is vol.UNDEFINED
        assert marker.description["suggested_value"] == _AMBER[key]
    validated = schema({})
    assert CONF_AMBER_PRICE_ENTITY not in validated
    assert CONF_AMBER_PRICE_REGION not in validated
    assert AemoMonitorConfiguration.validate_mapping(
        {CONF_AMBER_PRICE_ENTITY: None, CONF_AMBER_PRICE_REGION: None}
    ) == {}


def test_amber_selector_is_native_integration_filtered_and_labels_explain_the_binding():
    schema = build_page_schema("aemo_monitor", {})
    fields = {marker.schema: validator for marker, validator in schema.schema.items()}
    config = fields[CONF_AMBER_PRICE_ENTITY].config
    assert config["filter"] == [{"domain": ["sensor"], "integration": "amberelectric"}]
    assert config["multiple"] is False
    assert fields[CONF_AMBER_PRICE_REGION].config["options"] == list(AEMO_REGIONS)
    assert FIELD_SPECS_BY_KEY[CONF_AMBER_PRICE_ENTITY].redaction == "omit"
    translations = json.loads(
        (Path(__file__).resolve().parents[1] / "custom_components"
         / "home_energy_orchestrator" / "translations" / "en.json").read_text()
    )
    steps = translations["config"]["step"]
    for step in ("user", "reconfigure", "reconfigure_aemo_monitor"):
        assert steps[step]["data"][CONF_AMBER_PRICE_ENTITY]
        assert steps[step]["data"][CONF_AMBER_PRICE_REGION]
    help_text = steps["reconfigure_aemo_monitor"]["data_description"]
    assert "spot_per_kwh" in help_text[CONF_AMBER_PRICE_ENTITY]
    assert "No second API key" in help_text[CONF_AMBER_PRICE_ENTITY]
    assert "cannot be detected" in help_text[CONF_AMBER_PRICE_REGION]


async def test_reconfigure_rejects_partial_pair_without_changing_live_saved_settings(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Test Site", data={**ENTRY_DATA, **_BASE})
    entry.add_to_hass(hass)
    prior = dict(entry.data)
    opened = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    form = await hass.config_entries.flow.async_configure(
        opened["flow_id"], {"next_step_id": "reconfigure_aemo_monitor"}
    )
    assert form["type"] is FlowResultType.FORM
    rejected = await hass.config_entries.flow.async_configure(
        form["flow_id"], {**_BASE, CONF_AMBER_PRICE_ENTITY: _PRICE_SENSOR}
    )
    assert rejected["errors"] == {CONF_AMBER_PRICE_REGION: "invalid_amber_price_region"}
    assert entry.data == prior
    accepted = await hass.config_entries.flow.async_configure(
        form["flow_id"], {**_BASE, **_AMBER}
    )
    assert accepted["type"] is FlowResultType.MENU
    assert entry.data == prior
