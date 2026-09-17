"""Redacted diagnostics for safe support requests."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import EnergyConfigEntry
from .const import (
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
)
from .read_model import build_site_read_model


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EnergyConfigEntry
) -> dict[str, Any]:
    """Return calculated values only; entity IDs are deliberately omitted."""
    coordinator = entry.runtime_data
    actuator_keys = (
        CONF_FOXESS_WORK_MODE,
        CONF_FOXESS_FORCE_CHARGE_POWER,
        CONF_FOXESS_FORCE_DISCHARGE_POWER,
    )
    read_model = build_site_read_model(coordinator)
    return {
        "entry": {"version": entry.version, "options": {"mode": "observe"}},
        "actuators": {
            "mapped_count": sum(bool(entry.data.get(key)) for key in actuator_keys),
            **read_model.actuator_diagnostics(),
        },
        "normalized_telemetry": read_model.telemetry.diagnostics(),
        "ledger": read_model.operational.diagnostics(),
        "forecast": read_model.forecast_diagnostics(),
        "learning": read_model.learning.diagnostics(),
    }
