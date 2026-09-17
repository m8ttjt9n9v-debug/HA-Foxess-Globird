"""Compatibility tests for the persisted configuration surface."""

from __future__ import annotations

from scripts.config_contract import BASELINE_PATH, build_config_contract, rendered_contract


def test_config_contract_matches_reviewed_release_baseline() -> None:
    assert BASELINE_PATH.read_text(encoding="utf-8") == rendered_contract()


def test_config_pages_have_one_hundred_and_twenty_four_unique_fields() -> None:
    contract = build_config_contract()
    assert contract["config_entry_version"] == 6
    assert contract["page_field_count"] == 124
    assert contract["unique_page_field_count"] == 124
