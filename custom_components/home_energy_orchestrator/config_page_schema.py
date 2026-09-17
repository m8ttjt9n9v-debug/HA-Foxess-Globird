"""Build human configuration pages from the immutable field catalogue."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.helpers import selector

from .field_catalogue import FIELD_KEYS_BY_PAGE, FIELD_SPECS_BY_KEY, FieldSpec


def _marker(spec: FieldSpec, defaults: Mapping[str, object]) -> vol.Marker:
    """Preserve the existing required, optional and displayed-default rules."""
    if spec.required:
        if spec.has_default:
            default = defaults.get(spec.key, spec.default)
            if spec.page == "site" and spec.value_type == "bool":
                default = bool(default)
            return vol.Required(spec.key, default=default)
        return vol.Required(spec.key)

    value = defaults.get(spec.key)
    if (spec.selector_kind == "number" and value is not None) or value:
        return vol.Optional(spec.key, default=value)
    return vol.Optional(spec.key)


def _validator(spec: FieldSpec) -> Any:
    """Recreate the frozen Home Assistant selector or numeric coercion."""
    config = (
        None
        if spec.selector_config_json is None
        else json.loads(spec.selector_config_json)
    )
    if spec.selector_kind == "number":
        coerced_type = {"float": float, "int": int}[config["coerce"]]
        return vol.Coerce(coerced_type)
    if spec.selector_kind == "boolean":
        return selector.BooleanSelector()
    if spec.selector_kind == "entity":
        return selector.EntitySelector(
            selector.EntitySelectorConfig(**config) if config else None
        )
    if spec.selector_kind == "select":
        return selector.SelectSelector(
            selector.SelectSelectorConfig(**config) if config else None
        )
    if spec.selector_kind == "text":
        return selector.TextSelector(
            selector.TextSelectorConfig(**config) if config else None
        )
    if spec.selector_kind == "time":
        return selector.TimeSelector()
    raise ValueError(f"unsupported field selector {spec.selector_kind!r}")


def build_page_schema(page: str, defaults: Mapping[str, object]) -> vol.Schema:
    """Return one ordered configuration page without changing its UI contract."""
    return vol.Schema(
        {
            _marker(FIELD_SPECS_BY_KEY[key], defaults): _validator(
                FIELD_SPECS_BY_KEY[key]
            )
            for key in FIELD_KEYS_BY_PAGE[page]
        }
    )
