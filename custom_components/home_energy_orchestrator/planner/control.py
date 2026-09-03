"""Side-effect-free FoxESS control decisions.

This module deliberately returns an intent. A Home Assistant coordinator must
still enforce commissioning, entity-range checks, write ordering and response
verification before calling any FoxESS service.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class ControlInputs:
    """Qualified telemetry and operator policy for one control evaluation."""

    rehearsal: bool
    ready: bool
    automatic_charge: bool
    automatic_export: bool
    free_window_active: bool
    export_window_active: bool
    current_mode: str
    battery_soc: float
    charge_target_soc: float
    requested_charge_power_kw: float
    charge_power_max_kw: float
    planned_export_energy_kwh: float
    grid_import_kw: float
    export_import_limit_kw: float
    minimum_grid_soc: float
    configured_export_rate_c_kwh: float
    minimum_export_rate_c_kwh: float
    requested_discharge_power_kw: float
    discharge_power_max_kw: float


@dataclass(frozen=True, slots=True)
class ControlDecision:
    """A requested mode transition or a safe no-op."""

    action: str
    power_kw: float
    reason: str


def _bounded_power(requested: float, maximum: float) -> float:
    if not isfinite(requested) or not isfinite(maximum) or requested < 0 or maximum < 0:
        raise ValueError("power limits must be finite and non-negative")
    return round(min(requested, maximum), 3)


def decide_control(inputs: ControlInputs) -> ControlDecision:
    """Select one guarded intent, matching the YAML pilot's precedence rules."""
    numeric = (
        inputs.battery_soc,
        inputs.charge_target_soc,
        inputs.planned_export_energy_kwh,
        inputs.grid_import_kw,
        inputs.export_import_limit_kw,
        inputs.minimum_grid_soc,
        inputs.configured_export_rate_c_kwh,
        inputs.minimum_export_rate_c_kwh,
    )
    if not all(isfinite(value) for value in numeric):
        raise ValueError("control inputs must be finite")
    if any(value < 0 for value in numeric):
        raise ValueError("control inputs must be non-negative")

    forced_mode = inputs.current_mode in {"Force Charge", "Force Discharge"}
    if inputs.rehearsal:
        return ControlDecision(
            "restore_self_use" if forced_mode else "hold", 0.0, "rehearsal_mode"
        )
    if not inputs.ready:
        return ControlDecision(
            "restore_self_use" if forced_mode else "hold", 0.0, "telemetry_not_ready"
        )
    if inputs.free_window_active and inputs.export_window_active:
        return ControlDecision(
            "restore_self_use" if forced_mode else "hold", 0.0, "conflicting_windows"
        )

    charge_allowed = (
        inputs.automatic_charge
        and inputs.free_window_active
        and inputs.battery_soc < inputs.charge_target_soc
    )
    export_allowed = (
        inputs.automatic_export
        and inputs.export_window_active
        and inputs.planned_export_energy_kwh > 0
        and inputs.grid_import_kw < inputs.export_import_limit_kw
        and inputs.battery_soc > inputs.minimum_grid_soc
        and inputs.configured_export_rate_c_kwh >= inputs.minimum_export_rate_c_kwh
    )

    if charge_allowed and export_allowed:
        return ControlDecision(
            "restore_self_use" if forced_mode else "hold", 0.0, "conflicting_intents"
        )
    if charge_allowed:
        if inputs.current_mode == "Force Discharge":
            return ControlDecision("hold", 0.0, "export_session_latched")
        return ControlDecision(
            "force_charge",
            _bounded_power(inputs.requested_charge_power_kw, inputs.charge_power_max_kw),
            "free_window_below_target",
        )
    if export_allowed:
        if inputs.current_mode == "Force Charge":
            return ControlDecision("hold", 0.0, "charge_session_latched")
        return ControlDecision(
            "force_discharge",
            _bounded_power(inputs.requested_discharge_power_kw, inputs.discharge_power_max_kw),
            "export_window_ready",
        )
    if forced_mode:
        return ControlDecision("restore_self_use", 0.0, "no_active_policy")
    return ControlDecision("hold", 0.0, "no_active_policy")
