"""Compatibility tests for retained Home Assistant storage."""

from __future__ import annotations

from scripts.persistence_contract import (
    BASELINE_PATH,
    build_persistence_contract,
    rendered_contract,
)


def test_persistence_contract_matches_reviewed_release_baseline() -> None:
    assert BASELINE_PATH.read_text(encoding="utf-8") == rendered_contract()


def test_all_thirteen_stores_remain_private_and_version_one() -> None:
    contract = build_persistence_contract()
    stores = contract["stores"]
    assert contract["store_count"] == 13
    assert all(store["private"] is True for store in stores)
    assert all(store["version"] == 1 for store in stores)
