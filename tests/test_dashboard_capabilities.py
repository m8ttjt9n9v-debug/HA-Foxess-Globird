"""Capability, meaning and explicit-action checks for the shared dashboard."""

from __future__ import annotations

import re

from scripts.dashboard_contract import attribute_references, entity_references, load_dashboard, walk
from scripts.entity_attribute_contract import build_entity_attribute_contract
from scripts.entity_contract import build_entity_contract


def _view(path: str) -> dict:
    return next(view for view in load_dashboard()["views"] if view["path"] == path)


def _objects(value: object) -> list[dict]:
    return [item for item in walk(value) if isinstance(item, dict)]


def _markdown(value: object) -> str:
    return " ".join(item["content"] for item in _objects(value) if item.get("type") == "markdown")


def _section(path: str, heading: str) -> dict:
    return next(
        section
        for section in _view(path)["sections"]
        if any(card.get("heading") == heading for card in section["cards"])
    )


def test_capability_references_use_current_public_entity_and_attribute_contracts() -> None:
    dashboard = load_dashboard()
    entities = {item["default_entity_id"] for item in build_entity_contract()["entities"]}
    attributes = {
        item["default_entity_id"]: set(item["custom_attributes"])
        for item in build_entity_attribute_contract()["entities"]
    }
    assert entity_references(dashboard) <= entities
    assert all(
        attribute in attributes.get(entity, set())
        for entity, attribute in attribute_references(dashboard)
    )


def test_overview_distinguishes_forecast_measured_cost_and_dated_scorecard() -> None:
    objects = _objects(_view("overview"))
    names = {item.get("entity"): item.get("name") for item in objects if item.get("type") == "tile"}
    assert names["sensor.home_energy_estimated_net_cost"] == "Forecast net cost today"
    assert names["sensor.home_energy_measured_net_cost"] == "Measured net cost so far"
    scorecard = _section("overview", "Latest Matched Daily Scorecard")
    assert ("sensor.home_energy_forecast_scorecard_status", "result_date") in attribute_references(
        scorecard
    )
    assert "older than yesterday" in _markdown(scorecard)
    for item in _objects(scorecard):
        if item.get("entity", "").endswith(("_yesterday_cost", "_error_yesterday")):
            assert "Matched-day" in item["name"]
    assert "settled bill" in _markdown(_view("overview"))


def test_overview_operating_mode_is_read_only() -> None:
    overview = _view("overview")
    assert ("sensor.home_energy_status", "mode") in attribute_references(overview)
    assert all(
        item.get("entity", "").startswith(("sensor.", "binary_sensor."))
        for item in _objects(overview)
        if "entity" in item
    )
    assert not any("service" in item or "perform_action" in item for item in _objects(overview))


def test_entities_cards_never_expose_an_implicit_header_master_toggle() -> None:
    cards = [item for item in _objects(load_dashboard()) if item.get("type") == "entities"]
    assert cards
    assert all(card.get("show_header_toggle") is False for card in cards)


def test_device_requests_exist_only_in_confirmed_button_tap_actions() -> None:
    objects = _objects(load_dashboard())
    buttons = [item for item in objects if item.get("type") == "button"]
    actions = [item for item in objects if "service" in item or "perform_action" in item]
    assert len(actions) == 6
    allowed = {
        "button.press",
        "home_energy_orchestrator.manual_export_max",
        "home_energy_orchestrator.manual_self_use",
        "home_energy_orchestrator.manual_resume_automatic",
    }
    for action in actions:
        assert any(button.get("tap_action") is action for button in buttons)
        assert action["action"] == "call-service"
        assert action["service"] in allowed
        assert action["confirmation"]["text"].strip()
    assert not any(
        set(item) & {"on_load", "trigger", "triggers", "initial", "automation", "sequence"}
        for item in objects
    )


def test_manual_controls_are_separate_acknowledged_requests_not_switch_enabling() -> None:
    cards = {
        item["tap_action"]["service"]: item
        for item in _objects(_view("manual"))
        if item.get("tap_action", {}).get("service", "").startswith("home_energy_orchestrator.")
    }
    assert set(cards) == {
        "home_energy_orchestrator.manual_export_max",
        "home_energy_orchestrator.manual_self_use",
        "home_energy_orchestrator.manual_resume_automatic",
    }
    for service, card in cards.items():
        assert card["hold_action"]["action"] == card["double_tap_action"]["action"] == "none"
        data = card["tap_action"].get("service_data", {})
        if service.endswith(("manual_export_max", "manual_resume_automatic")):
            assert data == {"local_control_confirmed": True}
            assert (
                "competing inverter writers are disabled"
                in card["tap_action"]["confirmation"]["text"]
            )
        else:
            assert not data
    assert (
        "unchanged"
        in cards["home_energy_orchestrator.manual_resume_automatic"]["tap_action"]["confirmation"][
            "text"
        ]
    )
    assert "entry_id" in _markdown(_view("manual"))


