"""Contract checks for the portable example dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from scripts.entity_attribute_contract import (
    BASELINE_PATH as ATTRIBUTE_CONTRACT_PATH,
)
from scripts.entity_contract import BASELINE_PATH as ENTITY_CONTRACT_PATH

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "examples" / "dashboard.yaml"


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _walk(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _load_dashboard() -> dict[str, Any]:
    loaded = yaml.load(  # noqa: S506 - SafeLoader subclass is intentional.
        DASHBOARD_PATH.read_text(encoding="utf-8"),
        Loader=_UniqueKeyLoader,
    )
    assert isinstance(loaded, dict)
    return loaded


def test_dashboard_yaml_has_no_duplicate_mapping_keys() -> None:
    """Strict loading prevents silent card-field replacement."""
    _load_dashboard()


def test_dashboard_references_only_contracted_heo_entities() -> None:
    """Every portable HEO entity reference must exist in the public contract."""
    dashboard = _load_dashboard()
    contract = json.loads(ENTITY_CONTRACT_PATH.read_text(encoding="utf-8"))
    contracted = {item["default_entity_id"] for item in contract["entities"]}
    referenced: set[str] = set()
    for item in _walk(dashboard):
        if not isinstance(item, dict):
            continue
        entity = item.get("entity")
        if isinstance(entity, str) and ".home_energy_" in entity:
            referenced.add(entity)
        entity_id = item.get("entity_id")
        values = entity_id if isinstance(entity_id, list) else [entity_id]
        referenced.update(
            value
            for value in values
            if isinstance(value, str) and ".home_energy_" in value
        )

    assert referenced
    assert referenced <= contracted


def test_dashboard_attribute_cards_use_contracted_custom_attributes() -> None:
    """Attribute cards must not depend on undocumented HEO attributes."""
    dashboard = _load_dashboard()
    contract = json.loads(ATTRIBUTE_CONTRACT_PATH.read_text(encoding="utf-8"))
    attributes_by_entity = {
        item["default_entity_id"]: set(item["custom_attributes"])
        for item in contract["entities"]
    }
    references = {
        (item["entity"], item["attribute"])
        for item in _walk(dashboard)
        if isinstance(item, dict)
        and item.get("type") == "attribute"
        and isinstance(item.get("entity"), str)
        and ".home_energy_" in item["entity"]
        and isinstance(item.get("attribute"), str)
    }

    assert references
    assert not {
        (entity_id, attribute)
        for entity_id, attribute in references
        if attribute not in attributes_by_entity.get(entity_id, set())
    }
