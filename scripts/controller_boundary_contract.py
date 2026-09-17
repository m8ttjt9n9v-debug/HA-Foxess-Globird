"""Guard the Phase 7 controller and pure-planner boundaries."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = REPOSITORY_ROOT / "custom_components" / "home_energy_orchestrator"
CONTROLLER_SOURCES = (
    INTEGRATION_ROOT / "active.py",
    INTEGRATION_ROOT / "ev_active.py",
)
PLANNER_ROOT = INTEGRATION_ROOT / "planner"


def _imports_homeassistant(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").startswith("homeassistant")
    return any(alias.name.startswith("homeassistant") for alias in node.names)


def _is_hass_platform_access(node: ast.Attribute) -> bool:
    if node.attr not in {"states", "services"}:
        return False
    return ast.unparse(node.value) in {"hass", "self.hass"}


def validate_controller_boundary() -> None:
    """Reject platform access from planners and adapter bypass in controllers."""
    violations: list[str] = []
    for path in CONTROLLER_SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and _is_hass_platform_access(node):
                violations.append(
                    f"{path.name}:{node.lineno}: direct {ast.unparse(node)} access"
                )

    for path in sorted(PLANNER_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and _imports_homeassistant(
                node
            ):
                violations.append(
                    f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: "
                    "Home Assistant import in pure planner"
                )
            if isinstance(node, ast.Attribute) and node.attr in {"states", "services"}:
                violations.append(
                    f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: "
                    f"platform attribute {ast.unparse(node)} in pure planner"
                )
    if violations:
        raise ValueError(
            "controller/planner boundary violations:\n" + "\n".join(violations)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.parse_args()
    validate_controller_boundary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
