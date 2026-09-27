"""Tests for the release-note extraction used by the publishing workflow."""

from __future__ import annotations

import pytest

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
