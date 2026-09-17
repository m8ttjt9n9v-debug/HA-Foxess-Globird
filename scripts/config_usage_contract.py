"""Inventory direct persisted-configuration access in integration source."""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from pathlib import Path
from typing import Any

from custom_components.home_energy_orchestrator import const

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "custom_components" / "home_energy_orchestrator"
BASELINE_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "maintainability"
    / "config-usage-contract-v0.12.26.json"
)
_CONFIG_ACCESS_METHODS = {"get", "pop", "setdefault", "update_config_value"}
_BOUNDARY_FILES = {"__init__.py", "config_flow.py", "configuration.py"}


class _UsageVisitor(ast.NodeVisitor):
    def __init__(self, source: Path, constants: dict[str, str]) -> None:
        self.source = source
        self.constants = constants
        self.scope: list[str] = []
        self.records: list[dict[str, Any]] = []

    def _record(
        self,
        constant_node: ast.expr,
        receiver: ast.expr,
        access: str,
    ) -> None:
        if not isinstance(constant_node, ast.Name):
            return
        constant = constant_node.id
        if constant not in self.constants:
            return
        relative = self.source.relative_to(REPOSITORY_ROOT).as_posix()
        kind = "managed_mutation" if access == "update_config_value" else "raw_mapping"
        self.records.append(
            {
                "constant": constant,
                "key": self.constants[constant],
                "source": relative,
                "scope": ".".join(self.scope) or "<module>",
                "receiver": ast.unparse(receiver),
                "access": access,
                "kind": kind,
                "layer": (
                    "boundary" if self.source.name in _BOUNDARY_FILES else "runtime"
                ),
            }
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _CONFIG_ACCESS_METHODS
            and node.args
        ):
            self._record(node.args[0], node.func.value, node.func.attr)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:  # noqa: N802
        context = type(node.ctx).__name__.lower()
        self._record(node.slice, node.value, f"subscript_{context}")
        self.generic_visit(node)


def build_config_usage_contract() -> dict[str, Any]:
    """Return a deterministic AST inventory of direct config-key access."""
    constants = {
        name: value
        for name, value in vars(const).items()
        if name.startswith("CONF_") and isinstance(value, str)
    }
    records: list[dict[str, Any]] = []
    for source in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        visitor = _UsageVisitor(source, constants)
        visitor.visit(tree)
        records.extend(visitor.records)
    records.sort(
        key=lambda item: (
            item["source"],
            item["scope"],
            item["constant"],
            item["access"],
            item["receiver"],
        )
    )
    by_layer = Counter(item["layer"] for item in records)
    by_kind = Counter(item["kind"] for item in records)
    raw_by_layer = Counter(
        item["layer"] for item in records if item["kind"] == "raw_mapping"
    )
    by_source = Counter(item["source"] for item in records)
    return {
        "schema_version": 2,
        "release_baseline": "0.12.26",
        "access_count": len(records),
        "key_count": len({item["key"] for item in records}),
        "accesses_by_layer": dict(sorted(by_layer.items())),
        "accesses_by_kind": dict(sorted(by_kind.items())),
        "raw_accesses_by_layer": dict(sorted(raw_by_layer.items())),
        "accesses_by_source": dict(sorted(by_source.items())),
        "accesses": records,
    }


def rendered_contract() -> str:
    return json.dumps(build_config_usage_contract(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_contract()
    if args.write:
        BASELINE_PATH.write_text(rendered, encoding="utf-8")
    if args.check and (
        not BASELINE_PATH.is_file() or BASELINE_PATH.read_text(encoding="utf-8") != rendered
    ):
        raise SystemExit("Configuration usage contract changed; review and regenerate")
    if not args.write and not args.check:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
