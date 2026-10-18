"""Exercise narrow maintenance adapters at native HA service boundaries."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.update import DATA_COMPONENT, UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator import maintenance_adapter as adapter


class FakeHacsUpdate(UpdateEntity):
    """Only HACS's external download is fake; native HA install dispatch is real."""

    _attr_name = "HEO update"
    _attr_should_poll = False
    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.SPECIFIC_VERSION
    _attr_in_progress = False

    def __init__(self, repository):
        self.repository = repository
        self._attr_unique_id = str(repository.data.id)
        self.calls = []
        self.error = None
        self.downloaded_version = None

    @property
    def installed_version(self):
        return self.repository.display_installed_version

    @property
    def latest_version(self):
        return "v0.12.40"

    async def async_install(self, version, backup, **kwargs):
        self.calls.append((version, backup))
        if self.error:
            raise self.error
        self.repository.display_installed_version = self.downloaded_version or version


async def _hacs(hass):
    """Use HA's real registry and UpdateEntity service registration."""
    assert await async_setup_component(hass, "update", {})
    entry = MockConfigEntry(domain="hacs")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    repository = SimpleNamespace(
        data=SimpleNamespace(
            id="12345",
            full_name=adapter.REPOSITORY,
            category="integration",
            domain=adapter.DOMAIN,
            installed=True,
            releases=True,
            published_tags=["v0.12.40", "v0.12.39"],
        ),
        releases=SimpleNamespace(
            objects=[
                SimpleNamespace(tag_name="v0.12.40", draft=False, prerelease=False),
                SimpleNamespace(tag_name="v0.12.39", draft=False, prerelease=False),
            ]
        ),
        display_installed_version="v0.12.39",
        update_repository=AsyncMock(),
    )

    async def native_metadata_success(**kwargs):
        # HACS replaces release-model and published-tag lists on a completed
        # native metadata fetch, including a fetch with unchanged versions.
        repository.releases.objects = list(repository.releases.objects)
        repository.data.published_tags = list(repository.data.published_tags)
        repository.data.releases = True

    repository.update_repository.side_effect = native_metadata_success
    hacs = SimpleNamespace(
        system=SimpleNamespace(disabled=False),
        status=SimpleNamespace(startup=False),
        configuration=SimpleNamespace(config_entry=entry),
        repositories=SimpleNamespace(get_by_full_name=Mock(return_value=repository)),
    )
    hass.data["hacs"] = hacs
    component = hass.data[DATA_COMPONENT]
    platform = component._async_init_entity_platform("hacs", None)
    platform.config_entry = entry
    component._platforms["hacs"] = platform
    entity = FakeHacsUpdate(repository)
    await platform.async_add_entities([entity])
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    registry.async_update_entity(entity.entity_id, new_entity_id="update.my_renamed_heo_release")
    await hass.async_block_till_done()
    return hacs, repository, entity


async def test_catalog_binds_renamed_entity_by_repository_id(hass):
    hacs, repository, entity = await _hacs(hass)
    result = await adapter.async_hacs_catalog(hass)
    assert result == {
        "entity_id": "update.my_renamed_heo_release",
        "installed_version": "v0.12.39",
        "versions": ["v0.12.40", "v0.12.39"],
        "in_progress": False,
    }
    assert entity.entity_id == result["entity_id"]
    # Rebind after acquiring the shared metadata lock, even for a warm read.
    assert hacs.repositories.get_by_full_name.call_count == 2
    hacs.repositories.get_by_full_name.assert_called_with(adapter.REPOSITORY)
    repository.update_repository.assert_not_called()
    assert not entity.calls


async def test_explicit_refresh_updates_warm_catalog_and_does_not_install(hass, monkeypatch):
    _, repository, entity = await _hacs(hass)
    clock = [100.0]
    monkeypatch.setattr(adapter, "monotonic", lambda: clock[0])
    assert (await adapter.async_hacs_catalog(hass))["versions"][0] == "v0.12.40"

    async def refresh(**kwargs):
        assert kwargs == {"ignore_issues": True, "force": True}
        repository.data.published_tags.insert(0, "v0.12.43")
        repository.releases.objects = [
            SimpleNamespace(tag_name="v0.12.43", draft=False, prerelease=False),
            *repository.releases.objects,
        ]

    repository.update_repository.side_effect = refresh
    result = await adapter.async_refresh_hacs_catalog(hass)
    assert result["versions"] == ["v0.12.43", "v0.12.40", "v0.12.39"]
    assert result["release_last_checked"].endswith("+00:00")
    assert await adapter.async_refresh_hacs_catalog(hass) == result
    clock[0] = 130.0
    # Ordinary polling never gains a refresh timer, even after cooldown.
    assert (await adapter.async_hacs_catalog(hass))["versions"] == result["versions"]
    repository.update_repository.assert_awaited_once_with(ignore_issues=True, force=True)
    assert (await adapter.async_refresh_hacs_catalog(hass))["versions"] == result["versions"]
    assert repository.update_repository.await_count == 2
    assert entity.calls == []


