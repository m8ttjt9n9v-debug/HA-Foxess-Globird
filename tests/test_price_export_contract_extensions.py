"""Append-only market surfaces and legacy export journal compatibility."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from custom_components.home_energy_orchestrator.planner.export_session import ExportSessionState
from scripts.config_contract import ADDITIVE_CONFIG_KEYS, build_config_contract
from scripts.entity_contract import build_entity_contract, validate_against_release_baseline

ROOT = Path(__file__).resolve().parents[1]


def test_price_export_adds_only_five_reviewed_configuration_keys() -> None:
    extension = json.loads(
        (ROOT / "docs/maintainability/config-additions-price-export-v1.json").read_text()
    )
    historical = build_config_contract()
    current = build_config_contract(include_extensions=True)
    assert set(extension["additional_config_keys"]) == ADDITIVE_CONFIG_KEYS
    assert current["config_entry_version"] == historical["config_entry_version"] == 6
    assert (
        set(current["declared_config_keys"]) - set(historical["declared_config_keys"])
    ) == set(extension["additional_config_keys"])
    assert current["page_field_count"] == historical["page_field_count"] + 5


def test_price_export_admits_only_monitor_and_one_automatic_request() -> None:
    validate_against_release_baseline()
    baseline = json.loads(
        (ROOT / "docs/maintainability/entity-contract-v0.12.26.json").read_text()
    )
    old = {(record["platform"], record["key"]) for record in baseline["entities"]}
    new = {
        (record["platform"], record["key"])
        for record in build_entity_contract()["entities"]
    } - old
    assert new == {
        ("sensor", "aemo_market_status"), ("sensor", "aemo_spot_price"),
        ("switch", "aemo_monitor"), ("select", "aemo_region"),
        ("number", "aemo_export_threshold"), ("number", "aemo_import_threshold"),
        ("button", "aemo_clear_import_threshold"), ("switch", "critical_event_sell"),
    }


def test_legacy_export_journal_keeps_exact_four_field_payload() -> None:
    record = json.loads(
        (ROOT / "docs/maintainability/export-session-payload-additions-price-export-v1.json")
        .read_text()
    )
    payload = {
        "phase": "active", "requested_power_kw": 4.0,
        "attempts": 1, "last_command_at": "2026-01-01T01:00:00+00:00",
    }
    restored = ExportSessionState.from_payload(payload)
    assert set(payload) == set(record["retained_fields"])
    assert restored.authority_source == record["legacy_defaults"]["authority_source"]
    assert restored.price_deadline is None
    assert restored.to_payload() == payload


def test_price_export_uses_existing_journal_with_three_explicit_fields() -> None:
    deadline = datetime(2026, 1, 1, 1, 5, tzinfo=UTC)
    state = ExportSessionState(
        phase="active", requested_power_kw=4.0, attempts=1,
        authority_source="price", price_deadline=deadline,
        price_actuator_entities=(
            "select.battery_work_mode", "number.force_charge", "number.force_discharge",
        ),
    )
    record = json.loads(
        (ROOT / "docs/maintainability/export-session-payload-additions-price-export-v1.json")
        .read_text()
    )
    payload = state.to_payload()
    assert set(payload) == set(record["retained_fields"] + record["additional_fields"])
    assert payload["price_deadline"] == deadline.isoformat()
    assert payload["price_actuator_entities"] == list(state.price_actuator_entities)
    assert ExportSessionState.from_payload(payload) == state