def test_manual_feedback_exposes_hold_source_deadline_and_cleanup() -> None:
    attributes = {
        attribute
        for entity, attribute in attribute_references(_view("manual"))
        if entity == "sensor.home_energy_status"
    }
    assert {
        "manual_inverter_hold",
        "manual_inverter_target",
        "manual_inverter_status",
        "manual_inverter_power_kw",
        "manual_inverter_command_confirmed",
        "export_authority_source",
        "export_price_deadline",
        "export_session_phase",
        "last_control_reason",
    } <= attributes
    assert "not proof of physical grid export" in _markdown(_view("manual"))
    stop = next(
        item
        for item in _objects(_view("manual"))
        if item.get("type") == "button" and item.get("entity") == "button.home_energy_test_stop"
    )
    assert "diagnostic test" in stop["name"]
    assert "not the manual-hold Stop" in stop["tap_action"]["confirmation"]["text"]


def test_ready_by_section_retains_zero_quota_surplus_and_late_pre_free_handoff() -> None:
    tesla = _view("tesla")
    assert {
        "number.home_energy_ev_morning_solar_reserve_soc",
        "switch.home_energy_ev_morning_solar",
        "sensor.home_energy_ev_daily_backfill_status",
        "sensor.home_energy_ev_daily_backfill_remaining",
        "sensor.home_energy_ev_daily_backfill_delivered",
        "sensor.home_energy_ev_daily_backfill_planned_energy",
        "sensor.home_energy_ev_daily_backfill_shortfall",
        "sensor.home_energy_ev_daily_backfill_planned_start",
        "sensor.home_energy_ev_daily_backfill_current_target",
    } <= entity_references(tesla)
    assert "fixed allocation at zero" in _markdown(tesla)
    assert "becomes eligible again" in _markdown(tesla)
    assert "current protected budget" in _markdown(tesla)
    assert "stays suspended" not in _markdown(tesla)


def test_optional_market_panel_is_export_only_and_not_payment_confirmation() -> None:
    panel = _section("configuration", "Market Price and Automatic Export")
    references = entity_references(panel)
    assert {
        "switch.home_energy_aemo_monitor",
        "select.home_energy_aemo_region",
        "number.home_energy_aemo_export_threshold",
        "switch.home_energy_critical_event_sell",
    } <= references
    assert not any("buy" in entity or "reward" in entity for entity in references)
    assert "buying is unsupported" in _markdown(panel)
    assert "retailer event or payment" in _markdown(panel)
    assert "does not enable either request" in _markdown(panel)


def test_phase_groups_require_configured_mapping_without_site_specific_ids() -> None:
    advanced = _view("advanced")
    text = _markdown(advanced)
    for phase in "RST":
        assert f"Grid CT {phase} power" in text
        assert f"Grid {phase} voltage" in text
    assert "Never infer phase" in text
    assert ("sensor.home_energy_site_grid_current", "sources") in attribute_references(advanced)
    for item in _objects(load_dashboard()):
        if "entity" in item:
            assert ".home_energy_" in item["entity"]
    assert not re.search(
        r"\b(?:192\.168\.|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)", str(load_dashboard())
    )


def test_trip_view_uses_native_entities_and_explains_paid_override_and_cancellation() -> None:
    trip = _view("trip-charge")
    assert entity_references(trip) == {
        "datetime.home_energy_trip_ready_by",
        "select.home_energy_trip_target_soc",
        "switch.home_energy_trip_charge_scheduled",
        "sensor.home_energy_trip_charge_status",
        "sensor.home_energy_trip_charge_planned_start",
        "sensor.home_energy_trip_charge_duration",
        "number.home_energy_trip_extra_minutes",
    }
    text = _markdown(trip)
    for phrase in (
        "off by default",
        "paid grid energy",
        "exact-time",
        "Cancel",
        "normal policies",
        "Never run two trip schedulers",
    ):
        assert phrase in text
    assert not any(item.get("entity", "").startswith("input_") for item in _objects(trip))
    assert not any("service" in item for item in _objects(trip))