@pytest.mark.parametrize("cold_first", [False, True])
async def test_explicit_and_cold_refresh_share_one_inflight_operation(hass, cold_first):
    _, repository, entity = await _hacs(hass)
    releases = repository.releases.objects
    repository.releases.objects = []
    entered, finish = asyncio.Event(), asyncio.Event()

    async def refresh(**kwargs):
        entered.set()
        await finish.wait()
        repository.releases.objects = releases

    repository.update_repository.side_effect = refresh
    first_call = adapter.async_hacs_catalog if cold_first else adapter.async_refresh_hacs_catalog
    second_call = adapter.async_refresh_hacs_catalog if cold_first else adapter.async_hacs_catalog
    first = asyncio.create_task(first_call(hass))
    await entered.wait()
    others = [asyncio.create_task(second_call(hass)) for _ in range(3)]
    await asyncio.sleep(0)
    finish.set()
    results = await asyncio.gather(first, *others)
    assert all(result["versions"] == ["v0.12.40", "v0.12.39"] for result in results)
    repository.update_repository.assert_awaited_once()
    assert entity.calls == []


@pytest.mark.parametrize("failure", ["provider", "empty", "malformed", "timeout"])
async def test_failed_explicit_refresh_retains_catalog_without_retry_or_stale_install(
    hass, monkeypatch, failure,
):
    _, repository, entity = await _hacs(hass)
    clock = [100.0]
    monkeypatch.setattr(adapter, "monotonic", lambda: clock[0])
    previous = await adapter.async_hacs_catalog(hass)

    async def refresh(**kwargs):
        repository.releases.objects = []
        if failure == "provider":
            raise RuntimeError("Bearer PRIVATE at private host")
        if failure == "malformed":
            repository.data.published_tags = [None]
        if failure == "timeout":
            await asyncio.Event().wait()

    repository.update_repository.side_effect = refresh
    monkeypatch.setattr(adapter, "_CATALOG_REFRESH_TIMEOUT_SECONDS", 0.001)
    for _ in range(2):
        with pytest.raises(adapter.MaintenanceAdapterError) as error:
            await adapter.async_refresh_hacs_catalog(hass)
        assert str(error.value) in {"hacs_catalog_unsupported", "hacs_capability_unavailable"}
        assert await adapter.async_hacs_catalog(hass) == previous
    repository.update_repository.assert_awaited_once()
    with pytest.raises(adapter.MaintenanceAdapterError):
        await adapter.async_install(hass, "v0.12.40", Context())
    assert not entity.calls
    # A later explicit action, not a status read, may deliberately try again.
    clock[0] = 130.0
    repository.data.published_tags = ["v0.12.43"]

    async def recover(**kwargs):
        repository.releases.objects = [
            SimpleNamespace(tag_name="v0.12.43", draft=False, prerelease=False),
        ]

    repository.update_repository.side_effect = recover
    assert (await adapter.async_refresh_hacs_catalog(hass))["versions"] == ["v0.12.43"]
    assert repository.update_repository.await_count == 2


@pytest.mark.parametrize("after_success", [False, True])
async def test_explicit_refresh_rejects_busy_install_even_during_cooldown(hass, after_success):
    _, repository, entity = await _hacs(hass)
    if after_success:
        await adapter.async_refresh_hacs_catalog(hass)
    calls_before = repository.update_repository.await_count
    entity._attr_in_progress = True
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_install_busy"):
        await adapter.async_refresh_hacs_catalog(hass)
    assert repository.update_repository.await_count == calls_before
    assert entity.calls == []


async def test_install_starting_during_metadata_fetch_cannot_report_refresh_success(hass):
    _, repository, entity = await _hacs(hass)

    async def refresh(**kwargs):
        entity._attr_in_progress = True

    repository.update_repository.side_effect = refresh
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_install_busy"):
        await adapter.async_refresh_hacs_catalog(hass)
    repository.update_repository.assert_awaited_once()
    assert entity.calls == []


@pytest.mark.parametrize("change", ["repository", "entity", "provider"])
async def test_explicit_refresh_revalidates_binding_after_native_await(hass, change):
    hacs, repository, entity = await _hacs(hass)

    async def refresh(**kwargs):
        if change == "repository":
            replacement = SimpleNamespace(**vars(repository))
            hacs.repositories.get_by_full_name.return_value = replacement
            entity.repository = replacement
        elif change == "entity":
            replacement = FakeHacsUpdate(repository)
            replacement.entity_id = entity.entity_id
            hass.data[DATA_COMPONENT].get_entity = Mock(return_value=replacement)
        else:
            hass.data["hacs"] = SimpleNamespace(**vars(hacs))

    repository.update_repository.side_effect = refresh
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_entity_mismatch"):
        await adapter.async_refresh_hacs_catalog(hass)
    assert entity.calls == []


@pytest.mark.parametrize("change", ["provider", "entity"])
@pytest.mark.parametrize("soft_failure", [False, True])
async def test_failed_refresh_catalog_cannot_cross_later_binding_replacement(
    hass, change, soft_failure,
):
    hacs, repository, entity = await _hacs(hass)
    await adapter.async_hacs_catalog(hass)

    async def refresh(**kwargs):
        repository.releases.objects = []
        repository.data.releases = not soft_failure
        raise RuntimeError("metadata failed")

    repository.update_repository.side_effect = refresh
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
        await adapter.async_refresh_hacs_catalog(hass)
    assert (await adapter.async_hacs_catalog(hass))["versions"] == ["v0.12.40", "v0.12.39"]
    if change == "provider":
        hass.data["hacs"] = SimpleNamespace(**vars(hacs))
    else:
        replacement = FakeHacsUpdate(repository)
        replacement.entity_id = entity.entity_id
        hass.data[DATA_COMPONENT].get_entity = Mock(return_value=replacement)
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
        await adapter.async_hacs_catalog(hass)
    repository.update_repository.assert_awaited_once()
    assert entity.calls == []


