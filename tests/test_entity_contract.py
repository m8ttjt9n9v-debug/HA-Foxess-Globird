"""Compatibility tests for the public Home Assistant entity surface."""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from custom_components.home_energy_orchestrator import (
    binary_sensor,
    button,
    number,
    select,
    switch,
)
from custom_components.home_energy_orchestrator.entity_catalogue import ENTITY_SPECS
from scripts.entity_contract import BASELINE_PATH, build_entity_contract, rendered_contract

ROOT = Path(__file__).resolve().parents[1]


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


def test_entity_catalogue_is_complete_and_unique() -> None:
    """Every frozen public identity has exactly one catalogue spec."""
    contract = build_entity_contract()
    contracted = {
        (item["platform"], item["key"])
        for item in contract["entities"]
    }
    catalogued = {
        (spec.platform, spec.description.key)
        for spec in ENTITY_SPECS
    }

    assert len(ENTITY_SPECS) == 107
    assert len(catalogued) == len(ENTITY_SPECS)
    assert catalogued == contracted
    assert all(spec.value_projection for spec in ENTITY_SPECS)
    assert {
        spec.availability for spec in ENTITY_SPECS
    } == {"coordinator", "coordinator_and_projection"}
    assert not any(spec.deprecated for spec in ENTITY_SPECS)


def test_sensor_specs_match_native_value_projection_keys() -> None:
    """Sensor projection metadata must match the actual presentation mapping."""
    tree = ast.parse(
        (ROOT / "custom_components/home_energy_orchestrator/sensor.py").read_text(
            encoding="utf-8"
        )
    )
    projection: ast.Dict | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "EnergySensor":
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Assign):
                continue
            if any(
                isinstance(target, ast.Name) and target.id == "values"
                for target in child.targets
            ):
                assert isinstance(child.value, ast.Dict)
                projection = child.value
                break
    assert projection is not None
    projected_keys = {
        ast.literal_eval(key)
        for key in projection.keys
        if key is not None
    }
    catalogued_keys = {
        spec.description.key for spec in ENTITY_SPECS if spec.platform == "sensor"
    }

    assert projected_keys == catalogued_keys


def test_non_sensor_projection_owners_exist() -> None:
    """Non-sensor projection metadata must name a real implementation member."""
    classes = {
        name: value
        for module in (binary_sensor, button, number, select, switch)
        for name, value in vars(module).items()
        if inspect.isclass(value)
    }
    for spec in ENTITY_SPECS:
        if spec.platform == "sensor":
            continue
        class_name, member = spec.value_projection.split(".", 1)
        assert class_name in classes
        assert hasattr(classes[class_name], member)
