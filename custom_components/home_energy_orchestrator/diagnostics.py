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
from .solar_provider import capture_solis_solar


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
    solar_provider: dict[str, object] = {"reason": "not_selected"}
    power_sources = coordinator.runtime_config.power_sources
    if power_sources.house_load_source == "power_balance_cloud_solar":
        capture_solis_solar(
            hass, power_sources.solar_entity, diagnostics=solar_provider,
            cached_frame=coordinator.solis_frames.current_frame(),
        )
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
        "solar_provider": solar_provider,
    }