async def test_parallel_status_cannot_replace_validated_catalog_with_partial_failed_fetch(hass):
    _, repository, entity = await _hacs(hass)
    previous = await adapter.async_hacs_catalog(hass)
    entered, finish = asyncio.Event(), asyncio.Event()

    async def refresh(**kwargs):
        repository.data.published_tags = []  # A valid-looking partial native mutation.
        entered.set()
        await finish.wait()
        raise RuntimeError("Bearer PRIVATE at private host")

    repository.update_repository.side_effect = refresh
    refresh_task = asyncio.create_task(adapter.async_refresh_hacs_catalog(hass))
    await entered.wait()
    status_task = asyncio.create_task(adapter.async_hacs_catalog(hass))
    await asyncio.sleep(0)
    assert not status_task.done()
    finish.set()
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
        await refresh_task
    assert await status_task == previous
    assert await adapter.async_hacs_catalog(hass) == previous
    repository.update_repository.assert_awaited_once()
    assert entity.calls == []


async def test_cancelled_explicit_refresh_retains_choices_and_consumes_cooldown(hass):
    _, repository, entity = await _hacs(hass)
    previous = await adapter.async_hacs_catalog(hass)
    entered = asyncio.Event()

    async def refresh(**kwargs):
        repository.releases.objects = []
        entered.set()
        await asyncio.Event().wait()

    repository.update_repository.side_effect = refresh
    task = asyncio.create_task(adapter.async_refresh_hacs_catalog(hass))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await adapter.async_hacs_catalog(hass) == previous
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
        await adapter.async_refresh_hacs_catalog(hass)
    repository.update_repository.assert_awaited_once()
    assert entity.calls == []


@pytest.mark.parametrize("tags", [None, (), {}, "v0.12.40", [None], ["v0.12.40", 42]])
async def test_explicit_refresh_rejects_malformed_catalog_before_native_call(hass, tags):
    _, repository, entity = await _hacs(hass)
    repository.data.published_tags = tags
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_catalog_unsupported"):
        await adapter.async_refresh_hacs_catalog(hass)
    repository.update_repository.assert_not_called()
    assert entity.calls == []


async def test_explicit_refresh_retains_exact_stable_published_filters(hass):
    _, repository, entity = await _hacs(hass)

    async def refresh(**kwargs):
        repository.data.published_tags = [
            "v0.12.43", "v0.12.44", "v0.12.45", "v0.12.46rc1", "main", "v0.12.47",
        ]
        repository.releases.objects = [
            SimpleNamespace(tag_name=tag, draft=draft, prerelease=prerelease)
            for tag, draft, prerelease in [
                ("v0.12.43", False, False), ("v0.12.44", True, False),
                ("v0.12.45", False, True), ("v0.12.46rc1", False, False),
                ("main", False, False), ("v0.12.48", False, False),
                ("v0.12.47", None, False),
            ]
        ]

    repository.update_repository.side_effect = refresh
    assert (await adapter.async_refresh_hacs_catalog(hass))["versions"] == ["v0.12.43"]
    assert entity.calls == []


@pytest.mark.parametrize("soft_failure", [False, True])
async def test_native_return_without_fresh_release_models_never_claims_checked_success(
    hass, soft_failure,
):
    _, repository, entity = await _hacs(hass)
    previous = await adapter.async_hacs_catalog(hass)
    original_models = repository.releases.objects
    original_tags = repository.data.published_tags

    async def swallowed_or_noop(**kwargs):
        # A swallowed HACS release-fetch error can return None, advance its
        # last_fetched marker, and retain models/tags from an earlier fetch.
        repository.last_fetched = 1790000000
        if soft_failure:
            repository.data.releases = False

    repository.update_repository.side_effect = swallowed_or_noop
    with pytest.raises(adapter.MaintenanceAdapterError) as error:
        await adapter.async_refresh_hacs_catalog(hass)
    assert error.value.code in {"hacs_capability_unavailable", "hacs_repository_mismatch"}
    state = adapter._hydration(hass, repository)
    assert state.last_checked is None
    assert state.last_catalog == previous
    assert repository.releases.objects is original_models
    assert repository.data.published_tags is original_tags
    assert await adapter.async_hacs_catalog(hass) == previous
    if soft_failure:
        with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_repository_mismatch"):
            await adapter.async_install(hass, "v0.12.40", Context())
    assert entity.calls == []
    repository.update_repository.assert_awaited_once_with(ignore_issues=True, force=True)


async def test_unchanged_release_versions_with_new_native_models_is_a_verified_check(hass):
    _, repository, entity = await _hacs(hass)
    previous = await adapter.async_hacs_catalog(hass)
    old_models = repository.releases.objects
    result = await adapter.async_refresh_hacs_catalog(hass)
    assert repository.releases.objects is not old_models
    assert result["versions"] == previous["versions"]
    assert result["release_last_checked"].endswith("+00:00")
    assert entity.calls == []


