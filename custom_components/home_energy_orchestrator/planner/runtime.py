"""Composition boundary for the future active coordinator.

This module deliberately composes pure decisions only. It is the seam where
learned house protection, tariff eligibility, EV load-following and FoxESS
control will meet before an adapter is granted write permission.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .control import ControlDecision, ControlInputs, decide_control
from .ev import EvCurrentDecision, EvCurrentInputs, plan_ev_current_target
from .export import ExportPlan, calculate_export_plan
from .free_charge import FreeChargePowerPlan, calculate_free_charge_power
from .tariff import TariffGuardDecision, calculate_tariff_guard


@dataclass(frozen=True, slots=True)
class RuntimePlan:
    """All decisions for one evaluation, with no Home Assistant side effects."""

    control: ControlDecision
    ev_current: EvCurrentDecision
    tariff: TariffGuardDecision
    export: ExportPlan | None = None
    free_charge: FreeChargePowerPlan | None = None


def plan_runtime(
    control_inputs: ControlInputs,
    ev_inputs: EvCurrentInputs,
    *,
    tariff_inputs: dict[str, object],
    export_inputs: dict[str, float] | None = None,
    free_charge_inputs: dict[str, float] | None = None,
    learned_house_budget_kwh: float | None = None,
) -> RuntimePlan:
    """Evaluate tariff, EV and FoxESS policy in one deterministic pass."""
    tariff = calculate_tariff_guard(**tariff_inputs)
    ev_current = plan_ev_current_target(ev_inputs)
    free_charge_plan = None
    if free_charge_inputs is not None:
        free_charge_plan = calculate_free_charge_power(**free_charge_inputs)
        control_inputs = replace(
            control_inputs,
            requested_charge_power_kw=free_charge_plan.target_charge_power_kw,
        )
    export_plan = None
    if export_inputs is not None:
        protected_house = 0.0 if learned_house_budget_kwh is None else learned_house_budget_kwh
        export_plan = calculate_export_plan(
            export_inputs["available_ac_kwh"],
            protected_house,
            export_inputs.get("protected_ev_kwh", 0.0),
            export_inputs["allowance_remaining_kwh"],
            export_inputs["discharge_power_kw"],
        )
        control_inputs = replace(
            control_inputs,
            planned_export_energy_kwh=export_plan.planned_export_energy_kwh,
        )
    control = decide_control(control_inputs)
    return RuntimePlan(
        control=control,
        ev_current=ev_current,
        tariff=tariff,
        export=export_plan,
        free_charge=free_charge_plan,
    )
