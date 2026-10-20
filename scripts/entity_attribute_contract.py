"""Generate the immutable v0.12.26 custom entity-attribute baseline."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

from scripts.entity_contract import build_entity_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
READ_MODEL_SOURCE = (
    REPOSITORY_ROOT
    / "custom_components"
    / "home_energy_orchestrator"
    / "read_model.py"
)
BASELINE_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "maintainability"
    / "entity-attribute-contract-v0.12.26.json"
)
MANUAL_ADDITIONS_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "maintainability"
    / "entity-attribute-additions-manual-inverter-v1.json"
)
AEMO_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-attribute-additions-aemo-monitor-v1.json"
)
AMBER_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-attribute-additions-amber-price-v1.json"
)
PRICE_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-attribute-additions-price-export-v1.json"
)
AEMO_MONITOR_SOURCE = (
    REPOSITORY_ROOT / "custom_components" / "home_energy_orchestrator" / "aemo_monitor.py"
)
TRIP_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-attribute-additions-trip-charge-v1.json"
)
TRIP_SOURCE = (
    REPOSITORY_ROOT / "custom_components" / "home_energy_orchestrator" / "trip_charge.py"
)
EV_CAPACITY_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-attribute-additions-ev-capacity-v1.json"
)
TRIP_IMPACT_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-attribute-additions-trip-impact-v1.json"
)
TRIP_RESUME_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-attribute-additions-trip-resume-v1.json"
)
EV_STARTUP_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-attribute-additions-ev-startup-v1.json"
)
EV_FEEDBACK_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-attribute-additions-ev-feedback-v1.json"
)

_TELEMETRY_KEYS = (
    "battery_power",
    "grid_power",
    "house_load",
    "site_grid_current",
    "solar_power",
)
LOAD_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-attribute-additions-load-power-v1.json"
)
_SCORECARD_KEYS = (
    "forecast_error_yesterday",
    "forecast_scorecard_status",
    "forecast_yesterday_cost",
    "globird_yesterday_actual_cost",
)


def _method(tree: ast.Module, class_name: str, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == name:
                    return member
    raise ValueError(f"{class_name}.{name} was not found")


def _dict_return_keys(
    function: ast.FunctionDef,
    inherited_attributes: dict[str, frozenset[str]] | None = None,
) -> list[frozenset[str]]:
    results: list[frozenset[str]] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        keys: list[str] = []
        for key, value in zip(node.value.keys, node.value.values, strict=True):
            if key is None and inherited_attributes is not None:
                inherited = inherited_attributes.get(ast.unparse(value))
                if inherited is not None:
                    keys.extend(inherited)
                    continue
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
    read_model_tree = ast.parse(READ_MODEL_SOURCE.read_text(encoding="utf-8"))
    fleet_groups = _dict_return_keys(
        _method(read_model_tree, "SiteReadModel", "fleet_attributes")
    )
    if len(fleet_groups) != 1:
        raise ValueError("Fleet Summary must have one literal attribute mapping")
    read_model_groups = _dict_return_keys(
        _method(read_model_tree, "CostReadModel", "sensor_attributes")
    ) + _dict_return_keys(
        _method(read_model_tree, "TelemetrySampleReadModel", "entity_attributes")
    ) + _dict_return_keys(
        _method(read_model_tree, "OperationalReadModel", "zerohero_import_attributes")
    ) + _dict_return_keys(
        _method(read_model_tree, "CostReadModel", "export_revenue_attributes")
    ) + _dict_return_keys(
        _method(read_model_tree, "ScorecardReadModel", "sensor_attributes")
    ) + _dict_return_keys(
        _method(read_model_tree, "LearningReadModel", "occupancy_attributes")
    ) + _dict_return_keys(
        _method(read_model_tree, "EvReadModel", "control_attributes")
    ) + _dict_return_keys(
        _method(read_model_tree, "SiteReadModel", "status_attributes")
    )

    telemetry = _group_by_sentinel(read_model_groups, "positive_direction")
    zerohero_import = _group_by_sentinel(read_model_groups, "hourly_import_kwh")
    export_revenue = _group_by_sentinel(
        read_model_groups,
        "standard_export_revenue",
    )
    forecast = _group_by_sentinel(read_model_groups, "raw_optimistic_forecast")
    scorecard = _group_by_sentinel(read_model_groups, "result_date")
    # The full EV status mapping already contains ``gate``; the separate
    # unavailable fallback exposes only that same key.
    ev_control = _group_by_sentinel(read_model_groups, "decision_phase")
    capacity_groups = _dict_return_keys(
        _method(read_model_tree, "EvReadModel", "capacity_attributes")
    )
    if len(capacity_groups) != 1:
        raise ValueError("EV capacity must have one literal public attribute mapping")
    occupancy = _group_by_sentinel(read_model_groups, "selected_mode")
    status = _group_by_sentinel(read_model_groups, "ledger_status")

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
            _record("ev_usable_capacity", capacity_groups[0]),
            _record("house_occupancy_state", occupancy),
            _record("status", status),
        )
    )
    monitor_tree = ast.parse(AEMO_MONITOR_SOURCE.read_text(encoding="utf-8"))
    observations = _dict_return_keys(_method(monitor_tree, "AemoMonitorResult", "attributes"))
    if len(observations) != 1:
        raise ValueError("AEMO observations must have one literal attribute mapping")
    monitor_groups = _dict_return_keys(
        _method(monitor_tree, "AemoMarketMonitor", "result_attributes"),
        {"self.current_result.attributes()": observations[0]},
    )
    if len(monitor_groups) != 1:
        raise ValueError("AEMO monitor must have one expanded attribute mapping")
    records.extend(
        _record(key, monitor_groups[0]) for key in ("aemo_market_status", "aemo_spot_price")
    )
    trip_tree = ast.parse(TRIP_SOURCE.read_text(encoding="utf-8"))
    trip_groups = _dict_return_keys(_method(trip_tree, "TripChargeController", "attributes"))
    if len(trip_groups) != 1:
        raise ValueError("Trip Charge must have one literal public attribute mapping")
    records.append(_record("trip_charge_status", trip_groups[0]))
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


def validate_against_release_baseline() -> None:
    """Retain frozen attribute records and admit only explicit additions."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    additions = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (
            MANUAL_ADDITIONS_PATH,
            AEMO_ADDITIONS_PATH,
            AMBER_ADDITIONS_PATH,
            PRICE_ADDITIONS_PATH,
            TRIP_ADDITIONS_PATH,
            EV_CAPACITY_ADDITIONS_PATH,
            TRIP_IMPACT_ADDITIONS_PATH,
            TRIP_RESUME_ADDITIONS_PATH,
            EV_STARTUP_ADDITIONS_PATH,
            EV_FEEDBACK_ADDITIONS_PATH,
            LOAD_ADDITIONS_PATH,
        )
    ]
    for extension in additions:
        if extension.get("schema_version") != baseline.get("schema_version"):
            raise ValueError("attribute addition schema does not match the baseline")
        if extension.get("entity_count") != len(extension["entities"]):
            raise ValueError("attribute addition count does not match its records")
    current = build_entity_attribute_contract()
    if (
        baseline["entity_count"] + sum(item["entity_count"] for item in additions)
        != current["entity_count"]
    ):
        raise ValueError("custom attribute entity count differs from baseline plus additions")
    old = {record["entity_key"]: record for record in baseline["entities"]}
    added = {
        record["entity_key"]: record for extension in additions for record in extension["entities"]
    }
    if len(added) != sum(len(item["entities"]) for item in additions):
        raise ValueError("attribute additions contain duplicate identities")
    expected = {**old, **added}
    for extension in additions:
        attribute_additions = extension.get("attribute_additions", [])
        if extension.get("attribute_addition_count", 0) != len(attribute_additions):
            raise ValueError("attribute addition count does not match its records")
        for record in attribute_additions:
            key = record["entity_key"]
            if key not in expected:
                raise ValueError("attribute additions must identify a retained entity")
            retained = expected[key]
            attributes = record["custom_attributes"]
            if record["default_entity_id"] != retained["default_entity_id"]:
                raise ValueError("attribute additions cannot change an entity identity")
            if len(attributes) != len(set(attributes)) or set(attributes) & set(
                retained["custom_attributes"]
            ):
                raise ValueError("attribute additions cannot replace reviewed public keys")
            expected[key] = {
                **retained,
                "custom_attributes": sorted(retained["custom_attributes"] + attributes),
            }
    actual = {record["entity_key"]: record for record in current["entities"]}
    if old.keys() & added.keys() or old.keys() | added.keys() != actual.keys():
        raise ValueError("custom attribute identities differ from baseline plus additions")
    for key, record in expected.items():
        if actual[key] != record:
            raise ValueError(f"custom public attributes changed for {key!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_contract()
    if args.write:
        raise SystemExit(
            "The release attribute baseline is frozen; review versioned additions instead"
        )
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
