"""Generate the immutable v0.12.26 configuration-field UI contract."""

from __future__ import annotations

import argparse
import json
from datetime import time
from enum import Enum
from pathlib import Path
from typing import Any

import voluptuous as vol

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.config_page_schema import (
    iter_page_schema_fields,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "maintainability"
    / "config-field-contract-v0.12.26.json"
)
TRANSLATION_PATH = (
    REPOSITORY_ROOT
    / "custom_components"
    / "home_energy_orchestrator"
    / "translations"
    / "en.json"
)
ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-field-additions-price-export-v1.json"
)
CAPACITY_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-field-additions-ev-capacity-v1.json"
)
AMBER_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-field-additions-amber-price-v1.json"
)
LOAD_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-field-additions-load-power-v1.json"
)
SOLAR_SOAK_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs" / "maintainability" / "config-field-additions-solar-soak-v1.json"
)
EV_EXPORT_BUFFER_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs/maintainability/config-field-additions-ev-export-buffer-v1.json"
)
EV_LOCAL_CONNECTION_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs/maintainability/config-field-additions-ev-local-connection-v1.json"
)
EV_IMPORT_ADDITIONS_PATH = (
    REPOSITORY_ROOT / "docs/maintainability/config-field-additions-ev-import-v1.json"
)


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _default(marker: vol.Marker) -> tuple[bool, Any]:
    if marker.default is vol.UNDEFINED:
        return False, None
    value = marker.default() if callable(marker.default) else marker.default
    return True, _json_value(value)


def _input_contract(validator: Any) -> tuple[str, dict[str, Any] | None]:
    class_name = type(validator).__name__
    if isinstance(validator, vol.Coerce):
        coerced_type = getattr(validator, "type", None)
        return "number", {"coerce": getattr(coerced_type, "__name__", str(coerced_type))}
    if not class_name.endswith("Selector"):
        raise ValueError(f"unsupported configuration validator {class_name!r}")
    input_kind = class_name.removesuffix("Selector")
    input_kind = "".join(
        (f"_{character.lower()}" if character.isupper() else character)
        for character in input_kind
    ).lstrip("_")
    config = getattr(validator, "config", None)
    return input_kind, _json_value(config) if config else None


def build_config_field_contract() -> dict[str, Any]:
    """Return each actual wizard page field in display order."""
    flow = ConfigFlow()
    defaults = flow._apply_defaults({})  # noqa: SLF001
    translations = json.loads(TRANSLATION_PATH.read_text(encoding="utf-8"))["config"][
        "step"
    ]
    setup_labels = translations["user"]["data"]
    reconfigure_labels = translations["reconfigure"]["data"]
    records: list[dict[str, Any]] = []
    for page, expected_keys in flow._PAGE_FIELDS.items():  # noqa: SLF001
        schema = flow._page_schema(page, defaults)  # noqa: SLF001
        page_fields = tuple(iter_page_schema_fields(schema))
        actual_keys = tuple(marker.schema for marker, _ in page_fields)
        if actual_keys != tuple(expected_keys):
            raise ValueError(f"page schema order drifted for {page!r}")
        for order, (marker, validator) in enumerate(page_fields, start=1):
            has_default, default = _default(marker)
            input_kind, selector_config = _input_contract(validator)
            key = marker.schema
            if key not in setup_labels or key not in reconfigure_labels:
                raise ValueError(f"configuration label is missing for {key!r}")
            records.append(
                {
                    "key": key,
                    "page": page,
                    "order": order,
                    "required": isinstance(marker, vol.Required),
                    "has_default": has_default,
                    "default": default,
                    "input_kind": input_kind,
                    "input_config": selector_config,
                    "setup_label": setup_labels[key],
                    "reconfigure_label": reconfigure_labels[key],
                }
            )
    return {
        "schema_version": 1,
        "release_baseline": "0.12.26",
        "config_entry_version": flow.VERSION,
        "field_count": len(records),
        "fields": records,
    }


def rendered_contract() -> str:
    return json.dumps(build_config_field_contract(), indent=2, sort_keys=True) + "\n"


def validate_against_release_baseline() -> None:
    """Preserve frozen field records and admit only reviewed additional fields."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    extensions = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (
            ADDITIONS_PATH, CAPACITY_ADDITIONS_PATH, AMBER_ADDITIONS_PATH, LOAD_ADDITIONS_PATH,
            SOLAR_SOAK_ADDITIONS_PATH,
            EV_EXPORT_BUFFER_ADDITIONS_PATH,
            EV_LOCAL_CONNECTION_ADDITIONS_PATH,
            EV_IMPORT_ADDITIONS_PATH,
        )
    ]
    extension = {"schema_version": baseline["schema_version"], "fields": []}
    for addition in extensions:
        if addition.get("schema_version") != baseline["schema_version"]:
            raise ValueError("field addition schema does not match the baseline")
        if addition.get("field_count") != len(addition["fields"]):
            raise ValueError("field addition count does not match its records")
        extension["fields"].extend(addition["fields"])
    extension["field_count"] = len(extension["fields"])
    if extension.get("schema_version") != baseline["schema_version"]:
        raise ValueError("field addition schema does not match the baseline")
    if extension.get("field_count") != len(extension["fields"]):
        raise ValueError("field addition count does not match its records")
    retained = {field["key"]: field for field in baseline["fields"]}
    added = {field["key"]: field for field in extension["fields"]}
    if len(added) != len(extension["fields"]) or retained.keys() & added.keys():
        raise ValueError("field additions cannot replace frozen fields")
    current = build_config_field_contract()
    actual = {field["key"]: field for field in current["fields"]}
    if current["config_entry_version"] != baseline["config_entry_version"]:
        raise ValueError("configuration entry version changed")
    if current["field_count"] != baseline["field_count"] + len(added):
        raise ValueError("field count differs from baseline plus reviewed additions")
    expected = retained | added
    if actual.keys() != expected.keys():
        raise ValueError("configuration field identities changed beyond reviewed additions")
    for key, record in expected.items():
        if actual[key] != record:
            raise ValueError(f"configuration field changed beyond reviewed additions: {key}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_contract()
    if args.write:
        parser.error("The release field baseline is frozen; review additions separately")
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
