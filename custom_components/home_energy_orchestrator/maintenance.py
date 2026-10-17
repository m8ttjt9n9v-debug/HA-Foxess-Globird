"""One-site maintenance wrapper around HACS, backup and HA restart.

This never chooses a battery/EV policy or replays an interrupted operation.
Only the audit record survives boot; the brief actuator fence does not.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CoreState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from packaging.version import InvalidVersion, Version

from . import maintenance_adapter as adapter
from .const import DOMAIN
from .fleet_maintenance import PUBLIC_MAINTENANCE_CODES, async_require_admin
from .maintenance_barrier import KEY as FENCE_KEY
from .maintenance_safety import (
    maintenance_blockers,
    maintenance_locks,
    runtime_verification_blockers,
)
from .persistence import create_typed_value_repository

NODE_KEY = "heo_maintenance_node"
PHASES = {
    "waiting",
    "backing_up",
    "installing",
    "checking",
    "restart_requested",
    "restart_pending",
    "verified",
    "blocked",
    "failed",
    "interrupted",
    "unknown",
}
IN_PROGRESS = {"waiting", "backing_up", "installing", "checking", "restart_requested"}


def _time(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("naive_time")
    return result.astimezone(UTC)


def _decode(payload):
    if payload is None:
        return None
    if not isinstance(payload, dict) or type(payload.get("v")) is not int or payload["v"] != 1:
        raise ValueError("invalid_maintenance_record")
    required = {
        "v",
        "request_id",
        "action",
        "version",
        "issued_at",
        "expires_at",
        "boot_id",
        "settings_digest",
        "phase",
        "backup_id",
        "error",
    }
    if set(payload) != required or payload["phase"] not in PHASES:
        raise ValueError("invalid_maintenance_record")
    UUID(payload["request_id"])
    UUID(payload["boot_id"])
    if payload["action"] not in {"update_and_restart", "restart"}:
        raise ValueError("invalid_maintenance_record")
    if _time(payload["expires_at"]) <= _time(payload["issued_at"]):
        raise ValueError("invalid_maintenance_record")
    digest = payload["settings_digest"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("invalid_maintenance_record")
    for key in ("version", "backup_id", "error"):
        if payload[key] is not None and (
            not isinstance(payload[key], str) or len(payload[key]) > 160
        ):
            raise ValueError("invalid_maintenance_record")
    if not isinstance(payload["version"], str):
        raise ValueError("invalid_maintenance_record")
    Version(payload["version"].removeprefix("v"))
    if payload["error"] is not None and payload["error"] not in PUBLIC_MAINTENANCE_CODES:
        raise ValueError("invalid_maintenance_record")
    if (
        payload["backup_id"] is not None
        and re.fullmatch(
            r"[a-zA-Z0-9_-]{1,128}",
            payload["backup_id"],
        )
        is None
    ):
        raise ValueError("invalid_maintenance_record")
    return dict(payload)


class NodeMaintenance(DataUpdateCoordinator):
    """Host-wide, explicit maintenance; node evidence is authoritative."""

    def __init__(self, hass, running_version):
        super().__init__(
            hass,
            logging.getLogger(__name__),
            name="HEO maintenance",
            update_interval=timedelta(seconds=60),
            config_entry=None,
        )
        self.running_version = hass.data.setdefault("heo_running_version", str(running_version))
        self.boot_id = hass.data.setdefault("heo_maintenance_boot_id", uuid4().hex)
        self.boot_started = datetime.now(UTC)
        self.record = None
        self._task = None
        self._admission_lock = asyncio.Lock()
        self._repository = create_typed_value_repository(
            hass,
            storage_version=1,
            storage_key="home_energy_orchestrator.maintenance",
            decode=_decode,
            encode=lambda value: value,
        )
        self._trusted = False
        self._restart_watchdog = None

    async def async_restore(self):
        """Read the audit only. Never reinstall, restart or fence on setup."""
        try:
            self.record = await self._repository.async_load()
            self._trusted = self._repository.last_restore_status != "invalid"
        except Exception:  # storage failures cannot break ordinary HEO setup
            self._trusted = False
        if self.record and self.record["phase"] in IN_PROGRESS:
            if self.record["phase"] != "restart_requested":
                self.record = {**self.record, "phase": "interrupted", "error": "interrupted"}
                try:
                    await self._save()
                except HomeAssistantError:
                    self._trusted = False

    def _coordinators(self):
        entries = self.hass.config_entries.async_entries(DOMAIN)
        if not entries or any(entry.state != ConfigEntryState.LOADED for entry in entries):
            return []
        return [entry.runtime_data for entry in sorted(entries, key=lambda entry: entry.entry_id)]

    def _digest(self):
        entries = self.hass.config_entries.async_entries(DOMAIN)
        values = {
            entry.entry_id: {"data": dict(entry.data), "options": dict(entry.options)}
            for entry in entries
        }
        return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()

    async def _save(self):
        try:
            await self._repository.async_save(dict(self.record))
        except Exception as error:
            self._trusted = False
            raise HomeAssistantError("maintenance_storage_unavailable") from error

    async def _phase(self, phase, error=None, **changes):
        self.record = {**self.record, **changes, "phase": phase, "error": error}
        await self._save()
        self.async_set_updated_data(await self.async_status())

    async def _async_update_data(self):
        return await self.async_status()

    async def async_status(self):
        """Read-only capability, downloaded/running versions and audit status."""
        catalog = {}
        error = None
        try:
            catalog = await adapter.async_hacs_catalog(self.hass)
        except adapter.MaintenanceAdapterError as failure:
            error = failure.code
        if (
            self.record
            and self.record["phase"] == "restart_requested"
            and self.record["boot_id"] != self.boot_id
            and self.hass.state == CoreState.running
        ):
            expected = self.record["version"]
            healthy = not runtime_verification_blockers(self.hass, self._coordinators())
            same_version = _same_version(self.running_version, expected)
            preserved = self._digest() == self.record["settings_digest"]
            if healthy or (datetime.now(UTC) - self.boot_started).total_seconds() >= 120:
                await self._phase(
                    "verified" if healthy and same_version and preserved else "failed",
                    None if healthy and same_version and preserved else "verification_failed",
                )
        blockers = list(maintenance_blockers(self.hass, self._coordinators()))
        if not self._trusted:
            blockers.append("maintenance_storage_unavailable")
        record = self.record or {}
        phase = record.get("phase", "idle")
        return {
            "schema_version": 1,
            "phase": phase,
            "request_id": record.get("request_id"),
            "action": record.get("action"),
            "expected_version": record.get("version"),
            "running_version": self.running_version,
            "installed_version": catalog.get("installed_version"),
            "available_versions": catalog.get("versions", []),
            "blockers": blockers,
            "error": record.get("error") or error,
            "backup_id": record.get("backup_id"),
            "backup_verified": bool(record.get("backup_id")),
            "restart_pending": phase in {"restart_pending", "restart_requested"}
            or (
                bool(catalog.get("installed_version"))
                and not _same_version(catalog["installed_version"], self.running_version)
            ),
            "last_update": datetime.now(UTC).isoformat(),
        }

    async def async_submit(
        self,
        action,
        request_id,
        issued_at,
        version,
        context,
        wait_minutes=60,
    ):
        """Accept once, then execute locally even if the HTTP client disconnects."""
        await async_require_admin(self.hass, context)
        async with self._admission_lock:
            try:
                UUID(request_id)
                issued = _time(issued_at)
                if action not in {"update_and_restart", "restart"}:
                    raise ValueError
                if type(wait_minutes) not in {int, float} or not 1 <= wait_minutes <= 1440:
                    raise ValueError
                if action == "update_and_restart":
                    parsed = Version(version.removeprefix("v"))
                    if parsed.is_prerelease or parsed.is_devrelease:
                        raise ValueError
                else:
                    catalog = await adapter.async_hacs_catalog(self.hass)
                    version = catalog["installed_version"]
            except (ValueError, TypeError, AttributeError, InvalidVersion) as error:
                raise HomeAssistantError("invalid_maintenance_request") from error
            if self.record and self.record["request_id"] == request_id:
                if (self.record["action"], self.record["version"], self.record["issued_at"]) != (
                    action,
                    version,
                    issued_at,
                ):
                    raise HomeAssistantError("maintenance_request_conflict")
                return await self.async_status()
            age = (datetime.now(UTC) - issued).total_seconds()
            if age < -5 or age > 60 or (self.record and issued <= _time(self.record["issued_at"])):
                raise HomeAssistantError("stale_maintenance_request")
            if not self._trusted:
                raise HomeAssistantError("maintenance_storage_unavailable")
            if self._task is not None and not self._task.done():
                raise HomeAssistantError("maintenance_busy")
            if self.record and (
                self.record["phase"] == "restart_requested"
                or self.record["phase"] == "restart_pending"
                and action != "restart"
            ):
                raise HomeAssistantError("maintenance_verification_required")
            catalog = await adapter.async_hacs_catalog(self.hass)
            files_pending = not _same_version(catalog["installed_version"], self.running_version)
            if catalog["in_progress"]:
                raise HomeAssistantError("maintenance_busy")
            if files_pending and action == "update_and_restart":
                raise HomeAssistantError("maintenance_verification_required")
            if action == "update_and_restart":
                if version not in catalog["versions"]:
                    raise HomeAssistantError("release_not_available")
                if Version(version.removeprefix("v")) <= Version(
                    catalog["installed_version"].removeprefix("v"),
                ):
                    raise HomeAssistantError("release_not_newer")
            previous_backup = (
                self.record.get("backup_id")
                if self.record and (files_pending or self.record["phase"] == "restart_pending")
                else None
            )
            self.record = {
                "v": 1,
                "request_id": request_id,
                "action": action,
                "version": version,
                "issued_at": issued_at,
                "expires_at": (issued + timedelta(minutes=wait_minutes)).isoformat(),
                "boot_id": self.boot_id,
                "settings_digest": self._digest(),
                "phase": "waiting",
                "backup_id": previous_backup,
                "error": None,
            }
            await self._save()
            self._task = self.hass.async_create_background_task(
                self._run(context),
                "HEO explicit maintenance",
                eager_start=False,
            )
            return await self.async_status()

    def _check_current(self):
        if self._digest() != self.record["settings_digest"]:
            raise HomeAssistantError("maintenance_settings_changed")
        if datetime.now(UTC) >= _time(self.record["expires_at"]):
            raise HomeAssistantError("maintenance_expired")
        blockers = maintenance_blockers(self.hass, self._coordinators())
        if blockers:
            raise HomeAssistantError("maintenance_no_longer_idle")

    async def _run(self, context):
        installed = self.record["action"] == "restart" and not _same_version(
            self.record["version"],
            self.running_version,
        )
        restart_requested = False
        try:
            while maintenance_blockers(self.hass, self._coordinators()):
                if self._digest() != self.record["settings_digest"]:
                    raise HomeAssistantError("maintenance_settings_changed")
                if datetime.now(UTC) >= _time(self.record["expires_at"]):
                    raise HomeAssistantError("maintenance_expired")
                await asyncio.sleep(30)
            async with asyncio.timeout(1800), AsyncExitStack() as stack:
                for lock in maintenance_locks(self._coordinators()):
                    await stack.enter_async_context(lock)
                self._check_current()
                await async_require_admin(self.hass, context)
                self.hass.data[FENCE_KEY] = True
                await self._phase("backing_up")
                self._check_current()
                backup = await adapter.async_create_verified_backup(
                    self.hass,
                    self.record["request_id"],
                )
                self._check_current()
                await self._phase(
                    "checking", backup_id=self.record["backup_id"] or backup["backup_id"]
                )
                await adapter.async_check_config(self.hass)
                self._check_current()
                if self.record["action"] == "update_and_restart":
                    await async_require_admin(self.hass, context)
                    await self._phase("installing")
                    self._check_current()
                    installed = True  # A thrown/timeout call may have replaced files.
                    await adapter.async_install(self.hass, self.record["version"], context)
                    self._check_current()
                    await self._phase("checking")
                    await adapter.async_check_config(self.hass)
                    self._check_current()
                await self._phase("restart_requested")
                self._check_current()
                await async_require_admin(self.hass, context)
                self._check_current()
                # HA shutdown drains these locks. The process-local actuator
                # fence remains in place until stop or the bounded watchdog.
                await stack.aclose()
                self._check_current()
                await adapter.async_request_restart(self.hass, context)
                restart_requested = True
            # Do not hold reconciliation locks across HA shutdown/unload.
            self._restart_watchdog = self.hass.loop.call_later(
                120,
                lambda: self.hass.async_create_task(self._restart_not_observed()),
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            code = (
                error.code
                if isinstance(error, adapter.MaintenanceAdapterError)
                else str(error)
                if isinstance(error, HomeAssistantError)
                else "maintenance_failed"
            )
            if code not in PUBLIC_MAINTENANCE_CODES:
                code = "maintenance_failed"
            try:
                await self._phase("restart_pending" if installed else "failed", code)
            except HomeAssistantError:
                pass
        finally:
            if not restart_requested and self.hass.state == CoreState.running:
                self.hass.data.pop(FENCE_KEY, None)
            self.async_set_updated_data(await self.async_status())

    async def _restart_not_observed(self):
        if self.record["phase"] == "restart_requested":
            if self.hass.state == CoreState.running:
                self.hass.data.pop(FENCE_KEY, None)
            await self._phase("unknown", "restart_not_observed")

    async def async_shutdown(self):
        if self._restart_watchdog:
            self._restart_watchdog.cancel()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.hass.state == CoreState.running:
            self.hass.data.pop(FENCE_KEY, None)
        await super().async_shutdown()


def _same_version(left, right):
    try:
        return Version(left.removeprefix("v")) == Version(right.removeprefix("v"))
    except (InvalidVersion, AttributeError):
        return False
