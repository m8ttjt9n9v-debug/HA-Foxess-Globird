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


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EnergyConfigEntry
) -> dict[str, Any]:
    """Return calculated values only; entity IDs are deliberately omitted."""
    coordinator = entry.runtime_data
    ledger = coordinator.data
    learning = coordinator.learning_result
    occupancy = coordinator.occupancy_result
    heater_learning = coordinator.heater_learning_result
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
    telemetry = coordinator.telemetry
    forecast = coordinator.optimistic_forecast
    scorecard_date = coordinator.forecast_scorecard_date
    scorecard = (
        coordinator.forecast_feedback.record_for(scorecard_date)
        if scorecard_date is not None
        else None
    )
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
            "ev_smart_socket_recovery_phase": (
                ev_controller.smart_recovery.phase
                if ev_controller is not None
                else "unavailable"
            ),
            "ev_smart_socket_recovery_attempted": (
                ev_controller.smart_recovery.attempted
                if ev_controller is not None
                else False
            ),
            "ev_smart_socket_recovery_started_at": (
                ev_controller.smart_recovery.phase_started_at
                if ev_controller is not None
                else None
            ),
            "ev_smart_socket_recovery_current_a": (
                ev_controller.smart_recovery.recovery_current_a
                if ev_controller is not None
                else None
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
            "ev_pre_free_phase": (
                ev_controller.pre_free_phase if ev_controller is not None else "unavailable"
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
            "foxess_control_owner": automation.control_owner,
            "foxess_control_gate": foxess_gate,
            "foxess_writes_enabled": foxess_gate == "ready",
            "writes_enabled": foxess_gate == "ready",
        },
        "normalized_telemetry": {
            name: {
                "value": sample.value,
                "unit": sample.unit,
                "positive_direction": sample.positive_direction,
                "valid": sample.valid,
                "fresh": sample.fresh,
                "reason": sample.reason,
                "source_count": len(sample.sources),
            }
            for name, sample in (
                (
                    ("grid_power", telemetry.grid_power),
                    ("battery_power", telemetry.battery_power),
                    ("solar_power", telemetry.solar_power),
                    ("house_load", telemetry.house_load),
                    ("site_grid_current", telemetry.site_grid_current),
                )
                if telemetry is not None
                else ()
            )
        },
        "ledger": {
            "reason": ledger.reason,
            "battery_energy_kwh": ledger.battery_energy_kwh,
            "available_after_reserve_kwh": ledger.available_after_reserve_kwh,
            "grid_import_kw": ledger.grid_import_kw,
            "grid_export_kw": ledger.grid_export_kw,
        },
        "forecast": {
            "net_cost": (
                forecast.calibrated_net_cost if forecast is not None else None
            ),
            "raw_net_cost": forecast.raw_net_cost if forecast is not None else None,
            "assumed_zerohero_credit": (
                forecast.assumed_zerohero_credit if forecast is not None else None
            ),
            "export_realisation_fraction": (
                coordinator.forecast_feedback.export_realisation_fraction
            ),
            "forecast_remaining_export_kwh": (
                forecast.forecast_remaining_export_kwh
                if forecast is not None
                else None
            ),
            "learned_cost_bias": coordinator.forecast_feedback.learned_cost_bias,
            "scorecard_status": coordinator.forecast_scorecard_status,
            "scorecard_date": (
                scorecard_date.isoformat() if scorecard_date is not None else None
            ),
            "scorecard_forecast_cost": (
                scorecard.frozen_forecast_cost if scorecard is not None else None
            ),
            "scorecard_actual_cost": (
                scorecard.retailer_actual_cost if scorecard is not None else None
            ),
            "scorecard_error": (
                scorecard.forecast_error if scorecard is not None else None
            ),
            "scorecard_zerohero_status": (
                scorecard.retailer_zerohero_status if scorecard is not None else None
            ),
        },
        "learning": {
            "model": learning.model,
            "cycle_budget_kwh": learning.cycle_budget_kwh,
            "sample_count": learning.sample_count,
            "retained_sample_count": len(coordinator.demand_history.samples),
            "heater_sample_count": learning.heater_sample_count,
            "heater_retained_sample_count": len(coordinator.heater_history.samples),
            "heater_model": (
                heater_learning.model if heater_learning is not None else "not_mapped"
            ),
            "occupancy": occupancy.state,
            "occupancy_mode": occupancy.selected_mode,
            "occupancy_reason": occupancy.reason,
            "person_entities_found": occupancy.person_count,
            "people_home": occupancy.people_home,
            "all_people_away_for_hours": occupancy.all_people_away_for_hours,
        },
    }
