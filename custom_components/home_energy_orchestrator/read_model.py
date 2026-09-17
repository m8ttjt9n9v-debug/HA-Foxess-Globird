"""Immutable presentation model shared by entities, diagnostics and Fleet."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

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
    ev_control_status: str
    forecast_cost: float | None
    measured_cost: float | None
    latest_forecast_cost: float | None
    latest_actual_cost: float | None
    forecast_error: float | None
    zerohero_status: str
    latest_zerohero_status: str | None
    forecast_scorecard_status: str
    house_learning_samples: int
    ev_learning_samples: int
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
            "ev_control_status": self.ev_control_status,
            "estimated_net_cost": _rounded(self.forecast_cost, 2),
            "measured_net_cost": _rounded(self.measured_cost, 2),
            "forecast_yesterday_cost": self.latest_forecast_cost,
            "globird_yesterday_actual_cost": self.latest_actual_cost,
            "forecast_error_yesterday": self.forecast_error,
            "forecast_scorecard_status": self.forecast_scorecard_status,
            "zerohero_credit_status": self.zerohero_status,
            "zerohero_sellable_energy": self.sellable_energy_kwh,
            "zerohero_planned_export_energy": self.planned_export_kwh,
            "zerohero_planned_duration": self.planned_export_duration_minutes,
            "zerohero_planned_start": self.planned_export_start,
            "zerohero_export_status": self.export_status,
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
            "ev_control_status": self.ev_control_status,
            "forecast_cost": _rounded(self.forecast_cost, 2),
            "measured_cost": _rounded(self.measured_cost, 2),
            "latest_actual_cost": _rounded(self.latest_actual_cost, 2),
            "forecast_error": _rounded(self.forecast_error, 2),
            "zerohero_status": self.zerohero_status,
            "latest_zerohero_status": self.latest_zerohero_status,
            "forecast_scorecard_status": self.forecast_scorecard_status,
            "house_learning_samples": self.house_learning_samples,
            "ev_learning_samples": self.ev_learning_samples,
            "ledger_status": self.ledger_status,
            "tariff_status": self.tariff_status,
            "last_update": updated_at.isoformat(),
        }


def build_site_read_model(coordinator: EnergyCoordinator) -> SiteReadModel:
    """Build one canonical presentation snapshot from coordinator-owned state."""
    ledger = coordinator.data
    snapshot = coordinator.snapshot
    telemetry = coordinator.telemetry
    controller = coordinator.active_controller
    ev_controller = coordinator.ev_controller
    forecast = coordinator.optimistic_forecast
    plan = effective_export_plan(coordinator)
    candidate_plan = controller.export_plan if controller is not None else None
    scorecard = (
        coordinator.forecast_feedback.record_for(coordinator.forecast_scorecard_date)
        if coordinator.forecast_scorecard_date is not None
        else None
    )
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
        ev_control_status=(
            "unavailable" if ev_controller is None else ev_controller.last_reason
        ),
        forecast_cost=(
            None if forecast is None else forecast.calibrated_net_cost
        ),
        measured_cost=ledger.estimated_net_cost,
        latest_forecast_cost=(
            None if scorecard is None else scorecard.frozen_forecast_cost
        ),
        latest_actual_cost=(
            None if scorecard is None else scorecard.retailer_actual_cost
        ),
        forecast_error=None if scorecard is None else scorecard.forecast_error,
        zerohero_status=ledger.zerohero_credit_status,
        latest_zerohero_status=(
            None if scorecard is None else scorecard.retailer_zerohero_status
        ),
        forecast_scorecard_status=coordinator.forecast_scorecard_status,
        house_learning_samples=coordinator.learning_result.sample_count,
        ev_learning_samples=(
            0 if ev_controller is None else len(ev_controller.driving_history.samples)
        ),
        ledger_status=ledger.reason,
        tariff_status=ledger.tariff_reason,
    )