async def test_explicit_metadata_check_recovers_swallowed_hacs_release_failure(
    hass, monkeypatch,
):
    _, repository, entity = await _hacs(hass)
    clock = [100.0]
    monkeypatch.setattr(adapter, "monotonic", lambda: clock[0])
    previous = await adapter.async_hacs_catalog(hass)

    async def soft_failure(**kwargs):
        repository.data.releases = False

    repository.update_repository.side_effect = soft_failure
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
        await adapter.async_refresh_hacs_catalog(hass)
    assert await adapter.async_hacs_catalog(hass) == previous
    assert adapter._hydration(hass, repository).last_checked is None
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_repository_mismatch"):
        await adapter.async_install(hass, "v0.12.40", Context())
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
        await adapter.async_refresh_hacs_catalog(hass)
    repository.update_repository.assert_awaited_once()
    clock[0] = 130.0

    async def recovery(**kwargs):
        repository.data.releases = True
        repository.data.published_tags = ["v0.12.43"]
        repository.releases.objects = [
            SimpleNamespace(tag_name="v0.12.43", draft=False, prerelease=False),
        ]

    repository.update_repository.side_effect = recovery
    result = await adapter.async_refresh_hacs_catalog(hass)
    assert result["versions"] == ["v0.12.43"]
    assert result["release_last_checked"].endswith("+00:00")
    assert (await adapter.async_hacs_catalog(hass))["versions"] == ["v0.12.43"]
    assert repository.update_repository.await_count == 2
    assert entity.calls == []


async def test_release_false_without_exact_prior_catalog_cannot_use_or_autowarm_cache(hass):
    _, repository, entity = await _hacs(hass)
    repository.data.releases = False
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
        await adapter.async_hacs_catalog(hass)
    repository.update_repository.assert_not_called()
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_repository_mismatch"):
        await adapter.async_install(hass, "v0.12.40", Context())
    assert entity.calls == []
    # Only an explicit metadata check can recover this known exact repository.
    result = await adapter.async_refresh_hacs_catalog(hass)
    assert result["versions"] == ["v0.12.40", "v0.12.39"]
    assert repository.data.releases is True
    repository.update_repository.assert_awaited_once()
    assert entity.calls == []


async def test_cold_boot_hydrates_native_hacs_cache_once(hass):
    _, repository, entity = await _hacs(hass)
    releases = repository.releases.objects
    repository.releases.objects = []

    async def warm(**kwargs):
        assert kwargs == {"ignore_issues": True, "force": True}
        repository.releases.objects = releases

    repository.update_repository.side_effect = warm
    first = await adapter.async_hacs_catalog(hass)
    assert first["versions"] == ["v0.12.40", "v0.12.39"]
    assert await adapter.async_hacs_catalog(hass) == first
    repository.update_repository.assert_awaited_once_with(ignore_issues=True, force=True)
    assert not entity.calls


async def test_concurrent_cold_status_reads_share_one_native_hydration(hass):
    _, repository, entity = await _hacs(hass)
    releases = repository.releases.objects
    repository.releases.objects = []
    entered, finish = asyncio.Event(), asyncio.Event()

    async def warm(**kwargs):
        entered.set()
        await finish.wait()
        repository.releases.objects = releases

    repository.update_repository.side_effect = warm
    first = asyncio.create_task(adapter.async_hacs_catalog(hass))
    await entered.wait()
    others = [asyncio.create_task(adapter.async_hacs_catalog(hass)) for _ in range(3)]
    await asyncio.sleep(0)
    assert repository.update_repository.await_count == 1
    finish.set()
    results = await asyncio.gather(first, *others)
    assert all(result["versions"] == ["v0.12.40", "v0.12.39"] for result in results)
    repository.update_repository.assert_awaited_once()
    assert not entity.calls


@pytest.mark.parametrize("failure", ["provider_error", "empty"])
async def test_failed_cold_hydration_is_explicit_and_never_polled_again(hass, failure):
    _, repository, entity = await _hacs(hass)
    repository.releases.objects = []
    if failure == "provider_error":
        repository.update_repository.side_effect = RuntimeError("Bearer PRIVATE at private host")
    for _ in range(3):
        with pytest.raises(adapter.MaintenanceAdapterError) as error:
            await adapter.async_hacs_catalog(hass)
        assert str(error.value) == "hacs_capability_unavailable"
    repository.update_repository.assert_awaited_once()
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
        await adapter.async_install(hass, "v0.12.40", Context())
    assert not entity.calls
    repository.update_repository.assert_awaited_once()


@pytest.mark.parametrize("change", ["repository", "entity", "provider"])
async def test_cold_hydration_cannot_mix_replaced_native_binding(hass, change):
    hacs, repository, entity = await _hacs(hass)
    releases = repository.releases.objects
    repository.releases.objects = []

    async def warm(**kwargs):
        repository.releases.objects = releases
        if change == "repository":
            replacement = SimpleNamespace(
                data=repository.data, releases=repository.releases,
                display_installed_version=repository.display_installed_version,
            )
            hacs.repositories.get_by_full_name.return_value = replacement
            entity.repository = replacement
        elif change == "entity":
            replacement = FakeHacsUpdate(repository)
            replacement.entity_id = entity.entity_id
            component = hass.data[DATA_COMPONENT]
            component.get_entity = Mock(return_value=replacement)
        else:
            hass.data["hacs"] = SimpleNamespace(**vars(hacs))

    repository.update_repository.side_effect = warm
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_entity_mismatch"):
        await adapter.async_hacs_catalog(hass)
    assert not entity.calls


