"""Immutable presentation model shared by entities, diagnostics and Fleet."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .const import FOXESS_CONTROL_OWNER_CLOUD
from .planner.export import ExportPlan

if TYPE_CHECKING:
    from .coordinator import EnergyCoordinator


def control_mode(coordinator: EnergyCoordinator) -> str:
    """Return the commissioned control surface, not the ledger reason."""
    automation = coordinator.runtime_config.automation
    controller = coordinator.active_controller
    if (
        controller is not None
        and getattr(controller, "ownership_status", None) == "ownership_unknown"
    ):
        return "ownership_unknown"
    foxess_ready = controller is not None and controller.gate_status == "ready"
    if automation.control_owner == FOXESS_CONTROL_OWNER_CLOUD:
        return "foxcloud_scheduler"
    if foxess_ready and automation.battery_charge_enabled and automation.battery_export_enabled:
        return "local_modbus_charge_and_export"
    if foxess_ready and automation.battery_charge_enabled:
        return "local_modbus_free_charge"
    if foxess_ready and automation.battery_export_enabled:
        return "zerohero_export"
    if foxess_ready:
        return "local_modbus_ready"
    return "observe"


def effective_export_plan(coordinator: EnergyCoordinator) -> ExportPlan | None:
    """Expose an export plan only while export is actually permitted."""
    controller = coordinator.active_controller
    if (
        controller is None
        or not controller.export_effective_enabled
        or controller.export_plan is None
    ):
        return None
    return controller.export_plan


def export_status(coordinator: EnergyCoordinator) -> str:
    """Explain whether export is disabled, withheld, or running."""
    controller = coordinator.active_controller
    if controller is None:
        return "unavailable"
    if not coordinator.runtime_config.automation.battery_export_enabled:
        return "disabled"
    decision = controller.ev_before_export_decision
    if not decision.export_allowed:
        return f"withheld_{decision.reason}"
    return controller.export_session.phase


def _rounded(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(float(value), digits)


@dataclass(frozen=True, slots=True)
class CostReadModel:
    """Canonical measured and forecast cost presentation values."""

    measured_gross_cost: float | None
    measured_import_cost: float | None
    daily_supply_charge: float | None
    measured_export_revenue: float | None
    measured_zerohero_credit: float | None
    measured_net_cost: float | None
    calibrated_net_cost: float | None
    raw_net_cost: float | None
    assumed_zerohero_credit: float | None
    forecast_export_realisation_fraction: float | None
    forecast_remaining_export_kwh: float | None
    forecast_additional_export_revenue: float | None
    forecast_learned_cost_bias: float | None
    feedback_export_realisation_fraction: float
    feedback_learned_cost_bias: float

    def sensor_values(self) -> dict[str, object]:
        """Project the existing cost and forecast entity states."""
        # Cost has no Home Assistant unit (it is site-currency specific), so
        # preserve state rounding here rather than relying on display hints.
        return {
            "estimated_energy_cost": _rounded(self.measured_gross_cost, 2),
            "estimated_import_energy_cost": _rounded(
                self.measured_import_cost,
                2,
            ),
            "daily_supply_charge": _rounded(self.daily_supply_charge, 2),
            "estimated_export_revenue": _rounded(
                self.measured_export_revenue,
                2,
            ),
            "zerohero_credit": _rounded(self.measured_zerohero_credit, 2),
            "estimated_net_cost": _rounded(self.calibrated_net_cost, 2),
            "measured_net_cost": _rounded(self.measured_net_cost, 2),
            "forecast_export_realisation": round(
                self.feedback_export_realisation_fraction * 100,
                1,
            ),
        }

    def sensor_attributes(self) -> dict[str, object]:
        """Project the Estimated Net Cost entity's existing attributes."""
        return {
            "gross_cost": self.measured_gross_cost,
            "measured_export_revenue": self.measured_export_revenue,
            "measured_zerohero_credit": self.measured_zerohero_credit,
            "measured_net_cost": self.measured_net_cost,
            "assumed_zerohero_credit": self.assumed_zerohero_credit,
            "export_realisation_percent": (
                None
                if self.forecast_export_realisation_fraction is None
                else round(self.forecast_export_realisation_fraction * 100, 1)
            ),
            "forecast_remaining_export_kwh": self.forecast_remaining_export_kwh,
            "forecast_additional_export_revenue": (
                self.forecast_additional_export_revenue
            ),
            "raw_optimistic_forecast": self.raw_net_cost,
            "learned_cost_bias": self.forecast_learned_cost_bias,
        }


