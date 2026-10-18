"""Node maintenance lifecycle with real HA users and real typed Store journals."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from homeassistant.auth.const import GROUP_ID_ADMIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, CoreState
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator import maintenance as module
from custom_components.home_energy_orchestrator.const import DOMAIN
from custom_components.home_energy_orchestrator.maintenance import NodeMaintenance
from custom_components.home_energy_orchestrator.maintenance_adapter import MaintenanceAdapterError
from custom_components.home_energy_orchestrator.maintenance_barrier import KEY as FENCE_KEY

VERSION = "v0.12.40"


@pytest.fixture
async def node_rig(hass, monkeypatch):
    hass.set_state(CoreState.running)
    user = await hass.auth.async_create_user("Maintenance operator", group_ids=[GROUP_ID_ADMIN])
    context = Context(user_id=user.id)
    entry = MockConfigEntry(domain=DOMAIN, version=6, data={"reserve_kwh": 2})
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace()
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    blockers = []
    locks = [asyncio.Lock(), asyncio.Lock()]
    events = []
    catalog = {"installed_version": "v0.12.39", "versions": [VERSION], "in_progress": False}
    monkeypatch.setattr(module, "maintenance_blockers",
                        lambda _hass, _coordinators: tuple(blockers))
    monkeypatch.setattr(module, "maintenance_locks", lambda _coordinators: locks)
    # Session/freshness details are independently characterized by the actual
    # controller-model suite in test_maintenance_safety.py.
    if hasattr(module, "runtime_verification_blockers"):
        monkeypatch.setattr(module, "runtime_verification_blockers",
                            lambda _hass, _coordinators: tuple(blockers))

    async def native_catalog(_hass):
        return dict(catalog)

    async def backup(_hass, request_id):
        assert _hass.data[FENCE_KEY] is True
        assert all(lock.locked() for lock in locks)
        events.append("backup")
        return {"backup_id": "verified-backup", "agent_id": "backup.local"}

    async def install(_hass, version, _context):
        assert _hass.data[FENCE_KEY] is True
        assert events[0] == "backup"
        events.append("install")
        catalog["installed_version"] = version

    async def check(_hass):
        events.append("check")

    async def restart(_hass, _context):
        assert _hass.data[FENCE_KEY] is True
        # HA unload itself must acquire these locks: retaining them would
        # deadlock an otherwise successful restart.
        assert not any(lock.locked() for lock in locks)
        events.append("restart")

    native = module.adapter
    monkeypatch.setattr(native, "async_hacs_catalog", AsyncMock(side_effect=native_catalog))
    monkeypatch.setattr(native, "async_create_verified_backup", AsyncMock(side_effect=backup))
    monkeypatch.setattr(native, "async_install", AsyncMock(side_effect=install))
    monkeypatch.setattr(native, "async_check_config", AsyncMock(side_effect=check))
    monkeypatch.setattr(native, "async_request_restart", AsyncMock(side_effect=restart))
    node = NodeMaintenance(hass, "0.12.39")
    await node.async_restore()
    nodes = [node]

    async def submit(*, action="update_and_restart", request_id=None, issued_at=None,
                     version=VERSION, auth=context, wait_minutes=60):
        return await node.async_submit(
            action, request_id or uuid4().hex,
            issued_at or datetime.now(UTC).isoformat(), version, auth, wait_minutes,
        )

    async def finish():
        if node._task is not None:
            await node._task
        return await node.async_status()

    async def reboot(version="0.12.40"):
        hass.data.pop("heo_running_version", None)
        hass.data.pop("heo_maintenance_boot_id", None)
        fresh = NodeMaintenance(hass, version)
        nodes.append(fresh)
        await fresh.async_restore()
        return fresh

    rig = SimpleNamespace(node=node, context=context, user=user, entry=entry, blockers=blockers,
                          locks=locks, events=events, catalog=catalog, native=native,
                          submit=submit, finish=finish, reboot=reboot)
    yield rig
    for value in nodes:
        await value.async_shutdown()
    entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)


async def test_ordered_backup_install_check_restart_and_readonly_boot_verification(hass, node_rig):
    rig = node_rig
    result = await rig.submit()
    assert result["phase"] == "waiting"
    result = await rig.finish()
    assert rig.events == ["backup", "check", "install", "check", "restart"]
    assert result["phase"] == "restart_requested"
    assert result["installed_version"] == VERSION
    assert result["running_version"] == "0.12.39"
    assert result["restart_pending"] is True
    assert result["backup_verified"] is True
    stored = await rig.node._repository.store.async_load()
    assert stored["phase"] == "restart_requested"
    assert stored["backup_id"] == "verified-backup"
    assert hass.data[FENCE_KEY] is True
    # Simulate old-process stop; a new process never restores its write fence.
    await rig.node.async_shutdown()
    fresh = await rig.reboot()
    assert FENCE_KEY not in hass.data
    assert (await fresh.async_status())["phase"] == "verified"
    assert rig.events == ["backup", "check", "install", "check", "restart"]


async def test_restart_action_still_backs_up_but_never_installs(node_rig):
    rig = node_rig
    await rig.submit(action="restart", version=None)
    result = await rig.finish()
    assert rig.events == ["backup", "check", "restart"]
    assert result["expected_version"] == "v0.12.39"
    rig.native.async_install.assert_not_called()


@pytest.mark.parametrize("identity", ["anonymous", "missing", "non_admin", "inactive"])
async def test_real_auth_blocks_before_persistence_or_native_work(hass, node_rig, identity):
    rig = node_rig
    if identity == "anonymous":
        context = None
    elif identity == "missing":
        context = Context(user_id="unknown-user")
    else:
        user = await hass.auth.async_create_user(
            "Other operator", group_ids=[GROUP_ID_ADMIN] if identity == "inactive" else [])
        if identity == "inactive":
            await hass.auth.async_update_user(user, is_active=False)
        context = Context(user_id=user.id)
    with pytest.raises(HomeAssistantError, match="active administrator"):
        await rig.submit(auth=context)
    assert rig.node.record is None and rig.events == []
    assert await rig.node._repository.store.async_load() is None


@pytest.mark.parametrize("identity", ["anonymous", "missing", "non_admin", "inactive"])
async def test_release_check_requires_real_admin_before_metadata_access(
    hass, node_rig, monkeypatch, identity,
):
    rig = node_rig
    refresh = AsyncMock()
    monkeypatch.setattr(rig.native, "async_refresh_hacs_catalog", refresh)
    if identity == "anonymous":
        context = None
    elif identity == "missing":
        context = Context(user_id="unknown-user")
    else:
        user = await hass.auth.async_create_user(
            "Other release operator", group_ids=[GROUP_ID_ADMIN] if identity == "inactive" else [],
        )
        if identity == "inactive":
            await hass.auth.async_update_user(user, is_active=False)
        context = Context(user_id=user.id)
    with pytest.raises(HomeAssistantError, match="active administrator"):
        await rig.node.async_refresh_releases(context)
    refresh.assert_not_called()
    assert rig.node.release_refresh_state == "idle"
    assert rig.node.record is None and rig.events == []
    assert await rig.node._repository.store.async_load() is None


async def test_release_check_is_metadata_only_even_while_energy_work_is_active(
    hass, node_rig, monkeypatch,
):
    rig = node_rig
    rig.blockers[:] = ["battery_charge_session_active", "ev_session_active"]
    entered, finish = asyncio.Event(), asyncio.Event()
    checked = "2026-10-18T03:00:00+00:00"
    settings = dict(rig.entry.data), dict(rig.entry.options)

    async def refresh(_hass):
        entered.set()
        await finish.wait()
        rig.catalog["versions"] = ["v0.12.43", VERSION]
        return dict(rig.catalog) | {"release_last_checked": checked}

    native_refresh = AsyncMock(side_effect=refresh)
    monkeypatch.setattr(rig.native, "async_refresh_hacs_catalog", native_refresh)
    task = asyncio.create_task(rig.node.async_refresh_releases(rig.context))
    await entered.wait()
    assert rig.node.data["release_refresh_state"] == "checking"
    assert FENCE_KEY not in hass.data
    assert not any(lock.locked() for lock in rig.locks)
    finish.set()
    result = await task
    assert result["release_refresh_state"] == "ready"
    assert result["release_refresh_error"] is None
    assert result["release_last_checked"] == checked
    assert result["available_versions"] == ["v0.12.43", VERSION]
    assert result["phase"] == "idle" and result["error"] is None
    assert result["blockers"] == rig.blockers
    assert rig.node.record is None and rig.node._task is None
    assert await rig.node._repository.store.async_load() is None
    assert settings == (dict(rig.entry.data), dict(rig.entry.options))
    assert rig.events == [] and FENCE_KEY not in hass.data
    native_refresh.assert_awaited_once_with(hass)
    rig.native.async_create_verified_backup.assert_not_called()
    rig.native.async_install.assert_not_called()
    rig.native.async_check_config.assert_not_called()
    rig.native.async_request_restart.assert_not_called()


@pytest.mark.parametrize("failure", ["safe", "provider"])
async def test_release_check_failure_does_not_replace_existing_maintenance_audit(
    node_rig, monkeypatch, failure,
):
    rig = node_rig
    rig.native.async_create_verified_backup.side_effect = MaintenanceAdapterError("backup_busy")
    await rig.submit()
    await rig.finish()
    before = dict(rig.node.record)
    stored = await rig.node._repository.store.async_load()
    events = list(rig.events)
    rig.node.release_last_checked = "2026-10-18T02:00:00+00:00"
    refresh = AsyncMock(side_effect=(
        MaintenanceAdapterError("hacs_catalog_unsupported") if failure == "safe"
        else RuntimeError("Bearer PRIVATE at private host")
    ))
    monkeypatch.setattr(rig.native, "async_refresh_hacs_catalog", refresh)
    result = await rig.node.async_refresh_releases(rig.context)
    assert result["release_refresh_state"] == "failed"
    assert result["release_refresh_error"] == (
        "hacs_catalog_unsupported" if failure == "safe" else "hacs_capability_unavailable"
    )
    assert result["release_last_checked"] == "2026-10-18T02:00:00+00:00"
    assert result["phase"] == "failed" and result["error"] == "backup_busy"
    assert rig.node.record == before
    assert await rig.node._repository.store.async_load() == stored
    assert rig.events == events
    assert "PRIVATE" not in str(result)


async def test_release_check_cancellation_is_bounded_failure_not_maintenance_replay(
    hass, node_rig, monkeypatch,
):
    rig = node_rig
    entered = asyncio.Event()

    async def refresh(_hass):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(rig.native, "async_refresh_hacs_catalog", refresh)
    task = asyncio.create_task(rig.node.async_refresh_releases(rig.context))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert rig.node.data["release_refresh_state"] == "failed"
    assert rig.node.data["release_refresh_error"] == "hacs_capability_unavailable"
    assert rig.node.record is None and rig.events == []
    assert FENCE_KEY not in hass.data


async def test_duplicate_request_is_status_only_and_same_id_cannot_be_repurposed(node_rig):
    rig = node_rig
    request_id, issued = uuid4().hex, datetime.now(UTC).isoformat()
    await rig.submit(request_id=request_id, issued_at=issued)
    await rig.finish()
    previous = list(rig.events)
    result = await rig.submit(request_id=request_id, issued_at=issued)
    assert result["request_id"] == request_id and rig.events == previous
    with pytest.raises(HomeAssistantError, match="request_conflict"):
        await rig.submit(request_id=request_id, issued_at=issued, version="v0.12.41")


@pytest.mark.parametrize("age_seconds", [-6, 61])
async def test_stale_or_future_request_cannot_create_journal(node_rig, age_seconds):
    rig = node_rig
    issued = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
    with pytest.raises(HomeAssistantError, match="stale_maintenance_request"):
        await rig.submit(issued_at=issued)
    assert rig.node.record is None and not rig.events


async def test_older_distinct_request_is_not_replayed_after_terminal_failure(node_rig):
    rig = node_rig
    rig.native.async_create_verified_backup.side_effect = MaintenanceAdapterError("backup_failed")
    issued = datetime.now(UTC)
    await rig.submit(issued_at=issued.isoformat())
    assert (await rig.finish())["phase"] == "failed"
    with pytest.raises(HomeAssistantError, match="stale_maintenance_request"):
        await rig.submit(issued_at=(issued - timedelta(seconds=1)).isoformat())
    assert rig.native.async_create_verified_backup.call_count == 1


@pytest.mark.parametrize("change", ["settings", "session", "privilege"])
async def test_change_during_backup_aborts_before_install_or_restart(hass, node_rig, change):
    rig = node_rig

    async def backup(_hass, _request):
        rig.events.append("backup")
        if change == "settings":
            hass.config_entries.async_update_entry(rig.entry, data={"reserve_kwh": 4})
        elif change == "session":
            rig.blockers.append("ev_session_active")
        else:
            await hass.auth.async_update_user(rig.user, is_active=False)
        return {"backup_id": "verified-backup"}

    rig.native.async_create_verified_backup.side_effect = backup
    await rig.submit()
    result = await rig.finish()
    assert result["phase"] == "failed"
    rig.native.async_install.assert_not_called()
    rig.native.async_request_restart.assert_not_called()
    assert FENCE_KEY not in hass.data
    assert not any(lock.locked() for lock in rig.locks)


@pytest.mark.parametrize("boundary", ["backup", "precheck", "install", "postcheck", "restart"])
async def test_native_failure_never_blindly_retries_and_clears_fence(hass, node_rig, boundary):
    rig = node_rig
    failure = MaintenanceAdapterError("backup_failed")
    if boundary == "backup":
        rig.native.async_create_verified_backup.side_effect = failure
    elif boundary == "precheck":
        rig.native.async_check_config.side_effect = failure
    elif boundary == "postcheck":
        rig.native.async_check_config.side_effect = [None, failure]
    elif boundary == "install":
        rig.native.async_install.side_effect = failure
    else:
        rig.native.async_request_restart.side_effect = failure
    request_id, issued = uuid4().hex, datetime.now(UTC).isoformat()
    await rig.submit(request_id=request_id, issued_at=issued)
    result = await rig.finish()
    assert result["phase"] == (
        "failed" if boundary in {"backup", "precheck"} else "restart_pending")
    assert result["error"] == "backup_failed"
    assert FENCE_KEY not in hass.data
    previous = list(rig.events)
    await rig.submit(request_id=request_id, issued_at=issued)
    assert rig.events == previous
    assert rig.native.async_install.call_count <= 1
    assert rig.native.async_request_restart.call_count <= 1


@pytest.mark.parametrize("change", ["settings", "session"])
async def test_changed_state_after_files_replace_requires_manual_restart_review(
    hass, node_rig, change,
):
    rig = node_rig

    async def install(_hass, version, _context):
        rig.events.append("install")
        rig.catalog["installed_version"] = version
        if change == "settings":
            hass.config_entries.async_update_entry(rig.entry, options={"reserve_kwh": 4})
        else:
            rig.blockers.append("battery_export_session_active")

    rig.native.async_install.side_effect = install
    await rig.submit()
    result = await rig.finish()
    assert result["phase"] == "restart_pending"
    rig.native.async_request_restart.assert_not_called()
    assert result["installed_version"] == VERSION and result["running_version"] == "0.12.39"
    assert FENCE_KEY not in hass.data


async def test_post_install_configuration_check_cannot_hide_new_session(hass, node_rig):
    rig = node_rig
    count = 0

    async def check(_hass):
        nonlocal count
        count += 1
        if count == 2:
            rig.blockers.append("ev_full_charge_active")

    rig.native.async_check_config.side_effect = check
    await rig.submit()
    result = await rig.finish()
    assert result["phase"] == "restart_pending"
    rig.native.async_request_restart.assert_not_called()
    assert FENCE_KEY not in hass.data


async def test_backup_is_fully_awaited_before_any_install(node_rig):
    rig = node_rig
    entered, release = asyncio.Event(), asyncio.Event()

    async def backup(_hass, _request):
        entered.set()
        await release.wait()
        rig.events.append("backup")
        return {"backup_id": "verified-backup"}

    rig.native.async_create_verified_backup.side_effect = backup
    await rig.submit()
    await entered.wait()
    rig.native.async_install.assert_not_called()
    rig.native.async_request_restart.assert_not_called()
    with pytest.raises(HomeAssistantError, match="maintenance_busy"):
        await rig.submit(issued_at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat())
    release.set()
    assert (await rig.finish())["phase"] == "restart_requested"


async def test_waiting_session_is_not_stopped_or_fenced_and_expires(node_rig, freezer):
    rig = node_rig
    rig.blockers.append("battery_export_session_active")
    await rig.submit(wait_minutes=1)
    await asyncio.sleep(0)
    assert rig.node.record["phase"] == "waiting"
    assert rig.events == []
    assert FENCE_KEY not in rig.node.hass.data
    # Re-evaluate the saved original request after its deadline without waiting
    # a real 30-second poll or authorising a replacement operation.
    rig.node._task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await rig.node._task
    freezer.move_to(datetime.now(UTC) + timedelta(minutes=2))
    await rig.node._run(rig.context)
    assert rig.node.record["phase"] == "failed"
    assert rig.node.record["error"] == "maintenance_expired"
    assert rig.events == []


async def test_storage_failure_before_admission_never_starts_work(hass, node_rig, monkeypatch):
    rig = node_rig
    monkeypatch.setattr(type(rig.node._repository), "async_save",
                        AsyncMock(side_effect=OSError("private filesystem detail")))
    with pytest.raises(HomeAssistantError, match="maintenance_storage_unavailable"):
        await rig.submit()
    assert rig.events == [] and not rig.node._trusted
    assert FENCE_KEY not in hass.data


@pytest.mark.parametrize("phase", ["waiting", "backing_up", "installing", "checking",
                                   "restart_pending", "failed", "unknown"])
async def test_restored_intermediate_record_is_readonly_never_replayed(hass, node_rig, phase):
    rig = node_rig
    rig.native.async_create_verified_backup.side_effect = MaintenanceAdapterError("backup_failed")
    await rig.submit()
    await rig.finish()
    payload = {**rig.node.record, "phase": phase, "error": None}
    await rig.node._repository.store.async_save(payload)
    previous = list(rig.events)
    fresh = await rig.reboot("0.12.39")
    result = await fresh.async_status()
    assert result["phase"] == ("interrupted" if phase in module.IN_PROGRESS else phase)
    assert fresh._task is None
    assert FENCE_KEY not in hass.data and rig.events == previous


async def test_corrupt_journal_is_blocked_without_replacing_evidence(hass, node_rig):
    rig = node_rig
    await rig.node._repository.store.async_save({"v": 999, "token": "private-evidence"})
    fresh = await rig.reboot()
    status = await fresh.async_status()
    assert "maintenance_storage_unavailable" in status["blockers"]
    assert status["phase"] == "idle"
    assert await fresh._repository.store.async_load() == {"v": 999, "token": "private-evidence"}
    with pytest.raises(HomeAssistantError, match="maintenance_storage_unavailable"):
        await fresh.async_submit("restart", uuid4().hex, datetime.now(UTC).isoformat(),
                                 None, rig.context)
    assert rig.events == [] and FENCE_KEY not in hass.data


async def test_wrong_running_version_fails_after_boot_not_installed_version(node_rig):
    rig = node_rig
    await rig.submit()
    await rig.finish()
    await rig.node.async_shutdown()
    fresh = await rig.reboot("0.12.39")
    result = await fresh.async_status()
    assert result["phase"] == "failed" and result["error"] == "verification_failed"
    assert rig.native.async_install.call_count == 1
    assert rig.native.async_request_restart.call_count == 1


async def test_restart_watchdog_marks_unknown_without_retrying_or_retaining_fence(hass, node_rig):
    rig = node_rig
    await rig.submit()
    await rig.finish()
    assert hass.data[FENCE_KEY]
    await rig.node._restart_not_observed()
    assert rig.node.record["phase"] == "unknown"
    assert rig.node.record["error"] == "restart_not_observed"
    assert FENCE_KEY not in hass.data
    assert rig.native.async_request_restart.call_count == 1
    assert rig.native.async_install.call_count == 1


async def test_operator_settings_preserved_only_matching_boot_can_verify(hass, node_rig):
    rig = node_rig
    before_data, before_options = dict(rig.entry.data), dict(rig.entry.options)
    await rig.submit()
    assert (await rig.finish())["phase"] == "restart_requested"
    assert dict(rig.entry.data) == before_data and dict(rig.entry.options) == before_options
    assert (await rig.node.async_status())["phase"] == "restart_requested"
    await rig.node.async_shutdown()
    hass.config_entries.async_update_entry(rig.entry, data={"reserve_kwh": 4})
    fresh = await rig.reboot()
    assert (await fresh.async_status())["phase"] == "failed"


async def test_integration_reload_is_not_a_new_boot_or_new_running_code(hass, node_rig):
    rig = node_rig
    await rig.submit()
    await rig.finish()
    reload = NodeMaintenance(hass, "0.12.40")
    try:
        await reload.async_restore()
        assert reload.boot_id == rig.node.boot_id
        assert reload.running_version == "0.12.39"
        assert (await reload.async_status())["phase"] == "restart_requested"
        assert rig.native.async_request_restart.call_count == 1
    finally:
        await reload.async_shutdown()


async def test_post_boot_source_loading_gets_bounded_grace_not_false_verification(
    node_rig, freezer,
):
    rig = node_rig
    await rig.submit()
    await rig.finish()
    await rig.node.async_shutdown()
    rig.blockers.append("battery_telemetry_unavailable")
    fresh = await rig.reboot()
    assert (await fresh.async_status())["phase"] == "restart_requested"
    freezer.move_to(datetime.now(UTC) + timedelta(seconds=121))
    result = await fresh.async_status()
    assert result["phase"] == "failed" and result["error"] == "verification_failed"
    assert rig.native.async_install.call_count == 1
    assert rig.native.async_request_restart.call_count == 1


async def test_post_boot_recovered_sources_can_verify_without_any_replay(node_rig):
    rig = node_rig
    await rig.submit()
    await rig.finish()
    await rig.node.async_shutdown()
    rig.blockers.append("heo_storage_untrusted")
    fresh = await rig.reboot()
    assert (await fresh.async_status())["phase"] == "restart_requested"
    rig.blockers.clear()
    assert (await fresh.async_status())["phase"] == "verified"
    assert rig.native.async_install.call_count == 1
    assert rig.native.async_request_restart.call_count == 1


async def test_unloaded_entry_after_boot_times_out_without_false_success(
    hass, node_rig, monkeypatch, freezer,
):
    rig = node_rig
    await rig.submit()
    await rig.finish()
    await rig.node.async_shutdown()
    rig.entry._async_set_state(hass, ConfigEntryState.SETUP_ERROR, "failed")
    # Exercise the real health check: a failed entry gives _coordinators() an
    # empty result, not an endless exemption from the verification deadline.
    from custom_components.home_energy_orchestrator.maintenance_safety import (
        runtime_verification_blockers,
    )
    monkeypatch.setattr(module, "runtime_verification_blockers", runtime_verification_blockers)
    fresh = await rig.reboot()
    assert fresh._coordinators() == []
    assert (await fresh.async_status())["phase"] == "restart_requested"
    freezer.move_to(datetime.now(UTC) + timedelta(seconds=121))
    status = await fresh.async_status()
    assert status["phase"] == "failed" and status["error"] == "verification_failed"
    assert rig.native.async_request_restart.call_count == 1
    assert rig.native.async_install.call_count == 1
    assert FENCE_KEY not in hass.data


async def test_failed_explicit_restart_preserves_existing_download_obligation(node_rig):
    rig = node_rig
    rig.native.async_check_config.side_effect = [
        None, MaintenanceAdapterError("configuration_invalid"),
    ]
    await rig.submit()
    first = await rig.finish()
    assert first["phase"] == "restart_pending"
    original_backup = first["backup_id"]
    rig.native.async_create_verified_backup.side_effect = MaintenanceAdapterError("backup_failed")
    await rig.submit(action="restart", version=None,
                     issued_at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat())
    result = await rig.finish()
    assert result["restart_pending"] is True
    assert result["backup_id"] == original_backup
    assert result["installed_version"] == VERSION and result["running_version"] == "0.12.39"
    assert rig.native.async_install.call_count == 1


async def test_restore_checkpoint_failure_does_not_break_ordinary_heo_setup(
    hass, node_rig, monkeypatch,
):
    rig = node_rig
    rig.native.async_create_verified_backup.side_effect = MaintenanceAdapterError("backup_failed")
    await rig.submit()
    await rig.finish()
    await rig.node._repository.store.async_save({**rig.node.record, "phase": "installing"})
    monkeypatch.setattr(type(rig.node._repository), "async_save",
                        AsyncMock(side_effect=OSError("private filesystem detail")))
    fresh = await rig.reboot()
    assert fresh._trusted is False
    result = await fresh.async_status()
    assert "maintenance_storage_unavailable" in result["blockers"]
    assert fresh._task is None and FENCE_KEY not in hass.data


async def test_settings_change_during_pre_install_config_check_aborts(hass, node_rig):
    rig = node_rig

    async def check(_hass):
        hass.config_entries.async_update_entry(rig.entry, data={"reserve_kwh": 4})

    rig.native.async_check_config.side_effect = check
    await rig.submit()
    result = await rig.finish()
    assert result["error"] == "maintenance_settings_changed"
    rig.native.async_install.assert_not_called()
    rig.native.async_request_restart.assert_not_called()
    assert FENCE_KEY not in hass.data


@pytest.mark.parametrize("checkpoint", ["backing_up", "installing"])
@pytest.mark.parametrize("change", ["settings", "session"])
async def test_checkpoint_await_rechecks_before_backup_or_install(
    hass, node_rig, monkeypatch, checkpoint, change,
):
    """A durable phase checkpoint may yield while operator intent changes."""
    rig = node_rig
    original_phase = rig.node._phase

    async def phase(name, error=None, **values):
        await original_phase(name, error, **values)
        if name == checkpoint:
            if change == "settings":
                hass.config_entries.async_update_entry(rig.entry, data={"reserve_kwh": 4})
            else:
                rig.blockers.append("ev_session_active")

    monkeypatch.setattr(rig.node, "_phase", phase)
    await rig.submit()
    result = await rig.finish()
    assert result["phase"] == "failed"
    assert result["error"] == (
        "maintenance_settings_changed" if change == "settings" else "maintenance_no_longer_idle"
    )
    assert rig.native.async_create_verified_backup.call_count == (
        0 if checkpoint == "backing_up" else 1
    )
    rig.native.async_install.assert_not_called()
    rig.native.async_request_restart.assert_not_called()
    assert FENCE_KEY not in hass.data


async def test_backup_checkpoint_storage_failure_cannot_advance_to_install(
    hass, node_rig, monkeypatch,
):
    rig = node_rig
    original = rig.node._repository.async_save

    async def save(value):
        if value["phase"] == "checking":
            raise OSError("private disk path")
        await original(value)

    monkeypatch.setattr(type(rig.node._repository), "async_save", AsyncMock(side_effect=save))
    await rig.submit()
    result = await rig.finish()
    assert "maintenance_storage_unavailable" in result["blockers"]
    assert result["error"] == "maintenance_storage_unavailable"
    rig.native.async_install.assert_not_called()
    rig.native.async_request_restart.assert_not_called()
    assert FENCE_KEY not in hass.data
