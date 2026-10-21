"""Validation tests for the incremental entity semantic worksheet."""

from __future__ import annotations

import json

import pytest

from scripts import entity_semantics
from scripts.entity_contract import build_entity_contract
from scripts.entity_semantics import (
    EV_CAPACITY_EXTENSIONS_PATH,
    EV_FEEDBACK_EXTENSIONS_PATH,
    MANUAL_EXTENSIONS_PATH,
    SEMANTICS_PATH,
    SOLAR_SOAK_EXTENSIONS_PATH,
    entities_awaiting_review,
    load_semantic_contract,
    validate_semantic_contract,
)


def test_reviewed_entity_semantics_are_complete_and_current() -> None:
    contract = load_semantic_contract()
    validate_semantic_contract(contract)
    expected_count = build_entity_contract()["entity_count"]
    assert expected_count == 129
    assert contract["reviewed_entity_count"] == expected_count
    assert contract["total_entity_count"] == expected_count
    assert entities_awaiting_review(contract) == []


def test_solar_soak_semantics_add_only_three_shared_configuration_controls():
    addition = json.loads(SOLAR_SOAK_EXTENSIONS_PATH.read_text(encoding="utf-8"))
    assert addition["entity_count"] == 3
    assert addition["attribute_profiles"] == {}
    records = {item["key"]: item for item in addition["entities"]}
    assert set(records) == {
        "ev_solar_soak_battery_soc",
        "ev_solar_soak_average_minutes",
        "ev_solar_soak_adjustment_minutes",
    }
    assert all(item["role"] == "configuration" for item in records.values())
    assert all("EvSolarSoakNumber.native_value" in item["producer"] for item in records.values())
    assert all("telemetry is unavailable" in item["availability"] for item in records.values())
    assert "100% disables this extra buffer" in records["ev_solar_soak_battery_soc"]["definition"]
    assert "1 through 30" in records["ev_solar_soak_average_minutes"]["unit_and_sign"]
    assert "do not wait" in records["ev_solar_soak_adjustment_minutes"]["definition"]


def test_ev_feedback_semantics_are_additive_and_identify_the_same_capture() -> None:
    extension = json.loads(EV_FEEDBACK_EXTENSIONS_PATH.read_text(encoding="utf-8"))
    assert extension["entities"] == []
    assert extension["attribute_profiles"] == {}
    additions = extension["attribute_profile_additions"]
    assert set(additions) == {"ev_control_diagnostics_v1"}
    assert set(additions["ev_control_diagnostics_v1"]) == {"observed_soc_percent"}
    description = additions["ev_control_diagnostics_v1"]["observed_soc_percent"]
    assert "same synchronous feedback capture" in description
    assert "Missing field" in description and "present null" in description


def test_manual_semantics_add_only_reviewed_keys_to_existing_profiles() -> None:
    baseline = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
    manual = json.loads(MANUAL_EXTENSIONS_PATH.read_text(encoding="utf-8"))
    contract = load_semantic_contract()
    assert manual["entities"] == []
    assert manual["attribute_profiles"] == {}
    assert set(manual["attribute_profile_additions"]) == {
        "fleet_summary_v1", "orchestrator_status_v1",
    }
    for name, additions in manual["attribute_profile_additions"].items():
        assert len(additions) == 5
        assert not baseline["attribute_profiles"][name]["attributes"].keys() & additions.keys()
        assert contract["attribute_profiles"][name]["attributes"].items() >= {
            **baseline["attribute_profiles"][name]["attributes"], **additions,
        }.items()


@pytest.mark.parametrize("conflict", ["existing_key", "unknown_profile"])
def test_manual_semantics_cannot_replace_existing_attribute_definitions(
    monkeypatch, tmp_path, conflict: str,
) -> None:
    manual = json.loads(MANUAL_EXTENSIONS_PATH.read_text(encoding="utf-8"))
    if conflict == "existing_key":
        manual["attribute_profile_additions"]["fleet_summary_v1"]["battery_soc"] = "Changed"
    else:
        manual["attribute_profile_additions"]["unreviewed_profile"] = {"changed": "Changed"}
    path = tmp_path / "manual-semantics.json"
    path.write_text(json.dumps(manual), encoding="utf-8")
    monkeypatch.setattr(entity_semantics, "MANUAL_EXTENSIONS_PATH", path)
    with pytest.raises(ValueError, match="semantic additions"):
        load_semantic_contract()


def test_semantic_decisions_record_the_owner_approved_relabels() -> None:
    contract = load_semantic_contract()
    proposed = {
        item["key"]: item["proposed_display_name"]
        for item in contract["entities"]
        if item["decision"] == "relabel"
    }
    assert len(proposed) == 10
    assert len(proposed.values()) == len(set(proposed.values()))
    approved = {
        item["key"]
        for item in contract["entities"]
        if item["review_status"] == "owner_approved"
    }
    assert approved == set(proposed)
    assert all(
        item["review_status"] == "engineering_draft"
        for item in contract["entities"]
        if item["key"] not in approved
    )


def test_capacity_semantic_revision_preserves_frozen_baseline_and_other_records():
    baseline_text = SEMANTICS_PATH.read_text(encoding="utf-8")
    baseline = json.loads(baseline_text)
    current = {item["key"]: item for item in load_semantic_contract()["entities"]}
    for record in baseline["entities"]:
        if record["key"] != "ev_usable_capacity":
            assert current[record["key"]] == record
    capacity = current["ev_usable_capacity"]
    assert capacity["attribute_profile"] == "ev_capacity_v1"
    assert capacity["proposed_display_name"] == "EV Planning Capacity"
    assert capacity["review_status"] == "owner_approved"
    assert SEMANTICS_PATH.read_text(encoding="utf-8") == baseline_text


@pytest.mark.parametrize("conflict", ["identity", "predecessor", "field", "count", "duplicate"])
def test_capacity_semantic_revision_cannot_replace_unreviewed_records(
    monkeypatch, tmp_path, conflict
):
    extension = json.loads(EV_CAPACITY_EXTENSIONS_PATH.read_text(encoding="utf-8"))
    revision = extension["entity_revisions"][0]
    if conflict == "identity":
        revision["key"] = "status"
    elif conflict == "predecessor":
        revision["previous_definition"] = "Unreviewed predecessor"
    elif conflict == "field":
        revision["fields"]["default_entity_id"] = "sensor.unreviewed"
    elif conflict == "count":
        extension["entity_revision_count"] = 2
    else:
        extension["entity_revisions"].append(revision.copy())
        extension["entity_revision_count"] = 2
    path = tmp_path / "capacity-semantics.json"
    path.write_text(json.dumps(extension), encoding="utf-8")
    monkeypatch.setattr(entity_semantics, "EV_CAPACITY_EXTENSIONS_PATH", path)
    with pytest.raises(ValueError, match="semantic revision"):
        load_semantic_contract()
