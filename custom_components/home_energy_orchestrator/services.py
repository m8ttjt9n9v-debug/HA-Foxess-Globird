"""Explicit service endpoints for the commissioning test surface."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    SERVICE_TEST_FORCE_CHARGE,
    SERVICE_TEST_FORCE_DISCHARGE,
    SERVICE_TEST_STOP,
)

TEST_SCHEMA = vol.Schema(
    {
        vol.Optional("power_kw"): vol.Coerce(float),
        vol.Optional("duration_minutes"): vol.Coerce(float),
        vol.Optional("entry_id"): str,
    }
)


def register_services(hass: HomeAssistant) -> None:
    """Register services once for the integration domain."""
    if hass.services.has_service(DOMAIN, SERVICE_TEST_FORCE_CHARGE):
        return

    async def start_charge(call: ServiceCall) -> None:
        controller = _controller(hass, call.data.get("entry_id"))
        await controller.async_start(
            "charge",
            call.data.get("power_kw", controller.charge_power_kw),
            call.data.get("duration_minutes", controller.duration_minutes),
        )

    async def start_discharge(call: ServiceCall) -> None:
        controller = _controller(hass, call.data.get("entry_id"))
        await controller.async_start(
            "discharge",
            call.data.get("power_kw", controller.discharge_power_kw),
            call.data.get("duration_minutes", controller.duration_minutes),
        )

    async def stop(call: ServiceCall) -> None:
        await _controller(hass, call.data.get("entry_id")).async_stop()

    hass.services.async_register(
        DOMAIN, SERVICE_TEST_FORCE_CHARGE, start_charge, TEST_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_TEST_FORCE_DISCHARGE, start_discharge, TEST_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_TEST_STOP, stop, TEST_SCHEMA
    )


def unregister_services(hass: HomeAssistant) -> None:
    """Remove service endpoints after the final configured entry unloads."""
    for service in (SERVICE_TEST_FORCE_CHARGE, SERVICE_TEST_FORCE_DISCHARGE, SERVICE_TEST_STOP):
        hass.services.async_remove(DOMAIN, service)


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
