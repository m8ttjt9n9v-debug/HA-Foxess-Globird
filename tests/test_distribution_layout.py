"""Repository-layout checks for the HACS integration distribution."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = REPOSITORY_ROOT / "custom_components"
COMPONENT = COMPONENT_ROOT / "home_energy_orchestrator"


def test_hacs_integration_layout_is_stable() -> None:
    """Keep the local requirements that HACS validates from regressing."""

    component_directories = sorted(
        path.name
        for path in COMPONENT_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    )

    assert component_directories == ["home_energy_orchestrator"]
    assert (COMPONENT / "brand" / "icon.png").is_file()
    assert not (COMPONENT / "strings.json").exists()
    assert (COMPONENT / "translations" / "en.json").is_file()


def test_hacs_metadata_matches_the_integration_manifest() -> None:
    """Ensure the distribution metadata names the integration it packages."""

    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    hacs = json.loads((REPOSITORY_ROOT / "hacs.json").read_text(encoding="utf-8"))

    assert {
        "domain",
        "name",
        "version",
        "documentation",
        "issue_tracker",
        "codeowners",
    } <= manifest.keys()
    assert manifest["domain"] == "home_energy_orchestrator"
    assert manifest["codeowners"] == ["@m8ttjt9n9v-debug"]
    assert manifest["documentation"] == "https://github.com/m8ttjt9n9v-debug/HA-Foxess-Globird"
    assert (
        manifest["issue_tracker"] == "https://github.com/m8ttjt9n9v-debug/HA-Foxess-Globird/issues"
    )
    assert hacs["name"] == manifest["name"]
    assert hacs["country"] == "AU"
    assert hacs["homeassistant"] == "2026.8.3"


def test_example_dashboard_uses_the_integration_entity_ids() -> None:
    """Keep the shipped dashboard aligned with generated entity IDs."""
    dashboard = yaml.safe_load(
        (REPOSITORY_ROOT / "examples" / "dashboard.yaml").read_text(encoding="utf-8")
    )
    entity_ids = []
    for view in dashboard["views"]:
        for section in view.get("sections", []):
            for card in section.get("cards", []):
                for item in card.get("entities", []):
                    entity_ids.append(item if isinstance(item, str) else item["entity"])
                if "entity" in card:
                    entity_ids.append(card["entity"])
                for item in card.get("entities", []):
                    if isinstance(item, dict) and "entity" in item:
                        entity_ids.append(item["entity"])
    assert {
        "sensor.home_energy_status",
        "sensor.home_energy_battery_soc",
        "sensor.home_energy_solar_power",
        "sensor.home_energy_house_load",
        "sensor.home_energy_grid_import",
        "sensor.home_energy_grid_export",
            "sensor.home_energy_zerohero_import_window",
            "sensor.home_energy_ev_max_power",
    } <= set(entity_ids)
