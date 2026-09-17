"""Generate the Phase 2 clean-install entity usability audit."""

from __future__ import annotations

import argparse
from collections import Counter
from enum import Enum
from pathlib import Path
from typing import Any

from custom_components.home_energy_orchestrator.entity_catalogue import ENTITY_SPECS
from scripts.dashboard_contract import entity_references
from scripts.entity_semantics import load_semantic_contract, validate_semantic_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "maintainability"
    / "clean-install-usability-audit-v0.12.26.md"
)


def _value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def build_usability_audit() -> dict[str, Any]:
    """Return deterministic evidence without making presentation decisions."""
    semantic_contract = load_semantic_contract()
    validate_semantic_contract(semantic_contract)
    semantics = {item["key"]: item for item in semantic_contract["entities"]}
    dashboard_entities = entity_references()
    records = []
    for spec in ENTITY_SPECS:
        key = spec.description.key
        semantic = semantics[key]
        entity_id = f"{spec.platform}.home_energy_{key}"
        records.append(
            {
                "key": key,
                "entity_id": entity_id,
                "name": spec.description.name,
                "platform": spec.platform,
                "audience": semantic["audience"],
                "decision": semantic["decision"],
                "entity_category": _value(
                    getattr(spec.description, "entity_category", None)
                ),
                "translation_key": getattr(spec.description, "translation_key", None),
                "on_dashboard": entity_id in dashboard_entities,
            }
        )

    coverage = {}
    for audience in ("primary", "advanced", "diagnostic"):
        audience_records = [item for item in records if item["audience"] == audience]
        referenced = sum(item["on_dashboard"] for item in audience_records)
        coverage[audience] = {
            "total": len(audience_records),
            "referenced": referenced,
            "missing": len(audience_records) - referenced,
        }

    return {
        "entity_count": len(records),
        "dashboard_reference_count": len(dashboard_entities),
        "translated_count": sum(bool(item["translation_key"]) for item in records),
        "audience_counts": dict(Counter(item["audience"] for item in records)),
        "category_counts": dict(
            Counter(item["entity_category"] or "none" for item in records)
        ),
        "dashboard_coverage": coverage,
        "primary_missing_from_dashboard": [
            item for item in records if item["audience"] == "primary" and not item["on_dashboard"]
        ],
        "diagnostic_category_candidates": [
            item
            for item in records
            if item["audience"] == "diagnostic"
            and item["entity_category"] != "diagnostic"
        ],
        "relabel_candidates": [
            item
            for item in records
            if item["decision"] == "relabel"
            and semantics[item["key"]]["review_status"] != "owner_approved"
        ],
        "approved_relabels": [
            item
            for item in records
            if item["decision"] == "relabel"
            and semantics[item["key"]]["review_status"] == "owner_approved"
        ],
    }


def rendered_audit() -> str:
    """Render the evidence as a stable human-reviewable report."""
    audit = build_usability_audit()
    lines = [
        "# Clean-install usability audit — v0.12.26 baseline",
        "",
        "This generated report identifies remaining presentation gaps and records",
        "the owner-approved display-name changes. Category and dashboard decisions",
        "remain separate.",
        "",
        "## Summary",
        "",
        "| Measure | Result |",
        "|---|---:|",
        f"| Catalogue entities | {audit['entity_count']} |",
        f"| Portable dashboard references | {audit['dashboard_reference_count']} |",
        f"| Entity translation keys | {audit['translated_count']} |",
        f"| Proposed relabels awaiting owner review | {len(audit['relabel_candidates'])} |",
        f"| Owner-approved relabels | {len(audit['approved_relabels'])} |",
        "",
        "## Dashboard coverage by reviewed audience",
        "",
        "| Audience | Total | Referenced | Not referenced |",
        "|---|---:|---:|---:|",
    ]
    for audience, result in audit["dashboard_coverage"].items():
        lines.append(
            f"| {audience} | {result['total']} | {result['referenced']} "
            f"| {result['missing']} |"
        )
    lines.extend(
        (
            "",
            "Dashboard absence is audit evidence, not automatically a defect: Fleet,",
            "site overlays and deliberately advanced entities may be consumed elsewhere.",
            "The two primary omissions require a presentation decision before change.",
            "",
            "### Primary entities not referenced by the portable dashboard",
            "",
            "| Entity ID | Current name |",
            "|---|---|",
        )
    )
    for item in audit["primary_missing_from_dashboard"]:
        lines.append(f"| `{item['entity_id']}` | {item['name']} |")
    lines.extend(
        (
            "",
            "## Category evidence",
            "",
            f"Current categories: `{audit['category_counts']}`.",
            "",
            "The semantic review marks the following entities as diagnostic audience,",
            "but Home Assistant does not currently classify them as Diagnostic. This is",
            "a review list, not approval to change upgraded installations.",
            "",
            "| Entity ID | Current name | Current category |",
            "|---|---|---|",
        )
    )
    for item in audit["diagnostic_category_candidates"]:
        category = item["entity_category"] or "none"
        lines.append(f"| `{item['entity_id']}` | {item['name']} | {category} |")
    lines.extend(
        (
            "",
            "## Remaining Phase 2 decisions",
            "",
            "- The nine display-name changes in `terminology-review-v0.12.26.md`",
            "  are owner-approved and implemented in the catalogue.",
            "- Decide whether the two missing primary entities belong on the portable",
            "  dashboard or should be reclassified.",
            "- Review diagnostic-category candidates before registry presentation changes.",
            "- Translation adoption can now begin from the approved English labels.",
            "",
        )
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_audit()
    if args.write:
        AUDIT_PATH.write_text(rendered, encoding="utf-8")
    if args.check and (
        not AUDIT_PATH.is_file() or AUDIT_PATH.read_text(encoding="utf-8") != rendered
    ):
        raise SystemExit("Clean-install usability audit is stale; regenerate explicitly")
    if not args.write and not args.check:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
