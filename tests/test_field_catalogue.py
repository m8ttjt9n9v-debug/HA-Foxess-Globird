"""Immutable configuration FieldSpec catalogue tests."""

from __future__ import annotations

import json

from custom_components.home_energy_orchestrator.field_catalogue import (
    CATALOGUE_BASELINE,
    FIELD_KEYS_BY_PAGE,
    FIELD_SPECS,
    FIELD_SPECS_BY_KEY,
)
from scripts.config_field_contract import build_config_field_contract
from scripts.field_catalogue import CATALOGUE_PATH, rendered_catalogue


def test_generated_field_catalogue_is_current() -> None:
    assert CATALOGUE_PATH.read_text(encoding="utf-8") == rendered_catalogue()


def test_field_catalogue_exactly_covers_the_frozen_ui_contract() -> None:
    contract = build_config_field_contract()
    fields = contract["fields"]
    assert CATALOGUE_BASELINE == contract["release_baseline"]
    assert len(FIELD_SPECS) == contract["field_count"] == 125
    assert tuple(spec.key for spec in FIELD_SPECS) == tuple(
        field["key"] for field in fields
    )
    assert len(FIELD_SPECS_BY_KEY) == len(FIELD_SPECS)
    expected_pages: dict[str, list[str]] = {}
    for spec, field in zip(FIELD_SPECS, fields, strict=True):
        expected_pages.setdefault(field["page"], []).append(field["key"])
        assert spec.page == field["page"]
        assert spec.order == field["order"]
        assert spec.required is field["required"]
        assert spec.has_default is field["has_default"]
        assert spec.default == field["default"]
        assert spec.selector_kind == field["input_kind"]
        assert (
            None
            if spec.selector_config_json is None
            else json.loads(spec.selector_config_json)
        ) == field["input_config"]
        assert spec.translation_key == spec.key
    assert dict(FIELD_KEYS_BY_PAGE) == {
        page: tuple(keys) for page, keys in expected_pages.items()
    }


def test_field_catalogue_capability_and_redaction_rules_are_complete() -> None:
    for spec in FIELD_SPECS:
        expected_applicability = (
            "solar"
            if spec.page == "solar"
            else "ev"
            if spec.page in {"car", "charger", "ev_policies", "recovery"}
            else "always"
        )
        assert spec.applicability == expected_applicability
        expected_redaction = (
            "redact"
            if spec.key == "name"
            else "omit"
            if spec.selector_kind == "entity"
            else "retain"
        )
        assert spec.redaction == expected_redaction
