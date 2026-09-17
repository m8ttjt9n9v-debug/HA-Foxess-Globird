"""Generate the reviewed entity reference from catalogue and semantic contracts."""

from __future__ import annotations

import argparse
from enum import Enum
from pathlib import Path
from typing import Any

from custom_components.home_energy_orchestrator.entity_catalogue import ENTITY_SPECS
from scripts.entity_semantics import load_semantic_contract, validate_semantic_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "maintainability"
    / "entity-reference-v0.12.26.md"
)


def _text(value: Any) -> str:
    if isinstance(value, Enum):
        value = value.value
    if value is None or value == "":
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def rendered_reference() -> str:
    """Return deterministic Markdown for the complete entity catalogue."""
    semantic_contract = load_semantic_contract()
    validate_semantic_contract(semantic_contract)
    semantics = {item["key"]: item for item in semantic_contract["entities"]}
    lines = [
        "# Entity reference — v0.12.26 compatibility baseline",
        "",
        "This generated engineering reference joins the runtime entity catalogue",
        "to the reviewed semantic worksheet. It records current compatibility",
        "names, not approval of proposed relabels. Edit the catalogue or semantic",
        "worksheet, then regenerate this file; do not edit rows by hand.",
        "",
        f"Total entities: **{len(ENTITY_SPECS)}**.",
        "",
    ]
    for platform in (
        "binary_sensor",
        "button",
        "number",
        "select",
        "sensor",
        "switch",
    ):
        specs = sorted(
            (spec for spec in ENTITY_SPECS if spec.platform == platform),
            key=lambda spec: spec.description.key,
        )
        lines.extend(
            (
                f"## {platform.replace('_', ' ').title()}",
                "",
                "| Entity ID | Current name | Role | Audience | Unit | Projection "
                "| Availability | Decision | Definition |",
                "|---|---|---|---|---|---|---|---|---|",
            )
        )
        for spec in specs:
            description = spec.description
            semantic = semantics[description.key]
            entity_id = f"{platform}.home_energy_{description.key}"
            lines.append(
                "| "
                + " | ".join(
                    _text(value)
                    for value in (
                        f"`{entity_id}`",
                        description.name,
                        semantic["role"],
                        semantic["audience"],
                        getattr(description, "native_unit_of_measurement", None),
                        f"`{spec.value_projection}`",
                        spec.availability,
                        semantic["decision"],
                        semantic["definition"],
                    )
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_reference()
    if args.write:
        REFERENCE_PATH.write_text(rendered, encoding="utf-8")
    if args.check and (
        not REFERENCE_PATH.is_file()
        or REFERENCE_PATH.read_text(encoding="utf-8") != rendered
    ):
        raise SystemExit("Entity reference is stale; regenerate it explicitly")
    if not args.write and not args.check:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
