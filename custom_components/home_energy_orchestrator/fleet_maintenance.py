"""Administrator-only Fleet maintenance dispatch and read-only status polling.

Endpoints and credentials come only from trusted backend configuration. This
coordinator is neither an updater nor a generic remote-service proxy: every
node remains responsible for its persistent lease, backup, idle checks and
one-shot HACS/install/restart sequence. An ambiguous request is never replayed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from aiohttp import ClientTimeout
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)
_DOMAIN = "home_energy_orchestrator"
_NODE = "heo_maintenance_node"
_LIMIT = 32 * 1024
_TIMEOUT = ClientTimeout(total=20)
_KEY = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
_VERSION = re.compile(r"v?\d{1,5}\.\d{1,5}\.\d{1,5}(?:(?:rc|a|b)\d{1,5})?\Z")
_ACTIONS = {
    "update_and_restart": "maintenance_update_and_restart",
    "restart": "maintenance_restart",
}


async def async_require_admin(hass: HomeAssistant, context: Context | None) -> None:
    """Require a current active administrator, not an anonymous automation."""
    user_id = context.user_id if isinstance(context, Context) else None
    user = await hass.auth.async_get_user(user_id) if user_id else None
    if user is None or not user.is_active or not user.is_admin:
        raise HomeAssistantError("HEO maintenance requires an active administrator")


def _version(value: object) -> str | None:
    return value if isinstance(value, str) and _VERSION.fullmatch(value) else None


def _request_id(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 36:
        return None
    try:
        UUID(value)
    except ValueError:
        return None
    return value


def _timestamp(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = dt_util.parse_datetime(value)
    except (ValueError, OverflowError):
        return None
    return parsed.isoformat() if parsed and parsed.tzinfo is not None else None


def _unknown() -> dict[str, object]:
    return {"phase": "unknown", "available_versions": [], "blockers": ["status_unavailable"]}


def _sanitize(value: object) -> dict[str, object]:
    """Allow public protocol fields only, never raw provider output or errors."""
    if not isinstance(value, dict):
        return _unknown()
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        return {
            "phase": "initial_update_required",
            "available_versions": [],
            "blockers": ["initial_update_required"],
        }
    phase = value.get("phase")
    # The protocol deliberately uses machine codes, not arbitrary remote text.
    if not isinstance(phase, str) or phase not in _PHASES:
        return _unknown()
    versions = value.get("available_versions", [])
    blockers = value.get("blockers", [])
    if (
        not isinstance(versions, list)
        or len(versions) > 100
        or any(_version(version) is None for version in versions)
        or not isinstance(blockers, list)
        or len(blockers) > 40
        or any(not isinstance(blocker, str) for blocker in blockers)
    ):
        return _unknown()
    result: dict[str, object] = {
        "schema_version": 1,
        "phase": phase,
        "available_versions": list(dict.fromkeys(versions)),
        "blockers": list(
            dict.fromkeys(
                blocker if blocker in _BLOCKERS else "node_reported_blocker" for blocker in blockers
            )
        ),
    }
    for key in ("running_version", "installed_version", "expected_version"):
        if (version := _version(value.get(key))) is not None:
            result[key] = version
    if (request_id := _request_id(value.get("request_id"))) is not None:
        result["request_id"] = request_id
    for key in ("accepted", "restart_pending", "busy", "backup_verified"):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    for key in ("issued_at", "last_update", "started_at", "deadline"):
        if (timestamp := _timestamp(value.get(key))) is not None:
            result[key] = timestamp
    if isinstance(value.get("action"), str) and value["action"] in _ACTIONS:
        result["action"] = value["action"]
    error = value.get("error")
    if isinstance(error, str):
        result["error"] = error if error in _BLOCKERS else "node_reported_error"
    return result


_PHASES = frozenset(
    {
        "idle",
        "waiting",
        "backing_up",
        "installing",
        "checking",
        "restart_requested",
        "restart_pending",
        "verified",
        "failed",
        "blocked",
        "unknown",
        "interrupted",
        "initial_update_required",
    }
)
_BLOCKERS = frozenset(
    {
        "status_unavailable",
        "initial_update_required",
        "active_battery_session",
        "active_ev_session",
        "active_session",
        "startup_pending",
        "not_running",
        "busy",
        "maintenance_busy",
        "hacs_unavailable",
        "hacs_repository_unavailable",
        "hacs_repository_mismatch",
        "hacs_entity_mismatch",
        "hacs_install_unsupported",
        "hacs_installed_version_mismatch",
        "hacs_catalog_unsupported",
        "hacs_capability_unavailable",
        "release_version_invalid",
        "release_not_available",
        "release_not_newer",
        "hacs_install_busy",
        "downloaded_version_mismatch",
        "installed_manifest_invalid",
        "installed_manifest_mismatch",
        "backup_unavailable",
        "backup_failed",
        "backup_not_verified",
        "configuration_invalid",
        "configuration_check_failed",
        "restart_failed",
        "restart_unavailable",
        "restart_not_confirmed",
        "request_expired",
        "request_invalid",
        "storage_unavailable",
        "storage_invalid",
        "storage_failed",
        "runtime_unavailable",
        "runtime_version_mismatch",
        "settings_changed",
        "integration_not_loaded",
        "integration_error",
        "unsupported",
        "permission_denied",
        "outcome_unknown",
        "operation_interrupted",
        "stale_request",
        "request_conflict",
        "maintenance_storage_unavailable",
        "invalid_maintenance_request",
        "maintenance_request_conflict",
        "stale_maintenance_request",
        "maintenance_verification_required",
        "maintenance_settings_changed",
        "maintenance_expired",
        "maintenance_no_longer_idle",
        "maintenance_failed",
        "interrupted",
        "verification_failed",
        "restart_not_observed",
        "hacs_install_failed",
        "backup_request_invalid",
        "backup_busy",
        "local_backup_unavailable",
        "backup_evidence_unavailable",
        "backup_request_reused",
        "restart_request_failed",
        "home_assistant_not_running",
        "heo_runtime_unavailable",
        "heo_storage_untrusted",
        "battery_charge_session_active",
        "battery_export_session_active",
        "battery_diagnostic_active",
        "battery_manual_control_active",
        "trip_charge_active",
        "ev_full_charge_active",
        "battery_telemetry_unavailable",
        "battery_mode_feedback_unavailable",
        "battery_not_self_use",
        "battery_force_target_not_clear",
        "ev_session_active",
        "ev_reconciliation_pending",
        "ev_recovery_pending",
        "ev_charging_target_active",
        "ev_feedback_unavailable",
        "ev_physically_charging",
        "ev_charge_switch_on",
        "ev_full_feedback_unavailable",
    }
)


PUBLIC_MAINTENANCE_CODES = _BLOCKERS


class FleetMaintenanceHub(DataUpdateCoordinator[dict[str, dict[str, object]]]):
    """Poll fixed nodes and dispatch one explicit maintenance action per site."""

    def __init__(self, hass: HomeAssistant, targets: list[dict[str, object]]) -> None:
        super().__init__(
            hass, _LOGGER, name="HEO Fleet maintenance", update_interval=timedelta(seconds=60),
            config_entry=None,
        )
        self._targets = self.validate_targets(targets)
        self.selected_versions: dict[str, str] = {}
        self._generation = dict.fromkeys(self._targets, 0)
        self._locks = {key: asyncio.Lock() for key in self._targets}
        self.data = {key: _unknown() for key in self._targets}

    @staticmethod
    def validate_targets(targets):
        """Share validation with HA Check Configuration, before any restart."""
        targets_by_key = {}
        for target in targets:
            key, name = target.get("key"), target.get("name")
            if (
                not isinstance(key, str)
                or not _KEY.fullmatch(key)
                or key in targets_by_key
                or not isinstance(name, str)
                or not name.strip()
                or len(name) > 80
                or type(target.get("local")) is not bool
            ):
                raise HomeAssistantError("Invalid HEO maintenance target configuration")
            configured = {"key": key, "name": name, "local": target["local"]}
            if not target["local"]:
                origin, token = target.get("origin"), target.get("token")
                try:
                    parsed = urlsplit(origin) if isinstance(origin, str) else None
                    valid = (
                        parsed is not None
                        and parsed.scheme in {"http", "https"}
                        and parsed.hostname
                        and parsed.username is None
                        and parsed.password is None
                        and parsed.path in {"", "/"}
                        and not parsed.query
                        and not parsed.fragment
                        and parsed.port != 0
                    )
                except ValueError:
                    valid = False
                if (
                    not valid
                    or not isinstance(token, str)
                    or not token.strip()
                    or len(token) > 4096
                    or "\r" in token
                    or "\n" in token
                ):
                    raise HomeAssistantError("Invalid HEO maintenance target configuration")
                configured |= {"origin": origin.rstrip("/"), "token": token.strip()}
            elif any(item["local"] for item in targets_by_key.values()):
                raise HomeAssistantError("Only one local HEO maintenance target is allowed")
            targets_by_key[key] = configured
        return targets_by_key

    @property
    def targets(self) -> tuple[dict[str, object], ...]:
        """Expose UI identity without transport configuration or credentials."""
        return tuple(
            {field: target[field] for field in ("key", "name", "local")}
            for target in self._targets.values()
        )

    def _target(self, key: str) -> dict[str, object]:
        if key not in self._targets:
            raise HomeAssistantError("Unknown HEO maintenance target")
        return self._targets[key]

    async def async_select_version(self, key: str, version: str) -> None:
        """Select only a published version advertised by this exact node."""
        self._target(key)
        if _version(version) is None or version not in self.data[key].get("available_versions", []):
            raise HomeAssistantError("Selected HEO release is not available on this site")
        self.selected_versions[key] = version
        self.async_set_updated_data(dict(self.data))

    async def _remote(
        self, target: dict[str, object], service: str, payload: dict[str, object]
    ) -> object:
        token = target["token"]
        authorization = token if token.startswith("Bearer ") else f"Bearer {token}"
        url = f"{target['origin']}/api/services/{_DOMAIN}/{service}?return_response"
        session = async_get_clientsession(self.hass)
        async with session.post(
            url,
            json=payload,
            headers={"Authorization": authorization},
            timeout=_TIMEOUT,
            allow_redirects=False,
        ) as response:
            if response.status == 404:
                return {}
            if response.status != 200:
                raise ValueError("unusable_status")
            body = bytearray()
            async for chunk in response.content.iter_chunked(4096):
                body.extend(chunk)
                if len(body) > _LIMIT:
                    raise ValueError("response_limit")
            envelope = json.loads(body)
            if not isinstance(envelope, dict) or not isinstance(
                envelope.get("service_response"), dict
            ):
                raise ValueError("unusable_envelope")
            return envelope["service_response"]

    async def _read_status(self, key: str) -> dict[str, object]:
        target = self._target(key)
        try:
            if target["local"]:
                node = self.hass.data.get(_NODE)
                value = await node.async_status() if node is not None else None
            else:
                value = await self._remote(target, "maintenance_status", {})
            return _sanitize(value)
        except Exception:
            return _unknown()

    async def _async_update_data(self) -> dict[str, dict[str, object]]:
        """Only read status; do not start, retry or resume any operation."""
        keys = tuple(self._targets)
        generations = dict(self._generation)
        responses = await asyncio.gather(*(self._read_status(key) for key in keys))
        data = dict(self.data)
        for key, response in zip(keys, responses, strict=True):
            if generations[key] == self._generation[key] and not self._locks[key].locked():
                data[key] = response
        return data

    async def async_request(self, key: str, action: str, context: Context) -> dict[str, object]:
        """Submit once; an ambiguous result is unknown, never permission to retry."""
        await async_require_admin(self.hass, context)
        target = self._target(key)
        if action not in _ACTIONS:
            raise HomeAssistantError("Unsupported HEO maintenance action")
        lock = self._locks[key]
        if lock.locked():
            raise HomeAssistantError("HEO maintenance request is already in progress")
        async with lock:
            status = await self._read_status(key)
            if status.get("schema_version") != 1:
                self.async_set_updated_data(self.data | {key: status})
                raise HomeAssistantError(
                    "HEO maintenance status is unavailable or needs an initial update"
                )
            version = self.selected_versions.get(key) if action == "update_and_restart" else None
            if action == "update_and_restart" and version not in status["available_versions"]:
                raise HomeAssistantError("Selected HEO release is no longer available on this site")
            self._generation[key] += 1
            generation = self._generation[key]
            request_id = uuid4().hex
            payload = {
                "request_id": request_id,
                "issued_at": dt_util.utcnow().isoformat(),
                "wait_minutes": 60,
            }
            if version is not None:
                payload["version"] = version
            self.async_set_updated_data(
                self.data
                | {
                    key: status
                    | {
                        "phase": "submitting",
                        "request_id": request_id,
                        "action": action,
                    }
                }
            )
            try:
                if target["local"]:
                    node = self.hass.data.get(_NODE)
                    value = (
                        await node.async_submit(
                            action=action, context=context, **(payload | {"version": version})
                        )
                        if node is not None
                        else None
                    )
                else:
                    value = await self._remote(target, _ACTIONS[action], payload)
                result = _sanitize(value)
                if (
                    result.get("request_id") != request_id
                    or result.get("schema_version") != 1
                    or result.get("action") != action
                    or action == "update_and_restart"
                    and result.get("expected_version") != version
                ):
                    result = _unknown() | {"request_id": request_id, "action": action}
            except Exception:
                result = _unknown() | {"request_id": request_id, "action": action}
            if self._generation[key] == generation:
                self.async_set_updated_data(self.data | {key: result})
            return result
