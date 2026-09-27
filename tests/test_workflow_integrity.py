"""Contracts for repository automation that protects release verification."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW_DIRECTORY = Path(__file__).parents[1] / ".github" / "workflows"
USES_LINE = re.compile(
    r"^\s*-\s+uses:\s+[^@\s]+@(?P<revision>[0-9a-f]{40})(?:\s+#.*)?$"
)


def test_workflow_actions_are_pinned_to_immutable_revisions() -> None:
    """Do not let CI/release behavior silently change through a moving ref."""
    invalid = []
    for workflow in sorted(WORKFLOW_DIRECTORY.glob("*.yml")):
        for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            if "uses:" not in line:
                continue
            if USES_LINE.match(line) is None:
                invalid.append(f"{workflow}:{number}: {line.strip()}")

    message = "Workflow action references must use 40-character commit IDs:\n"
    assert not invalid, message + "\n".join(invalid)


def test_release_workflow_fetches_the_rollback_tag_before_rehearsal() -> None:
    """The tagged release job needs full history for the fixed rollback target."""
    release = (WORKFLOW_DIRECTORY / "release.yml").read_text(encoding="utf-8")
    assert "fetch-depth: 0" in release
    assert "scripts.previous_release_rehearsal --tag v0.12.26" in release


def test_release_workflow_uses_the_matching_changelog_section() -> None:
    """HACS must receive a descriptive GitHub Release title and notes."""
    release = (WORKFLOW_DIRECTORY / "release.yml").read_text(encoding="utf-8")
    assert "python -m scripts.release_notes" in release
    assert "--title-file .github-release-title.txt" in release
    assert "--notes-file .github-release-notes.md" in release
    assert "gh release edit" in release
    assert "--generate-notes" not in release
