"""Compatibility tests for the configuration wizard field surface."""

from __future__ import annotations

import json

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from scripts.config_field_contract import (
    BASELINE_PATH,
    TRANSLATION_PATH,
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
    assert contract["field_count"] == 134
    assert actual == expected
    assert len(actual) == len(set(actual))
    assert all(item["setup_label"] for item in contract["fields"])
    assert all(item["reconfigure_label"] for item in contract["fields"])
    assert all(
        item["setup_label"] == item["reconfigure_label"]
        for item in contract["fields"]
    )


def test_multiphase_grid_setup_explains_upstream_foxess_modbus_entities() -> None:
    translations = json.loads(
        TRANSLATION_PATH.read_text(encoding="utf-8")
    )["config"]["step"]
    for step in ("grid", "reconfigure_grid"):
        description = translations[step]["description"]
        assert "Grid Voltage R, S and T" in description
        assert "Grid CT R/S/T" in description
        assert "EPS Current R/S/T" in description
