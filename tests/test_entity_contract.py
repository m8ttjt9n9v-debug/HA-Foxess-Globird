"""Compatibility tests for the public Home Assistant entity surface."""

from __future__ import annotations

import json

from custom_components.home_energy_orchestrator.entity_catalogue import ENTITY_SPECS
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


def test_non_sensor_catalogue_is_complete_and_unique() -> None:
    """Every frozen non-sensor identity has exactly one catalogue spec."""
    contract = build_entity_contract()
    contracted = {
        (item["platform"], item["key"])
        for item in contract["entities"]
        if item["platform"] != "sensor"
    }
    catalogued = {
        (spec.platform, spec.description.key)
        for spec in ENTITY_SPECS
    }

    assert len(ENTITY_SPECS) == 15
    assert len(catalogued) == len(ENTITY_SPECS)
    assert catalogued == contracted
