"""Validation tests for the incremental entity semantic worksheet."""

from __future__ import annotations

from scripts.entity_semantics import (
    entities_awaiting_review,
    load_semantic_contract,
    validate_semantic_contract,
)


def test_reviewed_entity_semantics_are_complete_and_current() -> None:
    contract = load_semantic_contract()
    validate_semantic_contract(contract)
    assert contract["reviewed_entity_count"] == 107
    assert contract["total_entity_count"] == 107
    assert entities_awaiting_review(contract) == []


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
