"""Explicit additive selector amendments; frozen baseline files stay unchanged."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

AMENDMENT_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/maintainability/config-field-amendments-backfill-timing-v1.json"
)


def reviewed_field_amendments(fields: list[dict]) -> list[dict]:
    """Append only reviewed choices, preserving every other frozen field part."""
    amendment = json.loads(AMENDMENT_PATH.read_text(encoding="utf-8"))
    if amendment["schema_version"] != 1:
        raise ValueError("Unsupported selector amendment schema")
    result = deepcopy(fields)
    matches = [field for field in result if field["key"] == amendment["key"]]
    if len(matches) != 1:
        raise ValueError("Selector amendment must bind one existing field")
    field = matches[0]
    original = amendment["original_options"]
    added = amendment["append_options"]
    if (
        field["input_kind"] != "select"
        or field["input_config"]["options"] != original
        or not added or len(set(original + added)) != len(original + added)
    ):
        raise ValueError("Selector amendment cannot replace or duplicate existing choices")
    field["input_config"]["options"] = original + added
    return result
