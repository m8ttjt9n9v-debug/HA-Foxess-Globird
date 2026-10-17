"""Fleet maintenance permission, transport, privacy and no-replay contract."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from homeassistant.auth.const import GROUP_ID_ADMIN
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

from custom_components.home_energy_orchestrator.fleet_maintenance import (
    FleetMaintenanceHub,
    async_require_admin,
)

_ORIGIN = "https://site-alpha.invalid"
_BASE = f"{_ORIGIN}/api/services/home_energy_orchestrator/"
_TOKEN = "private-backend-credential-never-published"
_VERSION = "v0.12.40"


def _status(**changes):
    return {
        "schema_version": 1,
        "phase": "idle",
        "available_versions": [_VERSION],
        "running_version": "0.12.39",
        "installed_version": "v0.12.39",
        "blockers": [],
    } | changes


class _Node:
    def __init__(self):
        self.async_status = AsyncMock(return_value=_status())
        self.async_submit = AsyncMock(side_effect=self._submit)

    async def _submit(self, **payload):
        return _status(
            phase="waiting",
            request_id=payload["request_id"],
            action=payload["action"],
            expected_version=payload["version"],
            accepted=True,
        )


@pytest.fixture
async def admin(hass):
    user = await hass.auth.async_create_user("Maintenance operator", group_ids=[GROUP_ID_ADMIN])
    return Context(user_id=user.id)


def _hub(hass, *, local=True):
    target = {"key": "alpha", "name": "Site Alpha", "local": local}
    if local:
        hass.data["heo_maintenance_node"] = _Node()
    else:
        target |= {"origin": _ORIGIN, "token": _TOKEN}
    return FleetMaintenanceHub(hass, [target])


async def _select(hub):
    await hub.async_refresh()
    await hub.async_select_version("alpha", _VERSION)


async def test_local_status_poll_is_read_only_and_selected_release_is_exact(hass, admin):
    hub = _hub(hass)
    node = hass.data["heo_maintenance_node"]
    await _select(hub)
    assert hub.data["alpha"]["running_version"] == "0.12.39"
    assert hub.selected_versions == {"alpha": _VERSION}
    node.async_submit.assert_not_called()
    with pytest.raises(HomeAssistantError, match="not available"):
        await hub.async_select_version("alpha", "0.12.40")
    with pytest.raises(HomeAssistantError, match="Unknown"):
        await hub.async_select_version("unknown", _VERSION)
    assert hub.update_interval.total_seconds() == 60
    result = await hub.async_request("alpha", "update_and_restart", admin)
    assert result["phase"] == "waiting"
    assert result["accepted"] is True
    assert result["expected_version"] == _VERSION
    assert node.async_submit.call_count == 1
    submitted = node.async_submit.call_args.kwargs
    assert submitted["context"] is admin
    assert submitted["action"] == "update_and_restart"
    assert submitted["version"] == _VERSION
    assert submitted["wait_minutes"] == 60
    assert datetime.fromisoformat(submitted["issued_at"]).utcoffset().total_seconds() == 0
    assert len(submitted["request_id"]) == 32


async def test_restart_needs_no_version_but_preserves_admin_context(hass, admin):
    hub = _hub(hass)
    result = await hub.async_request("alpha", "restart", admin)
    assert result["action"] == "restart"
    assert "expected_version" not in result
    assert hass.data["heo_maintenance_node"].async_submit.call_args.kwargs["version"] is None


@pytest.mark.parametrize("identity", ["anonymous", "missing", "non_admin", "inactive"])
async def test_real_ha_auth_denies_before_any_node_or_network_access(hass, admin, identity):
    hub = _hub(hass)
    node = hass.data["heo_maintenance_node"]
    if identity == "anonymous":
        context = Context()
    elif identity == "missing":
        context = Context(user_id="nonexistent-user")
    else:
        user = await hass.auth.async_create_user(
            "Other operator", group_ids=[GROUP_ID_ADMIN] if identity == "inactive" else []
        )
        if identity == "inactive":
            await hass.auth.async_update_user(user, is_active=False)
        context = Context(user_id=user.id)
    with pytest.raises(HomeAssistantError, match="active administrator"):
        await hub.async_request("alpha", "restart", context)
    node.async_status.assert_not_called()
    node.async_submit.assert_not_called()
    assert "private" not in repr(hub.data)


async def test_require_admin_rechecks_deleted_users_and_denies_none(hass, admin):
    await async_require_admin(hass, admin)
    user = await hass.auth.async_get_user(admin.user_id)
    await hass.auth.async_remove_user(user)
    for context in (admin, None):
        with pytest.raises(HomeAssistantError, match="active administrator"):
            await async_require_admin(hass, context)


@pytest.mark.parametrize(
    "change",
    [
        {"key": "bad/key"},
        {"name": ""},
        {"local": "false"},
        {"origin": "file:///etc/passwd"},
        {"origin": "https://user:pass@site.invalid"},
        {"origin": "https://site.invalid/a"},
        {"origin": "https://site.invalid?secret=x"},
        {"origin": "https://site.invalid#fragment"},
        {"origin": "https://site.invalid:0"},
        {"origin": "https://site.invalid:wrong"},
        {"token": "\r\nInjected: value"},
        {"token": ""},
    ],
)
async def test_invalid_backend_target_fails_without_disclosing_input(hass, change):
    config = {
        "key": "alpha",
        "name": "Site Alpha",
        "local": False,
        "origin": _ORIGIN,
        "token": _TOKEN,
    } | change
    with pytest.raises(HomeAssistantError) as caught:
        FleetMaintenanceHub(hass, [config])
    assert str(caught.value) == "Invalid HEO maintenance target configuration"
    assert _TOKEN not in str(caught.value)


async def test_duplicate_keys_and_multiple_local_nodes_are_rejected(hass):
    target = {"key": "alpha", "name": "Site Alpha", "local": True}
    for second in (target, target | {"key": "bravo"}):
        with pytest.raises(HomeAssistantError):
            FleetMaintenanceHub(hass, [target, second])


async def test_fixed_authenticated_remote_api_has_no_arbitrary_service_or_url(
    hass, admin, aioclient_mock
):
    hub = _hub(hass, local=False)
    aioclient_mock.post(
        _BASE + "maintenance_status?return_response",
        json={
            "service_response": _status(),
            "changed_states": [],
        },
    )
    calls = []

    async def mutation(method, url, data):
        payload = data
        calls.append(payload)
        return AiohttpClientMockResponse(
            method,
            url,
            json={
                "service_response": _status(
                    request_id=payload["request_id"],
                    phase="waiting",
                    action="update_and_restart",
                    accepted=True,
                    expected_version=payload["version"],
                )
            },
        )

    aioclient_mock.post(
        _BASE + "maintenance_update_and_restart?return_response", side_effect=mutation
    )
    await _select(hub)
    result = await hub.async_request("alpha", "update_and_restart", admin)
    assert result["phase"] == "waiting"
    assert len(calls) == 1
    assert set(calls[0]) == {"request_id", "issued_at", "version", "wait_minutes"}
    assert hub.targets == ({"key": "alpha", "name": "Site Alpha", "local": False},)
    for request in aioclient_mock.mock_calls:
        assert request[3]["Authorization"] == f"Bearer {_TOKEN}"
    assert _TOKEN not in repr(hub.data)
    assert _ORIGIN not in repr(hub.data)
    assert "token" not in repr(hub.targets)
    count = aioclient_mock.call_count
    with pytest.raises(HomeAssistantError, match="Unsupported"):
        await hub.async_request("alpha", "http://untrusted.invalid/execute", admin)
    with pytest.raises(HomeAssistantError, match="Unknown"):
        await hub.async_request("not_configured", "restart", admin)
    assert aioclient_mock.call_count == count


@pytest.mark.parametrize("schema", [None, 0, 2, True, "1"])
async def test_missing_or_incompatible_protocol_requires_initial_manual_update(hass, admin, schema):
    hub = _hub(hass)
    node = hass.data["heo_maintenance_node"]
    node.async_status.return_value = _status(schema_version=schema)
    await hub.async_refresh()
    assert hub.data["alpha"]["phase"] == "initial_update_required"
    with pytest.raises(HomeAssistantError, match="initial update"):
        await hub.async_request("alpha", "restart", admin)
    node.async_submit.assert_not_called()


async def test_old_remote_missing_service_requires_initial_update(hass, admin, aioclient_mock):
    hub = _hub(hass, local=False)
    aioclient_mock.post(_BASE + "maintenance_status?return_response", status=404)
    await hub.async_refresh()
    assert hub.data["alpha"]["phase"] == "initial_update_required"
    with pytest.raises(HomeAssistantError, match="initial update"):
        await hub.async_request("alpha", "restart", admin)
    assert all("maintenance_status" in str(call[1]) for call in aioclient_mock.mock_calls)


async def test_request_rechecks_current_release_catalog_before_mutation(hass, admin):
    hub = _hub(hass)
    await _select(hub)
    node = hass.data["heo_maintenance_node"]
    node.async_status.return_value = _status(available_versions=[])
    with pytest.raises(HomeAssistantError, match="no longer available"):
        await hub.async_request("alpha", "update_and_restart", admin)
    node.async_submit.assert_not_called()


@pytest.mark.parametrize(
    "failure", ["timeout", "http", "bad_json", "oversized", "wrong_id", "shape"]
)
async def test_ambiguous_remote_mutation_is_unknown_and_never_retried(
    hass, admin, aioclient_mock, failure
):
    hub = _hub(hass, local=False)
    aioclient_mock.post(
        _BASE + "maintenance_status?return_response",
        json={
            "service_response": _status(),
        },
    )
    url = _BASE + "maintenance_restart?return_response"
    if failure == "timeout":
        aioclient_mock.post(url, exc=TimeoutError(_TOKEN))
    elif failure == "http":
        aioclient_mock.post(url, status=500, text=_TOKEN)
    elif failure == "bad_json":
        aioclient_mock.post(url, text=_TOKEN)
    elif failure == "oversized":
        aioclient_mock.post(url, text=" " * 40_000 + _TOKEN)
    elif failure == "wrong_id":
        aioclient_mock.post(url, json={"service_response": _status(request_id=uuid4().hex)})
    else:
        aioclient_mock.post(url, json={"service_response": [_TOKEN], "token": _TOKEN})
    result = await hub.async_request("alpha", "restart", admin)
    assert result["phase"] == "unknown"
    assert _TOKEN not in repr(hub.data)
    assert _ORIGIN not in repr(hub.data)
    await hub.async_refresh()
    assert hub.data["alpha"]["phase"] == "idle"
    mutation_calls = [
        call for call in aioclient_mock.mock_calls if "maintenance_restart" in str(call[1])
    ]
    assert len(mutation_calls) == 1


async def test_remote_redirect_is_not_followed(hass, admin, aioclient_mock):
    hub = _hub(hass, local=False)
    aioclient_mock.post(
        _BASE + "maintenance_status?return_response",
        json={
            "service_response": _status(),
        },
    )
    aioclient_mock.post(
        _BASE + "maintenance_restart?return_response",
        status=302,
        headers={"Location": "https://other-origin.invalid/credentials"},
    )
    result = await hub.async_request("alpha", "restart", admin)
    assert result["phase"] == "unknown"
    assert aioclient_mock.call_count == 2


async def test_unknown_fields_and_provider_errors_never_become_public_state(hass):
    hub = _hub(hass)
    node = hass.data["heo_maintenance_node"]
    node.async_status.return_value = _status(
        raw_error=_TOKEN,
        token=_TOKEN,
        origin=_ORIGIN,
        backup_id="private-backup-path",
        error=_TOKEN,
        blockers=[_TOKEN, "battery_export_session_active"],
    )
    await hub.async_refresh()
    assert hub.data["alpha"]["phase"] == "idle"
    assert hub.data["alpha"]["error"] == "node_reported_error"
    assert hub.data["alpha"]["blockers"] == [
        "node_reported_blocker",
        "battery_export_session_active",
    ]
    for private in (_TOKEN, _ORIGIN, "private-backup-path"):
        assert private not in repr(hub.data)
    node.async_status.side_effect = RuntimeError(f"{_TOKEN} {_ORIGIN}")
    await hub.async_refresh()
    assert hub.data["alpha"]["phase"] == "unknown"
    assert _TOKEN not in repr(hub.data)


@pytest.mark.parametrize(
    "changes",
    [
        {"phase": [_TOKEN]},
        {"available_versions": [_TOKEN]},
        {"available_versions": [_VERSION] * 101},
        {"blockers": {}},
    ],
)
async def test_malformed_or_unbounded_node_status_is_unknown(hass, changes):
    hub = _hub(hass)
    hass.data["heo_maintenance_node"].async_status.return_value = _status(**changes)
    await hub.async_refresh()
    assert hub.data["alpha"]["phase"] == "unknown"
    assert _TOKEN not in repr(hub.data)


async def test_poll_started_before_request_cannot_overwrite_newer_result(hass, admin):
    hub = _hub(hass)
    node = hass.data["heo_maintenance_node"]
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def status():
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
        return _status()

    node.async_status.side_effect = status
    poll = asyncio.create_task(hub.async_refresh())
    await started.wait()
    result = await hub.async_request("alpha", "restart", admin)
    release.set()
    await poll
    assert hub.data["alpha"]["request_id"] == result["request_id"]
    assert hub.data["alpha"]["phase"] == "waiting"


async def test_parallel_mutation_is_rejected_not_queued_or_replayed(hass, admin):
    hub = _hub(hass)
    node = hass.data["heo_maintenance_node"]
    started, release = asyncio.Event(), asyncio.Event()

    async def submit(**payload):
        started.set()
        await release.wait()
        return await node._submit(**payload)

    node.async_submit.side_effect = submit
    request = asyncio.create_task(hub.async_request("alpha", "restart", admin))
    await started.wait()
    with pytest.raises(HomeAssistantError, match="already in progress"):
        await hub.async_request("alpha", "restart", admin)
    await hub.async_refresh()
    assert hub.data["alpha"]["phase"] == "submitting"
    release.set()
    result = await request
    assert result["phase"] == "waiting"
    assert node.async_submit.call_count == 1


async def test_local_mutation_exception_is_sanitized_and_poll_does_not_replay(hass, admin):
    hub = _hub(hass)
    node = hass.data["heo_maintenance_node"]
    node.async_submit.side_effect = RuntimeError(f"{_TOKEN} {_ORIGIN}")
    result = await hub.async_request("alpha", "restart", admin)
    assert result["phase"] == "unknown"
    assert _TOKEN not in repr(result)
    await hub.async_refresh()
    assert node.async_submit.call_count == 1


@pytest.mark.parametrize("change", [{"action": "restart"}, {"expected_version": "v0.12.41"}])
async def test_matching_uuid_with_wrong_action_or_version_is_unknown(hass, admin, change):
    hub = _hub(hass)
    await _select(hub)
    node = hass.data["heo_maintenance_node"]

    async def submit(**payload):
        return await node._submit(**payload) | change

    node.async_submit.side_effect = submit
    result = await hub.async_request("alpha", "update_and_restart", admin)
    assert result["phase"] == "unknown"
    assert node.async_submit.call_count == 1
