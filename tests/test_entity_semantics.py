"""Validation tests for the incremental entity semantic worksheet."""

from __future__ import annotations

import json

import pytest

from scripts import entity_semantics
from scripts.entity_contract import build_entity_contract
from scripts.entity_semantics import (
    MANUAL_EXTENSIONS_PATH,
    SEMANTICS_PATH,
    entities_awaiting_review,
    load_semantic_contract,
    validate_semantic_contract,
)


def test_reviewed_entity_semantics_are_complete_and_current() -> None:
    contract = load_semantic_contract()
    validate_semantic_contract(contract)
    expected_count = build_entity_contract()["entity_count"]
    assert expected_count == 117
    assert contract["reviewed_entity_count"] == expected_count
    assert contract["total_entity_count"] == expected_count
    assert entities_awaiting_review(contract) == []


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
    assert len(proposed) == 9
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
