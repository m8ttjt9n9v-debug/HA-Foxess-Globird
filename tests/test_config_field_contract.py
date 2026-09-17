"""Compatibility tests for the configuration wizard field surface."""

from __future__ import annotations

import json

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from scripts.config_field_contract import (
    BASELINE_PATH,
    build_config_field_contract,
    rendered_contract,
)


def test_config_field_contract_matches_reviewed_release_baseline() -> None:
    assert json.loads(BASELINE_PATH.read_text(encoding="utf-8")) == (
        build_config_field_contract()
    )
    assert BASELINE_PATH.read_text(encoding="utf-8") == rendered_contract()


def test_config_field_contract_covers_every_wizard_field_once() -> None:
    contract = build_config_field_contract()
    expected = [key for fields in ConfigFlow._PAGE_FIELDS.values() for key in fields]
    actual = [item["key"] for item in contract["fields"]]
    assert contract["field_count"] == 124
    assert actual == expected
    assert len(actual) == len(set(actual))
