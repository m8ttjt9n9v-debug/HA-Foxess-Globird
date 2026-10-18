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


def test_01244_describes_explicit_metadata_check_not_an_automatic_updater() -> None:
    title, notes = release_text("v0.12.44", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.44 — Check Fleet releases on demand"
    assert "Check releases" in notes and "metadata" in notes
    assert "30-second attempt cooldown" in notes
    assert "normal charging need not stop" in notes
    assert "Both hub and target" in notes and "Older nodes" in notes
    assert "does not replace live dashboards" in notes
    assert not Version("0.12.44").is_prerelease


def test_01239_has_stable_recovery_and_readonly_fleet_notes() -> None:
    title, notes = release_text("v0.12.39", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.39 — Export restart recovery and Fleet versions"
    assert "valid unfinished" in notes and "Feed-in First" in notes
    assert "Existing retry timing" in notes and "persistent payloads are unchanged" in notes
    assert "Installed HEO" in notes and "explicit import" in notes
    assert "No live site is updated or restarted" in notes
    assert "not part of this release" in notes
    assert not Version("0.12.39").is_prerelease


def test_01240_has_stable_guarded_maintenance_and_separate_activation_notes() -> None:
    title, notes = release_text("v0.12.40", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.40 — Safe per-site Fleet updates and restarts"
    assert "administrator-only per-site" in notes
    assert "No all-site deployment or startup replay" in notes
    assert "completed verified" in notes and "unchanged settings" in notes
    assert "Connected keepalive and pending sessions still block" in notes
    assert "freshness limit or charging policy is weakened" in notes
    assert "downloaded and running versions distinct" in notes
    assert "does not install, configure or activate maintenance" in notes
    assert "separately approved initial HACS update" in notes
    assert "Repository tests do not establish live acceptance" in notes
    assert not Version("0.12.40").is_prerelease
    manifest = json.loads(
        Path("custom_components/home_energy_orchestrator/manifest.json").read_text()
    )
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    assert manifest["version"] == project["version"]
    assert Version(manifest["version"]) >= Version("0.12.40")
    # Native backup support is optional: order it first when configured, but
    # never make its presence a requirement for ordinary HEO setup/control.
    assert "backup" in manifest["after_dependencies"]
    assert "backup" not in manifest["dependencies"]


def test_01241_cold_catalog_notes_keep_metadata_and_installation_separate() -> None:
    title, notes = release_text("v0.12.41", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.41 — Load Fleet releases after Home Assistant restart"
    assert "HACS's own verified" in notes and "metadata only" in notes
    assert "one initialisation attempt" in notes and "repeating network" in notes
    assert "non-draft, non-prerelease" in notes
    assert "version-looking tag alone" in notes
    assert "Publishing installs nothing" in notes
    assert not Version("0.12.41").is_prerelease


def test_01242_covers_empty_restored_tags_without_adding_control_authority() -> None:
    title, notes = release_text("v0.12.42", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.42 — Restore Fleet release choices after restart"
    assert "HACS 2.0.5" in notes and "does not restore" in notes
    assert "Both the tag" in notes and "one-time native" in notes
    assert "full refreshed tag/model checks" in notes
    assert "No installation, restart, policy change" in notes
    assert "final installer remains cache-only" in notes
    assert not Version("0.12.42").is_prerelease


def test_01243_combined_policy_has_descriptive_stable_release_notes() -> None:
    title, notes = release_text("v0.12.43", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.43 — Combined solar and battery EV backfill"
    assert "Combine power before rounding" in notes
    assert "limit on total EV power" in notes
    assert "solar-only successor" in notes and "backward-compatible" in notes
    assert "Ready-by priority" in notes and "free-window takeover" in notes
    assert "Installation turns no policy on" in notes
    assert not Version("0.12.43").is_prerelease


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


def test_01231_telemetry_patch_has_bounded_descriptive_stable_notes() -> None:
    title, notes = release_text("v0.12.31", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.31 — Stable battery telemetry for EV backfill"
    assert "accepted source's own clock" in notes
    assert "freshness/coherence limits" in notes
    assert "No new settings" in notes and "no automatic price-triggered buying" in notes
    assert not Version("0.12.31").is_prerelease


def test_01232_installs_trip_entities_without_automatic_dashboard_or_policy_changes() -> None:
    title, notes = release_text("v0.12.32", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.32 — Built-in Trip Charge and clearer dashboards"
    assert "Default unarmed" in notes and "legacy" in notes
    assert "generation-bound" in notes and "restart-safe" in notes
    assert "HACS does not replace" in notes
    assert "No automatic price-triggered buying" in notes
    assert not Version("0.12.32").is_prerelease


def test_01234_describes_readonly_trip_scope_and_inclusive_sell_threshold() -> None:
    title, notes = release_text("v0.12.34", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.34 — Trip energy estimates and inclusive price export"
    assert "read-only Trip impact" in notes and "before the next free" in notes
    assert "at or above" in notes and "exactly the threshold" in notes
    assert "explicit card import" in notes and "intent are preserved" in notes
    assert "No automatic price-triggered buying" in notes
    assert not Version("0.12.34").is_prerelease


def test_01235_describes_pause_boundaries_and_live_setting_preservation() -> None:
    title, notes = release_text("v0.12.35", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.35 — Resume paused trips and preserve live settings"
    assert "original absolute timeout" in notes and "generation-bound" in notes
    assert "newer live" in notes and "final schedule confirmation" in notes
    assert "explicit" in notes and "does not silently migrate" in notes
    assert not Version("0.12.35").is_prerelease


def test_01236_describes_startup_hold_without_new_budget_or_activation() -> None:
    title, notes = release_text("v0.12.36", CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert title == "v0.12.36 — Preserve trip charging during startup"
    assert "already-enabled" in notes and "initial vehicle telemetry" in notes
    assert "without new EV commands" in notes and "absolute timeout" in notes
    assert "Do not automatically re-arm" in notes
    assert "does not migrate helpers or overwrite live dashboards" in notes
    assert not Version("0.12.36").is_prerelease
