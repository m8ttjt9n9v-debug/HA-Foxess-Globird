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
    assert contract["raw_accesses_by_layer"]["boundary"] > 0
    assert contract["raw_accesses_by_layer"].get("runtime", 0) == 0
    assert contract["accesses_by_kind"]["managed_mutation"] > 0
    assert {
        item["key"] for item in contract["accesses"] if item["key"] is not None
    } <= declared


def test_dynamic_config_access_is_confined_to_mutation_boundaries() -> None:
    """Variable-key access must remain at the reviewed mutation boundary."""
    contract = build_config_usage_contract()
    dynamic = [item for item in contract["accesses"] if item["key"] is None]
    dynamic_runtime = [
        item
        for item in dynamic
        if item["layer"] == "runtime" and item["key"] is None
    ]
    assert contract["dynamic_access_count"] == len(dynamic)
    assert dynamic_runtime == []
    assert len(dynamic) == 2
    assert {item["kind"] for item in dynamic} == {"mutation_boundary"}
    assert {item["layer"] for item in dynamic} == {"boundary"}
    assert {item["receiver"] for item in dynamic} == {"self.config"}


def test_runtime_config_writes_use_the_coordinator_boundary() -> None:
    """Constant-key runtime mutations must not bypass typed-config preparation."""
    runtime = [
        item
        for item in build_config_usage_contract()["accesses"]
        if item["layer"] == "runtime"
    ]
    raw_writes = [
        item
        for item in runtime
        if item["kind"] == "raw_mapping"
        and item["access"] in {"pop", "subscript_store"}
    ]
    assert raw_writes == []
    boundary_writes = [
        item
        for item in build_config_usage_contract()["accesses"]
        if item["kind"] == "mutation_boundary"
    ]
    assert len(boundary_writes) == 2
    assert {item["layer"] for item in boundary_writes} == {"boundary"}
    assert {
        (item["scope"], item["receiver"]) for item in boundary_writes
    } == {("EnergyCoordinator.update_config_value", "self.config")}
    mutations = [item for item in runtime if item["kind"] == "managed_mutation"]
    assert len(mutations) == 11
    assert {item["access"] for item in mutations} <= {
        "update_config_value",
        "update_persisted_config_value",
    }
