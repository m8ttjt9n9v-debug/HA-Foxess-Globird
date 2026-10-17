"""Narrow native HA/HACS boundaries for explicitly authorised maintenance.

This module is not an updater. HACS remains the only installer; Home Assistant
remains responsible for backup, configuration validation, and restart. These
functions do not grant permission, pause a controller, or retry an operation.
The caller must enforce administrator authorisation and its maintenance lease.
Optional integrations are inspected lazily so absence cannot break HEO setup.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from homeassistant.core import Context, HomeAssistant

DOMAIN = "home_energy_orchestrator"
REPOSITORY = "m8ttjt9n9v-debug/HA-Foxess-Globird"
_STABLE_TAG = re.compile(r"v?\d+\.\d+\.\d+\Z")
_MANIFEST = Path(__file__).with_name("manifest.json")
_CATALOG_HYDRATION = "heo_hacs_catalog_hydration"
_CATALOG_REFRESH_TIMEOUT_SECONDS = 10


@dataclass(slots=True)
class _CatalogHydration:
    """One native warm attempt per verified repository instance and process."""

    repository: Any
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    attempted: bool = False


class MaintenanceAdapterError(Exception):
    """Expose a bounded safe code, never a provider exception or credential."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _version(value: object):
    """Accept only a stable release tag, not branches, commits, or local builds."""
    from packaging.version import Version

    if not isinstance(value, str) or _STABLE_TAG.fullmatch(value) is None:
        raise MaintenanceAdapterError("release_version_invalid")
    return Version(value)


def _hacs_binding(hass: HomeAssistant) -> tuple[Any, Any]:
    """Bind a renamed update entity to this exact installed HACS repository."""
    from homeassistant.components.update import DATA_COMPONENT, UpdateEntity, UpdateEntityFeature
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import entity_registry as er

    hacs = hass.data.get("hacs")
    if hacs is None or hacs.system.disabled or hacs.status.startup:
        raise MaintenanceAdapterError("hacs_unavailable")
    entry = hacs.configuration.config_entry
    if (
        entry is None
        or entry.domain != "hacs"
        or entry.state is not ConfigEntryState.LOADED
        or hass.config_entries.async_get_entry(entry.entry_id) is not entry
    ):
        raise MaintenanceAdapterError("hacs_unavailable")
    repository = hacs.repositories.get_by_full_name(REPOSITORY)
    if repository is None:
        raise MaintenanceAdapterError("hacs_repository_unavailable")
    data = repository.data
    if (
        not isinstance(data.full_name, str)
        or data.full_name.casefold() != REPOSITORY.casefold()
        or data.category != "integration"
        or data.domain != DOMAIN
        or data.installed is not True
        or data.releases is not True
        or not str(data.id).isdecimal()
        or int(data.id) <= 0
    ):
        raise MaintenanceAdapterError("hacs_repository_mismatch")
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("update", "hacs", str(data.id))
    registered = registry.async_get(entity_id) if entity_id else None
    component = hass.data.get(DATA_COMPONENT)
    entity = component.get_entity(entity_id) if component and entity_id else None
    if (
        registered is None
        or registered.config_entry_id != entry.entry_id
        or registered.disabled_by is not None
        or not isinstance(entity, UpdateEntity)
        or getattr(entity, "repository", None) is not repository
        or not entity.available
        or not hass.services.has_service("update", "install")
    ):
        raise MaintenanceAdapterError("hacs_entity_mismatch")
    required = UpdateEntityFeature.INSTALL | UpdateEntityFeature.SPECIFIC_VERSION
    if entity.supported_features & required != required:
        raise MaintenanceAdapterError("hacs_install_unsupported")
    if entity.installed_version != repository.display_installed_version:
        raise MaintenanceAdapterError("hacs_installed_version_mismatch")
    # A commit installation must first be deliberately changed through HACS.
    _version(entity.installed_version)
    return repository, entity


def _catalog(repository: Any, entity: Any) -> dict[str, object]:
    """Use HACS's cached published releases; do not create a second API poller."""
    tags = repository.data.published_tags
    releases = repository.releases.objects
    if not isinstance(tags, list) or not isinstance(releases, list):
        raise MaintenanceAdapterError("hacs_catalog_unsupported")
    if not releases:
        # Persisted tag strings alone cannot establish draft/prerelease status.
        raise MaintenanceAdapterError("hacs_capability_unavailable")
    versions: list[str] = []
    for release in releases:
        tag = release.tag_name
        if (
            release.draft is not False
            or release.prerelease is not False
            or tag not in tags
            or not isinstance(tag, str)
            or _STABLE_TAG.fullmatch(tag) is None
            or tag in versions
        ):
            continue
        versions.append(tag)
    return {
        "entity_id": entity.entity_id,
        "installed_version": entity.installed_version,
        "versions": versions,
        "in_progress": entity.in_progress is not False,
    }


