"""Append-only market surfaces and legacy export journal compatibility."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from custom_components.home_energy_orchestrator.planner.export_session import ExportSessionState
from scripts.config_contract import (
    ADDITIVE_CONFIG_KEYS,
    AEMO_CONFIG_KEYS,
    AMBER_CONFIG_KEYS,
    EV_CAPACITY_CONFIG_KEYS,
    EV_EXPORT_BUFFER_CONFIG_KEYS,
    LOAD_CONFIG_KEYS,
    PRICE_EXPORT_CONFIG_KEYS,
    SOLAR_SOAK_CONFIG_KEYS,
    build_config_contract,
)
from scripts.entity_contract import (
    TRIP_ADDITIONS_PATH,
    build_entity_contract,
    validate_against_release_baseline,
)

ROOT = Path(__file__).resolve().parents[1]


def test_price_export_adds_only_five_reviewed_configuration_keys() -> None:
    extension = json.loads(
        (ROOT / "docs/maintainability/config-additions-price-export-v1.json").read_text()
    )
    historical = build_config_contract()
    current = build_config_contract(include_extensions=True)
    price_keys = AEMO_CONFIG_KEYS | PRICE_EXPORT_CONFIG_KEYS
    assert (
        set(extension["additional_config_keys"])
        == price_keys
        == {
            "aemo_export_threshold_per_kwh",
            "aemo_import_threshold_per_kwh",
            "aemo_monitor_enabled",
            "aemo_region",
            "critical_event_sell_enabled",
        }
    )
    assert current["config_entry_version"] == historical["config_entry_version"] == 6
    assert (
        (set(current["declared_config_keys"]) - set(historical["declared_config_keys"]))
        - EV_CAPACITY_CONFIG_KEYS
        - AMBER_CONFIG_KEYS
        - LOAD_CONFIG_KEYS
        - SOLAR_SOAK_CONFIG_KEYS
        - EV_EXPORT_BUFFER_CONFIG_KEYS
        == (price_keys)
    )
    assert (
        current["page_field_count"]
        - len(EV_CAPACITY_CONFIG_KEYS)
        - len(AMBER_CONFIG_KEYS)
        - len(LOAD_CONFIG_KEYS)
        - len(SOLAR_SOAK_CONFIG_KEYS)
        - len(EV_EXPORT_BUFFER_CONFIG_KEYS)
        == historical["page_field_count"] + 5
    )


def test_capacity_configuration_is_a_separate_three_key_addition() -> None:
    extension = json.loads(
        (ROOT / "docs/maintainability/config-additions-ev-capacity-v1.json").read_text()
    )
    historical = build_config_contract()
    current = build_config_contract(include_extensions=True)
    assert (
        set(extension["additional_config_keys"])
        == EV_CAPACITY_CONFIG_KEYS
        == {
            "ev_capacity_source",
            "ev_capacity_entity",
            "ev_capacity_fallback_kwh",
        }
    )
    price_keys = AEMO_CONFIG_KEYS | PRICE_EXPORT_CONFIG_KEYS
    assert not (EV_CAPACITY_CONFIG_KEYS & price_keys)
    assert ADDITIVE_CONFIG_KEYS == (
        price_keys
        | EV_CAPACITY_CONFIG_KEYS
        | AMBER_CONFIG_KEYS
        | LOAD_CONFIG_KEYS
        | SOLAR_SOAK_CONFIG_KEYS
        | EV_EXPORT_BUFFER_CONFIG_KEYS
    )
    assert (
        set(current["declared_config_keys"]) - set(historical["declared_config_keys"])
        == ADDITIVE_CONFIG_KEYS
    )
    assert historical["page_field_count"] == 135
    assert current["page_field_count"] == 135 + 5 + 3 + 2 + 1 + 3 + 1


def test_price_export_admits_only_monitor_and_one_automatic_request() -> None:
    validate_against_release_baseline()
    baseline = json.loads((ROOT / "docs/maintainability/entity-contract-v0.12.26.json").read_text())
    old = {(record["platform"], record["key"]) for record in baseline["entities"]}
    trip = json.loads(TRIP_ADDITIONS_PATH.read_text())
    trip_ids = {(record["platform"], record["key"]) for record in trip["entities"]}
    assert trip_ids == {
        ("datetime", "trip_ready_by"),
        ("select", "trip_target_soc"),
        ("switch", "trip_charge_scheduled"),
        ("number", "trip_extra_minutes"),
        ("sensor", "trip_charge_status"),
        ("sensor", "trip_charge_planned_start"),
        ("sensor", "trip_charge_duration"),
    }
    new = {
        (record["platform"], record["key"]) for record in build_entity_contract()["entities"]
    } - old
    load_ids = {("sensor", "ev_charging_power"), ("sensor", "house_load_excluding_ev")}
    solar_soak_ids = {
        ("number", "ev_solar_soak_battery_soc"),
        ("number", "ev_solar_soak_average_minutes"),
        ("number", "ev_solar_soak_adjustment_minutes"),
    }
    assert new - trip_ids - load_ids - solar_soak_ids - {
        ("number", "ev_before_export_soc_buffer")
    } == {
        ("sensor", "aemo_market_status"),
        ("sensor", "aemo_spot_price"),
        ("switch", "aemo_monitor"),
        ("select", "aemo_region"),
        ("number", "aemo_export_threshold"),
        ("number", "aemo_import_threshold"),
        ("button", "aemo_clear_import_threshold"),
        ("switch", "critical_event_sell"),
    }


def test_legacy_export_journal_keeps_exact_four_field_payload() -> None:
    record = json.loads(
        (
            ROOT / "docs/maintainability/export-session-payload-additions-price-export-v1.json"
        ).read_text()
    )
    payload = {
        "phase": "active",
        "requested_power_kw": 4.0,
        "attempts": 1,
        "last_command_at": "2026-01-01T01:00:00+00:00",
    }
    restored = ExportSessionState.from_payload(payload)
    assert set(payload) == set(record["retained_fields"])
    assert restored.authority_source == record["legacy_defaults"]["authority_source"]
    assert restored.price_deadline is None
    assert restored.to_payload() == payload


def test_price_export_uses_existing_journal_with_three_explicit_fields() -> None:
    deadline = datetime(2026, 1, 1, 1, 5, tzinfo=UTC)
    state = ExportSessionState(
        phase="active",
        requested_power_kw=4.0,
        attempts=1,
        authority_source="price",
        price_deadline=deadline,
        price_actuator_entities=(
            "select.battery_work_mode",
            "number.force_charge",
            "number.force_discharge",
        ),
    )
    record = json.loads(
        (
            ROOT / "docs/maintainability/export-session-payload-additions-price-export-v1.json"
        ).read_text()
    )
    payload = state.to_payload()
    assert set(payload) == set(record["retained_fields"] + record["additional_fields"])
    assert payload["price_deadline"] == deadline.isoformat()
    assert payload["price_actuator_entities"] == list(state.price_actuator_entities)
    assert ExportSessionState.from_payload(payload) == state


def test_grace_adds_only_optional_price_permission_boundary() -> None:
    record = json.loads(
        (
            ROOT / "docs/maintainability/export-session-payload-additions-price-grace-v1.json"
        ).read_text()
    )
    assert record["additional_optional_fields"] == ["price_permission_end"]
    assert record["ordinary_zerohero_payload_unchanged"]
    assert record["new_store_required"] is False
    end = datetime(2026, 1, 1, 1, 7, 30, tzinfo=UTC)
    state = ExportSessionState(
        phase="active",
        requested_power_kw=4,
        authority_source="price",
        price_deadline=end,
        price_actuator_entities=("select.mode", "number.charge", "number.discharge"),
        price_permission_end=end,
    )
    payload = state.to_payload()
    assert payload.pop("price_permission_end") == end.isoformat()
    legacy = ExportSessionState.from_payload(payload)
    assert legacy.price_permission_end is None
    assert legacy.to_payload() == payload
    assert ExportSessionState.from_payload(state.to_payload()) == state
