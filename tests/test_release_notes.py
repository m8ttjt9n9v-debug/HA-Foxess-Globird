"""Tests for the release-note extraction used by the publishing workflow."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from packaging.version import Version

from scripts.release_notes import CHANGELOG_PATH, release_text


def test_release_text_uses_only_the_matching_changelog_section() -> None:
    changelog = """# Changelog

## 1.2.3 — Useful change

- Explain the change.

## 1.2.2 — Earlier change

- Do not include this.
"""

    assert release_text("v1.2.3", changelog) == (
        "v1.2.3 — Useful change",
        "## Useful change\n\n- Explain the change.\n",
    )


def test_release_text_requires_matching_nonempty_section() -> None:
    with pytest.raises(ValueError, match="no section"):
        release_text("v1.2.3", "# Changelog\n")

    with pytest.raises(ValueError, match="no release notes"):
        release_text("v1.2.3", "## 1.2.3 — Empty\n\n## 1.2.2 — Earlier\n")


def test_published_rc7_has_descriptive_release_metadata() -> None:
    """The historical release repaired by the workflow must remain described."""
    title, notes = release_text("v0.12.29rc7", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.29rc7 — EV control hardening and conformance supervision"
    assert "conformance supervisor" in notes


def test_rc18_has_complete_descriptive_notes_and_candidate_flag() -> None:
    title, notes = release_text("v0.12.29rc18", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.29rc18 — Protected price export and trip helpers"
    assert "DispatchIS" in notes and "trip-charge" in notes
    assert "HACS does not" in notes and "No price-triggered buying" in notes
    assert Version("0.12.29rc18").is_prerelease
    assert not Version("0.12.28").is_prerelease
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "Version(os.environ" in workflow and ".is_prerelease" in workflow
    assert workflow.count('--prerelease="$release_prerelease"') == 2


def test_stable_01229_promotes_frozen_runtime_with_complete_notes() -> None:
    title, notes = release_text("v0.12.29", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.29 — Protected export, Fleet controls and trip helpers"
    assert "functionality-frozen rc18 runtime" in notes
    assert "release metadata only" in notes
    assert "DispatchIS" in notes and "Fleet" in notes and "trip-charge" in notes
    assert "HACS does not" in notes and "No automatic price-triggered buying" in notes
    assert "Live high-price export was not forced" in notes
    assert not Version("0.12.29").is_prerelease


def test_01230_handoff_patch_has_matching_descriptive_stable_metadata() -> None:
    title, notes = release_text("v0.12.30", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.30 — Ready-by and pre-free EV handoff"
    assert "additional earlier charging opportunity" in notes
    assert "current" in notes and "protected" in notes
    assert "Conservative timing is unchanged" in notes
    assert "no automatic price-triggered buying" in notes
    assert not Version("0.12.30").is_prerelease
    manifest = json.loads(
        Path("custom_components/home_energy_orchestrator/manifest.json").read_text()
    )
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    assert manifest["version"] == project["version"]
    current_title, _ = release_text(
        "v" + manifest["version"], CHANGELOG_PATH.read_text(encoding="utf-8")
    )
    assert current_title.startswith("v" + manifest["version"] + " — ")
