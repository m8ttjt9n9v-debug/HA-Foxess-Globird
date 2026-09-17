"""Generated entity-reference contract tests."""

from __future__ import annotations

from scripts.entity_reference import REFERENCE_PATH, rendered_reference


def test_entity_reference_matches_catalogue_and_semantics() -> None:
    """Generated documentation must not drift from its two source contracts."""
    assert REFERENCE_PATH.read_text(encoding="utf-8") == rendered_reference()


def test_entity_reference_contains_every_entity_once() -> None:
    """Each catalogue entity must have one table row."""
    rows = [
        line
        for line in rendered_reference().splitlines()
        if line.startswith("| `")
    ]
    assert len(rows) == 107
    assert len(set(rows)) == 107
