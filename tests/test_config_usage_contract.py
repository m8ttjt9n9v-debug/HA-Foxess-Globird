"""Persisted-configuration usage contract tests."""

from __future__ import annotations

import json

from scripts.config_contract import build_config_contract
from scripts.config_usage_contract import (
    BASELINE_PATH,
    build_config_usage_contract,
    rendered_contract,
)


def test_config_usage_matches_reviewed_baseline() -> None:
    """Direct raw mapping access must change only through explicit review."""
    assert json.loads(BASELINE_PATH.read_text(encoding="utf-8")) == (
        build_config_usage_contract()
    )
    assert BASELINE_PATH.read_text(encoding="utf-8") == rendered_contract()


def test_config_usage_only_references_declared_keys() -> None:
    """Every accessed serialized key must remain in the public vocabulary."""
    contract = build_config_usage_contract()
    declared = set(build_config_contract()["declared_config_keys"])
    assert contract["access_count"] > 0
    assert contract["accesses_by_layer"]["runtime"] > 0
    assert {item["key"] for item in contract["accesses"]} <= declared
