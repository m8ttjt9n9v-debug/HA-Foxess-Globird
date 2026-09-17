"""Contract tests for catalogue-driven human configuration pages."""

from __future__ import annotations

import json

import voluptuous as vol

from custom_components.home_energy_orchestrator.config_page_schema import (
    build_page_schema,
)
from custom_components.home_energy_orchestrator.field_catalogue import (
    FIELD_KEYS_BY_PAGE,
)
from scripts.config_field_contract import BASELINE_PATH, _default, _input_contract


def test_catalogue_pages_exactly_reproduce_frozen_field_contract() -> None:
    contract = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    expected_by_page: dict[str, list[dict[str, object]]] = {}
    for field in contract["fields"]:
        expected_by_page.setdefault(str(field["page"]), []).append(field)

    for page, expected_fields in expected_by_page.items():
        schema = build_page_schema(page, {})
        assert tuple(marker.schema for marker in schema.schema) == tuple(
            FIELD_KEYS_BY_PAGE[page]
        )
        for (marker, validator), expected in zip(
            schema.schema.items(), expected_fields, strict=True
        ):
            has_default, default = _default(marker)
            input_kind, input_config = _input_contract(validator)
            assert isinstance(marker, vol.Required) is expected["required"]
            assert has_default is expected["has_default"]
            assert default == expected["default"]
            assert input_kind == expected["input_kind"]
            assert input_config == expected["input_config"]


def test_catalogue_pages_preserve_dynamic_display_default_rules() -> None:
    battery = build_page_schema(
        "battery",
        {
            "battery_capacity_kwh": 0,
            "battery_power_entity": "",
            "battery_floor_percent": 17,
        },
    )
    markers = {marker.schema: marker for marker in battery.schema}
    assert markers["battery_capacity_kwh"].default() == 0
    assert markers["battery_power_entity"].default is vol.UNDEFINED
    assert markers["battery_floor_percent"].default() == 17

    site = build_page_schema("site", {"configure_solar": 1, "configure_ev": 0})
    site_markers = {marker.schema: marker for marker in site.schema}
    assert site_markers["configure_solar"].default() is True
    assert site_markers["configure_ev"].default() is False


def test_catalogue_number_validators_preserve_float_and_integer_coercion() -> None:
    battery = build_page_schema("battery", {})
    battery_capacity = next(
        validator
        for marker, validator in battery.schema.items()
        if marker.schema == "battery_capacity_kwh"
    )
    assert battery_capacity("12.5") == 12.5

    policies = build_page_schema("ev_policies", {})
    minimum_samples = next(
        validator
        for marker, validator in policies.schema.items()
        if marker.schema == "ev_learning_minimum_samples"
    )
    assert minimum_samples("14") == 14
