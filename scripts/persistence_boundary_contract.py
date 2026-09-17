"""Guard the Phase 5 typed persistence boundary."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = REPOSITORY_ROOT / "custom_components" / "home_energy_orchestrator"
REPOSITORY_SOURCE = INTEGRATION_ROOT / "persistence.py"
ACTIVE_CONTROLLER_SOURCES = {
    INTEGRATION_ROOT / "active.py",
    INTEGRATION_ROOT / "ev_active.py",
}


def validate_persistence_boundary() -> None:
    """Reject production Store loads or saves outside typed repositories."""
    violations: list[str] = []
    for path in sorted(INTEGRATION_ROOT.rglob("*.py")):
        if path == REPOSITORY_SOURCE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if path in ACTIVE_CONTROLLER_SOURCES and (
                (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "homeassistant.helpers.storage"
                    and any(alias.name == "Store" for alias in node.names)
                )
                or (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "Store"
                )
            ):
                relative = path.relative_to(REPOSITORY_ROOT)
                violations.append(
                    f"{relative}:{node.lineno}: raw Store dependency in active controller"
                )
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"async_load", "async_save"}
            ):
                continue
            receiver = ast.unparse(node.func.value)
            if "repository" not in receiver:
                relative = path.relative_to(REPOSITORY_ROOT)
                violations.append(f"{relative}:{node.lineno}: {receiver}.{node.func.attr}")
    if violations:
        raise ValueError(
            "production persistence bypasses typed repositories:\n"
            + "\n".join(violations)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.parse_args()
    validate_persistence_boundary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
