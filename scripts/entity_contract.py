"""Generate the immutable v0.12.26 entity-registry baseline."""

from __future__ import annotations

import argparse
import json
from enum import Enum
from pathlib import Path
from typing import Any

from custom_components.home_energy_orchestrator.entity_catalogue import ENTITY_SPECS

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPOSITORY_ROOT / "docs" / "maintainability" / "entity-contract-v0.12.26.json"
ADDITIONS_PATH = REPOSITORY_ROOT / "docs" / "maintainability" / "entity-additions-aemo-monitor.json"
PRICE_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-additions-price-export-v1.json"
)
TRIP_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-additions-trip-charge-v1.json"
)

APPROVED_DISPLAY_NAMES = {
    "automatic_export": "Automatic Battery Export",
    "bonus_zero_import_allowed": "ZEROHERO Local Telemetry Qualified",
    "ev_usable_capacity": "EV Planning Capacity",
    "free_charge_allowed": "Battery Free-Charge Energy Allowed",
    "status": "Orchestrator Status",
    "zerohero_export_status": "Automatic Battery Export Status",
    "zerohero_planned_duration": "Automatic Export Planned Duration",
    "zerohero_planned_export_energy": "Automatic Export Planned Energy",
    "zerohero_planned_start": "Automatic Export Planned Start",
    "zerohero_sellable_energy": "Sellable Battery Energy",
}
LOAD_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "entity-additions-load-power-v1.json"
)


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _description_record(platform: str, description: Any) -> dict[str, Any]:
    key = description.key
    return {
        "platform": platform,
        "key": key,
        "unique_id_template": "{config_entry_id}_" + key,
        "default_entity_id": f"{platform}.home_energy_{key}",
        "name": description.name,
        "translation_key": getattr(description, "translation_key", None),
        "unit": _json_value(getattr(description, "native_unit_of_measurement", None)),
        "device_class": _json_value(getattr(description, "device_class", None)),
        "state_class": _json_value(getattr(description, "state_class", None)),
        "entity_category": _json_value(getattr(description, "entity_category", None)),
        "enabled_by_default": bool(
            getattr(description, "entity_registry_enabled_default", True)
        ),
    }


def build_entity_contract() -> dict[str, Any]:
    """Return the deterministic current public entity identity contract."""
    records = [
        *(
            _description_record(spec.platform, spec.description)
            for spec in ENTITY_SPECS
        ),
    ]
    records.sort(key=lambda item: (item["platform"], item["key"]))
    return {
        "schema_version": 1,
        "release_baseline": "0.12.26",
        "entity_count": len(records),
        "entities": records,
    }


def rendered_contract() -> str:
    return json.dumps(build_entity_contract(), indent=2, sort_keys=True) + "\n"


def validate_against_release_baseline() -> None:
    """Preserve every baseline identity plus explicitly reviewed additions."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    additions = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (ADDITIONS_PATH, PRICE_ADDITIONS_PATH, TRIP_ADDITIONS_PATH, LOAD_ADDITIONS_PATH)
    ]
    for extension in additions:
        if extension.get("schema_version") != baseline.get("schema_version"):
            raise ValueError("entity addition schema does not match the baseline")
        if extension.get("entity_count") != len(extension["entities"]):
            raise ValueError("entity addition count does not match its records")
    current = build_entity_contract()
    if (
        baseline["entity_count"] + sum(item["entity_count"] for item in additions)
        != current["entity_count"]
    ):
        raise ValueError("entity count changed from the frozen release baseline")
    baseline_records = {
        (item["platform"], item["key"]): item for item in baseline["entities"]
    }
    current_records = {
        (item["platform"], item["key"]): item for item in current["entities"]
    }
    added_records = {
        (item["platform"], item["key"]): item
        for extension in additions
        for item in extension["entities"]
    }
    if len(added_records) != sum(len(item["entities"]) for item in additions):
        raise ValueError("entity additions contain duplicate identities")
    if (
        baseline_records.keys() & added_records.keys()
        or baseline_records.keys() | added_records.keys() != current_records.keys()
    ):
        raise ValueError("entity identity changed from the frozen release baseline")
    for identity, expected in added_records.items():
        if current_records[identity] != expected:
            raise ValueError(f"unreviewed entity addition changed: {identity!r}")
    for identity, old in baseline_records.items():
        new = current_records[identity]
        expected_name = APPROVED_DISPLAY_NAMES.get(old["key"], old["name"])
        if new["name"] != expected_name:
            raise ValueError(f"unapproved display-name change for {old['key']!r}")
        for field in old.keys() - {"name"}:
            if new[field] != old[field]:
                raise ValueError(
                    f"incompatible {field} change for {old['key']!r}"
                )


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
        except ValueError as err:
            raise SystemExit(str(err)) from err
    if not args.write and not args.check:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
