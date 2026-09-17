"""Phase 4 canonical presentation-boundary tests."""

from __future__ import annotations

from scripts.presentation_contract import validate_presentation_contract


def test_presentation_consumers_use_only_the_canonical_read_model() -> None:
    validate_presentation_contract()
