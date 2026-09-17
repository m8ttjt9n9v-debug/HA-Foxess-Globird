"""Compatibility tests for the public Home Assistant entity surface."""

from __future__ import annotations

import json

from scripts.entity_contract import BASELINE_PATH, build_entity_contract, rendered_contract


def test_entity_contract_matches_reviewed_release_baseline() -> None:
    """Public entity identity changes require an explicit baseline review."""
    assert json.loads(BASELINE_PATH.read_text(encoding="utf-8")) == build_entity_contract()
    assert BASELINE_PATH.read_text(encoding="utf-8") == rendered_contract()


def test_entity_contract_contains_one_hundred_and_seven_unique_entities() -> None:
    contract = build_entity_contract()
    assert contract["entity_count"] == 107
    unique_ids = [item["unique_id_template"] for item in contract["entities"]]
    entity_ids = [item["default_entity_id"] for item in contract["entities"]]
    assert len(unique_ids) == len(set(unique_ids))
    assert len(entity_ids) == len(set(entity_ids))