async def test_cold_hydration_deadline_cancels_native_wait_and_never_retries(hass, monkeypatch):
    _, repository, entity = await _hacs(hass)
    repository.releases.objects = []
    cancelled = asyncio.Event()

    async def warm(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    repository.update_repository.side_effect = warm
    monkeypatch.setattr(adapter, "_CATALOG_REFRESH_TIMEOUT_SECONDS", 0.001)
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
        await adapter.async_hacs_catalog(hass)
    assert cancelled.is_set()
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
        await adapter.async_hacs_catalog(hass)
    repository.update_repository.assert_awaited_once()
    assert entity.calls == []


async def test_explicit_cancellation_also_consumes_single_cold_hydration_attempt(hass):
    _, repository, entity = await _hacs(hass)
    repository.releases.objects = []
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def warm(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    repository.update_repository.side_effect = warm
    task = asyncio.create_task(adapter.async_hacs_catalog(hass))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
        await adapter.async_hacs_catalog(hass)
    repository.update_repository.assert_awaited_once()
    assert entity.calls == []


async def test_cold_native_models_retain_strict_stable_and_published_filters(hass):
    _, repository, _ = await _hacs(hass)
    repository.releases.objects = []
    published_tags = repository.data.published_tags + ["v0.12.41", "v0.12.42", "v0.12.43rc1"]
    repository.data.published_tags = []

    async def warm(**kwargs):
        repository.data.published_tags = published_tags
        repository.releases.objects = [
            SimpleNamespace(tag_name="v0.12.41", draft=False, prerelease=True),
            SimpleNamespace(tag_name="v0.12.42", draft=True, prerelease=False),
            SimpleNamespace(tag_name="v0.12.43rc1", draft=False, prerelease=False),
            SimpleNamespace(tag_name="v0.12.44", draft=False, prerelease=False),
            SimpleNamespace(tag_name="v0.12.40", draft=False, prerelease=False),
        ]

    repository.update_repository.side_effect = warm
    assert (await adapter.async_hacs_catalog(hass))["versions"] == ["v0.12.40"]
    repository.update_repository.assert_awaited_once_with(ignore_issues=True, force=True)


async def test_final_installer_refuses_cold_cache_until_prior_status_warm(hass):
    _, repository, entity = await _hacs(hass)
    releases = repository.releases.objects
    repository.releases.objects = []

    async def warm(**kwargs):
        repository.releases.objects = releases

    repository.update_repository.side_effect = warm
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
        await adapter.async_install(hass, "v0.12.40", Context())
    repository.update_repository.assert_not_called()
    assert entity.calls == []
    assert (await adapter.async_hacs_catalog(hass))["versions"] == ["v0.12.40", "v0.12.39"]
    with patch.object(adapter, "_read_manifest_version", return_value="0.12.40"):
        await adapter.async_install(hass, "v0.12.40", Context())
    repository.update_repository.assert_awaited_once()
    assert entity.calls == [("v0.12.40", False)]


async def test_actual_cold_restore_with_empty_models_and_tags_warms_both_once(hass):
    _, repository, entity = await _hacs(hass)
    releases = repository.releases.objects
    tags = repository.data.published_tags
    repository.releases.objects = []
    repository.data.published_tags = []

    async def warm(**kwargs):
        assert repository.releases.objects == [] and repository.data.published_tags == []
        assert kwargs == {"ignore_issues": True, "force": True}
        repository.releases.objects = releases
        repository.data.published_tags = tags

    repository.update_repository.side_effect = warm
    result = await adapter.async_hacs_catalog(hass)
    assert result["versions"] == ["v0.12.40", "v0.12.39"]
    assert result["entity_id"] == entity.entity_id
    assert await adapter.async_hacs_catalog(hass) == result
    repository.update_repository.assert_awaited_once_with(ignore_issues=True, force=True)
    assert not entity.calls


async def test_native_refresh_without_tag_population_cannot_admit_install_or_retry(hass):
    _, repository, entity = await _hacs(hass)
    releases = repository.releases.objects
    repository.releases.objects = []
    repository.data.published_tags = []

    async def models_only(**kwargs):
        repository.releases.objects = releases

    repository.update_repository.side_effect = models_only
    for _ in range(3):
        assert (await adapter.async_hacs_catalog(hass))["versions"] == []
    with pytest.raises(adapter.MaintenanceAdapterError, match="release_not_available"):
        await adapter.async_install(hass, "v0.12.40", Context())
    repository.update_repository.assert_awaited_once()
    assert not entity.calls


async def test_native_refresh_of_only_tags_cannot_replace_release_metadata(hass):
    _, repository, entity = await _hacs(hass)
    repository.releases.objects = []
    repository.data.published_tags = []

    async def tags_only(**kwargs):
        repository.data.published_tags = ["v0.12.40"]

    repository.update_repository.side_effect = tags_only
    for _ in range(3):
        with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
            await adapter.async_hacs_catalog(hass)
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_capability_unavailable"):
        await adapter.async_install(hass, "v0.12.40", Context())
    repository.update_repository.assert_awaited_once()
    assert not entity.calls


@pytest.mark.parametrize("tags", [None, (), {}, "v0.12.40", [None], ["v0.12.40", 42]])
async def test_malformed_cold_tags_never_trigger_native_warm(hass, tags):
    _, repository, entity = await _hacs(hass)
    repository.releases.objects = []
    repository.data.published_tags = tags
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_catalog_unsupported"):
        await adapter.async_hacs_catalog(hass)
    repository.update_repository.assert_not_called()
    assert not entity.calls


async def test_catalog_only_uses_cached_stable_published_tags(hass):
    _, repository, _ = await _hacs(hass)
    for tag, draft, prerelease in [
        ("v0.12.41", True, False),
        ("v0.12.42rc1", False, True),
        ("main", False, False),
        ("a" * 40, False, False),
        ("0.12.41+local", False, False),
        ("0.12.41.dev1", False, False),
    ]:
        repository.data.published_tags.append(tag)
        repository.releases.objects.append(
            SimpleNamespace(tag_name=tag, draft=draft, prerelease=prerelease)
        )
    repository.releases.objects.append(
        SimpleNamespace(tag_name="v0.12.43", draft=False, prerelease=False)
    )
    result = await adapter.async_hacs_catalog(hass)
    assert result["versions"] == ["v0.12.40", "v0.12.39"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("full_name", "another/repository"),
        ("category", "plugin"),
        ("domain", "another_integration"),
        ("installed", False),
        ("releases", False),
        ("id", "0"),
        ("id", "not-a-repository-id"),
    ],
)
async def test_repository_identity_mismatch_blocks_catalog_and_install(hass, field, value):
    _, repository, entity = await _hacs(hass)
    repository.releases.objects = []
    repository.data.published_tags = []
    setattr(repository.data, field, value)
    with pytest.raises(adapter.MaintenanceAdapterError):
        await adapter.async_hacs_catalog(hass)
    with pytest.raises(adapter.MaintenanceAdapterError):
        await adapter.async_install(hass, "v0.12.40", Context())
    repository.update_repository.assert_not_called()
    assert entity.calls == []


@pytest.mark.parametrize("failure", ["missing", "shape", "disabled", "startup", "unloaded"])
async def test_missing_or_unsupported_hacs_is_only_a_maintenance_failure(hass, failure):
    hacs, _, _ = await _hacs(hass)
    if failure == "missing":
        hass.data.pop("hacs")
    elif failure == "shape":
        hass.data["hacs"] = object()
    elif failure == "disabled":
        hacs.system.disabled = True
    elif failure == "startup":
        hacs.status.startup = True
    else:
        hacs.configuration.config_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    with pytest.raises(adapter.MaintenanceAdapterError) as error:
        await adapter.async_hacs_catalog(hass)
    assert str(error.value) == error.value.code
    assert "http" not in str(error.value)


async def test_unrelated_runtime_entity_cannot_adopt_a_registry_match(hass):
    _, _, entity = await _hacs(hass)
    entity.repository = SimpleNamespace()
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_entity_mismatch"):
        await adapter.async_hacs_catalog(hass)


@pytest.mark.parametrize("failure", ["component", "service", "feature", "disabled", "releases"])
async def test_missing_install_capability_cannot_be_guessed(hass, failure):
    _, repository, entity = await _hacs(hass)
    if failure == "component":
        hass.data.pop(DATA_COMPONENT)
    elif failure == "service":
        hass.services.async_remove("update", "install")
    elif failure == "feature":
        entity._attr_supported_features = UpdateEntityFeature.INSTALL
    elif failure == "disabled":
        er.async_get(hass).async_update_entity(
            entity.entity_id, disabled_by=er.RegistryEntryDisabler.USER
        )
    else:
        repository.releases.objects = None
    with pytest.raises(adapter.MaintenanceAdapterError):
        await adapter.async_hacs_catalog(hass)


@pytest.mark.parametrize("busy", [True, 0, 55, None])
async def test_any_non_false_install_progress_blocks_another_download(hass, busy):
    _, _, entity = await _hacs(hass)
    entity._attr_in_progress = busy
    with pytest.raises(adapter.MaintenanceAdapterError, match="hacs_install_busy"):
        await adapter.async_install(hass, "v0.12.40", Context())
    assert not entity.calls


async def test_install_uses_native_update_service_exact_tag_and_context(hass):
    _, _, entity = await _hacs(hass)
    events = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, events.append)
    context = Context()
    with patch.object(adapter, "_read_manifest_version", return_value="0.12.40"):
        await adapter.async_install(hass, "v0.12.40", context)
    await hass.async_block_till_done()
    assert entity.calls == [("v0.12.40", False)]
    event = next(e for e in events if e.data["domain"] == "update")
    assert event.context is context
    assert event.data["service_data"] == {
        "entity_id": "update.my_renamed_heo_release",
        "version": "v0.12.40",
        "backup": False,
    }


