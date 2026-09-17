"""Generate the immutable v0.12.26 entity-registry baseline."""

from __future__ import annotations

import argparse
import json
from enum import Enum
from pathlib import Path
from typing import Any

from custom_components.home_energy_orchestrator import (
    button,
    number,
    select,
    sensor,
    switch,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPOSITORY_ROOT / "docs" / "maintainability" / "entity-contract-v0.12.26.json"


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
    descriptions = {
        "sensor": sensor.DESCRIPTIONS,
        "switch": (
            switch.SAFETY_DESCRIPTION,
            switch.CHARGE_DESCRIPTION,
            switch.EXPORT_DESCRIPTION,
            switch.EV_DESCRIPTION,
            switch.EV_BEFORE_EXPORT_DESCRIPTION,
            switch.CHARGE_TO_FULL_DESCRIPTION,
        ),
        "number": (*number.DESCRIPTIONS, number.EV_BEFORE_EXPORT_TARGET_DESCRIPTION),
        "button": button.DESCRIPTIONS,
        "select": (select.DESCRIPTION,),
    }
    records = [
        _description_record(platform, description)
        for platform, platform_descriptions in descriptions.items()
        for description in platform_descriptions
    ]
    records.append(
        {
            "platform": "binary_sensor",
            "key": "sign_conventions_verified",
            "unique_id_template": "{config_entry_id}_sign_conventions_verified",
            "default_entity_id": "binary_sensor.home_energy_sign_conventions_verified",
            "name": "Sign Conventions Verified",
            "translation_key": None,
            "unit": None,
            "device_class": None,
            "state_class": None,
            "entity_category": "diagnostic",
            "enabled_by_default": True,
        }
    )
    records.sort(key=lambda item: (item["platform"], item["key"]))
    return {
        "schema_version": 1,
        "release_baseline": "0.12.26",
        "entity_count": len(records),
        "entities": records,
    }


def rendered_contract() -> str:
    return json.dumps(build_entity_contract(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_contract()
    if args.write:
        BASELINE_PATH.write_text(rendered, encoding="utf-8")
    if args.check:
        if not BASELINE_PATH.is_file() or BASELINE_PATH.read_text(encoding="utf-8") != rendered:
            raise SystemExit(
                "Entity contract changed; review the compatibility impact and regenerate explicitly"
            )
    if not args.write and not args.check:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