@dataclass(frozen=True, slots=True)
class ScorecardReadModel:
    """Canonical prior-day forecast-versus-retailer result."""

    status: str
    result_date: date | None
    forecast_cost: float | None
    raw_forecast_cost: float | None
    actual_cost: float | None
    forecast_error: float | None
    zerohero_status: str | None
    planned_export_kwh: float | None
    realised_export_kwh: float | None
    export_realisation_ratio: float | None
    feedback_applied: bool
    learned_export_realisation_fraction: float
    learned_cost_bias: float

    def sensor_attributes(self) -> dict[str, object]:
        """Project the four scorecard entities' shared existing attributes."""
        return {
            "result_date": (
                None if self.result_date is None else self.result_date.isoformat()
            ),
            "forecast_cost": self.forecast_cost,
            "raw_forecast_cost": self.raw_forecast_cost,
            "actual_cost": self.actual_cost,
            "forecast_error": self.forecast_error,
            "zerohero_status": self.zerohero_status,
            "planned_export_kwh": self.planned_export_kwh,
            "realised_export_kwh": self.realised_export_kwh,
            "export_realisation_ratio": self.export_realisation_ratio,
            "forecast_feedback_applied": self.feedback_applied,
            "learned_export_realisation_percent": round(
                self.learned_export_realisation_fraction * 100,
                1,
            ),
            "learned_cost_bias": self.learned_cost_bias,
        }


@dataclass(frozen=True, slots=True)
class LearningReadModel:
    """Canonical house-learning and occupancy presentation values."""

    model: str
    cycle_budget_kwh: float
    base_cycle_budget_kwh: float
    heater_cycle_budget_kwh: float | None
    remaining_cycle_budget_kwh: float | None
    sample_count: int
    retained_sample_count: int
    heater_sample_count: int
    heater_retained_sample_count: int
    heater_model: str
    budget_occupancy: str
    occupancy_state: str
    occupancy_mode: str
    occupancy_reason: str
    person_count: int
    people_home: int
    all_people_away_for_hours: float

    def sensor_values(self) -> dict[str, object]:
        """Project the existing house-learning entity states."""
        return {
            "learned_house_energy": self.cycle_budget_kwh,
            "learned_base_house_energy": self.base_cycle_budget_kwh,
            "learned_heater_energy": self.heater_cycle_budget_kwh,
            "remaining_house_energy": self.remaining_cycle_budget_kwh,
            "learning_samples": self.sample_count,
            "learning_status": self.model,
            "heater_learning_samples": self.heater_sample_count,
            "house_occupancy_state": self.occupancy_state,
        }

    def occupancy_attributes(self) -> dict[str, object]:
        """Project the House Occupancy State entity's existing attributes."""
        return {
            "selected_mode": self.occupancy_mode,
            "person_entities_found": self.person_count,
            "people_home": self.people_home,
            "all_people_away_for_hours": self.all_people_away_for_hours,
            "reason": self.occupancy_reason,
        }

    def diagnostics(self) -> dict[str, object]:
        """Project the existing redacted learning support payload."""
        return {
            "model": self.model,
            "cycle_budget_kwh": self.cycle_budget_kwh,
            "sample_count": self.sample_count,
            "retained_sample_count": self.retained_sample_count,
            "heater_sample_count": self.heater_sample_count,
            "heater_retained_sample_count": self.heater_retained_sample_count,
            "heater_model": self.heater_model,
            "occupancy": self.occupancy_state,
            "occupancy_mode": self.occupancy_mode,
            "occupancy_reason": self.occupancy_reason,
            "person_entities_found": self.person_count,
            "people_home": self.people_home,
            "all_people_away_for_hours": self.all_people_away_for_hours,
        }


