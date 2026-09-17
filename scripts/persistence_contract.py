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


def _assigned_name(node: ast.AnnAssign | ast.Assign) -> str:
    target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
    return ast.unparse(target)


def build_persistence_contract() -> dict[str, object]:
    """Return every production Store construction and its compatibility fields."""
    stores: list[dict[str, object]] = []
    for path in sorted(INTEGRATION_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AnnAssign, ast.Assign)):
                continue
            value = node.value
            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "Store"
                and len(value.args) >= 3
            ):
                continue
            private = next(
                (
                    ast.literal_eval(keyword.value)
                    for keyword in value.keywords
                    if keyword.arg == "private"
                ),
                False,
            )
            stores.append(
                {
                    "source": path.relative_to(REPOSITORY_ROOT).as_posix(),
                    "attribute": _assigned_name(node),
                    "version": ast.literal_eval(value.args[1]),
                    "storage_key_expression": ast.unparse(value.args[2]),
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_contract()
    if args.write:
        BASELINE_PATH.write_text(rendered, encoding="utf-8")
    if args.check:
        if not BASELINE_PATH.is_file() or BASELINE_PATH.read_text(
            encoding="utf-8"
        ) != rendered:
            raise SystemExit(
                "Persistence contract changed; review migration and compatibility impact"
            )
    if not args.write and not args.check:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
