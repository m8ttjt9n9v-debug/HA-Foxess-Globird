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
        last_reason="battery_idle",
        last_actions=("set_self_use",),
        writes_performed=2,
        export_effective_enabled=True,
        export_plan=ExportPlan(12.3456, 7.6543, 0.76543, "ready"),
        export_planned_start=datetime(2026, 9, 17, 18, 0, tzinfo=UTC),
        charge_session=SimpleNamespace(phase="charging"),
        charge_power_target_kw=7.5,
        export_session=SimpleNamespace(phase="exporting"),
        automatic_export_remaining_kwh=4.5,
        export_protected_ev_kwh=2.0,
        ev_before_export_decision=SimpleNamespace(
            export_allowed=True,
            reason="target_met",
        ),
    )
    source = SimpleNamespace(
        entity_id="sensor.source",
        raw_value="1.23",
        raw_unit="kW",
        updated_at=datetime(2026, 9, 17, 9, 59, tzinfo=UTC),
    )

    def telemetry_sample(
        value: float, unit: str, positive_direction: str
    ) -> SimpleNamespace:
        return SimpleNamespace(
            value=value,
            unit=unit,
            positive_direction=positive_direction,
            valid=True,
            fresh=True,
            reason="ok",
            sources=(source,),
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
            gate_status="ready",
            decision_phase="free_power",
            allowance_phase="within_allowance",
            allowance_house_load_kw=1.25,
            allowance_ev_power_kw=10.5,
            target_current_a=16.0,
            requested_current_a=15.0,
            actual_current_a=14.0,
            target_limit_percent=90,
            applied_limit_percent=89,
            charge_switch_on=True,
            grid_average=SimpleNamespace(
                result=lambda _now: SimpleNamespace(
                    value=-2.5,
                    age_coverage_ratio=0.95,
                    source_value_valid=True,
                )
            ),
            ev_average=SimpleNamespace(
                result=lambda _now: SimpleNamespace(
                    value=14.5,
                    source_value_valid=True,
                )
            ),
            reconciliation=SimpleNamespace(phase="confirming", attempts=2),
            smart_recovery=SimpleNamespace(
                phase="healthy",
                attempted=True,
                phase_started_at=datetime(2026, 9, 17, 9, 0, tzinfo=UTC),
                recovery_current_a=6.0,
            ),
            last_actions=("set_current",),
            writes_performed=4,
            last_write_at=datetime(2026, 9, 17, 9, 1, tzinfo=UTC),
            solar_spill=SimpleNamespace(
                phase="tracking",
                current_a=12.0,
                reconstructed_surplus_kw=8.2,
            ),
            pre_free_session=SimpleNamespace(
                active=True,
                frozen_start=datetime(2026, 9, 17, 13, 15, tzinfo=UTC),
            ),
            pre_free_phase="planned",
            pre_free_plan=SimpleNamespace(
                planned_energy_kwh=4.2,
                planned_start=datetime(2026, 9, 17, 13, 30, tzinfo=UTC),
            ),
            pre_free_current_a=10.0,
            outside_control_active=True,
            daily_backfill_active=False,
            daily_backfill_cycle_ready_at=datetime(
                2026, 9, 18, 4, 30, tzinfo=UTC
            ),
            daily_backfill_session_target_kwh=5.5,
            daily_backfill_plan=SimpleNamespace(
                phase="planned",
                remaining_allocation_kwh=6.0,
                planned_energy_kwh=5.5,
                allocation_shortfall_kwh=0.5,
                planned_start=datetime(2026, 9, 18, 5, 0, tzinfo=UTC),
                current_ceiling_a=16.0,
            ),
            daily_backfill_delivered_kwh=1.25,
            daily_backfill_frozen_start=None,
            charge_to_full_started_at=datetime(
                2026, 9, 17, 8, 30, tzinfo=UTC
            ),
            daily_driving_energy_kwh=9.5,
            learned_charge_limit=SimpleNamespace(
                p85_daily_energy_kwh=11.0,
                usable_capacity_kwh=72.0,
                free_window_soc_gain_percent=35.0,
                limit_percent=82,
                mode="learned",
            ),
            driving_history=SimpleNamespace(samples=(1, 2, 3)),
        ),
        data=SimpleNamespace(
            battery_potential_capacity_kwh=30.0,
            battery_energy_kwh=20.0,
            available_after_reserve_kwh=15.0,
            grid_import_kw=0.5,
            grid_export_kw=0.1,
            free_energy_remaining_kwh=40.0,
            daily_import_kwh=10.0,
            free_window_import_kwh=8.0,
            daily_export_kwh=5.0,
            standard_window_export_kwh=4.0,
            boosted_window_export_kwh=2.0,
            standard_rate_export_kwh=4.0,
            offpeak_rate_export_kwh=1.0,
            boosted_rate_export_kwh=2.0,
            free_charge_allowed_kwh=30.0,
            bonus_zero_import_allowed=True,
            estimated_energy_cost=3.456,
            estimated_import_energy_cost=4.567,
            daily_supply_charge=1.234,
            standard_export_revenue=0.2,
            offpeak_export_revenue=0.3,
            boosted_bonus_revenue=0.4,
            estimated_export_revenue=1.112,
            zerohero_credit=1.0,
            estimated_net_cost=2.344,
            zerohero_credit_status="pending_window_completion",
            reason="ready",
            tariff_reason="ready",
            ev_max_power_kw=11.04,
        ),
        snapshot=SimpleNamespace(
            battery_soc=61.234,
            house_load_kw=1.23456,
            ev_soc=74.0,
        ),
        telemetry=SimpleNamespace(
            battery_power=telemetry_sample(-3.45678, "kW", "positive_charge"),
            grid_power=telemetry_sample(-1.23456, "kW", "positive_import"),
            solar_power=telemetry_sample(4.56789, "kW", "positive_generation"),
            house_load=telemetry_sample(1.23456, "kW", "positive_consumption"),
            site_grid_current=telemetry_sample(3.2, "A", "positive_import"),
        ),
        zerohero_import=SimpleNamespace(
            last_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
            hourly_import_kwh={"16": 0.1, "17": 0.2},
        ),
        zerohero_export=SimpleNamespace(imported_kwh=0.12345),
        manual_test=SimpleNamespace(
            preview_charge=lambda: SimpleNamespace(amount=1.25),
            current_import_rate=lambda: 0.57,
            preview_discharge=lambda: SimpleNamespace(amount=0.75),
            current_export_rate=lambda: 0.10,
            status="idle",
            remaining_minutes=0.0,
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
        demand_history=SimpleNamespace(
            samples=(1, 2, 3, 4, 5, 6, 7),
            max_age_days=35,
            sample_limit=28,
        ),
        demand_sampler=object(),
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
        "battery_potential_capacity": 30.0,
        "battery_energy": 20.0,
        "available_energy": 15.0,
        "grid_import": 0.5,
        "grid_export": 0.1,
        "site_grid_current": 3.2,
        "free_energy_remaining": 40.0,
        "daily_import": 10.0,
        "free_window_import": 8.0,
        "daily_export": 5.0,
        "standard_export_window": 4.0,
        "offpeak_export": 1.0,
        "free_charge_allowed": 30.0,
        "free_charge_power_target": 7.5,
        "free_charge_completion": "charging",
        "bonus_zero_import_allowed": True,
        "zerohero_import_window": 0.3,
        "tariff_status": "ready",
        "zerohero_export_window": 0.123,
        "ev_before_export_status": "target_met",
        "test_charge_estimated_cost": 1.25,
        "test_charge_import_rate": 0.57,
        "test_discharge_estimated_earning": 0.75,
        "test_discharge_export_rate": 0.10,
        "test_status": "idle",
        "test_remaining_minutes": 0.0,
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
        "ev_soc": 74.0,
        "ev_max_power": 11.04,
        "ev_current_target": 16.0,
        "ev_requested_current": 15.0,
        "ev_actual_current": 14.0,
        "ev_charge_limit_target": 90,
        "ev_applied_charge_limit": 89,
        "ev_grid_current_average": -2.5,
        "ev_actual_current_average": 14.5,
        "ev_reconciliation_attempts": 2,
        "ev_smart_socket_recovery_status": "healthy",
        "ev_solar_spill_status": "tracking",
        "ev_solar_spill_current_target": 12.0,
        "ev_solar_spill_surplus": 8.2,
        "ev_pre_free_status": "planned",
        "ev_pre_free_planned_energy": 4.2,
        "ev_pre_free_planned_start": datetime(
            2026, 9, 17, 13, 30, tzinfo=UTC
        ),
        "ev_pre_free_current_target": 10.0,
        "ev_daily_backfill_status": "planned",
        "ev_daily_backfill_remaining": 6.0,
        "ev_daily_backfill_delivered": 1.25,
        "ev_daily_backfill_planned_energy": 5.5,
        "ev_daily_backfill_shortfall": 0.5,
        "ev_daily_backfill_planned_start": datetime(
            2026, 9, 18, 5, 0, tzinfo=UTC
        ),
        "ev_daily_backfill_current_target": 16.0,
        "ev_daily_driving_energy": 9.5,
        "ev_driving_p85": 11.0,
        "ev_driving_learning_samples": 3,
        "ev_usable_capacity": 72.0,
        "ev_free_window_soc_gain": 35.0,
        "ev_learned_charge_limit": 82,
        "ev_driving_learning_status": "learned",
        "estimated_energy_cost": 3.46,
        "estimated_import_energy_cost": 4.57,
        "daily_supply_charge": 1.23,
        "estimated_export_revenue": 1.11,
        "zerohero_credit": 1.0,
        "forecast_export_realisation": 80.0,
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


def test_telemetry_read_model_preserves_entity_and_diagnostic_shapes() -> None:
    telemetry = build_site_read_model(_coordinator()).telemetry

    assert telemetry.entity_attributes("grid_power") == {
        "positive_direction": "positive_import",
        "valid": True,
        "fresh": True,
        "reason": "ok",
        "sources": [
            {
                "entity_id": "sensor.source",
                "raw_value": "1.23",
                "raw_unit": "kW",
                "updated_at": "2026-09-17T09:59:00+00:00",
            }
        ],
    }
    assert telemetry.diagnostics()["grid_power"] == {
        "value": -1.23456,
        "unit": "kW",
        "positive_direction": "positive_import",
        "valid": True,
        "fresh": True,
        "reason": "ok",
        "source_count": 1,
    }
    assert set(telemetry.diagnostics()) == {
        "grid_power",
        "battery_power",
        "solar_power",
        "house_load",
        "site_grid_current",
    }


def test_missing_telemetry_preserves_empty_attribute_and_diagnostic_payloads() -> None:
    coordinator = _coordinator()
    coordinator.telemetry = None

    telemetry = build_site_read_model(coordinator).telemetry

    assert telemetry.entity_attributes("grid_power") is None
    assert telemetry.diagnostics() == {}


def test_ev_control_attributes_preserve_existing_public_values() -> None:
    model = build_site_read_model(_coordinator())

    assert model.ev.control_attributes() == {
        "gate": "ready",
        "decision_phase": "free_power",
        "allowance_phase": "within_allowance",
        "allowance_house_load_kw": 1.25,
        "allowance_ev_power_kw": 10.5,
        "target_current_a": 16.0,
        "target_limit_percent": 90,
        "requested_current_a": 15.0,
        "actual_current_a": 14.0,
        "applied_limit_percent": 89,
        "charge_switch_on": True,
        "reconciliation_phase": "confirming",
        "reconciliation_attempts": 2,
        "maximum_reconciliation_attempts": 3,
        "smart_socket_recovery_phase": "healthy",
        "smart_socket_recovery_attempted": True,
        "smart_socket_recovery_started_at": datetime(
            2026, 9, 17, 9, 0, tzinfo=UTC
        ),
        "smart_socket_recovery_current_a": 6.0,
        "grid_average_coverage": 0.95,
        "grid_source_valid": True,
        "ev_average_source_valid": True,
        "last_actions": ("set_current",),
        "writes_performed": 4,
        "last_write_at": datetime(2026, 9, 17, 9, 1, tzinfo=UTC),
        "solar_spill_phase": "tracking",
        "solar_spill_current_a": 12.0,
        "solar_spill_reconstructed_kw": 8.2,
        "pre_free_session_active": True,
        "pre_free_phase": "planned",
        "pre_free_frozen_start": datetime(
            2026, 9, 17, 13, 15, tzinfo=UTC
        ),
        "pre_free_planned_energy_kwh": 4.2,
        "pre_free_planned_start": datetime(
            2026, 9, 17, 13, 30, tzinfo=UTC
        ),
        "pre_free_current_a": 10.0,
        "outside_control_active": True,
        "daily_backfill_active": False,
        "daily_backfill_cycle_ready_at": datetime(
            2026, 9, 18, 4, 30, tzinfo=UTC
        ),
        "daily_backfill_delivered_kwh": 1.25,
        "daily_backfill_session_target_kwh": 5.5,
        "daily_backfill_frozen_start": None,
        "charge_to_full_started_at": datetime(
            2026, 9, 17, 8, 30, tzinfo=UTC
        ),
        "driving_learning_mode": "learned",
        "driving_learning_samples": 3,
        "driving_p85_kwh": 11.0,
        "learned_general_limit_percent": 82,
    }


def test_export_revenue_attributes_use_authoritative_accounting_components() -> None:
    model = build_site_read_model(_coordinator())

    assert model.cost.export_revenue_attributes() == {
        "standard_rate_export_kwh": 4.0,
        "offpeak_rate_export_kwh": 1.0,
        "standard_window_export_kwh": 4.0,
        "boosted_rate_export_kwh": 2.0,
        "boosted_window_export_kwh": 2.0,
        "standard_rate_per_kwh": 0.0,
        "offpeak_rate_per_kwh": 0.0,
        "additional_boost_rate_per_kwh": 0.1,
        "standard_export_revenue": 0.2,
        "offpeak_export_revenue": 0.3,
        "boosted_bonus_revenue": 0.4,
    }


def test_ev_actuator_diagnostics_preserve_existing_support_values() -> None:
    model = build_site_read_model(_coordinator())

    assert model.ev.actuator_diagnostics("ready") == {
        "ev_control_gate": "ready",
        "ev_writes_enabled": True,
        "ev_last_reason": "free_window",
        "ev_last_actions": ("set_current",),
        "ev_writes_performed": 4,
        "ev_target_current_a": 16.0,
        "ev_target_limit_percent": 90,
        "ev_requested_current_a": 15.0,
        "ev_actual_current_a": 14.0,
        "ev_applied_limit_percent": 89,
        "ev_charge_switch_on": True,
        "ev_reconciliation_phase": "confirming",
        "ev_reconciliation_attempts": 2,
        "ev_smart_socket_recovery_phase": "healthy",
        "ev_smart_socket_recovery_attempted": True,
        "ev_smart_socket_recovery_started_at": datetime(
            2026, 9, 17, 9, 0, tzinfo=UTC
        ),
        "ev_smart_socket_recovery_current_a": 6.0,
        "ev_solar_spill_phase": "tracking",
        "ev_solar_spill_current_a": 12.0,
        "ev_pre_free_session_active": True,
        "ev_pre_free_phase": "planned",
        "ev_pre_free_planned_energy_kwh": 4.2,
        "ev_pre_free_planned_start": datetime(
            2026, 9, 17, 13, 30, tzinfo=UTC
        ),
        "ev_pre_free_current_a": 10.0,
        "ev_outside_control_active": True,
    }


def test_status_attributes_preserve_existing_public_values() -> None:
    model = build_site_read_model(_coordinator())

    assert model.status_attributes() == {
        "mode": "local_modbus_charge_and_export",
        "ledger_status": "ready",
        "control_gate": "ready",
        "last_control_reason": "battery_idle",
        "last_control_actions": ("set_self_use",),
        "writes_performed": 2,
        "automatic_control_enabled": False,
        "automatic_charge_enabled": True,
        "free_charge_schedule_confirmed": False,
        "sign_conventions_verified": False,
        "foxess_modbus_control_effective": True,
        "foxess_control_owner": "local_modbus",
        "automatic_export_enabled": True,
        "automatic_export_effective": True,
        "ev_before_export_status": "target_met",
        "ev_automatic_control_enabled": False,
        "ev_control_gate": "ready",
        "ev_writes_enabled": True,
        "ev_last_control_reason": "free_window",
        "ev_last_control_actions": ("set_current",),
        "ev_writes_performed": 4,
        "ev_decision_phase": "free_power",
        "ev_allowance_phase": "within_allowance",
        "ev_target_current_a": 16.0,
        "ev_target_limit_percent": 90,
        "ev_reconciliation_phase": "confirming",
        "ev_reconciliation_attempts": 2,
        "ev_last_write_at": datetime(2026, 9, 17, 9, 1, tzinfo=UTC),
        "ev_driving_learning_mode": "learned",
        "ev_driving_learning_samples": 3,
        "ev_learned_general_limit_percent": 82,
        "export_session_phase": "exporting",
        "charge_session_phase": "charging",
        "charge_power_target_kw": 7.5,
        "export_allowance_remaining_kwh": 4.5,
        "automatic_export_remaining_kwh": 4.5,
        "export_protected_ev_kwh": 2.0,
        "rehearsal_mode": True,
        "integration": "home_energy_orchestrator",
        "learning_model": "occupied_combined_p80",
        "learning_samples": 7,
        "heater_learning_samples": 5,
        "house_occupancy": "home",
        "house_occupancy_reason": "people_home",
        "learning_max_age_days": 35,
        "learning_sample_limit": 28,
        "learning_sampler_enabled": True,
    }


def test_missing_ev_controller_preserves_unavailable_state_defaults() -> None:
    coordinator = _coordinator()
    coordinator.ev_controller = None

    values = build_site_read_model(coordinator).ev.sensor_values()

    assert values["ev_soc"] == 74.0
    assert values["ev_max_power"] == 11.04
    assert values["ev_control_status"] == "unavailable"
    assert values["ev_reconciliation_attempts"] == 0
    assert values["ev_smart_socket_recovery_status"] == "unavailable"
    assert values["ev_daily_backfill_status"] == "disabled"
    assert values["ev_driving_learning_samples"] == 0
    assert values["ev_driving_learning_status"] == "unavailable"
    assert values["ev_current_target"] is None
    ev_model = build_site_read_model(coordinator).ev
    assert ev_model.control_attributes() == {"gate": "unavailable"}
    diagnostics = ev_model.actuator_diagnostics("disabled")
    assert diagnostics["ev_control_gate"] == "disabled"
    assert diagnostics["ev_writes_enabled"] is False
    assert diagnostics["ev_last_reason"] == "unavailable"
    assert diagnostics["ev_last_actions"] == ()
    assert diagnostics["ev_reconciliation_phase"] == "unavailable"
    assert diagnostics["ev_smart_socket_recovery_phase"] == "unavailable"
    assert diagnostics["ev_pre_free_session_active"] is False


def test_status_attributes_preserve_no_controller_fallbacks() -> None:
    coordinator = _coordinator()
    coordinator.active_controller = None
    coordinator.ev_controller = None

    attributes = build_site_read_model(coordinator).status_attributes()

    assert attributes["control_gate"] == "unavailable"
    assert attributes["last_control_reason"] == "unavailable"
    assert attributes["ev_control_gate"] == "disabled"
    assert attributes["ev_last_control_reason"] == "unavailable"
    assert attributes["export_session_phase"] == "unavailable"
    assert attributes["charge_session_phase"] == "unavailable"


def test_active_daily_backfill_exposes_frozen_start() -> None:
    coordinator = _coordinator()
    frozen_start = datetime(2026, 9, 18, 4, 45, tzinfo=UTC)
    coordinator.ev_controller.daily_backfill_active = True
    coordinator.ev_controller.daily_backfill_frozen_start = frozen_start

    model = build_site_read_model(coordinator)

    assert model.ev.daily_backfill_status == "active"
    assert model.ev.daily_backfill_planned_start == frozen_start


def test_site_read_model_is_immutable() -> None:
    model = build_site_read_model(_coordinator())

    with pytest.raises(FrozenInstanceError):
        model.battery_soc = 0  # type: ignore[misc]
