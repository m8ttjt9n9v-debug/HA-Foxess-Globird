"""Explicit per-site release checks are metadata, never a maintenance operation."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from homeassistant.auth.const import GROUP_ID_ADMIN
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError

from custom_components.home_energy_orchestrator import FLEET_KEY, maintenance, maintenance_adapter
from custom_components.home_energy_orchestrator.fleet_maintenance import _sanitize
from custom_components.home_energy_orchestrator.maintenance import NODE_KEY
from tests.test_fleet_maintenance import _BASE, _ORIGIN, _TOKEN, _hub, _status
from tests.test_maintenance_entities import _id, _setup, _users


@pytest.fixture
async def operator(hass):
    user = await hass.auth.async_create_user("Release operator", group_ids=[GROUP_ID_ADMIN])
    return Context(user_id=user.id)


def _checked(**changes):
    return _status(
        available_versions=["v0.12.44", "v0.12.43"],
        release_refresh_state="ready", release_refresh_error=None,
        release_last_checked="2026-10-18T04:00:00+00:00",
    ) | changes


async def test_local_explicit_check_updates_warm_choices_without_submitting(hass, operator):
    hub = _hub(hass)
    node = hass.data[NODE_KEY]
    await hub.async_refresh()
    node.async_refresh_releases = AsyncMock(return_value=_checked())
    result = await hub.async_check_releases("alpha", operator)
    assert result["available_versions"] == ["v0.12.44", "v0.12.43"]
    assert result["release_refresh_state"] == "ready"
    assert hub.selected_versions == {}
    node.async_refresh_releases.assert_awaited_once_with(operator)
    node.async_submit.assert_not_called()
    await hub.async_refresh()
    assert node.async_refresh_releases.await_count == 1


@pytest.mark.parametrize("identity", ["anonymous", "missing", "non_admin", "inactive"])
async def test_release_check_auth_precedes_node_or_network(hass, operator, identity):
    hub = _hub(hass)
    node = hass.data[NODE_KEY]
    node.async_refresh_releases = AsyncMock(return_value=_checked())
    context = Context() if identity == "anonymous" else Context(user_id="missing")
    if identity in {"non_admin", "inactive"}:
        user = await hass.auth.async_create_user(
            "Other", group_ids=[GROUP_ID_ADMIN] if identity == "inactive" else []
        )
        if identity == "inactive":
            await hass.auth.async_update_user(user, is_active=False)
        context = Context(user_id=user.id)
    with pytest.raises(HomeAssistantError, match="active administrator"):
        await hub.async_check_releases("alpha", context)
    node.async_status.assert_not_called()
    node.async_refresh_releases.assert_not_called()
    node.async_submit.assert_not_called()


async def test_remote_check_uses_only_fixed_authenticated_metadata_endpoint(
    hass, operator, aioclient_mock,
):
    hub = _hub(hass, local=False)
    aioclient_mock.post(
        _BASE + "maintenance_refresh_releases?return_response",
        json={"service_response": _checked()},
    )
    result = await hub.async_check_releases("alpha", operator)
    assert result["release_refresh_state"] == "ready"
    assert aioclient_mock.call_count == 1
    request = aioclient_mock.mock_calls[0]
    assert request[2] == {} and request[3]["Authorization"] == f"Bearer {_TOKEN}"
    assert _TOKEN not in repr(result) and _ORIGIN not in repr(result)


@pytest.mark.parametrize("local", [True, False])
async def test_old_node_retains_existing_choices_and_reports_update_needed(
    hass, operator, aioclient_mock, local,
):
    hub = _hub(hass, local=local)
    previous = _status(phase="waiting", error="maintenance_expired")
    hub.async_set_updated_data({"alpha": previous})
    if not local:
        aioclient_mock.post(_BASE + "maintenance_refresh_releases?return_response", status=404)
    result = await hub.async_check_releases("alpha", operator)
    assert result["phase"] == "waiting" and result["error"] == "maintenance_expired"
    assert result["available_versions"] == previous["available_versions"]
    assert result["release_refresh_error"] == "release_refresh_unsupported"


@pytest.mark.parametrize("status", [302, 401, 403, 500])
async def test_refresh_network_failure_keeps_choices_but_never_claims_success(
    hass, operator, aioclient_mock, status,
):
    hub = _hub(hass, local=False)
    hub.async_set_updated_data({"alpha": _status()})
    aioclient_mock.post(
        _BASE + "maintenance_refresh_releases?return_response", status=status,
        headers={"Location": "https://other.invalid/no-credentials"},
    )
    result = await hub.async_check_releases("alpha", operator)
    assert result["phase"] == "idle"
    assert result["available_versions"] == _status()["available_versions"]
    assert result["release_refresh_state"] == "failed"
    assert result["release_refresh_error"] == "release_refresh_failed"
    assert "release_last_checked" not in result
    assert aioclient_mock.call_count == 1


@pytest.mark.parametrize("payload", [None, [], {"schema_version": 2}, _status()])
async def test_malformed_check_reply_is_bounded_failure(hass, operator, payload):
    hub = _hub(hass)
    hub.async_set_updated_data({"alpha": _status()})
    hass.data[NODE_KEY].async_refresh_releases = AsyncMock(return_value=payload)
    result = await hub.async_check_releases("alpha", operator)
    assert result["release_refresh_error"] == "release_refresh_failed"
    assert result["available_versions"] == _status()["available_versions"]


async def test_old_poll_cannot_overwrite_check_and_parallel_clicks_are_not_queued(hass, operator):
    hub = _hub(hass)
    node = hass.data[NODE_KEY]
    poll_started, finish_poll, check_started, finish_check = (asyncio.Event() for _ in range(4))

    async def status():
        poll_started.set()
        await finish_poll.wait()
        return _status()

    async def refresh(context):
        check_started.set()
        await finish_check.wait()
        return _checked()

    node.async_status.side_effect = status
    node.async_refresh_releases = AsyncMock(side_effect=refresh)
    poll = asyncio.create_task(hub.async_refresh())
    await poll_started.wait()
    check = asyncio.create_task(hub.async_check_releases("alpha", operator))
    await check_started.wait()
    with pytest.raises(HomeAssistantError, match="already in progress"):
        await hub.async_check_releases("alpha", operator)
    with pytest.raises(HomeAssistantError, match="already in progress"):
        await hub.async_request("alpha", "restart", operator)
    finish_check.set()
    await check
    finish_poll.set()
    await poll
    assert hub.data["alpha"]["available_versions"] == _checked()["available_versions"]
    assert node.async_refresh_releases.await_count == 1
    node.async_submit.assert_not_called()


async def test_cancelled_check_cannot_leave_ui_checking_or_keep_request_lock(hass, operator):
    hub = _hub(hass)
    started = asyncio.Event()

    async def refresh(context):
        started.set()
        await asyncio.Event().wait()

    hass.data[NODE_KEY].async_refresh_releases = AsyncMock(side_effect=refresh)
    task = asyncio.create_task(hub.async_check_releases("alpha", operator))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert hub.data["alpha"]["release_refresh_state"] == "failed"
    assert not hub._locks["alpha"].locked()


@pytest.mark.parametrize("value", [[], {}, "private-provider-error", 1, None])
def test_refresh_fields_reject_untrusted_remote_values(value):
    result = _sanitize(_status(release_refresh_state=value, release_refresh_error=value))
    assert "release_refresh_state" not in result
    assert "private-provider-error" not in repr(result)


@pytest.mark.parametrize(
    "blockers", [(), ("battery_charge_session_active", "ev_physically_charging")],
)
async def test_real_button_checks_releases_without_maintenance_or_policy_changes(
    hass, monkeypatch, blockers,
):
    entry, events, never = await _setup(hass, monkeypatch, fleet=True)
    admin, _ = await _users(hass)
    catalog = {
        "installed_version": f"v{hass.data[NODE_KEY].running_version}",
        "versions": ["v9.9.9"], "in_progress": False,
        "release_last_checked": "2026-10-18T04:00:00+00:00",
    }
    refresh = AsyncMock(return_value=catalog)
    monkeypatch.setattr(maintenance_adapter, "async_refresh_hacs_catalog", refresh)
    monkeypatch.setattr(maintenance_adapter, "async_hacs_catalog", AsyncMock(return_value=catalog))
    monkeypatch.setattr(maintenance, "maintenance_blockers", lambda *args: blockers)
    before = dict(entry.data)
    await hass.services.async_call(
        "button", "press",
        {"entity_id": _id(hass, entry, "button", "fleet_alpha_check_releases")},
        blocking=True, context=Context(user_id=admin.id),
    )
    await hass.async_block_till_done()
    assert hass.data[FLEET_KEY].data["alpha"]["release_refresh_state"] == "ready"
    assert hass.data[FLEET_KEY].data["alpha"]["available_versions"] == ["v9.9.9"]
    assert hass.data[FLEET_KEY].data["alpha"]["blockers"] == list(blockers)
    assert hass.data[NODE_KEY].record is None and dict(entry.data) == before
    assert [event.data["service"] for event in events] == ["press"]
    for method in never.values():
        method.assert_not_called()


async def test_actual_check_button_denies_nonadministrator_before_hacs(hass, monkeypatch):
    entry, _, never = await _setup(hass, monkeypatch, fleet=True)
    _, ordinary = await _users(hass)
    refresh = AsyncMock()
    monkeypatch.setattr(maintenance_adapter, "async_refresh_hacs_catalog", refresh)
    with pytest.raises(HomeAssistantError, match="active administrator"):
        await hass.services.async_call(
            "button", "press",
            {"entity_id": _id(hass, entry, "button", "fleet_alpha_check_releases")},
            blocking=True, context=Context(user_id=ordinary.id),
        )
    refresh.assert_not_called()
    for method in never.values():
        method.assert_not_called()