@dataclass(frozen=True, slots=True)
class EvReadModel:
    """Canonical EV entity-state presentation values."""

    soc_percent: float | None
    maximum_power_kw: float
    control_status: str
    target_current_a: float | None
    requested_current_a: float | None
    actual_current_a: float | None
    target_limit_percent: float | None
    applied_limit_percent: float | None
    grid_average_a: float | None
    actual_average_a: float | None
    reconciliation_attempts: int
    smart_recovery_phase: str
    solar_spill_phase: str
    solar_spill_current_a: float | None
    solar_spill_surplus_kw: float | None
    pre_free_phase: str
    pre_free_planned_energy_kwh: float | None
    pre_free_planned_start: datetime | None
    pre_free_current_a: float | None
    daily_backfill_status: str
    daily_backfill_remaining_kwh: float | None
    daily_backfill_delivered_kwh: float | None
    daily_backfill_planned_energy_kwh: float | None
    daily_backfill_shortfall_kwh: float | None
    daily_backfill_planned_start: datetime | None
    daily_backfill_current_a: float | None
    daily_driving_energy_kwh: float | None
    driving_p85_kwh: float | None
    learning_samples: int
    usable_capacity_kwh: float | None
    free_window_soc_gain_percent: float | None
    learned_charge_limit_percent: float | None
    learning_status: str

    def sensor_values(self) -> dict[str, object]:
        """Project the existing EV entity states."""
        return {
            "ev_soc": self.soc_percent,
            "ev_max_power": self.maximum_power_kw,
            "ev_control_status": self.control_status,
            "ev_current_target": self.target_current_a,
            "ev_requested_current": self.requested_current_a,
            "ev_actual_current": self.actual_current_a,
            "ev_charge_limit_target": self.target_limit_percent,
            "ev_applied_charge_limit": self.applied_limit_percent,
            "ev_grid_current_average": self.grid_average_a,
            "ev_actual_current_average": self.actual_average_a,
            "ev_reconciliation_attempts": self.reconciliation_attempts,
            "ev_smart_socket_recovery_status": self.smart_recovery_phase,
            "ev_solar_spill_status": self.solar_spill_phase,
            "ev_solar_spill_current_target": self.solar_spill_current_a,
            "ev_solar_spill_surplus": self.solar_spill_surplus_kw,
            "ev_pre_free_status": self.pre_free_phase,
            "ev_pre_free_planned_energy": self.pre_free_planned_energy_kwh,
            "ev_pre_free_planned_start": self.pre_free_planned_start,
            "ev_pre_free_current_target": self.pre_free_current_a,
            "ev_daily_backfill_status": self.daily_backfill_status,
            "ev_daily_backfill_remaining": self.daily_backfill_remaining_kwh,
            "ev_daily_backfill_delivered": self.daily_backfill_delivered_kwh,
            "ev_daily_backfill_planned_energy": self.daily_backfill_planned_energy_kwh,
            "ev_daily_backfill_shortfall": self.daily_backfill_shortfall_kwh,
            "ev_daily_backfill_planned_start": self.daily_backfill_planned_start,
            "ev_daily_backfill_current_target": self.daily_backfill_current_a,
            "ev_daily_driving_energy": self.daily_driving_energy_kwh,
            "ev_driving_p85": self.driving_p85_kwh,
            "ev_driving_learning_samples": self.learning_samples,
            "ev_usable_capacity": self.usable_capacity_kwh,
            "ev_free_window_soc_gain": self.free_window_soc_gain_percent,
            "ev_learned_charge_limit": self.learned_charge_limit_percent,
            "ev_driving_learning_status": self.learning_status,
        }