async def test_install_revalidates_catalog_after_a_previous_display(hass):
    _, repository, entity = await _hacs(hass)
    assert "v0.12.40" in (await adapter.async_hacs_catalog(hass))["versions"]
    repository.data.published_tags.remove("v0.12.40")
    with pytest.raises(adapter.MaintenanceAdapterError, match="release_not_available"):
        await adapter.async_install(hass, "v0.12.40", Context())
    assert not entity.calls


@pytest.mark.parametrize("version", ["main", "v0.12.40rc1", "v0.12.39", "v0.12.38", "0.12.40"])
async def test_install_rejects_arbitrary_old_or_non_exact_versions(hass, version):
    _, _, entity = await _hacs(hass)
    with pytest.raises(adapter.MaintenanceAdapterError):
        await adapter.async_install(hass, version, Context())
    assert not entity.calls


@pytest.mark.parametrize("failure", ["provider", "downloaded", "manifest"])
async def test_failed_or_mismatched_download_never_requests_restart(hass, failure):
    _, _, entity = await _hacs(hass)
    if failure == "provider":
        entity.error = HomeAssistantError("Bearer SECRET at http://private.example")
    if failure == "downloaded":
        entity.downloaded_version = "v0.12.41"
    manifest = "0.12.41" if failure == "manifest" else "0.12.40"
    restart = AsyncMock()
    hass.services.async_register("homeassistant", "restart", restart)
    with (
        patch.object(adapter, "_read_manifest_version", return_value=manifest),
        pytest.raises(adapter.MaintenanceAdapterError) as error,
    ):
        await adapter.async_install(hass, "v0.12.40", Context())
    assert "SECRET" not in str(error.value)
    assert "private" not in str(error.value)
    assert len(entity.calls) == 1
    restart.assert_not_called()


