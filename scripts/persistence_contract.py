"""Generate the immutable v0.12.26 Home Assistant storage baseline."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = REPOSITORY_ROOT / "custom_components" / "home_energy_orchestrator"
BASELINE_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "maintainability"
    / "persistence-contract-v0.12.26.json"
)
MANUAL_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "persistence-additions-manual-inverter-v1.json"
)
AEMO_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "persistence-additions-aemo-monitor-v1.json"
)


def _assigned_name(node: ast.AnnAssign | ast.Assign) -> str:
    target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
    return ast.unparse(target)


def _factory_store_attribute(assigned: str) -> str:
    """Return the retained logical Store attribute for repository factories."""
    if assigned == "self._repository":
        return "self._store"
    if assigned.endswith("_repository"):
        return f"{assigned.removesuffix('_repository')}_store"
    return assigned


def build_persistence_contract() -> dict[str, object]:
    """Return every production Store construction and its compatibility fields."""
    stores: list[dict[str, object]] = []
    for path in sorted(INTEGRATION_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AnnAssign, ast.Assign)):
                continue
            value = node.value
            if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Name):
                continue
            assigned = _assigned_name(node)
            if value.func.id == "Store" and len(value.args) >= 3:
                version_node = value.args[1]
                storage_key_node = value.args[2]
                private_default = False
                attribute = assigned
            elif value.func.id == "create_typed_value_repository":
                keywords = {
                    keyword.arg: keyword.value
                    for keyword in value.keywords
                    if keyword.arg is not None
                }
                if "storage_version" not in keywords or "storage_key" not in keywords:
                    continue
                version_node = keywords["storage_version"]
                storage_key_node = keywords["storage_key"]
                private_default = True
                attribute = _factory_store_attribute(assigned)
            else:
                continue
            private = next(
                (
                    ast.literal_eval(keyword.value)
                    for keyword in value.keywords
                    if keyword.arg == "private"
                ),
                private_default,
            )
            stores.append(
                {
                    "source": path.relative_to(REPOSITORY_ROOT).as_posix(),
                    "attribute": attribute,
                    "version": ast.literal_eval(version_node),
                    "storage_key_expression": ast.unparse(storage_key_node),
                    "private": private,
                }
            )
    stores.sort(key=lambda item: (str(item["source"]), str(item["attribute"])))
    return {
        "schema_version": 1,
        "release_baseline": "0.12.26",
        "store_count": len(stores),
        "stores": stores,
    }


def rendered_contract() -> str:
    """Return deterministic JSON for review and CI comparison."""
    return json.dumps(build_persistence_contract(), indent=2, sort_keys=True) + "\n"


def validate_against_release_baseline() -> None:
    """Permit explicit extension stores, preserving all old obligations."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    additions = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (MANUAL_ADDITIONS_PATH, AEMO_ADDITIONS_PATH)
    ]
    for extension in additions:
        if extension.get("schema_version") != baseline.get("schema_version"):
            raise ValueError("storage addition schema does not match the baseline")
        if extension.get("store_count") != len(extension["stores"]):
            raise ValueError("storage addition count does not match its records")
    current = build_persistence_contract()
    expected_stores = sorted(
        baseline["stores"] + [store for extension in additions for store in extension["stores"]],
        key=lambda item: (item["source"], item["attribute"]),
    )
    identities = [(item["source"], item["attribute"]) for item in expected_stores]
    if len(identities) != len(set(identities)):
        raise ValueError("storage addition overlaps an existing obligation")
    if current != {
        **baseline,
        "store_count": baseline["store_count"] + sum(item["store_count"] for item in additions),
        "stores": expected_stores,
    }:
        raise ValueError("Persistence contract changed beyond the reviewed extensions")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_contract()
    if args.write:
        parser.error("The release baseline is frozen; review additions in their own contract")
    if args.check:
        try:
            validate_against_release_baseline()
        except ValueError as error:
            raise SystemExit(str(error)) from error
    if not args.write and not args.check:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
