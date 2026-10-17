"""Compatibility tests for retained Home Assistant storage."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from scripts import persistence_contract
from scripts.persistence_contract import (
    BASELINE_PATH,
    MAINTENANCE_ADDITIONS_PATH,
    build_persistence_contract,
    validate_against_release_baseline,
)


def test_persistence_contract_matches_reviewed_release_baseline() -> None:
    validate_against_release_baseline()


def test_baseline_and_extension_stores_remain_private_and_version_one() -> None:
    contract = build_persistence_contract()
    stores = contract["stores"]
    assert contract["store_count"] == 17
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert baseline["store_count"] == 13
    assert all(record in stores for record in baseline["stores"])
    assert all(store["private"] is True for store in stores)
    assert all(store["version"] == 1 for store in stores)


@pytest.mark.parametrize(
    "source", ["active.py", "manual_inverter.py", "trip_charge.py", "maintenance.py"]
)
def test_reviewed_addition_does_not_allow_storage_drift(monkeypatch, source) -> None:
    current = deepcopy(build_persistence_contract())
    changed = next(item for item in current["stores"] if item["source"].endswith(source))
    changed["version"] = 2
    monkeypatch.setattr(persistence_contract, "build_persistence_contract", lambda: current)
    with pytest.raises(ValueError, match="changed beyond"):
        validate_against_release_baseline()


def test_maintenance_is_a_separate_private_host_wide_storage_extension() -> None:
    extension = json.loads(MAINTENANCE_ADDITIONS_PATH.read_text(encoding="utf-8"))
    assert extension == {
        "schema_version": 1,
        "extension": "maintenance_v1",
        "store_count": 1,
        "stores": [{
            "source": "custom_components/home_energy_orchestrator/maintenance.py",
            "attribute": "self._store",
            "version": 1,
            "storage_key_expression": "'home_energy_orchestrator.maintenance'",
            "private": True,
        }],
    }
    assert extension["stores"][0] in build_persistence_contract()["stores"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("private", False),
        ("storage_key_expression", "'home_energy_orchestrator.some_other_state'"),
        ("attribute", "self._different_store"),
    ],
)
def test_maintenance_addition_cannot_weaken_existing_storage_obligations(monkeypatch, field, value):
    contract = deepcopy(build_persistence_contract())
    record = next(item for item in contract["stores"] if item["source"].endswith("maintenance.py"))
    record[field] = value
    monkeypatch.setattr(persistence_contract, "build_persistence_contract", lambda: contract)
    with pytest.raises(ValueError, match="changed beyond"):
        validate_against_release_baseline()


def test_persistence_generator_cannot_overwrite_frozen_baseline(monkeypatch, capsys):
    before = BASELINE_PATH.read_bytes()
    monkeypatch.setattr("sys.argv", ["persistence_contract", "--write"])
    with pytest.raises(SystemExit) as error:
        persistence_contract.main()
    assert error.value.code == 2
    assert "baseline is frozen" in capsys.readouterr().err
    assert BASELINE_PATH.read_bytes() == before
