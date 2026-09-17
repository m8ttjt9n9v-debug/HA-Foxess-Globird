"""Generate the immutable v0.12.26 custom entity-attribute baseline."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

from scripts.entity_contract import build_entity_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SENSOR_SOURCE = (
    REPOSITORY_ROOT
    / "custom_components"
    / "home_energy_orchestrator"
    / "sensor.py"
)
BASELINE_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "maintainability"
    / "entity-attribute-contract-v0.12.26.json"
)

_TELEMETRY_KEYS = (
    "battery_power",
    "grid_power",
    "house_load",
    "site_grid_current",
    "solar_power",
)
_SCORECARD_KEYS = (
    "forecast_error_yesterday",
    "forecast_scorecard_status",
    "forecast_yesterday_cost",
    "globird_yesterday_actual_cost",
)


def _method(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "EnergySensor":
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == name:
                    return member
    raise ValueError(f"EnergySensor.{name} was not found")


def _dict_return_keys(function: ast.FunctionDef) -> list[frozenset[str]]:
    results: list[frozenset[str]] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        keys: list[str] = []
        for key in node.value.keys:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                raise ValueError(
                    f"{function.name} contains a non-literal public attribute key"
                )
            keys.append(key.value)
        results.append(frozenset(keys))
    return results


def _group_by_sentinel(
    groups: list[frozenset[str]], sentinel: str
) -> frozenset[str]:
    matches = [group for group in groups if sentinel in group]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one attribute group containing {sentinel!r}; got {len(matches)}"
        )
    return matches[0]


def _record(entity_key: str, attributes: frozenset[str]) -> dict[str, Any]:
    return {
        "entity_key": entity_key,
        "default_entity_id": f"sensor.home_energy_{entity_key}",
        "custom_attributes": sorted(attributes),
    }


def build_entity_attribute_contract() -> dict[str, Any]:
    """Return the deterministic custom public-attribute contract."""
    tree = ast.parse(SENSOR_SOURCE.read_text(encoding="utf-8"))
    fleet_groups = _dict_return_keys(_method(tree, "_fleet_summary_attributes"))
    if len(fleet_groups) != 1:
        raise ValueError("Fleet Summary must have one literal attribute mapping")
    groups = _dict_return_keys(_method(tree, "extra_state_attributes"))

    telemetry = _group_by_sentinel(groups, "positive_direction")
    zerohero_import = _group_by_sentinel(groups, "hourly_import_kwh")
    export_revenue = _group_by_sentinel(groups, "standard_export_revenue")
    forecast = _group_by_sentinel(groups, "raw_optimistic_forecast")
    scorecard = _group_by_sentinel(groups, "result_date")
    # The full EV status mapping already contains ``gate``; the separate
    # unavailable fallback exposes only that same key.
    ev_control = _group_by_sentinel(groups, "decision_phase")
    occupancy = _group_by_sentinel(groups, "selected_mode")
    status = _group_by_sentinel(groups, "ledger_status")

    records = [_record("fleet_summary", fleet_groups[0])]
    records.extend(_record(key, telemetry) for key in _TELEMETRY_KEYS)
    records.extend(
        (
            _record("zerohero_import_window", zerohero_import),
            _record("estimated_export_revenue", export_revenue),
            _record("estimated_net_cost", forecast),
        )
    )
    records.extend(_record(key, scorecard) for key in _SCORECARD_KEYS)
    records.extend(
        (
            _record("ev_control_status", ev_control),
            _record("house_occupancy_state", occupancy),
            _record("status", status),
        )
    )
    records.sort(key=lambda item: item["entity_key"])

    known_entities = {
        item["default_entity_id"] for item in build_entity_contract()["entities"]
    }
    unknown = sorted(
        record["default_entity_id"]
        for record in records
        if record["default_entity_id"] not in known_entities
    )
    if unknown:
        raise ValueError(f"attribute contract references unknown entities: {unknown}")

    return {
        "schema_version": 1,
        "release_baseline": "0.12.26",
        "entity_count": len(records),
        "entities": records,
    }


def rendered_contract() -> str:
    return json.dumps(build_entity_attribute_contract(), indent=2, sort_keys=True) + "\n"


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
                "Entity attribute contract changed; review compatibility and regenerate explicitly"
            )
    if not args.write and not args.check:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
