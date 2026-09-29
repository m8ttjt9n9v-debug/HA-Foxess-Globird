"""Contract tests for catalogue-driven human configuration pages."""

from __future__ import annotations

import json

import voluptuous as vol
from homeassistant.data_entry_flow import section

from custom_components.home_energy_orchestrator.config_page_schema import (
    build_page_schema,
    iter_page_schema_fields,
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
        page_fields = tuple(iter_page_schema_fields(schema))
        assert tuple(marker.schema for marker, _ in page_fields) == tuple(
            FIELD_KEYS_BY_PAGE[page]
        )
        for (marker, validator), expected in zip(
            page_fields, expected_fields, strict=True
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
    assert markers["battery_capacity_kwh"].description["suggested_value"] == 0
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


def test_grid_phase_fields_are_grouped_in_visible_matching_pairs() -> None:
    grid = build_page_schema("grid", {})
    sections = {
        marker.schema: validator
        for marker, validator in grid.schema.items()
        if isinstance(validator, section)
    }
    assert tuple(sections) == ("phase_r", "phase_s", "phase_t")
    for phase in "rst":
        fields = sections[f"phase_{phase}"].schema.schema
        assert tuple(marker.schema for marker in fields) == (
            f"site_grid_phase_{phase}_power_entity",
            f"site_grid_phase_{phase}_voltage_entity",
        )