@dataclass(frozen=True, slots=True)
class SiteReadModel:
    """One immutable view of values shared by public presentation surfaces."""

    orchestrator_status: str
    battery_soc: float | None
    battery_power_kw: float | None
    grid_power_kw: float | None
    solar_power_kw: float | None
    house_load_kw: float | None
    sellable_energy_kwh: float | None
    planned_export_kwh: float | None
    planned_export_duration_minutes: float | None
    planned_export_start: datetime | None
    foxess_control_gate: str
    charging_status: str
    export_status: str
    ev: EvReadModel
    cost: CostReadModel
    scorecard: ScorecardReadModel
    learning: LearningReadModel
    zerohero_status: str
    latest_zerohero_status: str | None
    ledger_status: str
    tariff_status: str

    def sensor_values(self) -> dict[str, object]:
        """Project existing individual sensor states without changing formatting."""
        return {
            "status": self.orchestrator_status,
            "fleet_summary": self.orchestrator_status,
            "battery_soc": self.battery_soc,
            "battery_power": self.battery_power_kw,
            "grid_power": self.grid_power_kw,
            "solar_power": self.solar_power_kw,
            "house_load": self.house_load_kw,
            "forecast_yesterday_cost": self.scorecard.forecast_cost,
            "globird_yesterday_actual_cost": self.scorecard.actual_cost,
            "forecast_error_yesterday": self.scorecard.forecast_error,
            "forecast_scorecard_status": self.scorecard.status,
            "zerohero_credit_status": self.zerohero_status,
            "zerohero_sellable_energy": self.sellable_energy_kwh,
            "zerohero_planned_export_energy": self.planned_export_kwh,
            "zerohero_planned_duration": self.planned_export_duration_minutes,
            "zerohero_planned_start": self.planned_export_start,
            "zerohero_export_status": self.export_status,
            **self.cost.sensor_values(),
            **self.learning.sensor_values(),
            **self.ev.sensor_values(),
        }

    def fleet_attributes(self, updated_at: datetime) -> dict[str, object]:
        """Project the stable Fleet Summary schema version 1 payload."""
        return {
            "summary_schema_version": 1,
            "battery_soc": _rounded(self.battery_soc, 2),
            "battery_power_kw": _rounded(self.battery_power_kw),
            "grid_power_kw": _rounded(self.grid_power_kw),
            "solar_power_kw": _rounded(self.solar_power_kw),
            "house_load_kw": _rounded(self.house_load_kw),
            "sellable_energy_kwh": _rounded(self.sellable_energy_kwh),
            "planned_export_kwh": _rounded(self.planned_export_kwh),
            "orchestrator_status": self.orchestrator_status,
            "foxess_control_gate": self.foxess_control_gate,
            "charging_status": self.charging_status,
            "export_status": self.export_status,
            "ev_control_status": self.ev.control_status,
            "forecast_cost": _rounded(self.cost.calibrated_net_cost, 2),
            "measured_cost": _rounded(self.cost.measured_net_cost, 2),
            "latest_actual_cost": _rounded(self.scorecard.actual_cost, 2),
            "forecast_error": _rounded(self.scorecard.forecast_error, 2),
            "zerohero_status": self.zerohero_status,
            "latest_zerohero_status": self.latest_zerohero_status,
            "forecast_scorecard_status": self.scorecard.status,
            "house_learning_samples": self.learning.sample_count,
            "ev_learning_samples": self.ev.learning_samples,
            "ledger_status": self.ledger_status,
            "tariff_status": self.tariff_status,
            "last_update": updated_at.isoformat(),
        }

    def forecast_diagnostics(self) -> dict[str, object]:
        """Project the existing redacted forecast support payload."""
        return {
            "net_cost": self.cost.calibrated_net_cost,
            "raw_net_cost": self.cost.raw_net_cost,
            "assumed_zerohero_credit": self.cost.assumed_zerohero_credit,
            "export_realisation_fraction": (
                self.cost.feedback_export_realisation_fraction
            ),
            "forecast_remaining_export_kwh": (
                self.cost.forecast_remaining_export_kwh
            ),
            "learned_cost_bias": self.cost.feedback_learned_cost_bias,
            "scorecard_status": self.scorecard.status,
            "scorecard_date": (
                None
                if self.scorecard.result_date is None
                else self.scorecard.result_date.isoformat()
            ),
            "scorecard_forecast_cost": self.scorecard.forecast_cost,
            "scorecard_actual_cost": self.scorecard.actual_cost,
            "scorecard_error": self.scorecard.forecast_error,
            "scorecard_zerohero_status": self.scorecard.zerohero_status,
        }


