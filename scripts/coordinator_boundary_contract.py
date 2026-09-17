"""Guard the Phase 6 coordinator-to-platform boundary."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COORDINATOR_SOURCE = (
    REPOSITORY_ROOT
    / "custom_components"
    / "home_energy_orchestrator"
    / "coordinator.py"
)


def validate_coordinator_boundary() -> None:
    """Reject direct Home Assistant state access from the coordinator facade."""
    tree = ast.parse(
        COORDINATOR_SOURCE.read_text(encoding="utf-8"),
        filename=str(COORDINATOR_SOURCE),
    )
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != "states":
            continue
        receiver = ast.unparse(node.value)
        if receiver in {"hass", "self.hass"}:
            violations.append(f"coordinator.py:{node.lineno}: {receiver}.states")
    if violations:
        raise ValueError(
            "coordinator bypasses the telemetry adapter:\n" + "\n".join(violations)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.parse_args()
    validate_coordinator_boundary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