@pytest.mark.parametrize(
    "contents", ['{}', '{"domain":"other","version":"0.12.40"}', '{"domain":']
)
async def test_installed_manifest_is_validated_off_loop(hass, tmp_path, contents):
    await _hacs(hass)
    path = tmp_path / "manifest.json"
    path.write_text(contents)
    with (
        patch.object(adapter, "_MANIFEST", path),
        pytest.raises(adapter.MaintenanceAdapterError),
    ):
        await adapter.async_install(hass, "v0.12.40", Context())


def _backup(hass, *, agent_id="hassio.local"):
    from homeassistant.components.backup.manager import BackupManagerState

    archives = {}
    manager = SimpleNamespace(
        state=BackupManagerState.IDLE,
        backup_agents={agent_id: object()},
        config=SimpleNamespace(
            data=SimpleNamespace(create_backup=SimpleNamespace(password="existing-private-key"))
        ),
        async_get_backups=AsyncMock(side_effect=lambda: (dict(archives), {})),
    )

    async def create(**kwargs):
        archives["native-archive-id"] = SimpleNamespace(
            backup_id="native-archive-id",
            agents={agent_id: SimpleNamespace(size=4096)},
            extra_metadata=dict(kwargs["extra_metadata"]),
            homeassistant_included=True,
            database_included=True,
            homeassistant_version=HA_VERSION,
            failed_agent_ids=[],
            failed_addons=[],
            failed_folders=[],
        )
        # HAOS returns a different job ID. Adopting this as the backup ID fails.
        return SimpleNamespace(backup_job_id="creation-job-not-archive-id")

    manager.async_create_backup = AsyncMock(side_effect=create)
    manager.async_get_backup = AsyncMock(side_effect=lambda key: (archives.get(key), {}))
    hass.data["backup"] = manager
    return manager, archives


@pytest.mark.parametrize("agent_id", ["hassio.local", "backup.local"])
async def test_backup_is_completed_correlated_and_read_back(hass, agent_id):
    manager, _ = _backup(hass, agent_id=agent_id)
    result = await adapter.async_create_verified_backup(hass, "request-123")
    assert result == {"backup_id": "native-archive-id", "agent_id": agent_id}
    kwargs = manager.async_create_backup.call_args.kwargs
    assert kwargs == {
        "agent_ids": [agent_id],
        "extra_metadata": {"heo_maintenance_request": "request-123"},
        "include_addons": None,
        "include_all_addons": False,
        "include_database": True,
        "include_folders": None,
        "include_homeassistant": True,
        "name": "HEO pre-maintenance backup",
        "password": "existing-private-key",
    }
    manager.async_get_backup.assert_awaited_once_with("native-archive-id")
    assert "existing-private-key" not in str(result)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("homeassistant_included", False),
        ("database_included", False),
        ("homeassistant_version", "ancient"),
        ("failed_agent_ids", ["hassio.local"]),
        ("failed_addons", ["something"]),
        ("failed_folders", ["ssl"]),
        ("agents", {}),
        ("agents", {"hassio.local": SimpleNamespace(size=0)}),
        ("agents", {"hassio.local": SimpleNamespace(size=True)}),
    ],
)
async def test_partial_or_empty_backup_fails_closed(hass, field, value):
    manager, _ = _backup(hass)
    original = manager.async_get_backup.side_effect

    def incomplete(key):
        backup, errors = original(key)
        setattr(backup, field, value)
        return backup, errors

    manager.async_get_backup.side_effect = incomplete
    with pytest.raises(adapter.MaintenanceAdapterError, match="backup_not_verified"):
        await adapter.async_create_verified_backup(hass, "request-123")