def _build_ev_read_model(
    coordinator: EnergyCoordinator, now: datetime
) -> EvReadModel:
    """Build the EV state projection without changing controller decisions."""
    snapshot = coordinator.snapshot
    ledger = coordinator.data
    controller = coordinator.ev_controller
    if controller is None:
        return EvReadModel(
            soc_percent=None if snapshot is None else snapshot.ev_soc,
            maximum_power_kw=ledger.ev_max_power_kw,
            control_status="unavailable",
            target_current_a=None,
            requested_current_a=None,
            actual_current_a=None,
            target_limit_percent=None,
            applied_limit_percent=None,
            grid_average_a=None,
            actual_average_a=None,
            reconciliation_attempts=0,
            smart_recovery_phase="unavailable",
            solar_spill_phase="unavailable",
            solar_spill_current_a=None,
            solar_spill_surplus_kw=None,
            pre_free_phase="unavailable",
            pre_free_planned_energy_kwh=None,
            pre_free_planned_start=None,
            pre_free_current_a=None,
            daily_backfill_status="disabled",
            daily_backfill_remaining_kwh=None,
            daily_backfill_delivered_kwh=None,
            daily_backfill_planned_energy_kwh=None,
            daily_backfill_shortfall_kwh=None,
            daily_backfill_planned_start=None,
            daily_backfill_current_a=None,
            daily_driving_energy_kwh=None,
            driving_p85_kwh=None,
            learning_samples=0,
            usable_capacity_kwh=None,
            free_window_soc_gain_percent=None,
            learned_charge_limit_percent=None,
            learning_status="unavailable",
        )
    grid_average = controller.grid_average.result(now)
    actual_average = controller.ev_average.result(now)
    learned = controller.learned_charge_limit
    pre_free_plan = controller.pre_free_plan
    daily_plan = controller.daily_backfill_plan
    return EvReadModel(
        soc_percent=None if snapshot is None else snapshot.ev_soc,
        maximum_power_kw=ledger.ev_max_power_kw,
        control_status=controller.last_reason,
        target_current_a=controller.target_current_a,
        requested_current_a=controller.requested_current_a,
        actual_current_a=controller.actual_current_a,
        target_limit_percent=controller.target_limit_percent,
        applied_limit_percent=controller.applied_limit_percent,
        grid_average_a=grid_average.value,
        actual_average_a=actual_average.value,
        reconciliation_attempts=controller.reconciliation.attempts,
        smart_recovery_phase=controller.smart_recovery.phase,
        solar_spill_phase=controller.solar_spill.phase,
        solar_spill_current_a=controller.solar_spill.current_a,
        solar_spill_surplus_kw=controller.solar_spill.reconstructed_surplus_kw,
        pre_free_phase=controller.pre_free_phase,
        pre_free_planned_energy_kwh=(
            None if pre_free_plan is None else pre_free_plan.planned_energy_kwh
        ),
        pre_free_planned_start=(
            None if pre_free_plan is None else pre_free_plan.planned_start
        ),
        pre_free_current_a=controller.pre_free_current_a,
        daily_backfill_status=(
            "active"
            if controller.daily_backfill_active
            else daily_plan.phase
            if daily_plan is not None
            else "disabled"
        ),
        daily_backfill_remaining_kwh=(
            None if daily_plan is None else daily_plan.remaining_allocation_kwh
        ),
        daily_backfill_delivered_kwh=controller.daily_backfill_delivered_kwh,
        daily_backfill_planned_energy_kwh=(
            None if daily_plan is None else daily_plan.planned_energy_kwh
        ),
        daily_backfill_shortfall_kwh=(
            None if daily_plan is None else daily_plan.allocation_shortfall_kwh
        ),
        daily_backfill_planned_start=(
            controller.daily_backfill_frozen_start
            if controller.daily_backfill_active
            else daily_plan.planned_start
            if daily_plan is not None
            else None
        ),
        daily_backfill_current_a=(
            None if daily_plan is None else daily_plan.current_ceiling_a
        ),
        daily_driving_energy_kwh=controller.daily_driving_energy_kwh,
        driving_p85_kwh=(
            None if learned is None else learned.p85_daily_energy_kwh
        ),
        learning_samples=len(controller.driving_history.samples),
        usable_capacity_kwh=(
            None if learned is None else learned.usable_capacity_kwh
        ),
        free_window_soc_gain_percent=(
            None if learned is None else learned.free_window_soc_gain_percent
        ),
        learned_charge_limit_percent=(
            None if learned is None else learned.limit_percent
        ),
        learning_status="unavailable" if learned is None else learned.mode,
    )


