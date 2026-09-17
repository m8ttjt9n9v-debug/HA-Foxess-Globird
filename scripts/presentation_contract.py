"""Guard the Phase 4 canonical presentation boundary."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = REPOSITORY_ROOT / "custom_components" / "home_energy_orchestrator"
SENSOR_SOURCE = INTEGRATION_ROOT / "sensor.py"
DIAGNOSTICS_SOURCE = INTEGRATION_ROOT / "diagnostics.py"


def _function(
    tree: ast.Module, name: str, *, class_name: str | None = None
) -> ast.AsyncFunctionDef | ast.FunctionDef:
    scope: list[ast.stmt] = tree.body
    if class_name is not None:
        owner = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        if owner is None:
            raise ValueError(f"{class_name} was not found")
        scope = owner.body
    for node in scope:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise ValueError(f"{class_name + '.' if class_name else ''}{name} was not found")


def _returns(function: ast.AsyncFunctionDef | ast.FunctionDef) -> list[ast.Return]:
    return [node for node in ast.walk(function) if isinstance(node, ast.Return)]


def _assert_single_return(function: ast.FunctionDef, expected: str) -> None:
    returns = _returns(function)
    if len(returns) != 1 or ast.unparse(returns[0].value) != expected:
        raise ValueError(f"{function.name} must return only {expected}")


def validate_presentation_contract() -> None:
    """Raise when presentation code bypasses the canonical read model."""
    sensor_tree = ast.parse(SENSOR_SOURCE.read_text(encoding="utf-8"))
    native_value = _function(sensor_tree, "native_value", class_name="EnergySensor")
    _assert_single_return(
        native_value,
        "read_model.sensor_values()[self.entity_description.key]",
    )
    fleet = _function(
        sensor_tree, "_fleet_summary_attributes", class_name="EnergySensor"
    )
    _assert_single_return(
        fleet,
        "build_site_read_model(self.coordinator).fleet_attributes(dt_util.now())",
    )

    attributes = _function(
        sensor_tree, "extra_state_attributes", class_name="EnergySensor"
    )
    if any(isinstance(node, ast.BinOp) for node in ast.walk(attributes)):
        raise ValueError("extra_state_attributes must route projections, not calculate")
    calls = {ast.unparse(node.func) for node in ast.walk(attributes) if isinstance(node, ast.Call)}
    allowed_calls = {
        "self._fleet_summary_attributes",
        "build_site_read_model",
        "read_model.telemetry.entity_attributes",
        "read_model.operational.zerohero_import_attributes",
        "read_model.cost.export_revenue_attributes",
        "read_model.cost.sensor_attributes",
        "read_model.scorecard.sensor_attributes",
        "read_model.ev.control_attributes",
        "read_model.learning.occupancy_attributes",
        "read_model.status_attributes",
    }
    if unexpected := calls - allowed_calls:
        raise ValueError(
            "extra_state_attributes contains non-canonical calls: "
            + ", ".join(sorted(unexpected))
        )

    diagnostics_tree = ast.parse(DIAGNOSTICS_SOURCE.read_text(encoding="utf-8"))
    diagnostics = _function(diagnostics_tree, "async_get_config_entry_diagnostics")
    returns = _returns(diagnostics)
    if len(returns) != 1 or not isinstance(returns[0].value, ast.Dict):
        raise ValueError("diagnostics must return one literal projection mapping")
    payload = returns[0].value
    values = {
        ast.literal_eval(key): ast.unparse(value)
        for key, value in zip(payload.keys, payload.values, strict=True)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    expected = {
        "normalized_telemetry": "read_model.telemetry.diagnostics()",
        "ledger": "read_model.operational.diagnostics()",
        "forecast": "read_model.forecast_diagnostics()",
        "learning": "read_model.learning.diagnostics()",
    }
    for key, expression in expected.items():
        if values.get(key) != expression:
            raise ValueError(f"diagnostics {key!r} must project {expression}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.parse_args()
    validate_presentation_contract()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
