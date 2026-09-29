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
        assert "choose one method" in description
        assert "required for multiphase" not in translations[step]["data"][
            "site_grid_current_entity"
        ]
        sections = translations[step]["sections"]
        assert tuple(sections) == ("phase_r", "phase_s", "phase_t")
        for phase in "rst":
            assert sections[f"phase_{phase}"]["name"] == f"PHASE {phase.upper()}"
            assert tuple(sections[f"phase_{phase}"]["data"]) == (
                f"site_grid_phase_{phase}_power_entity",
                f"site_grid_phase_{phase}_voltage_entity",
            )


def test_ev_policy_screen_explains_each_field_and_groups_outside_safeguards() -> None:
    translations = json.loads(
        TRANSLATION_PATH.read_text(encoding="utf-8")
    )["config"]["step"]
    keys = ConfigFlow._PAGE_FIELDS["ev_policies"]
    assert keys.index("ev_pre_free_backfill_enabled") < keys.index(
        "ev_daily_backfill_energy_kwh"
    )
    assert keys.index("ev_outside_inverter_percent") + 1 == keys.index(
        "ev_outside_battery_reserve_percent"
    )
    assert keys.index("ev_outside_battery_reserve_percent") + 1 == keys.index(
        "ev_protected_baseline_a"
    )
    for step in ("ev_policies", "reconfigure_ev_policies"):
        screen = translations[step]
        assert set(screen["data_description"]) == set(keys)
        assert all(screen["data_description"][key].strip() for key in keys)
        assert "90%" in screen["data_description"]["ev_free_window_charge_limit_percent"]
        assert "keep-alive" in screen["data_description"]["ev_outside_battery_reserve_percent"]
    assert translations["ev_policies"]["data"] == translations[
        "reconfigure_ev_policies"
    ]["data"]
    assert translations["ev_policies"]["data_description"] == translations[
        "reconfigure_ev_policies"
    ]["data_description"]
