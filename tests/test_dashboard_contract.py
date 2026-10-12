"""Contract checks for the portable example dashboard."""

from __future__ import annotations

from scripts.dashboard_contract import (
    attribute_references,
    entity_references,
    load_dashboard,
)
from scripts.entity_attribute_contract import build_entity_attribute_contract
from scripts.entity_contract import build_entity_contract


def test_dashboard_yaml_has_no_duplicate_mapping_keys() -> None:
    """Strict loading prevents silent card-field replacement."""
    load_dashboard()


def test_dashboard_references_only_contracted_heo_entities() -> None:
    """Every portable HEO entity reference must exist in the public contract."""
    contract = build_entity_contract()
    contracted = {item["default_entity_id"] for item in contract["entities"]}
    referenced = entity_references()

    assert referenced
    assert referenced <= contracted


def test_dashboard_attribute_cards_use_contracted_custom_attributes() -> None:
    """Attribute cards must not depend on undocumented HEO attributes."""
    contract = build_entity_attribute_contract()
    attributes_by_entity = {
        item["default_entity_id"]: set(item["custom_attributes"])
        for item in contract["entities"]
    }
    references = attribute_references()

    assert references
    assert not {
        (entity_id, attribute)
        for entity_id, attribute in references
        if attribute not in attributes_by_entity.get(entity_id, set())
    }


def test_market_panel_has_one_export_request_and_no_buying_or_reward_controls() -> None:
    dashboard = load_dashboard()
    configuration = next(view for view in dashboard["views"] if view["path"] == "configuration")
    panel = next(
        section for section in configuration["sections"]
        if any(
            card.get("heading") == "Market Price and Automatic Export" for card in section["cards"]
        )
    )
    references = entity_references(panel)
    assert "switch.home_energy_critical_event_sell" in references
    assert "sensor.home_energy_aemo_spot_price" in references
    assert not any(
        "buy" in entity or "credit" in entity or "limit" in entity for entity in references
    )
    assert (
        "sensor.home_energy_aemo_market_status", "interval_end"
    ) in attribute_references(panel)
