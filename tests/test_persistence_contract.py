"""Compatibility tests for retained Home Assistant storage."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from scripts import persistence_contract
from scripts.persistence_contract import (
    BASELINE_PATH,
    build_persistence_contract,
    validate_against_release_baseline,
)


def test_persistence_contract_matches_reviewed_release_baseline() -> None:
    validate_against_release_baseline()


def test_baseline_and_extension_stores_remain_private_and_version_one() -> None:
    contract = build_persistence_contract()
    stores = contract["stores"]
    assert contract["store_count"] == 16
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert baseline["store_count"] == 13
    assert all(record in stores for record in baseline["stores"])
    assert all(store["private"] is True for store in stores)
    assert all(store["version"] == 1 for store in stores)


@pytest.mark.parametrize(
    "source", ["active.py", "manual_inverter.py", "trip_charge.py"]
)
def test_reviewed_addition_does_not_allow_storage_drift(monkeypatch, source) -> None:
    current = deepcopy(build_persistence_contract())
    changed = next(item for item in current["stores"] if item["source"].endswith(source))
    changed["version"] = 2
    monkeypatch.setattr(persistence_contract, "build_persistence_contract", lambda: current)
    with pytest.raises(ValueError, match="changed beyond"):
        validate_against_release_baseline()
