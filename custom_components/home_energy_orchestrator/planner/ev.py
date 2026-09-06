"""Faithful, adapter-neutral Tesla charging policy.

The base current planner is a direct port of the Mangerton three-minute
supervisory allocation.  Site-specific extensions, including the daily free
energy ceiling, are deliberately applied after that decision so they cannot
silently replace its branch order.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, isfinite


@dataclass(frozen=True, slots=True)
class FreeWindowCurrentInputs:
    """Inputs used by the canonical Mangerton free-window current policy."""

    in_free_window: bool
    connected: bool
    ceiling_a: float
    effective_minimum_a: float
    protected_baseline_a: float
    requested_a: float
    service_limit_a: float
    service_headroom_a: float
    grid_average_a: float
    grid_average_valid: bool
    actual_ev_current_a: float
    ev_average_a: float
    ev_average_source_valid: bool
    elapsed_minutes: float
    settle_minutes: float
    current_step_a: float
    ev_priority: bool
    charge_to_full: bool = False


@dataclass(frozen=True, slots=True)
class EvCurrentDecision:
    """One auditable EV current decision."""

    current_a: float
    phase: str


def plan_free_window_current(inputs: FreeWindowCurrentInputs) -> EvCurrentDecision:
    """Port the canonical Mangerton branch order without topology assumptions."""
    _validate_free_window_inputs(inputs)
    ceiling = inputs.ceiling_a
    baseline = min(inputs.protected_baseline_a, ceiling)
    bounded_request = max(min(inputs.requested_a, ceiling), baseline)
    house_hold = min(max(bounded_request, inputs.effective_minimum_a), ceiling)
    grid_target = max(inputs.service_limit_a - inputs.service_headroom_a, 0.0)
    grid_error = grid_target - inputs.grid_average_a
    ev_average_valid = (
        inputs.ev_average_source_valid and inputs.actual_ev_current_a > 0
    )
    raw_aligned = inputs.ev_average_a + grid_error
    stepped_aligned = floor(raw_aligned / inputs.current_step_a) * inputs.current_step_a
    bounded_aligned = max(min(stepped_aligned, ceiling), baseline)

    if not inputs.in_free_window or not inputs.connected or ceiling <= 0:
        return _decision(baseline, "inactive")
    if inputs.grid_average_a > inputs.service_limit_a:
        if ev_average_valid:
            return _decision(bounded_aligned, "service_limit_correction")
        return _decision(baseline, "service_limit_feedback_unavailable")
    if inputs.charge_to_full:
        return _decision(ceiling, "charge_to_full_priority")
    if inputs.ev_priority:
        return _decision(ceiling, "ev_priority_maximum")
    if inputs.elapsed_minutes < inputs.settle_minutes:
        return _decision(inputs.effective_minimum_a, "settling_foxess")
    if not inputs.grid_average_valid or inputs.service_limit_a <= 0:
        return _decision(inputs.effective_minimum_a, "telemetry_fallback_minimum")
    if not ev_average_valid:
        return _decision(house_hold, "ev_feedback_hold")
    if abs(grid_error) <= 0.5:
        return _decision(house_hold, "service_deadband_hold")
    return _decision(
        min(max(bounded_aligned, inputs.effective_minimum_a), ceiling),
        "house_battery_priority",
    )


@dataclass(frozen=True, slots=True)
class ChargeLimitInputs:
    """Inputs for the separate policy-limit and anti-pause actuator target."""

    connected: bool
    policy_limit_percent: float
    current_limit_percent: float
    vehicle_soc_percent: float | None
    protected_baseline_required: bool
    direct_limit_headroom_percent: float
    minimum_percent: float
    maximum_percent: float
    step_percent: float


def plan_charge_limit_target(inputs: ChargeLimitInputs) -> float:
    """Preserve policy while protecting a powered connector from pause faults."""
    _validate_charge_limit_inputs(inputs)
    if not inputs.connected:
        return inputs.current_limit_percent
    policy = _clip(
        inputs.policy_limit_percent, inputs.minimum_percent, inputs.maximum_percent
    )
    if not inputs.protected_baseline_required or inputs.vehicle_soc_percent is None:
        return policy
    raw_guard = inputs.vehicle_soc_percent + inputs.direct_limit_headroom_percent
    stepped_guard = ceil(raw_guard / inputs.step_percent) * inputs.step_percent
    guard = _clip(stepped_guard, inputs.minimum_percent, inputs.maximum_percent)
    return round(max(policy, guard), 3)


@dataclass(frozen=True, slots=True)
class AllowanceCeilingInputs:
    """Configurable whole-site allowance extension applied after base policy."""

    base_current_a: float
    protected_baseline_a: float
    minimum_charge_a: float
    current_step_a: float
    voltage_v: float
    phase_count: int
    remaining_window_hours: float
    allowance_kwh: float
    imported_in_window_kwh: float | None
    projected_other_import_kwh: float
    projected_ev_energy_kwh: float
    safety_margin_kwh: float = 0.0


def apply_daily_allowance_ceiling(inputs: AllowanceCeilingInputs) -> EvCurrentDecision:
    """Cap only sessions projected to exceed the configured whole-site allowance.

    This is intentionally not an even-spread charging algorithm.  If the
    projected house, battery and EV energy fits, the canonical current passes
    through unchanged.  Pacing begins only when the complete projection would
    exceed the configured allowance.
    """
    _validate_allowance_inputs(inputs)
    baseline = min(inputs.protected_baseline_a, inputs.base_current_a)
    if inputs.imported_in_window_kwh is None:
        return _decision(baseline, "allowance_meter_unavailable")
    projected_total = (
        inputs.imported_in_window_kwh
        + inputs.projected_other_import_kwh
        + inputs.projected_ev_energy_kwh
        + inputs.safety_margin_kwh
    )
    if projected_total <= inputs.allowance_kwh:
        return _decision(inputs.base_current_a, "allowance_not_constraining")

    ev_budget = max(
        inputs.allowance_kwh
        - inputs.imported_in_window_kwh
        - inputs.projected_other_import_kwh
        - inputs.safety_margin_kwh,
        0.0,
    )
    if inputs.remaining_window_hours <= 0 or ev_budget <= 0:
        return _decision(baseline, "allowance_exhausted")
    average_power_kw = ev_budget / inputs.remaining_window_hours
    raw_cap_a = average_power_kw * 1000 / (inputs.voltage_v * inputs.phase_count)
    stepped_cap_a = floor(raw_cap_a / inputs.current_step_a) * inputs.current_step_a
    cap = min(stepped_cap_a, inputs.base_current_a)
    if cap < inputs.minimum_charge_a:
        return _decision(baseline, "allowance_below_charger_minimum")
    return _decision(max(cap, baseline), "allowance_pacing")


def _decision(current_a: float, phase: str) -> EvCurrentDecision:
    return EvCurrentDecision(round(max(current_a, 0.0), 3), phase)


def _validate_free_window_inputs(inputs: FreeWindowCurrentInputs) -> None:
    values = (
        inputs.ceiling_a,
        inputs.effective_minimum_a,
        inputs.protected_baseline_a,
        inputs.requested_a,
        inputs.service_limit_a,
        inputs.service_headroom_a,
        inputs.actual_ev_current_a,
        inputs.ev_average_a,
        inputs.elapsed_minutes,
        inputs.settle_minutes,
        inputs.current_step_a,
    )
    if not all(isfinite(value) for value in (*values, inputs.grid_average_a)):
        raise ValueError("EV current inputs must be finite")
    if any(value < 0 for value in values) or inputs.current_step_a <= 0:
        raise ValueError("EV current inputs must be non-negative with a positive step")
    if inputs.protected_baseline_a > inputs.ceiling_a:
        raise ValueError("protected baseline cannot exceed the physical ceiling")
    if inputs.effective_minimum_a > inputs.ceiling_a:
        raise ValueError("effective minimum cannot exceed the physical ceiling")


def _validate_charge_limit_inputs(inputs: ChargeLimitInputs) -> None:
    values = (
        inputs.policy_limit_percent,
        inputs.current_limit_percent,
        inputs.direct_limit_headroom_percent,
        inputs.minimum_percent,
        inputs.maximum_percent,
        inputs.step_percent,
    )
    if inputs.vehicle_soc_percent is not None:
        values += (inputs.vehicle_soc_percent,)
    if not all(isfinite(value) for value in values):
        raise ValueError("charge-limit inputs must be finite")
    if inputs.step_percent <= 0 or inputs.minimum_percent > inputs.maximum_percent:
        raise ValueError("charge-limit range must be ordered with a positive step")


def _validate_allowance_inputs(inputs: AllowanceCeilingInputs) -> None:
    values = (
        inputs.base_current_a,
        inputs.protected_baseline_a,
        inputs.minimum_charge_a,
        inputs.current_step_a,
        inputs.voltage_v,
        inputs.remaining_window_hours,
        inputs.allowance_kwh,
        inputs.projected_other_import_kwh,
        inputs.projected_ev_energy_kwh,
        inputs.safety_margin_kwh,
    )
    if inputs.imported_in_window_kwh is not None:
        values += (inputs.imported_in_window_kwh,)
    if not all(isfinite(value) for value in values) or any(value < 0 for value in values):
        raise ValueError("allowance inputs must be finite and non-negative")
    if inputs.current_step_a <= 0 or inputs.voltage_v <= 0 or inputs.phase_count < 1:
        raise ValueError("allowance topology and current step must be positive")
    if inputs.protected_baseline_a > inputs.base_current_a:
        raise ValueError("allowance baseline cannot exceed the base current")


def _clip(value: float, minimum: float, maximum: float) -> float:
    return round(max(min(value, maximum), minimum), 3)
