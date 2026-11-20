"""Reviewed configuration amendments; frozen baseline files stay unchanged."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

AMENDMENT_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/maintainability/config-field-amendments-backfill-timing-v1.json"
)
RETIREMENT_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/maintainability/config-field-retirements-free-allowance-v1.json"
)


def reviewed_field_amendments(fields: list[dict]) -> list[dict]:
    """Apply exact reviewed selector, label and legacy-field retirements."""
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
    retired = json.loads(RETIREMENT_PATH.read_text(encoding="utf-8"))
    guard = next(field for field in result if field["key"] == "ev_allowance_guard_enabled")
    for label in ("setup_label", "reconfigure_label"):
        if guard[label] != retired["guard_label_before"]:
            raise ValueError("Allowance guard label differs from the reviewed original")
        guard[label] = retired["guard_label_after"]
    matches = [field for field in result if field["key"] == retired["key"]]
    if retired["schema_version"] != 1 or len(matches) != 1 or (
        matches[0]["page"] != retired["page"] or matches[0]["order"] != retired["order"]
        or retired["persisted_key_retained"] is not True
    ):
        raise ValueError("Retirement must bind exactly the reviewed legacy field")
    result.remove(matches[0])
    for field in result:
        if field["page"] == retired["page"] and field["order"] > retired["order"]:
            field["order"] -= 1
    return result
