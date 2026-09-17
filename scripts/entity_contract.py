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

APPROVED_DISPLAY_NAMES = {
    "automatic_export": "Automatic Battery Export",
    "bonus_zero_import_allowed": "ZEROHERO Local Telemetry Qualified",
    "free_charge_allowed": "Battery Free-Charge Energy Allowed",
    "status": "Orchestrator Status",
    "zerohero_export_status": "Automatic Battery Export Status",
    "zerohero_planned_duration": "Automatic Export Planned Duration",
    "zerohero_planned_export_energy": "Automatic Export Planned Energy",
    "zerohero_planned_start": "Automatic Export Planned Start",
    "zerohero_sellable_energy": "Sellable Battery Energy",
}


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
    """Allow only owner-approved display-name deltas from v0.12.26."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    current = build_entity_contract()
    if baseline["entity_count"] != current["entity_count"]:
        raise ValueError("entity count changed from the frozen release baseline")
    baseline_records = {
        (item["platform"], item["key"]): item for item in baseline["entities"]
    }
    current_records = {
        (item["platform"], item["key"]): item for item in current["entities"]
    }
    if baseline_records.keys() != current_records.keys():
        raise ValueError("entity identity changed from the frozen release baseline")
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
        BASELINE_PATH.write_text(rendered, encoding="utf-8")
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
