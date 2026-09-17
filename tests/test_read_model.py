"""Canonical presentation-model characterization tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_FOXESS_CONTROL_OWNER,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from custom_components.home_energy_orchestrator.planner.export import ExportPlan
from custom_components.home_energy_orchestrator.read_model import build_site_read_model


def _coordinator() -> SimpleNamespace:
    scorecard = SimpleNamespace(
        frozen_forecast_cost=1.234,
        frozen_raw_forecast_cost=1.111,
        retailer_actual_cost=1.456,
        forecast_error=0.222,
        retailer_zerohero_status="achieved",
        planned_export_kwh=10.0,
        realised_export_kwh=8.0,
        export_realisation_ratio=0.8,
        feedback_applied=True,
    )
    controller = SimpleNamespace(
        ownership_status="owned",
        gate_status="ready",
        export_effective_enabled=True,
        export_plan=ExportPlan(12.3456, 7.6543, 0.76543, "ready"),
        export_planned_start=datetime(2026, 9, 17, 18, 0, tzinfo=UTC),
        charge_session=SimpleNamespace(phase="charging"),
        export_session=SimpleNamespace(phase="exporting"),
        ev_before_export_decision=SimpleNamespace(
            export_allowed=True,
            reason="target_met",
        ),
    )
    return SimpleNamespace(
        runtime_config=RuntimeConfiguration.from_mapping(
            {
                CONF_FOXESS_CONTROL_OWNER: FOXESS_CONTROL_OWNER_MODBUS,
                CONF_AUTOMATIC_CHARGE_ENABLED: True,
                CONF_AUTOMATIC_EXPORT_ENABLED: True,
            }
        ),
        active_controller=controller,
        ev_controller=SimpleNamespace(
            last_reason="free_window",
            driving_history=SimpleNamespace(samples=(1, 2, 3)),
        ),
        data=SimpleNamespace(
            estimated_energy_cost=3.456,
            estimated_export_revenue=1.112,
            zerohero_credit=1.0,
            estimated_net_cost=2.344,
            zerohero_credit_status="pending_window_completion",
            reason="ready",
            tariff_reason="ready",
        ),
        snapshot=SimpleNamespace(battery_soc=61.234, house_load_kw=1.23456),
        telemetry=SimpleNamespace(
            battery_power=SimpleNamespace(value=-3.45678),
            grid_power=SimpleNamespace(value=-1.23456),
            solar_power=SimpleNamespace(value=4.56789),
        ),
        optimistic_forecast=SimpleNamespace(
            calibrated_net_cost=2.345,
            raw_net_cost=2.567,
            assumed_zerohero_credit=1.0,
            export_realisation_fraction=0.75,
            forecast_remaining_export_kwh=7.6543,
            forecast_additional_export_revenue=0.42,
            learned_cost_bias=-0.05,
        ),
        forecast_scorecard_date=date(2026, 9, 16),
        forecast_scorecard_status="matched",
        forecast_feedback=SimpleNamespace(
            record_for=lambda _day: scorecard,
            export_realisation_fraction=0.8,
            learned_cost_bias=-0.04,
        ),
        learning_result=SimpleNamespace(
            model="occupied_combined_p80",
            cycle_budget_kwh=6.5,
            sample_count=7,
            heater_sample_count=5,
            occupancy="home",
        ),
        base_learning_result=SimpleNamespace(cycle_budget_kwh=5.0),
        heater_learning_result=SimpleNamespace(
            cycle_budget_kwh=1.5,
            model="p80",
        ),
        learning_remaining_kwh=2.25,
        demand_history=SimpleNamespace(samples=(1, 2, 3, 4, 5, 6, 7)),
        heater_history=SimpleNamespace(samples=(1, 2, 3, 4, 5)),
        occupancy_result=SimpleNamespace(
            state="home",
            selected_mode="auto",
            reason="people_home",
            person_count=2,
            people_home=1,
            all_people_away_for_hours=0.0,
        ),
    )


def test_site_read_model_projects_existing_sensor_and_fleet_values() -> None:
    coordinator = _coordinator()
    model = build_site_read_model(coordinator)
    updated_at = datetime(2026, 9, 17, 10, 25, tzinfo=UTC)

    assert model.sensor_values() == {
        "status": "local_modbus_charge_and_export",
        "fleet_summary": "local_modbus_charge_and_export",
        "battery_soc": 61.234,
        "battery_power": -3.45678,
        "grid_power": -1.23456,
        "solar_power": 4.56789,
        "house_load": 1.23456,
        "ev_control_status": "free_window",
        "estimated_net_cost": 2.35,
        "measured_net_cost": 2.34,
        "forecast_yesterday_cost": 1.234,
        "globird_yesterday_actual_cost": 1.456,
        "forecast_error_yesterday": 0.222,
        "forecast_scorecard_status": "matched",
        "zerohero_credit_status": "pending_window_completion",
        "zerohero_sellable_energy": 12.3456,
        "zerohero_planned_export_energy": 7.6543,
        "zerohero_planned_duration": 45.9,
        "zerohero_planned_start": datetime(2026, 9, 17, 18, 0, tzinfo=UTC),
        "zerohero_export_status": "exporting",
        "learned_house_energy": 6.5,
        "learned_base_house_energy": 5.0,
        "learned_heater_energy": 1.5,
        "remaining_house_energy": 2.25,
        "learning_samples": 7,
        "learning_status": "occupied_combined_p80",
        "heater_learning_samples": 5,
        "house_occupancy_state": "home",
    }
    assert model.fleet_attributes(updated_at) == {
        "summary_schema_version": 1,
        "battery_soc": 61.23,
        "battery_power_kw": -3.457,
        "grid_power_kw": -1.235,
        "solar_power_kw": 4.568,
        "house_load_kw": 1.235,
        "sellable_energy_kwh": 12.346,
        "planned_export_kwh": 7.654,
        "orchestrator_status": "local_modbus_charge_and_export",
        "foxess_control_gate": "ready",
        "charging_status": "charging",
        "export_status": "exporting",
        "ev_control_status": "free_window",
        "forecast_cost": 2.35,
        "measured_cost": 2.34,
        "latest_actual_cost": 1.46,
        "forecast_error": 0.22,
        "zerohero_status": "pending_window_completion",
        "latest_zerohero_status": "achieved",
        "forecast_scorecard_status": "matched",
        "house_learning_samples": 7,
        "ev_learning_samples": 3,
        "ledger_status": "ready",
        "tariff_status": "ready",
        "last_update": "2026-09-17T10:25:00+00:00",
    }
    assert model.cost.sensor_attributes() == {
        "gross_cost": 3.456,
        "measured_export_revenue": 1.112,
        "measured_zerohero_credit": 1.0,
        "measured_net_cost": 2.344,
        "assumed_zerohero_credit": 1.0,
        "export_realisation_percent": 75.0,
        "forecast_remaining_export_kwh": 7.6543,
        "forecast_additional_export_revenue": 0.42,
        "raw_optimistic_forecast": 2.567,
        "learned_cost_bias": -0.05,
    }
    assert model.scorecard.sensor_attributes() == {
        "result_date": "2026-09-16",
        "forecast_cost": 1.234,
        "raw_forecast_cost": 1.111,
        "actual_cost": 1.456,
        "forecast_error": 0.222,
        "zerohero_status": "achieved",
        "planned_export_kwh": 10.0,
        "realised_export_kwh": 8.0,
        "export_realisation_ratio": 0.8,
        "forecast_feedback_applied": True,
        "learned_export_realisation_percent": 80.0,
        "learned_cost_bias": -0.04,
    }
    assert model.forecast_diagnostics() == {
        "net_cost": 2.345,
        "raw_net_cost": 2.567,
        "assumed_zerohero_credit": 1.0,
        "export_realisation_fraction": 0.8,
        "forecast_remaining_export_kwh": 7.6543,
        "learned_cost_bias": -0.04,
        "scorecard_status": "matched",
        "scorecard_date": "2026-09-16",
        "scorecard_forecast_cost": 1.234,
        "scorecard_actual_cost": 1.456,
        "scorecard_error": 0.222,
        "scorecard_zerohero_status": "achieved",
    }
    assert model.learning.occupancy_attributes() == {
        "selected_mode": "auto",
        "person_entities_found": 2,
        "people_home": 1,
        "all_people_away_for_hours": 0.0,
        "reason": "people_home",
    }
    assert model.learning.diagnostics() == {
        "model": "occupied_combined_p80",
        "cycle_budget_kwh": 6.5,
        "sample_count": 7,
        "retained_sample_count": 7,
        "heater_sample_count": 5,
        "heater_retained_sample_count": 5,
        "heater_model": "p80",
        "occupancy": "home",
        "occupancy_mode": "auto",
        "occupancy_reason": "people_home",
        "person_entities_found": 2,
        "people_home": 1,
        "all_people_away_for_hours": 0.0,
    }


def test_candidate_export_remains_visible_while_effective_plan_is_withheld() -> None:
    coordinator = _coordinator()
    coordinator.active_controller.export_effective_enabled = False
    coordinator.active_controller.ev_before_export_decision = SimpleNamespace(
        export_allowed=False,
        reason="ev_below_target",
    )

    model = build_site_read_model(coordinator)

    assert model.sellable_energy_kwh == 12.3456
    assert model.planned_export_kwh is None
    assert model.planned_export_duration_minutes is None
    assert model.planned_export_start is None
    assert model.export_status == "withheld_ev_below_target"


def test_site_read_model_is_immutable() -> None:
    model = build_site_read_model(_coordinator())

    with pytest.raises(FrozenInstanceError):
        model.battery_soc = 0  # type: ignore[misc]
