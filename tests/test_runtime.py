from __future__ import annotations

from dataclasses import replace

from custom_components.home_energy_orchestrator.planner.control import ControlInputs
from custom_components.home_energy_orchestrator.planner.ev import EvCurrentInputs
from custom_components.home_energy_orchestrator.planner.runtime import plan_runtime


def _control_inputs() -> ControlInputs:
    return ControlInputs(
        rehearsal=False,
        ready=True,
        automatic_charge=True,
        automatic_export=False,
        free_window_active=True,
        export_window_active=False,
        current_mode="Self Use",
        battery_soc=60,
        charge_target_soc=100,
        requested_charge_power_kw=15,
        charge_power_max_kw=15,
        planned_export_energy_kwh=0,
        grid_import_kw=0,
        export_import_limit_kw=0.2,
        minimum_grid_soc=10,
        configured_export_rate_c_kwh=15,
        minimum_export_rate_c_kwh=15,
        requested_discharge_power_kw=8,
        discharge_power_max_kw=15,
    )


def _ev_inputs() -> EvCurrentInputs:
    return EvCurrentInputs(
        free_window_active=True,
        cable_connected=True,
        ceiling_a=16,
        protected_baseline_a=1,
        effective_minimum_a=1,
        requested_current_a=16,
        service_current_a=63,
        headroom_a=1,
        grid_average_a=20,
        grid_coverage_ratio=1,
        ev_average_a=16,
        ev_current_now_a=16,
        ev_feedback_source_valid=True,
        elapsed_free_window_minutes=20,
        settle_minutes=5,
        bonus_window_active=True,
        inverter_capacity_kw=15,
        ev_phase_count=3,
    )


def test_runtime_plan_keeps_tariff_and_ev_decisions_together() -> None:
    plan = plan_runtime(
        _control_inputs(),
        _ev_inputs(),
        tariff_inputs={
            "daily_free_allowance_kwh": 50,
            "imported_today_kwh": 47,
            "requested_free_charge_kwh": 10,
            "bonus_window_active": True,
            "grid_import_kw": 0.0,
            "grid_telemetry_valid": True,
            "zero_import_minutes": 5,
        },
    )
    assert plan.control.action == "force_charge"
    # Free-window current is governed by the import allowance; the slower
    # percentage cap applies only to explicit load-following sessions.
    assert plan.ev_current.target_current_a == 16
    assert plan.tariff.free_energy_remaining_kwh == 3
    assert plan.tariff.bonus_zero_import_allowed


def test_runtime_plan_applies_learned_house_budget_before_export() -> None:
    control = _control_inputs()
    control = replace(
        control,
        automatic_charge=False,
        automatic_export=True,
        free_window_active=False,
        export_window_active=True,
    )
    plan = plan_runtime(
        control,
        _ev_inputs(),
        tariff_inputs={
            "daily_free_allowance_kwh": 50,
            "imported_today_kwh": 0,
            "requested_free_charge_kwh": 0,
            "bonus_window_active": False,
            "grid_import_kw": 0.0,
            "grid_telemetry_valid": True,
            "zero_import_minutes": 0,
        },
        export_inputs={
            "available_ac_kwh": 20,
            "protected_ev_kwh": 2,
            "allowance_remaining_kwh": 20,
            "discharge_power_kw": 5,
        },
        learned_house_budget_kwh=4,
    )
    assert plan.export is not None
    assert plan.export.planned_export_energy_kwh == 14
    assert plan.control.action == "force_discharge"


def test_runtime_plan_uses_allowance_paced_charge_target() -> None:
    plan = plan_runtime(
        _control_inputs(),
        _ev_inputs(),
        tariff_inputs={
            "daily_free_allowance_kwh": 50,
            "imported_today_kwh": 0,
            "requested_free_charge_kwh": 50,
            "bonus_window_active": False,
            "grid_import_kw": 0.0,
            "grid_telemetry_valid": True,
            "zero_import_minutes": 0,
        },
        free_charge_inputs={
            "allowance_remaining_kwh": 45,
            "hours_remaining": 3,
            "house_load_kw": 4,
            "pv_generation_kw": 0,
            "inverter_charge_limit_kw": 15,
            "safety_margin_kw": 1,
        },
    )
    assert plan.free_charge is not None
    assert plan.free_charge.target_charge_power_kw == 10
    assert plan.control.power_kw == 10


def test_runtime_plan_restores_normal_mode_when_charge_target_reaches_zero() -> None:
    control = replace(_control_inputs(), current_mode="Force Charge")
    plan = plan_runtime(
        control,
        _ev_inputs(),
        tariff_inputs={
            "daily_free_allowance_kwh": 50,
            "imported_today_kwh": 50,
            "requested_free_charge_kwh": 1,
            "bonus_window_active": False,
            "grid_import_kw": 0.0,
            "grid_telemetry_valid": True,
            "zero_import_minutes": 0,
        },
        free_charge_inputs={
            "allowance_remaining_kwh": 0,
            "hours_remaining": 1,
            "house_load_kw": 4,
            "pv_generation_kw": 0,
            "inverter_charge_limit_kw": 15,
            "safety_margin_kw": 1,
        },
    )
    assert plan.free_charge is not None
    assert plan.free_charge.reason == "allowance_exhausted"
    assert plan.control.action == "restore_self_use"


def test_runtime_plan_restores_backup_when_battery_full_before_threshold() -> None:
    control = replace(_control_inputs(), current_mode="Force Charge")
    plan = plan_runtime(
        control,
        _ev_inputs(),
        tariff_inputs={
            "daily_free_allowance_kwh": 50,
            "imported_today_kwh": 48,
            "requested_free_charge_kwh": 2,
            "bonus_window_active": False,
            "grid_import_kw": 0.0,
            "grid_telemetry_valid": True,
            "zero_import_minutes": 0,
        },
        free_charge_completion_inputs={"imported_kwh": 48, "battery_soc": 100},
    )
    assert plan.free_charge_completion is not None
    assert plan.free_charge_completion.action == "backup"
    assert plan.control.action == "restore_backup"