async def async_hacs_catalog(hass: HomeAssistant) -> dict[str, object]:
    """Use verified HACS releases, warming its cold native cache at most once.

    HACS may restore neither published tags nor release-model objects after
    boot. An empty valid tag list is a cold cache, not an identity failure. Use
    its native refresh once, not a new reader or a periodic failed-fetch loop.
    Refreshed published membership and explicit stable metadata remain required.
    """
    try:
        repository, entity = _hacs_binding(hass)
        releases = repository.releases.objects
        if not isinstance(releases, list) or releases:
            return _catalog(repository, entity)
        tags = repository.data.published_tags
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise MaintenanceAdapterError("hacs_catalog_unsupported")
        provider = hass.data["hacs"]
        hydrations = hass.data.setdefault(_CATALOG_HYDRATION, {})
        hydration = hydrations.setdefault(id(repository), _CatalogHydration(repository))
        async with hydration.lock:
            rebound_repository, rebound_entity = _hacs_binding(hass)
            if (
                hass.data.get("hacs") is not provider
                or rebound_repository is not repository
                or rebound_entity is not entity
            ):
                raise MaintenanceAdapterError("hacs_entity_mismatch")
            if not repository.releases.objects and not hydration.attempted:
                # Consume before awaiting: cancellation/failure never schedules
                # another network request on the next maintenance status poll.
                hydration.attempted = True
                try:
                    async with asyncio.timeout(_CATALOG_REFRESH_TIMEOUT_SECONDS):
                        await repository.update_repository(ignore_issues=True, force=True)
                except Exception:
                    raise MaintenanceAdapterError("hacs_capability_unavailable") from None
            rebound_repository, rebound_entity = _hacs_binding(hass)
            if (
                hass.data.get("hacs") is not provider
                or rebound_repository is not repository
                or rebound_entity is not entity
            ):
                raise MaintenanceAdapterError("hacs_entity_mismatch")
            return _catalog(repository, entity)
    except MaintenanceAdapterError:
        raise
    except Exception:
        raise MaintenanceAdapterError("hacs_capability_unavailable") from None


def _read_manifest_version() -> str:
    """Read only our installed manifest, off the event loop."""
    contents = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(contents, dict) or contents.get("domain") != DOMAIN:
        raise MaintenanceAdapterError("installed_manifest_invalid")
    value = contents.get("version")
    _version(value)
    return value


async def async_install(hass: HomeAssistant, version: str, context: Context) -> None:
    """Pin one approved newer stable release through the real update service."""
    try:
        selected = _version(version)
        # Status/admission may warm HACS earlier. Do not introduce a metadata
        # network await between the node's final idle checkpoint and this write;
        # a cache lost meanwhile must fail closed for deliberate reassessment.
        catalog = _catalog(*_hacs_binding(hass))
        if version not in catalog["versions"]:
            raise MaintenanceAdapterError("release_not_available")
        if selected <= _version(catalog["installed_version"]):
            raise MaintenanceAdapterError("release_not_newer")
        if catalog["in_progress"]:
            raise MaintenanceAdapterError("hacs_install_busy")
        await hass.services.async_call(
            "update",
            "install",
            {"entity_id": catalog["entity_id"], "version": version, "backup": False},
            blocking=True,
            context=context,
        )
        _, entity = _hacs_binding(hass)
        if _version(entity.installed_version) != selected:
            raise MaintenanceAdapterError("downloaded_version_mismatch")
        installed = await hass.async_add_executor_job(_read_manifest_version)
        if _version(installed) != selected:
            raise MaintenanceAdapterError("installed_manifest_mismatch")
    except MaintenanceAdapterError:
        raise
    except Exception:
        # A timeout/error can occur after files were changed. Do not retry here.
        raise MaintenanceAdapterError("hacs_install_failed") from None


