"""Explicit service endpoints for the commissioning test surface."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    SERVICE_TEST_FORCE_CHARGE,
    SERVICE_TEST_FORCE_DISCHARGE,
    SERVICE_TEST_STOP,
)
from .fleet_maintenance import async_require_admin
from .maintenance import NODE_KEY
from .maintenance_barrier import maintenance_writes_blocked
from .manual_inverter import ManualInverterError
from .manual_test import ManualTestError

TEST_SCHEMA = vol.Schema(
    {
        vol.Optional("power_kw"): vol.Coerce(float),
        vol.Optional("duration_minutes"): vol.Coerce(float),
        vol.Optional("entry_id"): str,
    }
)
MANUAL_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("local_control_confirmed", default=False): bool,
        vol.Optional("request_id"): vol.All(str, vol.Length(min=1, max=120)),
        vol.Optional("issued_at"): str,
    }
)
MANUAL_SERVICES = {
    "manual_export_max": "export_max",
    "manual_self_use": "self_use",
    "manual_resume_automatic": "automatic",
}


def register_services(hass: HomeAssistant) -> None:
    """Register services once for the integration domain."""
    if hass.services.has_service(DOMAIN, SERVICE_TEST_FORCE_CHARGE):
        return

    async def start_charge(call: ServiceCall) -> None:
        controller = _controller(hass, call.data.get("entry_id"))
        await _async_start(
            controller,
            "charge",
            call.data.get("power_kw", controller.charge_power_kw),
            call.data.get("duration_minutes", controller.duration_minutes),
        )

    async def start_discharge(call: ServiceCall) -> None:
        controller = _controller(hass, call.data.get("entry_id"))
        await _async_start(
            controller,
            "discharge",
            call.data.get("power_kw", controller.discharge_power_kw),
            call.data.get("duration_minutes", controller.duration_minutes),
        )

    async def stop(call: ServiceCall) -> None:
        await _controller(hass, call.data.get("entry_id")).async_stop()

    hass.services.async_register(DOMAIN, SERVICE_TEST_FORCE_CHARGE, start_charge, TEST_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_TEST_FORCE_DISCHARGE, start_discharge, TEST_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_TEST_STOP, stop, TEST_SCHEMA)

    async def manual_request(call: ServiceCall) -> dict[str, object]:
        if maintenance_writes_blocked(hass):
            raise HomeAssistantError("maintenance_in_progress")
        controller = _controller(hass, call.data.get("entry_id"))
        automatic = getattr(controller.coordinator, "active_controller", None)
        if automatic is None:
            raise HomeAssistantError("manual inverter control is not available")
        try:
            return await automatic.manual.async_request(
                MANUAL_SERVICES[call.service],
                local_control_confirmed=call.data["local_control_confirmed"],
                request_id=call.data.get("request_id"),
                issued_at=call.data.get("issued_at"),
            )
        except ManualInverterError as error:
            raise HomeAssistantError(str(error)) from error

    for name in MANUAL_SERVICES:
        hass.services.async_register(
            DOMAIN,
            name,
            manual_request,
            MANUAL_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

    async def maintenance_status(call):
        return await hass.data[NODE_KEY].async_status()

    async def maintenance_refresh_releases(call):
        return await hass.data[NODE_KEY].async_refresh_releases(call.context)

    async def maintenance_request(call):
        return await hass.data[NODE_KEY].async_submit(
            "update_and_restart" if call.service == "maintenance_update_and_restart" else "restart",
            call.data["request_id"], call.data["issued_at"], call.data.get("version"),
            call.context, call.data["wait_minutes"],
        )

    hass.services.async_register(
        DOMAIN, "maintenance_status", maintenance_status, vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "maintenance_refresh_releases", maintenance_refresh_releases, vol.Schema({}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    for action in ("maintenance_update_and_restart", "maintenance_restart"):
        fields = {
            vol.Required("request_id"): str, vol.Required("issued_at"): str,
            vol.Optional("wait_minutes", default=60): vol.All(
                vol.Coerce(float), vol.Range(min=1, max=1440),
            ),
        }
        if action == "maintenance_update_and_restart":
            fields[vol.Required("version")] = str
        hass.services.async_register(
            DOMAIN, action, maintenance_request, vol.Schema(fields),
            supports_response=SupportsResponse.OPTIONAL,
        )

    async def fleet_request(call):
        await async_require_admin(hass, call.context)
        hub = hass.data.get("heo_fleet_maintenance")
        if hub is None:
            raise HomeAssistantError("fleet_maintenance_not_configured")
        if call.service == "fleet_maintenance_refresh":
            await hub.async_refresh()
            return {}
        if call.service == "fleet_maintenance_check_releases":
            return await hub.async_check_releases(call.data["site"], call.context)
        return await hub.async_request(
            call.data["site"],
            "update_and_restart" if call.service == "fleet_maintenance_update" else "restart",
            call.context,
        )

    for action in ("fleet_maintenance_update", "fleet_maintenance_restart",
                   "fleet_maintenance_refresh", "fleet_maintenance_check_releases"):
        hass.services.async_register(
            DOMAIN, action, fleet_request,
            vol.Schema({} if action.endswith("refresh") else {vol.Required("site"): str}),
            supports_response=SupportsResponse.OPTIONAL,
        )


def unregister_services(hass: HomeAssistant) -> None:
    """Remove service endpoints after the final configured entry unloads."""
    for service in (SERVICE_TEST_FORCE_CHARGE, SERVICE_TEST_FORCE_DISCHARGE, SERVICE_TEST_STOP):
        hass.services.async_remove(DOMAIN, service)
    for name in MANUAL_SERVICES:
        hass.services.async_remove(DOMAIN, name)
    for name in (
        "maintenance_status", "maintenance_update_and_restart", "maintenance_restart",
        "fleet_maintenance_update", "fleet_maintenance_restart", "fleet_maintenance_refresh",
        "maintenance_refresh_releases", "fleet_maintenance_check_releases",
    ):
        hass.services.async_remove(DOMAIN, name)


async def _async_start(controller, kind: str, power_kw: float, duration_minutes: float) -> None:
    """Present an expected diagnostic rejection as a readable HA service error."""
    try:
        await controller.async_start(kind, power_kw, duration_minutes)
    except ManualTestError as err:
        raise HomeAssistantError(str(err)) from err


def _controller(hass: HomeAssistant, entry_id: str | None = None):
    entries = hass.data.get(DOMAIN, {})
    if entry_id is not None:
        value = entries.get(entry_id)
        if isinstance(value, dict) and value.get("manual_test") is not None:
            return value["manual_test"]
        raise HomeAssistantError(f"no configured entry matches {entry_id}")
    if len(entries) > 1:
        raise HomeAssistantError("entry_id is required when multiple sites are configured")
    for value in entries.values():
        if isinstance(value, dict) and value.get("manual_test") is not None:
            return value["manual_test"]
    raise HomeAssistantError("no Home Energy Orchestrator entry is configured")
