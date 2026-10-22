"""Reviewed append-only Amber configuration, attributes and journal provenance."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from custom_components.home_energy_orchestrator.aemo_monitor import (
    AemoMarketMonitor,
    AemoMonitorResult,
    _MonitorState,
)
from custom_components.home_energy_orchestrator.configuration import AemoMonitorConfiguration
from scripts.config_contract import (
    ADDITIVE_CONFIG_KEYS,
    AEMO_CONFIG_KEYS,
    AMBER_ADDITIONS_PATH,
    AMBER_CONFIG_KEYS,
    EV_CAPACITY_CONFIG_KEYS,
    EV_EXPORT_BUFFER_CONFIG_KEYS,
    EV_IMPORT_CONFIG_KEYS,
    EV_LOCAL_CONNECTION_CONFIG_KEYS,
    LOAD_CONFIG_KEYS,
    PRICE_EXPORT_CONFIG_KEYS,
    SOLAR_SOAK_CONFIG_KEYS,
    build_config_contract,
)
from scripts.config_field_contract import (
    AMBER_ADDITIONS_PATH as AMBER_FIELDS_PATH,
)
from scripts.config_field_contract import build_config_field_contract
from scripts.config_usage_contract import (
    AMBER_ADDITIONS_PATH as AMBER_USAGE_PATH,
)
from scripts.config_usage_contract import build_config_usage_contract
from scripts.entity_attribute_contract import (
    AEMO_ADDITIONS_PATH as AEMO_ATTRIBUTES_PATH,
)
from scripts.entity_attribute_contract import (
    AMBER_ADDITIONS_PATH as AMBER_ATTRIBUTES_PATH,
)
from scripts.entity_attribute_contract import build_entity_attribute_contract
from scripts.entity_semantics import (
    AMBER_EXTENSIONS_PATH,
    load_semantic_contract,
)
from scripts.persistence_contract import build_persistence_contract
from tests.test_price_export_active import NOW

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_PATH = ROOT / "docs/maintainability/aemo-monitor-payload-additions-amber-price-v1.json"


def test_amber_price_configuration_is_only_its_separate_two_key_extension():
    reviewed = json.loads(AMBER_ADDITIONS_PATH.read_text())
    assert (
        set(reviewed["additional_config_keys"])
        == AMBER_CONFIG_KEYS
        == {
            "amber_price_entity",
            "amber_price_region",
        }
    )
    assert ADDITIVE_CONFIG_KEYS == (
        AEMO_CONFIG_KEYS
        | PRICE_EXPORT_CONFIG_KEYS
        | EV_CAPACITY_CONFIG_KEYS
        | AMBER_CONFIG_KEYS
        | LOAD_CONFIG_KEYS
        | SOLAR_SOAK_CONFIG_KEYS
        | EV_EXPORT_BUFFER_CONFIG_KEYS
        | EV_LOCAL_CONNECTION_CONFIG_KEYS
        | EV_IMPORT_CONFIG_KEYS
    )
    retained = build_config_contract()
    current = build_config_contract(include_extensions=True)
    assert retained["config_entry_version"] == current["config_entry_version"] == 6
    assert retained["page_field_count"] == 135
    assert current["page_field_count"] == 152
    assert set(current["declared_config_keys"]) - set(retained["declared_config_keys"]) == (
        ADDITIVE_CONFIG_KEYS
    )
    assert reviewed["automatic_control_defaults_changed"] is False
    assert reviewed["electrical_direction_verification_changed"] is False
    assert reviewed["new_credentials_or_http_poller"] is False


def test_only_two_explicit_optional_fields_follow_the_retained_price_page():
    reviewed = json.loads(AMBER_FIELDS_PATH.read_text())
    current = build_config_field_contract()
    amber_fields = [field for field in current["fields"] if field["key"] in AMBER_CONFIG_KEYS]
    assert reviewed["field_count"] == 2
    assert amber_fields == reviewed["fields"]
    assert [field["order"] for field in amber_fields] == [6, 7]
    assert all(
        field["required"] is False and field["has_default"] is False for field in amber_fields
    )


def test_amber_configuration_reads_are_exactly_reviewed_boundary_reads():
    reviewed = json.loads(AMBER_USAGE_PATH.read_text())
    current = build_config_usage_contract(include_extensions=True)["accesses"]
    actual = [item for item in current if item["key"] in AMBER_CONFIG_KEYS]
    assert reviewed["access_count"] == len(actual) == 4
    assert actual == reviewed["accesses"]
    assert {item["layer"] for item in actual} == {"boundary"}
    assert {item["kind"] for item in actual} == {"raw_mapping"}
    assert {item["access"] for item in actual} == {"get"}
    assert {item["source"] for item in actual} == {
        "custom_components/home_energy_orchestrator/configuration.py",
    }


def test_provider_attributes_extend_existing_entities_without_new_identity():
    original = json.loads(AEMO_ATTRIBUTES_PATH.read_text())
    extension = json.loads(AMBER_ATTRIBUTES_PATH.read_text())
    assert extension["entity_count"] == 0 and extension["entities"] == []
    assert extension["attribute_addition_count"] == 2
    additions = {item["entity_key"]: item for item in extension["attribute_additions"]}
    actual = {item["entity_key"]: item for item in build_entity_attribute_contract()["entities"]}
    assert set(additions) == {"aemo_market_status", "aemo_spot_price"}
    for old in original["entities"]:
        added = additions[old["entity_key"]]
        assert added["default_entity_id"] == old["default_entity_id"]
        assert set(added["custom_attributes"]) == {
            "source_entity",
            "source_updated_at",
            "source_confirmed",
            "amber_price_entity",
            "amber_price_region",
            "amber_source_status",
            "aemo_fallback_status",
        }
        assert not set(added["custom_attributes"]) & set(old["custom_attributes"])
        assert actual[old["entity_key"]]["custom_attributes"] == sorted(
            old["custom_attributes"] + added["custom_attributes"]
        )


def test_amber_semantics_only_append_descriptions_to_the_retained_market_profile():
    extension = json.loads(AMBER_EXTENSIONS_PATH.read_text())
    assert extension["entity_count"] == 0
    assert extension["entities"] == []
    assert extension["attribute_profiles"] == {}
    assert "DispatchIS branch" in extension["extension_note"]
    assert "not proof of a HEO HTTP fetch" in extension["extension_note"]
    additions = extension["attribute_profile_additions"]
    assert set(additions) == {"aemo_market_observation_v1"}
    records = additions["aemo_market_observation_v1"]
    attribute_extension = json.loads(AMBER_ATTRIBUTES_PATH.read_text())
    assert set(records) == set(attribute_extension["attribute_additions"][0]["custom_attributes"])
    current = load_semantic_contract()["attribute_profiles"]["aemo_market_observation_v1"]
    assert current["attributes"].items() >= records.items()
    assert "ex-GST" in records["source_entity"]
    assert "flags remain null" in records["source_confirmed"]
    assert "cannot prove its region" in records["amber_price_region"]
    assert "higher AEMO price cannot override" in records["amber_source_status"]


async def test_amber_journal_provenance_uses_existing_store_and_no_new_root_authority(hass):
    reviewed = json.loads(PAYLOAD_PATH.read_text())
    result = AemoMonitorResult(
        "possible_export_event",
        "NSW1",
        3.0,
        None,
        price_per_kwh=4,
        price_per_mwh=4000,
        interval_start=NOW,
        interval_end=NOW + timedelta(minutes=5),
        first_seen_at=NOW,
        successful_fetch_at=NOW,
        source_kind="amber",
        source_url="homeassistant://sensor.selected_price",
        source_entity="sensor.selected_price",
        source_updated_at=NOW,
        source_confirmed=True,
    )
    payload = _MonitorState(observations=[result], active_candidate=result).payload()
    assert reviewed["storage_version"] == 1
    assert reviewed["additional_stores"] == reviewed["additional_root_keys"] == []
    assert sorted(payload) == reviewed["retained_root_keys"]
    assert reviewed["export_session_schema_changed"] is False
    assert reviewed["restored_history_grants_current_permission"] is False
    old = json.loads(AEMO_ATTRIBUTES_PATH.read_text())["entities"][0]["custom_attributes"]
    observation_fields = set(old) - {"recent_observation_count", "persistence_status"}
    assert set(payload["observations"][0]) == observation_fields | set(
        reviewed["additional_observation_fields"]
    )
    monitor = AemoMarketMonitor(
        hass,
        "amber-contract",
        AemoMonitorConfiguration(
            True,
            "NSW1",
            3.0,
            None,
            "sensor.selected_price",
            "NSW1",
        ),
    )
    restored = monitor._decode_state(payload)
    assert restored.observations[0].source_kind == "amber"
    assert restored.observations[0].source_confirmed is True
    assert restored.observations[0].price_status is None
    assert restored.observations[0].apc_flag is None
    assert restored.observations[0].market_suspended_flag is None
    assert restored.observations[0].intervention is None
    assert not monitor.current_result.price_trigger_valid
    stores = build_persistence_contract()["stores"]
    # The separate paid-cap extension adds one counter, not Amber authority.
    assert len(stores) == 18
    assert [record for record in stores if record["source"].endswith("aemo_monitor.py")] == [
        {
            "attribute": "self._store",
            "private": True,
            "source": "custom_components/home_energy_orchestrator/aemo_monitor.py",
            "storage_key_expression": reviewed["storage_key_expression"],
            "version": 1,
        }
    ]
