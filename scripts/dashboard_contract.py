"""Strict parser and reference inventory for the portable dashboard."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = REPOSITORY_ROOT / "examples" / "dashboard.yaml"


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeyLoader,
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


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def walk(value: Any) -> Iterator[Any]:
    """Yield every nested dashboard value."""
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def load_dashboard() -> dict[str, Any]:
    """Strictly load the portable dashboard."""
    loaded = yaml.load(  # noqa: S506 - SafeLoader subclass is intentional.
        DASHBOARD_PATH.read_text(encoding="utf-8"),
        Loader=UniqueKeyLoader,
    )
    if not isinstance(loaded, dict):
        raise ValueError("portable dashboard must contain one mapping")
    return loaded


def entity_references(dashboard: dict[str, Any] | None = None) -> set[str]:
    """Return all portable HEO entity IDs referenced by cards or actions."""
    dashboard = load_dashboard() if dashboard is None else dashboard
    referenced: set[str] = set()
    for item in walk(dashboard):
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
    return referenced


def attribute_references(
    dashboard: dict[str, Any] | None = None,
) -> set[tuple[str, str]]:
    """Return HEO custom attributes referenced by dashboard attribute cards."""
    dashboard = load_dashboard() if dashboard is None else dashboard
    return {
        (item["entity"], item["attribute"])
        for item in walk(dashboard)
        if isinstance(item, dict)
        and item.get("type") == "attribute"
        and isinstance(item.get("entity"), str)
        and ".home_energy_" in item["entity"]
        and isinstance(item.get("attribute"), str)
    }
