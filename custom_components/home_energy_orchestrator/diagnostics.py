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
from .ev_adapter import ev_control_gate_status
from .read_model import build_site_read_model


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EnergyConfigEntry
) -> dict[str, Any]:
    """Return calculated values only; entity IDs are deliberately omitted."""
    coordinator = entry.runtime_data
    ledger = coordinator.data
    actuator_keys = (
        CONF_FOXESS_WORK_MODE,
        CONF_FOXESS_FORCE_CHARGE_POWER,
        CONF_FOXESS_FORCE_DISCHARGE_POWER,
    )
    runtime = coordinator.runtime_config
    automation = runtime.automation
    ev_preferences = runtime.ev_preferences
    active_controller = getattr(coordinator, "active_controller", None)
    ev_controller = getattr(coordinator, "ev_controller", None)
    foxess_gate = active_controller.gate_status if active_controller is not None else "unavailable"
    ev_gate = (
        ev_controller.gate_status
        if ev_controller is not None
        else ev_control_gate_status(coordinator.runtime_config)
    )
    read_model = build_site_read_model(coordinator)
    return {
        "entry": {"version": entry.version, "options": {"mode": "observe"}},
        "actuators": {
            "mapped_count": sum(bool(entry.data.get(key)) for key in actuator_keys),
            "safety_lock_engaged": automation.safety_lock,
            "sign_conventions_verified": runtime.electrical.verified,
            "foxess_automatic_control_enabled": automation.master_enabled,
            "automatic_charge_enabled": automation.battery_charge_enabled,
            "free_charge_schedule_confirmed": automation.free_charge_schedule_confirmed,
            "charge_session_phase": (
                active_controller.charge_session.phase
                if active_controller is not None
                else "unavailable"
            ),
            "charge_power_target_kw": (
                active_controller.charge_power_target_kw
                if active_controller is not None
                else None
            ),
            "automatic_export_enabled": automation.battery_export_enabled,
            "automatic_export_effective": (
                active_controller.export_effective_enabled
                if active_controller is not None
                else False
            ),
            "ev_before_export_enabled": ev_preferences.before_export_enabled,
            "ev_before_export_soc_target_percent": (
                ev_preferences.before_export_soc_target
            ),
            "ev_before_export_status": (
                active_controller.ev_before_export_decision.reason
                if active_controller is not None
                else "unavailable"
            ),
            "ev_automatic_control_enabled": automation.ev_control_enabled,
            **read_model.ev.actuator_diagnostics(ev_gate),
            "export_session_phase": (
                active_controller.export_session.phase
                if active_controller is not None
                else "unavailable"
            ),
            "foxess_control_owner": automation.control_owner,
            "foxess_control_gate": foxess_gate,
            "foxess_writes_enabled": foxess_gate == "ready",
            "writes_enabled": foxess_gate == "ready",
        },
        "normalized_telemetry": read_model.telemetry.diagnostics(),
        "ledger": {
            "reason": ledger.reason,
            "battery_energy_kwh": ledger.battery_energy_kwh,
            "available_after_reserve_kwh": ledger.available_after_reserve_kwh,
            "grid_import_kw": ledger.grid_import_kw,
            "grid_export_kw": ledger.grid_export_kw,
        },
        "forecast": read_model.forecast_diagnostics(),
        "learning": read_model.learning.diagnostics(),
    }
