"""Contract checks for the portable example dashboard."""

from __future__ import annotations

import json

from scripts.dashboard_contract import (
    attribute_references,
    entity_references,
    load_dashboard,
)
from scripts.entity_attribute_contract import (
    BASELINE_PATH as ATTRIBUTE_CONTRACT_PATH,
)
from scripts.entity_contract import BASELINE_PATH as ENTITY_CONTRACT_PATH


def test_dashboard_yaml_has_no_duplicate_mapping_keys() -> None:
    """Strict loading prevents silent card-field replacement."""
    load_dashboard()


def test_dashboard_references_only_contracted_heo_entities() -> None:
    """Every portable HEO entity reference must exist in the public contract."""
    contract = json.loads(ENTITY_CONTRACT_PATH.read_text(encoding="utf-8"))
    contracted = {item["default_entity_id"] for item in contract["entities"]}
    referenced = entity_references()

    assert referenced
    assert referenced <= contracted


def test_dashboard_attribute_cards_use_contracted_custom_attributes() -> None:
    """Attribute cards must not depend on undocumented HEO attributes."""
    contract = json.loads(ATTRIBUTE_CONTRACT_PATH.read_text(encoding="utf-8"))
    attributes_by_entity = {
        item["default_entity_id"]: set(item["custom_attributes"])
        for item in contract["entities"]
    }
    references = attribute_references()

    assert references
    assert not {
        (entity_id, attribute)
        for entity_id, attribute in references
        if attribute not in attributes_by_entity.get(entity_id, set())
    }
