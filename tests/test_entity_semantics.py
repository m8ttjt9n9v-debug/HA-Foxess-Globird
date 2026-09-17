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
    assert contract["reviewed_entity_count"] == 71
    assert contract["total_entity_count"] == 107
    assert len(entities_awaiting_review(contract)) == 36


def test_semantic_decisions_remain_draft_until_owner_review() -> None:
    contract = load_semantic_contract()
    assert {item["review_status"] for item in contract["entities"]} == {
        "engineering_draft"
    }
