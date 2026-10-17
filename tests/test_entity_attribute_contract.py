"""Compatibility tests for custom public Home Assistant attributes."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from scripts import entity_attribute_contract
from scripts.entity_attribute_contract import (
    AEMO_ADDITIONS_PATH,
    BASELINE_PATH,
    EV_CAPACITY_ADDITIONS_PATH,
    MANUAL_ADDITIONS_PATH,
    PRICE_ADDITIONS_PATH,
    TRIP_ADDITIONS_PATH,
    TRIP_IMPACT_ADDITIONS_PATH,
    TRIP_RESUME_ADDITIONS_PATH,
    build_entity_attribute_contract,
    validate_against_release_baseline,
)


def test_entity_attribute_contract_matches_reviewed_release_baseline() -> None:
    """Custom attribute changes require an explicit compatibility review."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    contract = build_entity_attribute_contract()
    validate_against_release_baseline()
    assert baseline["entity_count"] == 16
    manual = json.loads(MANUAL_ADDITIONS_PATH.read_text(encoding="utf-8"))
    monitor = json.loads(AEMO_ADDITIONS_PATH.read_text(encoding="utf-8"))
    price = json.loads(PRICE_ADDITIONS_PATH.read_text(encoding="utf-8"))
    trip = json.loads(TRIP_ADDITIONS_PATH.read_text(encoding="utf-8"))
    capacity = json.loads(EV_CAPACITY_ADDITIONS_PATH.read_text(encoding="utf-8"))
    impact = json.loads(TRIP_IMPACT_ADDITIONS_PATH.read_text(encoding="utf-8"))
    resume = json.loads(TRIP_RESUME_ADDITIONS_PATH.read_text(encoding="utf-8"))
    assert resume["entities"] == [] and resume["entity_count"] == 0
    assert resume["attribute_additions"] == [{
        "entity_key": "trip_charge_status",
        "default_entity_id": "sensor.home_energy_trip_charge_status",
        "custom_attributes": [
            "first_started_at", "full_stop_at", "full_stop_generation",
            "full_stop_reason", "timeout_at",
        ],
    }]
    assert impact["entities"] == [] and impact["entity_count"] == 0
    assert impact["attribute_additions"] == [{
        "entity_key": "trip_charge_status",
        "default_entity_id": "sensor.home_energy_trip_charge_status",
        "custom_attributes": ["energy_impact"],
    }]
    expected = {
        record["entity_key"]: deepcopy(record)
        for record in (
            baseline["entities"] + monitor["entities"] + trip["entities"] + capacity["entities"]
        )
    }
    for extension in (manual, price, impact, resume):
        for record in extension["attribute_additions"]:
            retained = expected[record["entity_key"]]
            retained["custom_attributes"] = sorted(
                retained["custom_attributes"] + record["custom_attributes"]
            )
    assert sorted(expected.values(), key=lambda item: item["entity_key"]) == contract["entities"]


def test_entity_attribute_contract_has_unique_entities_and_attributes() -> None:
    contract = build_entity_attribute_contract()
    assert contract["entity_count"] == 20
    entity_ids = [item["default_entity_id"] for item in contract["entities"]]
    assert len(entity_ids) == len(set(entity_ids))
    for item in contract["entities"]:
        attributes = item["custom_attributes"]
        assert attributes
        assert attributes == sorted(set(attributes))


def test_attribute_generator_cannot_overwrite_the_frozen_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Printing the merged contract must never replace the historical baseline."""
    before = BASELINE_PATH.read_text(encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["entity_attribute_contract", "--write"])
    with pytest.raises(SystemExit, match="baseline is frozen"):
        entity_attribute_contract.main()
    assert BASELINE_PATH.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("key", ["grid_power", "fleet_summary", "status", "ev_usable_capacity"])
def test_attribute_compatibility_rejects_unreviewed_baseline_or_extension_changes(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    """Compatibility checks protect both the retained baseline and additions."""
    contract = build_entity_attribute_contract()
    record = next(item for item in contract["entities"] if item["entity_key"] == key)
    record["custom_attributes"].append("unreviewed_attribute")
    monkeypatch.setattr(
        entity_attribute_contract, "build_entity_attribute_contract", lambda: contract
    )
    with pytest.raises(ValueError, match="custom public attributes changed"):
        validate_against_release_baseline()


@pytest.mark.parametrize("conflict", ["existing_key", "duplicate_key", "entity", "identity"])
def test_manual_attribute_additions_cannot_replace_reviewed_contracts(
    monkeypatch, tmp_path, conflict: str,
) -> None:
    extension = json.loads(MANUAL_ADDITIONS_PATH.read_text(encoding="utf-8"))
    record = extension["attribute_additions"][0]
    if conflict == "existing_key":
        record["custom_attributes"].append("summary_schema_version")
    elif conflict == "duplicate_key":
        record["custom_attributes"].append(record["custom_attributes"][0])
    elif conflict == "entity":
        record["entity_key"] = "unreviewed_entity"
    else:
        record["default_entity_id"] = "sensor.unreviewed_identity"
    path = tmp_path / "manual-attributes.json"
    path.write_text(json.dumps(extension), encoding="utf-8")
    monkeypatch.setattr(entity_attribute_contract, "MANUAL_ADDITIONS_PATH", path)
    with pytest.raises(ValueError, match="attribute additions"):
        validate_against_release_baseline()
