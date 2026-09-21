"""Tests for Home Assistant service error presentation."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.home_energy_orchestrator.const import (
    DOMAIN,
    SERVICE_TEST_FORCE_CHARGE,
    SERVICE_TEST_FORCE_DISCHARGE,
)
from custom_components.home_energy_orchestrator.manual_test import ManualTestError
from custom_components.home_energy_orchestrator.services import (
    register_services,
    unregister_services,
)


@pytest.mark.parametrize(
    ("service", "kind"),
    (
        (SERVICE_TEST_FORCE_CHARGE, "charge"),
        (SERVICE_TEST_FORCE_DISCHARGE, "discharge"),
    ),
)
async def test_diagnostic_gate_rejection_is_a_readable_service_error(
    hass, service: str, kind: str
) -> None:
    """Expected safety rejections must not be rendered as an unknown error."""
    controller = type(
        "RejectingController",
        (),
        {
            "charge_power_kw": 1.0,
            "discharge_power_kw": 1.0,
            "duration_minutes": 1.0,
            "async_start": AsyncMock(
                side_effect=ManualTestError(
                    "disable Rehearsal mode before running a diagnostic test"
                )
            ),
        },
    )()
    hass.data[DOMAIN] = {"entry": {"manual_test": controller}}
    register_services(hass)

    with pytest.raises(HomeAssistantError, match="disable Rehearsal mode"):
        await hass.services.async_call(DOMAIN, service, blocking=True)

    controller.async_start.assert_awaited_once_with(kind, 1.0, 1.0)
    unregister_services(hass)