@pytest.mark.parametrize("failure", ["missing", "cloud_only", "busy", "provider", "listing"])
async def test_backup_missing_capability_or_provider_failure_is_sanitized(hass, failure):
    from homeassistant.components.backup.manager import BackupManagerState

    manager, _ = _backup(hass)
    if failure == "missing":
        hass.data.pop("backup")
    elif failure == "cloud_only":
        manager.backup_agents = {"some.cloud": object()}
    elif failure == "busy":
        manager.state = BackupManagerState.CREATE_BACKUP
    elif failure == "provider":
        manager.async_create_backup.side_effect = HomeAssistantError("Bearer SECRET /private/file")
    else:
        manager.async_get_backups.return_value = ({}, {"hassio.local": RuntimeError("SECRET")})
        manager.async_get_backups.side_effect = None
    with pytest.raises(adapter.MaintenanceAdapterError) as error:
        await adapter.async_create_verified_backup(hass, "request-123")
    assert "SECRET" not in str(error.value)
    assert "/private" not in str(error.value)


async def test_an_existing_backup_cannot_be_adopted_by_reusing_request_id(hass):
    manager, _ = _backup(hass)
    await adapter.async_create_verified_backup(hass, "request-123")
    with pytest.raises(adapter.MaintenanceAdapterError, match="backup_request_reused"):
        await adapter.async_create_verified_backup(hass, "request-123")
    assert manager.async_create_backup.await_count == 1


async def test_missing_or_uncorrelated_created_archive_is_not_success(hass):
    manager, archives = _backup(hass)
    original = manager.async_create_backup.side_effect

    async def uncorrelated(**kwargs):
        result = await original(**kwargs)
        archives["native-archive-id"].extra_metadata = {}
        return result

    manager.async_create_backup.side_effect = uncorrelated
    with pytest.raises(adapter.MaintenanceAdapterError, match="backup_not_verified"):
        await adapter.async_create_verified_backup(hass, "request-123")


async def test_create_response_does_not_prove_backup_job_completed(hass):
    from homeassistant.components.backup.manager import BackupManagerState

    manager, _ = _backup(hass)
    original = manager.async_create_backup.side_effect

    async def still_in_progress(**kwargs):
        result = await original(**kwargs)
        manager.state = BackupManagerState.CREATE_BACKUP
        return result

    manager.async_create_backup.side_effect = still_in_progress
    with pytest.raises(adapter.MaintenanceAdapterError, match="backup_not_verified"):
        await adapter.async_create_verified_backup(hass, "request-123")


async def test_configuration_adapter_runs_actual_native_yaml_validation(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    path = Path(hass.config.path("configuration.yaml"))
    path.write_text("{}\n")
    await adapter.async_check_config(hass)
    path.write_text("homeassistant: [broken\n")
    with pytest.raises(adapter.MaintenanceAdapterError, match="configuration_invalid"):
        await adapter.async_check_config(hass)


async def test_configuration_provider_failure_is_sanitized(hass):
    with (
        patch(
            "homeassistant.config.async_check_ha_config_file", side_effect=RuntimeError("SECRET")
        ),
        pytest.raises(adapter.MaintenanceAdapterError, match="configuration_check_failed") as error,
    ):
        await adapter.async_check_config(hass)
    assert "SECRET" not in str(error.value)


async def test_restart_uses_native_service_context_and_stop_scheduler(hass):
    from homeassistant.components.homeassistant import async_set_stop_handler

    assert await async_setup_component(hass, "homeassistant", {})
    scheduler = AsyncMock()
    async_set_stop_handler(hass, scheduler)
    context = Context()
    events = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, events.append)
    with patch("homeassistant.config.async_check_ha_config_file", return_value=None):
        await adapter.async_request_restart(hass, context)
    await hass.async_block_till_done()
    scheduler.assert_awaited_once_with(hass, True)
    event = next(e for e in events if e.data["service"] == "restart")
    assert event.context is context


async def test_native_restart_configuration_rejection_never_calls_stop_scheduler(hass):
    from homeassistant.components.homeassistant import async_set_stop_handler

    assert await async_setup_component(hass, "homeassistant", {})
    scheduler = AsyncMock()
    async_set_stop_handler(hass, scheduler)
    with (
        patch("homeassistant.config.async_check_ha_config_file", return_value="private error"),
        pytest.raises(adapter.MaintenanceAdapterError, match="restart_request_failed"),
    ):
        await adapter.async_request_restart(hass, Context())
    scheduler.assert_not_called()


@pytest.mark.parametrize("failure", ["missing", "invalid_config", "provider"])
async def test_restart_missing_or_rejected_never_claims_completed_reboot(hass, failure):
    if failure != "missing":
        async def fail(_call):
            raise HomeAssistantError("SECRET private details")

        hass.services.async_register("homeassistant", "restart", fail)
    with pytest.raises(adapter.MaintenanceAdapterError) as error:
        await adapter.async_request_restart(hass, Context())
    assert str(error.value) in {"restart_unavailable", "restart_request_failed"}
    assert "SECRET" not in str(error.value)
