"""Separate append-only contracts for optional host/Fleet maintenance.

These five dynamic patterns are not replacements or additions to the retained
canonical EntitySpec catalogue. Their actual native entity constructors, status
serializers and private journal decoder are checked against a reviewed contract.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator import maintenance as node_module
from custom_components.home_energy_orchestrator import maintenance_adapter as adapter
from custom_components.home_energy_orchestrator import maintenance_entities as entities
from custom_components.home_energy_orchestrator.fleet_maintenance import (
    _PHASES,
    FleetMaintenanceHub,
    _sanitize,
)
from custom_components.home_energy_orchestrator.maintenance import NodeMaintenance, _decode
from custom_components.home_energy_orchestrator.maintenance_barrier import KEY as FENCE_KEY
from scripts.entity_attribute_contract import (
    validate_against_release_baseline as validate_attributes,
)
from scripts.entity_contract import build_entity_contract
from scripts.entity_contract import validate_against_release_baseline as validate_entities

CONTRACT = json.loads((
    Path(__file__).resolve().parents[1]
    / "docs" / "maintainability" / "maintenance-entities-v1.json"
).read_text(encoding="utf-8"))


def _record(**changes):
    return {
        "v": 1,
        "request_id": str(uuid4()),
        "action": "update_and_restart",
        "version": "v0.12.40",
        "issued_at": "2026-10-17T00:00:00+00:00",
        "expires_at": "2026-10-17T01:00:00+00:00",
        "boot_id": uuid4().hex,
        "settings_digest": "a" * 64,
        "phase": "waiting",
        "backup_id": None,
        "error": None,
    } | changes


def test_existing_canonical_entity_and_attribute_contracts_are_unchanged():
    validate_entities()
    validate_attributes()
    canonical = build_entity_contract()
    assert canonical["entity_count"] == 124
    assert not any(
        record["key"] == "maintenance" or record["key"].startswith("fleet_")
        for record in canonical["entities"]
        if record["key"] != "fleet_summary"
    )


def test_all_five_patterns_match_actual_native_entity_constructors(hass):
    entry = MockConfigEntry(domain="home_energy_orchestrator", entry_id="contract-entry")
    target = {"key": "site_key", "name": "Configured site", "local": True}
    node = NodeMaintenance(hass, "0.12.40")
    hub = FleetMaintenanceHub(hass, [target])
    native = [
        entities.MaintenanceStatus(node, entry),
        entities.MaintenanceStatus(hub, entry, target),
        entities.MaintenanceVersion(hub, entry, target),
        entities.MaintenanceButton(hub, entry, target, "update_and_restart"),
        entities.MaintenanceButton(hub, entry, target, "restart"),
    ]
    assert CONTRACT["schema_version"] == 1
    assert CONTRACT["entity_pattern_count"] == len(native) == 5
    for actual, expected in zip(native, CONTRACT["entity_patterns"], strict=True):
        substitutions = {"config_entry_id": entry.entry_id, "site_key": target["key"]}
        assert type(actual).__name__ == expected["class"]
        assert actual.entity_id.split(".", 1)[0] == expected["platform"]
        assert actual.unique_id == expected["unique_id_template"].format(**substitutions)
        assert actual.entity_id == expected["default_entity_id_template"].format(**substitutions)
        assert actual.unique_id == f"{entry.entry_id}_" + expected["key_template"].format(
            **substitutions
        )
        assert actual.entity_registry_enabled_default is True
    assert hub.selected_versions == {} and node.record is None


async def test_node_public_status_attributes_match_reviewed_contract(hass, monkeypatch):
    monkeypatch.setattr(adapter, "async_hacs_catalog", AsyncMock(return_value={
        "installed_version": "v0.12.39", "versions": ["v0.12.40"], "in_progress": False,
    }))
    node = NodeMaintenance(hass, "0.12.39")
    await node.async_restore()
    status = await node.async_status()
    assert sorted(status) == CONTRACT["node_status_attributes"]
    node.async_set_updated_data(status)
    entry = MockConfigEntry(domain="home_energy_orchestrator")
    entity = entities.MaintenanceStatus(node, entry)
    assert entity.extra_state_attributes == status
    assert entity.native_value == "idle"
    assert node.record is None and FENCE_KEY not in hass.data


def test_fleet_public_key_whitelist_is_exhaustive_and_excludes_provider_details():
    payload = {
        "schema_version": 1, "phase": "waiting", "available_versions": ["v0.12.40"],
        "blockers": [], "running_version": "v0.12.39", "installed_version": "v0.12.39",
        "expected_version": "v0.12.40", "request_id": str(uuid4()), "accepted": True,
        "restart_pending": False, "busy": False, "backup_verified": True,
        "issued_at": "2026-10-17T00:00:00+00:00", "last_update": "2026-10-17T00:00:00+00:00",
        "started_at": "2026-10-17T00:00:00+00:00", "deadline": "2026-10-17T01:00:00+00:00",
        "action": "update_and_restart", "error": "hacs_unavailable",
        "token": "private-provider-secret", "origin": "private-provider-origin",
        "provider_exception": "private-provider-exception", "backup_id": "private-node-backup",
    }
    result = _sanitize(payload)
    assert sorted(result) == CONTRACT["fleet_status_allowed_attributes"]
    assert not any("private-" in str(value) for value in result.values())
    assert sorted(_PHASES) == CONTRACT["fleet_accepted_node_phases"]
    assert sorted(node_module.PHASES) == CONTRACT["node_journal_phases"]


def test_journal_schema_requires_exact_fields_and_known_phase():
    valid = _record()
    assert sorted(valid) == CONTRACT["node_journal_fields"]
    assert _decode(valid) == valid
    assert _decode(None) is None
    for field in valid:
        missing = deepcopy(valid)
        missing.pop(field)
        with pytest.raises((ValueError, TypeError, KeyError)):
            _decode(missing)
    with pytest.raises(ValueError):
        _decode(valid | {"unexpected_field": "private-value"})
    with pytest.raises(ValueError):
        _decode(valid | {"phase": "unreviewed_install_phase"})


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("v", 2), ("v", True), ("request_id", "not-a-uuid"), ("action", "arbitrary_service"),
        ("issued_at", "2026-10-17T00:00:00"), ("expires_at", "not-a-time"),
        ("expires_at", "2026-10-16T23:00:00+00:00"),
        ("boot_id", ""), ("boot_id", "not-a-process-uuid"),
        ("settings_digest", "a" * 63), ("settings_digest", "g" * 64),
        ("version", "not-a-version"), ("version", None),
        ("backup_id", 42), ("backup_id", "../private/archive"),
        ("error", {"private": "provider-output"}), ("error", "unreviewed_provider_error"),
    ],
)
def test_malformed_journal_fields_do_not_relax_the_private_schema(field, invalid):
    with pytest.raises((ValueError, TypeError, KeyError)):
        _decode(_record(**{field: invalid}))


@pytest.mark.parametrize("corrupt", ["phase", "schema", "extra_field"])
async def test_invalid_restored_journal_stays_untouched_and_never_replays(
    hass, monkeypatch, corrupt,
):
    payload = _record()
    if corrupt == "phase":
        payload["phase"] = "unreviewed_install_phase"
    elif corrupt == "schema":
        payload["v"] = 99
    else:
        payload["private_provider_field"] = "must-not-be-exposed"
    node = NodeMaintenance(hass, "0.12.39")
    await node._repository.store.async_save(payload)
    operations = [AsyncMock() for _ in range(3)]
    for name, method in zip(
        ("async_install", "async_create_verified_backup", "async_request_restart"),
        operations, strict=True,
    ):
        monkeypatch.setattr(adapter, name, method)
    await node.async_restore()
    assert node.record is None
    assert node._trusted is False
    assert node._task is None and FENCE_KEY not in hass.data
    assert await node._repository.store.async_load() == payload
    status = await node.async_status()
    assert status["phase"] == "idle"
    assert "maintenance_storage_unavailable" in status["blockers"]
    assert "must-not-be-exposed" not in str(status)
    for operation in operations:
        operation.assert_not_called()


@pytest.mark.parametrize("phase", sorted(node_module.IN_PROGRESS))
async def test_valid_unfinished_audit_restore_is_not_an_instruction_to_resume(
    hass, monkeypatch, phase,
):
    node = NodeMaintenance(hass, "0.12.39")
    await node._repository.store.async_save(_record(phase=phase))
    operations = [AsyncMock() for _ in range(3)]
    for name, method in zip(
        ("async_install", "async_create_verified_backup", "async_request_restart"),
        operations, strict=True,
    ):
        monkeypatch.setattr(adapter, name, method)
    await node.async_restore()
    assert node._trusted is True
    assert node.record["phase"] == ("restart_requested" if phase == "restart_requested"
                                    else "interrupted")
    assert node._task is None and FENCE_KEY not in hass.data
    for operation in operations:
        operation.assert_not_called()


async def test_interrupted_audit_checkpoint_failure_is_not_an_heo_setup_failure(hass, monkeypatch):
    node = NodeMaintenance(hass, "0.12.39")
    await node._repository.store.async_save(_record(phase="backing_up"))
    monkeypatch.setattr(
        node._repository.store, "async_save", AsyncMock(side_effect=OSError("private-path"))
    )
    await node.async_restore()
    assert node._trusted is False
    assert node.record["phase"] == "interrupted"
    assert node._task is None and FENCE_KEY not in hass.data
    status = await node.async_status()
    assert "maintenance_storage_unavailable" in status["blockers"]
    assert "private-path" not in str(status)