def build_site_read_model(
    coordinator: EnergyCoordinator, now: datetime | None = None
) -> SiteReadModel:
    """Build one canonical presentation snapshot from coordinator-owned state."""
    ledger = coordinator.data
    snapshot = coordinator.snapshot
    telemetry = coordinator.telemetry
    controller = coordinator.active_controller
    now = now or dt_util.now()
    forecast = coordinator.optimistic_forecast
    plan = effective_export_plan(coordinator)
    candidate_plan = controller.export_plan if controller is not None else None
    scorecard = (
        coordinator.forecast_feedback.record_for(coordinator.forecast_scorecard_date)
        if coordinator.forecast_scorecard_date is not None
        else None
    )
    feedback = coordinator.forecast_feedback
    learning = coordinator.learning_result
    base_learning = coordinator.base_learning_result
    heater_learning = coordinator.heater_learning_result
    occupancy = coordinator.occupancy_result
    cost = CostReadModel(
        measured_gross_cost=ledger.estimated_energy_cost,
        measured_import_cost=ledger.estimated_import_energy_cost,
        daily_supply_charge=ledger.daily_supply_charge,
        measured_export_revenue=ledger.estimated_export_revenue,
        measured_zerohero_credit=ledger.zerohero_credit,
        measured_net_cost=ledger.estimated_net_cost,
        calibrated_net_cost=(
            None if forecast is None else forecast.calibrated_net_cost
        ),
        raw_net_cost=None if forecast is None else forecast.raw_net_cost,
        assumed_zerohero_credit=(
            None if forecast is None else forecast.assumed_zerohero_credit
        ),
        forecast_export_realisation_fraction=(
            None if forecast is None else forecast.export_realisation_fraction
        ),
        forecast_remaining_export_kwh=(
            None if forecast is None else forecast.forecast_remaining_export_kwh
        ),
        forecast_additional_export_revenue=(
            None
            if forecast is None
            else forecast.forecast_additional_export_revenue
        ),
        forecast_learned_cost_bias=(
            None if forecast is None else forecast.learned_cost_bias
        ),
        feedback_export_realisation_fraction=feedback.export_realisation_fraction,
        feedback_learned_cost_bias=feedback.learned_cost_bias,
    )
    scorecard_model = ScorecardReadModel(
        status=coordinator.forecast_scorecard_status,
        result_date=coordinator.forecast_scorecard_date,
        forecast_cost=(
            None if scorecard is None else scorecard.frozen_forecast_cost
        ),
        raw_forecast_cost=(
            None if scorecard is None else scorecard.frozen_raw_forecast_cost
        ),
        actual_cost=(
            None if scorecard is None else scorecard.retailer_actual_cost
        ),
        forecast_error=(
            None if scorecard is None else scorecard.forecast_error
        ),
        zerohero_status=(
            None if scorecard is None else scorecard.retailer_zerohero_status
        ),
        planned_export_kwh=(
            None if scorecard is None else scorecard.planned_export_kwh
        ),
        realised_export_kwh=(
            None if scorecard is None else scorecard.realised_export_kwh
        ),
        export_realisation_ratio=(
            None if scorecard is None else scorecard.export_realisation_ratio
        ),
        feedback_applied=False if scorecard is None else scorecard.feedback_applied,
        learned_export_realisation_fraction=feedback.export_realisation_fraction,
        learned_cost_bias=feedback.learned_cost_bias,
    )
    learning_model = LearningReadModel(
        model=learning.model,
        cycle_budget_kwh=learning.cycle_budget_kwh,
        base_cycle_budget_kwh=base_learning.cycle_budget_kwh,
        heater_cycle_budget_kwh=(
            None if heater_learning is None else heater_learning.cycle_budget_kwh
        ),
        remaining_cycle_budget_kwh=coordinator.learning_remaining_kwh,
        sample_count=learning.sample_count,
        retained_sample_count=len(coordinator.demand_history.samples),
        heater_sample_count=learning.heater_sample_count,
        heater_retained_sample_count=len(coordinator.heater_history.samples),
        heater_model=(
            "not_mapped" if heater_learning is None else heater_learning.model
        ),
        budget_occupancy=learning.occupancy,
        occupancy_state=occupancy.state,
        occupancy_mode=occupancy.selected_mode,
        occupancy_reason=occupancy.reason,
        person_count=occupancy.person_count,
        people_home=occupancy.people_home,
        all_people_away_for_hours=occupancy.all_people_away_for_hours,
    )
    ev_model = _build_ev_read_model(coordinator, now)
    return SiteReadModel(
        orchestrator_status=control_mode(coordinator),
        battery_soc=None if snapshot is None else snapshot.battery_soc,
        battery_power_kw=(
            None if telemetry is None else telemetry.battery_power.value
        ),
        grid_power_kw=None if telemetry is None else telemetry.grid_power.value,
        solar_power_kw=None if telemetry is None else telemetry.solar_power.value,
        house_load_kw=None if snapshot is None else snapshot.house_load_kw,
        sellable_energy_kwh=(
            None if candidate_plan is None else candidate_plan.sellable_energy_kwh
        ),
        planned_export_kwh=(
            None if plan is None else plan.planned_export_energy_kwh
        ),
        planned_export_duration_minutes=(
            None if plan is None else round(plan.planned_duration_h * 60, 1)
        ),
        planned_export_start=(
            None if plan is None or controller is None else controller.export_planned_start
        ),
        foxess_control_gate=(
            "unavailable" if controller is None else controller.gate_status
        ),
        charging_status=(
            "unavailable" if controller is None else controller.charge_session.phase
        ),
        export_status=export_status(coordinator),
        ev=ev_model,
        cost=cost,
        scorecard=scorecard_model,
        learning=learning_model,
        zerohero_status=ledger.zerohero_credit_status,
        latest_zerohero_status=(
            None if scorecard is None else scorecard.retailer_zerohero_status
        ),
        ledger_status=ledger.reason,
        tariff_status=ledger.tariff_reason,
    )
