"""Redacted diagnostics for safe support requests."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import EnergyConfigEntry
from .const import (
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_REHEARSAL_MODE,
    DEFAULT_FOXESS_CONTROL_OWNER,
)
from .ev_adapter import ev_control_gate_status


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
    )
    safety_locked = bool(entry.data.get(CONF_REHEARSAL_MODE, True))
    active_controller = getattr(coordinator, "active_controller", None)
    ev_controller = getattr(coordinator, "ev_controller", None)
    foxess_gate = active_controller.gate_status if active_controller is not None else "unavailable"
    ev_gate = (
        ev_controller.gate_status
        if ev_controller is not None
        else ev_control_gate_status(coordinator.config)
    )
    return {
        "entry": {"version": entry.version, "options": {"mode": "observe"}},
        "actuators": {
            "mapped_count": sum(bool(entry.data.get(key)) for key in actuator_keys),
            "safety_lock_engaged": safety_locked,
            "foxess_automatic_control_enabled": bool(
                entry.data.get(CONF_AUTOMATIC_CONTROL_ENABLED, False)
            ),
            "automatic_export_enabled": bool(entry.data.get(CONF_AUTOMATIC_EXPORT_ENABLED, False)),
            "ev_automatic_control_enabled": bool(
                entry.data.get(CONF_EV_AUTOMATIC_CONTROL_ENABLED, False)
            ),
            "ev_control_gate": ev_gate,
            "ev_writes_enabled": ev_gate == "ready",
            "ev_last_reason": (
                ev_controller.last_reason if ev_controller is not None else "unavailable"
            ),
            "ev_last_actions": (ev_controller.last_actions if ev_controller is not None else ()),
            "ev_writes_performed": (
                ev_controller.writes_performed if ev_controller is not None else 0
            ),
            "ev_target_current_a": (
                ev_controller.target_current_a if ev_controller is not None else None
            ),
            "ev_target_limit_percent": (
                ev_controller.target_limit_percent if ev_controller is not None else None
            ),
            "ev_requested_current_a": (
                ev_controller.requested_current_a if ev_controller is not None else None
            ),
            "ev_actual_current_a": (
                ev_controller.actual_current_a if ev_controller is not None else None
            ),
            "ev_applied_limit_percent": (
                ev_controller.applied_limit_percent if ev_controller is not None else None
            ),
            "ev_charge_switch_on": (
                ev_controller.charge_switch_on if ev_controller is not None else None
            ),
            "ev_reconciliation_phase": (
                ev_controller.reconciliation.phase if ev_controller is not None else "unavailable"
            ),
            "ev_reconciliation_attempts": (
                ev_controller.reconciliation.attempts if ev_controller is not None else 0
            ),
            "ev_solar_spill_phase": (
                ev_controller.solar_spill.phase if ev_controller is not None else "unavailable"
            ),
            "ev_solar_spill_current_a": (
                ev_controller.solar_spill.current_a if ev_controller is not None else None
            ),
            "ev_pre_free_session_active": (
                ev_controller.pre_free_session.active if ev_controller is not None else False
            ),
            "ev_pre_free_planned_energy_kwh": (
                ev_controller.pre_free_plan.planned_energy_kwh
                if ev_controller is not None and ev_controller.pre_free_plan is not None
                else None
            ),
            "ev_pre_free_planned_start": (
                ev_controller.pre_free_plan.planned_start
                if ev_controller is not None and ev_controller.pre_free_plan is not None
                else None
            ),
            "ev_pre_free_current_a": (
                ev_controller.pre_free_current_a if ev_controller is not None else None
            ),
            "ev_outside_control_active": (
                ev_controller.outside_control_active if ev_controller is not None else False
            ),
            "export_session_phase": (
                active_controller.export_session.phase
                if active_controller is not None
                else "unavailable"
            ),
            "foxess_control_owner": entry.data.get(
                CONF_FOXESS_CONTROL_OWNER, DEFAULT_FOXESS_CONTROL_OWNER
            ),
            "foxess_control_gate": foxess_gate,
            "foxess_writes_enabled": foxess_gate == "ready",
            "writes_enabled": foxess_gate == "ready",
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
