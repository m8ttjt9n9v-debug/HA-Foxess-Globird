"""Redacted diagnostics for safe support requests."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import EnergyConfigEntry
from .const import (
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_EV_CHARGE_LIMIT,
    CONF_EV_CHARGE_SWITCH,
    CONF_EV_CURRENT_LIMIT,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_REHEARSAL_MODE,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EnergyConfigEntry
) -> dict[str, Any]:
    """Return calculated values only; entity IDs are deliberately omitted."""
    coordinator = entry.runtime_data
    ledger = coordinator.data
    learning = coordinator.learning_result
    actuator_keys = (
        CONF_FOXESS_WORK_MODE,
        CONF_FOXESS_FORCE_CHARGE_POWER,
        CONF_FOXESS_FORCE_DISCHARGE_POWER,
        CONF_EV_CHARGE_LIMIT,
        CONF_EV_CURRENT_LIMIT,
        CONF_EV_CHARGE_SWITCH,
    )
    safety_locked = bool(entry.data.get(CONF_REHEARSAL_MODE, True))
    active_controller = getattr(coordinator, "active_controller", None)
    ev_controller = getattr(active_controller, "ev_controller", None)
    foxess_gate = (
        active_controller.gate_status if active_controller is not None else "unavailable"
    )
    ev_gate = ev_controller.gate_status if ev_controller is not None else "unavailable"
    return {
        "entry": {"version": entry.version, "options": {"mode": "observe"}},
        "actuators": {
            "mapped_count": sum(bool(entry.data.get(key)) for key in actuator_keys),
            "safety_lock_engaged": safety_locked,
            "foxess_automatic_control_enabled": bool(
                entry.data.get(CONF_AUTOMATIC_CONTROL_ENABLED, False)
            ),
            "ev_automatic_control_enabled": bool(
                entry.data.get(CONF_EV_AUTOMATIC_CONTROL_ENABLED, False)
            ),
            "foxess_control_gate": foxess_gate,
            "ev_control_gate": ev_gate,
            "foxess_writes_enabled": foxess_gate == "ready",
            "ev_writes_enabled": ev_gate == "ready",
            "writes_enabled": foxess_gate == "ready" or ev_gate == "ready",
        },
        "ledger": {
            "reason": ledger.reason,
            "battery_energy_kwh": ledger.battery_energy_kwh,
            "available_after_reserve_kwh": ledger.available_after_reserve_kwh,
            "grid_import_kw": ledger.grid_import_kw,
            "grid_export_kw": ledger.grid_export_kw,
        },
        "learning": {
            "model": learning.model,
            "cycle_budget_kwh": learning.cycle_budget_kwh,
            "sample_count": learning.sample_count,
            "retained_sample_count": len(coordinator.demand_history.samples),
        },
    }
