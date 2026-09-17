"""Clean-install entity usability audit tests."""

from __future__ import annotations

from scripts.entity_usability_audit import (
    AUDIT_PATH,
    build_usability_audit,
    rendered_audit,
)


def test_clean_install_usability_audit_is_current() -> None:
    """The reviewed report must track catalogue, semantics and dashboard."""
    assert AUDIT_PATH.read_text(encoding="utf-8") == rendered_audit()


def test_clean_install_usability_audit_accounts_for_every_entity() -> None:
    """Audience coverage and open presentation decisions must stay explicit."""
    audit = build_usability_audit()
    assert audit["entity_count"] == 107
    assert sum(audit["audience_counts"].values()) == 107
    assert sum(
        result["total"] for result in audit["dashboard_coverage"].values()
    ) == 107
    assert not audit["relabel_candidates"]
    assert len(audit["approved_relabels"]) == 9
    assert audit["translated_count"] == 0
    assert audit["primary_missing_from_dashboard"]
    assert audit["diagnostic_category_candidates"]
