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

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "maintainability"
    / "config-field-contract-v0.12.26.json"
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
    if class_name == "Coerce":
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
    records: list[dict[str, Any]] = []
    for page, expected_keys in flow._PAGE_FIELDS.items():  # noqa: SLF001
        schema = flow._page_schema(page, defaults)  # noqa: SLF001
        actual_keys = tuple(marker.schema for marker in schema.schema)
        if actual_keys != tuple(expected_keys):
            raise ValueError(f"page schema order drifted for {page!r}")
        for order, (marker, validator) in enumerate(schema.schema.items(), start=1):
            has_default, default = _default(marker)
            input_kind, selector_config = _input_contract(validator)
            records.append(
                {
                    "key": marker.schema,
                    "page": page,
                    "order": order,
                    "required": isinstance(marker, vol.Required),
                    "has_default": has_default,
                    "default": default,
                    "input_kind": input_kind,
                    "input_config": selector_config,
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
                "Configuration field contract changed; review compatibility and regenerate"
            )
    if not args.write and not args.check:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