async def async_create_verified_backup(hass: HomeAssistant, request_id: str) -> dict[str, str]:
    """Wait for a correlated native HA+database backup on a known local agent."""
    try:
        from homeassistant.components.backup import async_get_manager
        from homeassistant.components.backup.manager import BackupManagerState
        from homeassistant.const import __version__ as ha_version

        if not isinstance(request_id, str) or not request_id or len(request_id) > 120:
            raise MaintenanceAdapterError("backup_request_invalid")
        manager = async_get_manager(hass)
        if manager.state is not BackupManagerState.IDLE:
            raise MaintenanceAdapterError("backup_busy")
        # Supervisor's local agent is not a LocalBackupAgent; do not take the
        # first cloud agent or assume local_backup_agents contains HAOS storage.
        agent_id = next(
            (agent for agent in ("hassio.local", "backup.local") if agent in manager.backup_agents),
            None,
        )
        if agent_id is None:
            raise MaintenanceAdapterError("local_backup_unavailable")
        before, errors = await manager.async_get_backups()
        if agent_id in errors:
            raise MaintenanceAdapterError("backup_evidence_unavailable")
        marker = {"heo_maintenance_request": request_id}
        if any(
            backup.extra_metadata.get("heo_maintenance_request") == request_id
            for backup in before.values()
        ):
            raise MaintenanceAdapterError("backup_request_reused")
        # Preserve the operator's existing key. No new password, external
        # destination, or automatic-backup retention policy is introduced.
        password = manager.config.data.create_backup.password
        await manager.async_create_backup(
            agent_ids=[agent_id],
            extra_metadata=marker,
            include_addons=None,
            include_all_addons=False,
            include_database=True,
            include_folders=None,
            include_homeassistant=True,
            name="HEO pre-maintenance backup",
            password=password,
        )
        if manager.state is not BackupManagerState.IDLE:
            raise MaintenanceAdapterError("backup_not_verified")
        # NewBackup.backup_job_id is NOT a backup ID on HAOS. Correlate the
        # completed archive instead of adopting an old last-backup timestamp.
        backups, errors = await manager.async_get_backups()
        if agent_id in errors:
            raise MaintenanceAdapterError("backup_evidence_unavailable")
        matched = [
            backup
            for backup in backups.values()
            if backup.extra_metadata.get("heo_maintenance_request") == request_id
        ]
        if len(matched) != 1:
            raise MaintenanceAdapterError("backup_not_verified")
        backup = matched[0]
        # Read this exact archive back from the manager, not just the creation
        # job response. Native providers check its existence before returning.
        verified, errors = await manager.async_get_backup(backup.backup_id)
        agent = verified.agents.get(agent_id) if verified is not None else None
        if (
            agent_id in errors
            or verified is None
            or verified.backup_id != backup.backup_id
            or not isinstance(verified.backup_id, str)
            or not verified.backup_id
            or verified.extra_metadata.get("heo_maintenance_request") != request_id
            or verified.homeassistant_included is not True
            or verified.database_included is not True
            or verified.homeassistant_version != ha_version
            or verified.failed_agent_ids
            or verified.failed_addons
            or verified.failed_folders
            or agent is None
            or isinstance(agent.size, bool)
            or not isinstance(agent.size, int)
            or agent.size <= 0
        ):
            raise MaintenanceAdapterError("backup_not_verified")
        return {"backup_id": verified.backup_id, "agent_id": agent_id}
    except MaintenanceAdapterError:
        raise
    except Exception:
        raise MaintenanceAdapterError("backup_failed") from None


async def async_check_config(hass: HomeAssistant) -> None:
    """Run Home Assistant's native configuration validator, failing closed."""
    try:
        from homeassistant.config import async_check_ha_config_file

        if await async_check_ha_config_file(hass) is not None:
            raise MaintenanceAdapterError("configuration_invalid")
    except MaintenanceAdapterError:
        raise
    except Exception:
        raise MaintenanceAdapterError("configuration_check_failed") from None


async def async_request_restart(hass: HomeAssistant, context: Context) -> None:
    """Request the native restart once; success means scheduled, not rebooted."""
    try:
        if not hass.services.has_service("homeassistant", "restart"):
            raise MaintenanceAdapterError("restart_unavailable")
        await hass.services.async_call(
            "homeassistant", "restart", {}, blocking=True, context=context
        )
    except MaintenanceAdapterError:
        raise
    except Exception:
        raise MaintenanceAdapterError("restart_request_failed") from None
