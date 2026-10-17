"""Native integration, registry, and frontend boundaries for Fleet maintenance."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.home_energy_orchestrator import FLEET_KEY
from custom_components.home_energy_orchestrator import maintenance_adapter as adapter
from custom_components.home_energy_orchestrator.const import DOMAIN
from custom_components.home_energy_orchestrator.maintenance import NODE_KEY
from tests.test_setup import ENTRY_DATA

CATALOG = {
    "entity_id": "update.verified_heo_release",
    "installed_version": "v0.12.41",
    "versions": ["v0.12.41", "v0.12.40", "v0.12.39"],
    "in_progress": False,
}
LOCAL = {"key": "alpha", "name": "Local site", "local": True}
SERVICES = (
    "maintenance_status",
    "maintenance_update_and_restart",
    "maintenance_restart",
    "fleet_maintenance_update",
    "fleet_maintenance_restart",
    "fleet_maintenance_refresh",
)


@pytest.mark.parametrize("sites", [
    [{"key": "alpha", "name": "One", "local": True},
     {"key": "alpha", "name": "Duplicate", "local": False,
      "origin": "http://remote.invalid", "token": "PRIVATE"}],
    [{"key": "alpha", "name": "One", "local": True},
     {"key": "bravo", "name": "Second local", "local": True}],
    [{"key": "bravo", "name": "Remote", "origin": "http://remote.invalid/path",
      "token": "PRIVATE"}],
    [{"key": "bravo", "name": "Remote", "origin": "http://remote.invalid", "token": ""}],
])
def test_invalid_backend_target_is_rejected_by_configuration_check(sites):
    import voluptuous as vol

    from custom_components.home_energy_orchestrator import CONFIG_SCHEMA

    with pytest.raises(vol.Invalid):
        CONFIG_SCHEMA({DOMAIN: {"fleet_maintenance": {"sites": sites}}})


async def _setup(hass, monkeypatch, *, fleet=False, catalog=True, extra_entries=()):
    """Load real HEO platforms and services, never any remote site or actuator."""
    for entity, value, unit in (
        ("sensor.test_battery_soc", "60", "%"),
        ("sensor.test_grid_power", "0", "kW"),
        ("sensor.test_house_load", "0.8", "kW"),
    ):
        hass.states.async_set(entity, value, {"unit_of_measurement": unit})
    entry = MockConfigEntry(domain=DOMAIN, version=6, title="Test site", data=dict(ENTRY_DATA))
    entry.add_to_hass(hass)
    for other in extra_entries:
        other.add_to_hass(hass)
    if catalog:
        monkeypatch.setattr(adapter, "async_hacs_catalog", AsyncMock(return_value=dict(CATALOG)))
    never = {
        name: AsyncMock(side_effect=AssertionError(f"Setup must not invoke {name}"))
        for name in ("async_install", "async_create_verified_backup", "async_request_restart")
    }
    for name, method in never.items():
        monkeypatch.setattr(adapter, name, method)
    events = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, events.append)
    config = {DOMAIN: {"fleet_maintenance": {"sites": [dict(LOCAL)]}}} if fleet else {}
    assert await async_setup_component(hass, DOMAIN, config)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry, events, never


def _id(hass, entry, platform, key):
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id is not None
    return entity_id


async def _users(hass):
    # Create the administrator first: HA deliberately makes its first user
    # owner, so creating the ordinary user first would test a false boundary.
    admin = await hass.auth.async_create_user("Administrator", group_ids=[GROUP_ID_ADMIN])
    user = await hass.auth.async_create_user("Household member", group_ids=[GROUP_ID_USER])
    assert admin.is_admin and not user.is_admin
    return admin, user


async def test_default_setup_adds_readonly_node_status_but_no_fleet_controls(hass, monkeypatch):
    entry, events, never = await _setup(hass, monkeypatch)
    status = hass.states.get(_id(hass, entry, "sensor", "maintenance"))
    assert status.state == "idle"
    assert status.attributes["schema_version"] == 1
    assert status.attributes["installed_version"] == CATALOG["installed_version"]
    assert status.attributes["available_versions"] == CATALOG["versions"]
    assert status.attributes["restart_pending"] is False
    assert status.attributes["backup_verified"] is False
    assert FLEET_KEY not in hass.data
    registry = er.async_get(hass)
    assert not any(
        value.config_entry_id == entry.entry_id and "fleet_alpha" in value.unique_id
        for value in registry.entities.values()
    )
    assert all(hass.services.has_service(DOMAIN, service) for service in SERVICES)
    assert hass.states.get("sensor.home_energy_available_energy").state == "8.0"
    assert hass.states.get("sensor.home_energy_status").attributes["writes_performed"] == 0
    assert dict(entry.data) == ENTRY_DATA
    assert events == []
    for method in never.values():
        method.assert_not_called()


async def test_absent_hacs_and_backup_do_not_break_ordinary_heo_setup(hass, monkeypatch):
    assert "hacs" not in hass.data and "backup" not in hass.data
    entry, events, never = await _setup(hass, monkeypatch, catalog=False)
    status = hass.states.get(_id(hass, entry, "sensor", "maintenance"))
    assert status.state == "idle"
    assert status.attributes["error"] == "hacs_unavailable"
    assert status.attributes["installed_version"] is None
    assert status.attributes["available_versions"] == []
    assert hass.states.get("sensor.home_energy_status").state == "observe"
    assert hass.states.get("sensor.home_energy_available_energy").state == "8.0"
    assert events == []
    for method in never.values():
        method.assert_not_called()


async def test_blocked_cold_hacs_metadata_cannot_prevent_ordinary_heo_setup(hass, monkeypatch):
    from tests.test_maintenance_adapter import _hacs

    _, repository, _ = await _hacs(hass)
    repository.releases.objects = []

    async def blocked(**kwargs):
        await asyncio.Event().wait()

    repository.update_repository.side_effect = blocked
    monkeypatch.setattr(adapter, "_CATALOG_REFRESH_TIMEOUT_SECONDS", 0.001)
    entry, events, never = await _setup(hass, monkeypatch, catalog=False)
    status = hass.states.get(_id(hass, entry, "sensor", "maintenance"))
    assert status.attributes["error"] == "hacs_capability_unavailable"
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.home_energy_available_energy").state == "8.0"
    assert dict(entry.data) == ENTRY_DATA
    await hass.data[NODE_KEY].async_status()
    repository.update_repository.assert_awaited_once()
    assert events == []
    for method in never.values():
        method.assert_not_called()


async def test_explicit_yaml_local_hub_adds_exact_native_controls_without_commands(
    hass, monkeypatch,
):
    entry, events, never = await _setup(hass, monkeypatch, fleet=True)
    hub = hass.data[FLEET_KEY]
    assert hub.owner_entry_id == entry.entry_id
    assert hub.targets == (LOCAL,)
    assert entry.runtime_data.fleet_maintenance is hub
    assert hass.states.get(_id(hass, entry, "sensor", "fleet_alpha_maintenance")).state == "idle"
    release = hass.states.get(_id(hass, entry, "select", "fleet_alpha_release"))
    assert release.attributes["options"] == CATALOG["versions"]
    for action in ("update_and_restart", "restart"):
        assert hass.states.get(_id(hass, entry, "button", f"fleet_alpha_{action}")) is not None
    assert hub.selected_versions == {}
    assert events == []
    for method in never.values():
        method.assert_not_called()


async def test_periodic_status_polling_never_installs_an_available_release(
    hass, monkeypatch, freezer,
):
    _, events, never = await _setup(hass, monkeypatch, fleet=True)
    freezer.tick(timedelta(seconds=65))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.data[NODE_KEY].record is None
    assert hass.data[FLEET_KEY].selected_versions == {}
    assert events == []
    for method in never.values():
        method.assert_not_called()


async def test_admin_select_uses_exact_catalog_value_without_mutating_site_policies(
    hass, monkeypatch,
):
    entry, _, never = await _setup(hass, monkeypatch, fleet=True)
    admin, _ = await _users(hass)
    entity_id = _id(hass, entry, "select", "fleet_alpha_release")
    before = dict(entry.data)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity_id, "option": "v0.12.40"},
        blocking=True, context=Context(user_id=admin.id),
    )
    assert hass.data[FLEET_KEY].selected_versions == {"alpha": "v0.12.40"}
    assert hass.states.get(entity_id).state == "v0.12.40"
    assert dict(entry.data) == before
    assert hass.data[NODE_KEY].record is None
    for method in never.values():
        method.assert_not_called()


@pytest.mark.parametrize("action", ["update_and_restart", "restart"])
async def test_frontend_button_preserves_admin_context_to_node(hass, monkeypatch, action):
    entry, _, never = await _setup(hass, monkeypatch, fleet=True)
    admin, _ = await _users(hass)
    hub = hass.data[FLEET_KEY]
    hub.selected_versions["alpha"] = "v0.12.40"
    node = hass.data[NODE_KEY]
    submit = AsyncMock()

    async def accepted(**kwargs):
        return {
            "schema_version": 1,
            "phase": "waiting",
            "request_id": kwargs["request_id"],
            "action": kwargs["action"],
            "expected_version": kwargs["version"],
            "available_versions": CATALOG["versions"],
            "blockers": [],
        }

    submit.side_effect = accepted
    monkeypatch.setattr(node, "async_submit", submit)
    context = Context(user_id=admin.id)
    await hass.services.async_call(
        "button", "press",
        {"entity_id": _id(hass, entry, "button", f"fleet_alpha_{action}")},
        blocking=True, context=context,
    )
    submit.assert_awaited_once()
    payload = submit.call_args.kwargs
    assert payload["context"] is context
    assert payload["action"] == action
    assert payload["version"] == ("v0.12.40" if action == "update_and_restart" else None)
    assert hub.data["alpha"]["phase"] == "waiting"
    for method in never.values():
        method.assert_not_called()


@pytest.mark.parametrize("action", ["update_and_restart", "restart"])
async def test_nonadmin_direct_button_service_cannot_use_backend_maintenance(
    hass, monkeypatch, action,
):
    entry, _, _ = await _setup(hass, monkeypatch, fleet=True)
    _, user = await _users(hass)
    node = hass.data[NODE_KEY]
    submit = AsyncMock()
    monkeypatch.setattr(node, "async_submit", submit)
    hub = hass.data[FLEET_KEY]
    hub.selected_versions["alpha"] = "v0.12.40"
    with pytest.raises(HomeAssistantError, match="administrator"):
        await hass.services.async_call(
            "button", "press",
            {"entity_id": _id(hass, entry, "button", f"fleet_alpha_{action}")},
            blocking=True, context=Context(user_id=user.id),
        )
    submit.assert_not_called()
    assert hub.data["alpha"]["phase"] == "idle"
    assert node.record is None


async def test_nonadmin_direct_select_service_cannot_change_approved_release(hass, monkeypatch):
    entry, _, _ = await _setup(hass, monkeypatch, fleet=True)
    _, user = await _users(hass)
    with pytest.raises(HomeAssistantError, match="administrator"):
        await hass.services.async_call(
            "select", "select_option",
            {"entity_id": _id(hass, entry, "select", "fleet_alpha_release"), "option": "v0.12.40"},
            blocking=True, context=Context(user_id=user.id),
        )
    assert hass.data[FLEET_KEY].selected_versions == {}


@pytest.mark.parametrize("service", ["fleet_maintenance_update", "fleet_maintenance_restart"])
async def test_no_user_context_cannot_invoke_maintenance_service(hass, monkeypatch, service):
    await _setup(hass, monkeypatch, fleet=True)
    with pytest.raises(HomeAssistantError, match="administrator"):
        await hass.services.async_call(DOMAIN, service, {"site": "alpha"}, blocking=True)
    assert hass.data[NODE_KEY].record is None


async def test_node_status_service_is_readonly_without_hub_or_hacs(hass, monkeypatch):
    _, events, _ = await _setup(hass, monkeypatch, catalog=False)
    result = await hass.services.async_call(
        DOMAIN, "maintenance_status", {}, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    assert result["phase"] == "idle"
    assert result["error"] == "hacs_unavailable"
    assert hass.data[NODE_KEY].record is None
    assert [event.data["service"] for event in events] == ["maintenance_status"]


async def test_user_renamed_maintenance_entities_and_boot_identity_survive_reload(
    hass, monkeypatch,
):
    entry, _, never = await _setup(hass, monkeypatch, fleet=True)
    registry = er.async_get(hass)
    node, hub = hass.data[NODE_KEY], hass.data[FLEET_KEY]
    boot_id = node.boot_id
    identities = [
        ("sensor", "maintenance"),
        ("sensor", "fleet_alpha_maintenance"),
        ("select", "fleet_alpha_release"),
        ("button", "fleet_alpha_update_and_restart"),
        ("button", "fleet_alpha_restart"),
    ]
    for index, (platform, key) in enumerate(identities):
        registry.async_update_entity(
            _id(hass, entry, platform, key),
            new_entity_id=f"{platform}.my_maintenance_{index}",
            name=f"My maintenance {index}",
            icon="mdi:shield-check",
        )
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.data[NODE_KEY] is node
    assert hass.data[NODE_KEY].boot_id == boot_id
    assert hass.data[FLEET_KEY] is hub
    for index, (platform, key) in enumerate(identities):
        entity_id = _id(hass, entry, platform, key)
        assert entity_id == f"{platform}.my_maintenance_{index}"
        item = registry.async_get(entity_id)
        assert item.name == f"My maintenance {index}"
        assert item.icon == "mdi:shield-check"
        assert hass.states.get(entity_id) is not None
    for method in never.values():
        method.assert_not_called()


async def test_last_entry_unload_unregisters_maintenance_services(hass, monkeypatch):
    entry, _, never = await _setup(hass, monkeypatch, fleet=True)
    assert all(hass.services.has_service(DOMAIN, service) for service in SERVICES)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert all(not hass.services.has_service(DOMAIN, service) for service in SERVICES)
    assert hass.states.get("sensor.home_energy_maintenance").state == "unavailable"
    for method in never.values():
        method.assert_not_called()


async def test_multiple_entries_without_explicit_hub_owner_do_not_duplicate_controls(
    hass, monkeypatch,
):
    other = MockConfigEntry(domain=DOMAIN, version=6, title="Other site", data=dict(ENTRY_DATA))
    entry, _, _ = await _setup(hass, monkeypatch, fleet=True, extra_entries=(other,))
    assert hass.data[FLEET_KEY].owner_entry_id is None
    assert entry.runtime_data.fleet_maintenance is None
    assert hass.states.get(_id(hass, entry, "sensor", "maintenance")) is not None
    assert not any(
        item.config_entry_id == entry.entry_id and "fleet_alpha" in item.unique_id
        for item in er.async_get(hass).entities.values()
    )
