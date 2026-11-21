"""Build human configuration pages from the immutable field catalogue."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from math import isfinite
from typing import Any

import voluptuous as vol
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .configuration import valid_ev_reservation_unplugged_soc_max_age_minutes
from .const import (
    CONF_EV_BEFORE_EXPORT_IMPORT_CONFIRM_SECONDS,
    CONF_EV_BEFORE_EXPORT_SOC_BUFFER,
    CONF_EV_CAPACITY_FALLBACK_KWH,
    CONF_EV_RESERVATION_SOC_MAX_AGE_HOURS,
    CONF_EV_RESERVATION_UNPLUGGED_SOC_MAX_AGE_MINUTES,
    CONF_EV_SOLAR_SOAK_ADJUSTMENT_MINUTES,
    CONF_EV_SOLAR_SOAK_AVERAGE_MINUTES,
    CONF_EV_SOLAR_SOAK_BATTERY_SOC,
    CONF_EV_SOLAR_SOAK_MAX_ENABLED,
    CONF_EV_SOLAR_SOAK_START_SOC,
    CONF_EV_SOLAR_SOAK_STOP_SOC,
    CONF_EV_SURPLUS_REARM_ENERGY,
)
from .field_catalogue import FIELD_KEYS_BY_PAGE, FIELD_SPECS_BY_KEY, FieldSpec


class CapacityCoerce(vol.Coerce):
    """Keep numeric UI semantics without accepting booleans as capacity."""

    def __init__(self) -> None:
        super().__init__(float)

    def __call__(self, value: Any) -> float:
        if isinstance(value, bool):
            raise vol.Invalid("Capacity must be a number, not boolean")
        try:
            result = super().__call__(value)
        except OverflowError as error:
            raise vol.Invalid("Capacity is too large") from error
        if not isfinite(result) or not 0 <= result <= 1000:
            raise vol.Invalid("Capacity must be finite and between 0 and 1000 kWh")
        return result


class WholeMinuteSelector(selector.NumberSelector):
    """Keep the numeric UI without coercing invalid planning durations."""

    def __call__(self, data: Any) -> float:
        if not valid_ev_reservation_unplugged_soc_max_age_minutes(data):
            raise vol.Invalid("Use a whole number of minutes from 0 to 1440")
        return super().__call__(data)


GRID_PHASE_SECTIONS: dict[str, tuple[str, str]] = {
    phase: (
        f"site_grid_phase_{phase[-1]}_power_entity",
        f"site_grid_phase_{phase[-1]}_voltage_entity",
    )
    for phase in ("phase_r", "phase_s", "phase_t")
}
_GRID_SECTION_BY_POWER = {
    keys[0]: name for name, keys in GRID_PHASE_SECTIONS.items()
}
_GRID_SECTION_KEYS = {key for keys in GRID_PHASE_SECTIONS.values() for key in keys}
SOLAR_SOAK_SECTION = {
    "solar_soak": (
        CONF_EV_SOLAR_SOAK_BATTERY_SOC,
        CONF_EV_SOLAR_SOAK_AVERAGE_MINUTES,
        CONF_EV_SOLAR_SOAK_ADJUSTMENT_MINUTES,
    ),
    "solar_soak_max": (
        CONF_EV_SOLAR_SOAK_MAX_ENABLED,
        CONF_EV_SOLAR_SOAK_START_SOC,
        CONF_EV_SOLAR_SOAK_STOP_SOC,
    ),
}
_SOLAR_SOAK_SECTION_KEYS = {key for keys in SOLAR_SOAK_SECTION.values() for key in keys}


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
        # A voluptuous default silently re-inserts the old value when the user
        # clears an optional field.  HA's suggested_value pre-fills the UI
        # without turning an omitted selector into a saved mapping.
        return vol.Optional(spec.key, description={"suggested_value": value})
    return vol.Optional(spec.key)


def _validator(spec: FieldSpec) -> Any:
    """Recreate the frozen Home Assistant selector or numeric coercion."""
    config = (
        None
        if spec.selector_config_json is None
        else json.loads(spec.selector_config_json)
    )
    if spec.selector_kind == "number":
        if spec.key == CONF_EV_RESERVATION_UNPLUGGED_SOC_MAX_AGE_MINUTES:
            return WholeMinuteSelector(selector.NumberSelectorConfig(**config))
        if (spec.key in _SOLAR_SOAK_SECTION_KEYS
                or spec.key in {CONF_EV_BEFORE_EXPORT_SOC_BUFFER,
                                CONF_EV_BEFORE_EXPORT_IMPORT_CONFIRM_SECONDS,
                                CONF_EV_RESERVATION_SOC_MAX_AGE_HOURS,
                                CONF_EV_SURPLUS_REARM_ENERGY}):
            return selector.NumberSelector(selector.NumberSelectorConfig(**config))
        if spec.key == CONF_EV_CAPACITY_FALLBACK_KWH:
            return CapacityCoerce()
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
    """Return one ordered page, grouping matched grid phases for operators."""
    fields: dict[vol.Marker, Any] = {}
    for key in FIELD_KEYS_BY_PAGE[page]:
        if page == "ev_policies" and key in _SOLAR_SOAK_SECTION_KEYS:
            name, keys = next((name, keys) for name, keys in SOLAR_SOAK_SECTION.items()
                              if key in keys)
            if key == keys[0]:
                fields[vol.Required(name)] = section(
                    vol.Schema({
                        _marker(FIELD_SPECS_BY_KEY[item], defaults): _validator(
                            FIELD_SPECS_BY_KEY[item]
                        )
                        for item in keys
                    }),
                    {"collapsed": False},
                )
            continue
        if page == "grid" and key in _GRID_SECTION_KEYS:
            phase = _GRID_SECTION_BY_POWER.get(key)
            if phase is not None:
                fields[vol.Required(phase)] = section(
                    vol.Schema(
                        {
                            _marker(FIELD_SPECS_BY_KEY[phase_key], defaults): _validator(
                                FIELD_SPECS_BY_KEY[phase_key]
                            )
                            for phase_key in GRID_PHASE_SECTIONS[phase]
                        }
                    ),
                    {"collapsed": False},
                )
            continue
        fields[_marker(FIELD_SPECS_BY_KEY[key], defaults)] = _validator(
            FIELD_SPECS_BY_KEY[key]
        )
    return vol.Schema(fields)


def iter_page_schema_fields(schema: vol.Schema) -> Iterator[tuple[vol.Marker, Any]]:
    """Yield real fields in display order, including those inside sections."""
    for marker, validator in schema.schema.items():
        if isinstance(validator, section):
            yield from validator.schema.schema.items()
        else:
            yield marker, validator
