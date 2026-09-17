"""Compatibility tests for custom public Home Assistant attributes."""

from __future__ import annotations

import json

from scripts.entity_attribute_contract import (
    BASELINE_PATH,
    build_entity_attribute_contract,
    rendered_contract,
)


def test_entity_attribute_contract_matches_reviewed_release_baseline() -> None:
    """Custom attribute changes require an explicit compatibility review."""
    assert json.loads(BASELINE_PATH.read_text(encoding="utf-8")) == (
        build_entity_attribute_contract()
    )
    assert BASELINE_PATH.read_text(encoding="utf-8") == rendered_contract()


def test_entity_attribute_contract_has_unique_entities_and_attributes() -> None:
    contract = build_entity_attribute_contract()
    assert contract["entity_count"] == 16
    entity_ids = [item["default_entity_id"] for item in contract["entities"]]
    assert len(entity_ids) == len(set(entity_ids))
    for item in contract["entities"]:
        attributes = item["custom_attributes"]
        assert attributes
        assert attributes == sorted(set(attributes))
