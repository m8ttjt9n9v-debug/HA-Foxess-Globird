from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.home_energy_orchestrator.planner.ev import (
    AllowanceCeilingInputs,
    ChargeLimitInputs,
    FreeWindowCurrentInputs,
    apply_daily_allowance_ceiling,
    estimate_other_free_window_import_kwh,
    estimate_vehicle_energy_to_target_kwh,
    plan_charge_limit_target,
    plan_free_window_current,
)

BASE = FreeWindowCurrentInputs(
    in_free_window=True,
    connected=True,
    ceiling_a=32,
    effective_minimum_a=6,
    protected_baseline_a=1,
    requested_a=12,
    service_limit_a=63,
    service_headroom_a=1,
    grid_average_a=52,
    grid_average_valid=True,
    actual_ev_current_a=12,
    ev_average_a=12,
    ev_average_source_valid=True,
    elapsed_minutes=10,
    settle_minutes=5,
    current_step_a=1,
    ev_priority=False,
)


@pytest.mark.parametrize(
    ("changes", "expected", "phase"),
    [
        ({"in_free_window": False}, 1, "inactive"),
        ({"connected": False}, 1, "inactive"),
        ({"grid_average_a": 65}, 9, "service_limit_correction"),
        (
            {"grid_average_a": 65, "ev_average_source_valid": False},
            1,
            "service_limit_feedback_unavailable",
        ),
        ({"charge_to_full": True}, 32, "charge_to_full_priority"),
        ({"ev_priority": True}, 32, "ev_priority_maximum"),
        ({"elapsed_minutes": 2}, 6, "settling_foxess"),
        ({"grid_average_valid": False}, 6, "telemetry_fallback_minimum"),
        ({"actual_ev_current_a": 0}, 12, "ev_feedback_hold"),
        ({"grid_average_a": 62.2}, 12, "service_deadband_hold"),
        ({}, 22, "house_battery_priority"),
    ],
)
def test_mangerton_free_window_branch_order(changes, expected, phase):
    decision = plan_free_window_current(replace(BASE, **changes))
    assert decision.current_a == expected
    assert decision.phase == phase


def test_service_overrun_can_reduce_to_protected_baseline():
    decision = plan_free_window_current(
        replace(BASE, grid_average_a=100, ev_average_a=6, requested_a=6)
    )
    assert decision.current_a == 1
    assert decision.phase == "service_limit_correction"


def test_arbitrary_phase_site_does_not_change_base_current_policy():
    """Topology belongs to the extension, not the Mangerton current branches."""
    assert plan_free_window_current(replace(BASE, ceiling_a=16)).current_a == 16


def test_exporting_grid_current_is_a_valid_signed_measurement():
    decision = plan_free_window_current(replace(BASE, grid_average_a=-4))
    assert decision.current_a == 32
    assert decision.phase == "house_battery_priority"


def test_charge_limit_retained_away_and_policy_kept_separate_from_guard():
    base = ChargeLimitInputs(
        connected=False,
        policy_limit_percent=80,
        current_limit_percent=90,
        vehicle_soc_percent=89,
        protected_baseline_required=True,
        direct_limit_headroom_percent=2,
        minimum_percent=50,
        maximum_percent=100,
        step_percent=1,
    )
    assert plan_charge_limit_target(base) == 90
    assert plan_charge_limit_target(replace(base, connected=True)) == 91
    assert plan_charge_limit_target(
        replace(base, connected=True, vehicle_soc_percent=60)
    ) == 80


ALLOWANCE = AllowanceCeilingInputs(
    base_current_a=16,
    protected_baseline_a=1,
    minimum_charge_a=1,
    current_step_a=1,
    voltage_v=230,
    phase_count=3,
    remaining_window_hours=2,
    allowance_kwh=50,
    imported_in_window_kwh=10,
    projected_other_import_kwh=25,
    projected_ev_energy_kwh=5,
)


def test_normal_small_session_is_not_evenly_spread_or_throttled():
    decision = apply_daily_allowance_ceiling(ALLOWANCE)
    assert decision.current_a == 16
    assert decision.phase == "allowance_not_constraining"


def test_projected_overrun_activates_topology_aware_allowance_pacing():
    decision = apply_daily_allowance_ceiling(
        replace(ALLOWANCE, projected_ev_energy_kwh=30)
    )
    # 15 kWh / 2 h / (230 V * 3 phases) = 10.86 A, floored to a 1 A step.
    assert decision.current_a == 10
    assert decision.phase == "allowance_pacing"


def test_allowance_is_configured_not_literal():
    decision = apply_daily_allowance_ceiling(
        replace(
            ALLOWANCE,
            allowance_kwh=20,
            imported_in_window_kwh=4,
            projected_other_import_kwh=8,
            projected_ev_energy_kwh=20,
            remaining_window_hours=1,
        )
    )
    assert decision.current_a == 11
    assert decision.phase == "allowance_pacing"


def test_missing_allowance_meter_fails_to_protected_baseline():
    decision = apply_daily_allowance_ceiling(
        replace(ALLOWANCE, imported_in_window_kwh=None)
    )
    assert decision.current_a == 1
    assert decision.phase == "allowance_meter_unavailable"


def test_exhausted_allowance_cannot_claim_zero_when_path_requires_baseline():
    decision = apply_daily_allowance_ceiling(
        replace(ALLOWANCE, imported_in_window_kwh=50, projected_ev_energy_kwh=20)
    )
    assert decision.current_a == 1
    assert decision.phase == "allowance_exhausted"


def test_allowance_validation_rejects_invalid_topology():
    with pytest.raises(ValueError):
        apply_daily_allowance_ceiling(replace(ALLOWANCE, phase_count=0))


def test_vehicle_need_uses_live_stored_energy_instead_of_fixed_capacity():
    # 45 kWh stored at 60% implies 75 kWh usable capacity. Reaching 80%
    # requires 15 kWh in the pack, or 16.667 kWh at 90% wall efficiency.
    assert estimate_vehicle_energy_to_target_kwh(
        stored_energy_kwh=45,
        current_soc_percent=60,
        target_soc_percent=80,
        charge_efficiency_percent=90,
    ) == 16.667


def test_small_vehicle_top_up_projection_is_not_a_fixed_site_value():
    assert estimate_vehicle_energy_to_target_kwh(
        stored_energy_kwh=72,
        current_soc_percent=96,
        target_soc_percent=100,
        charge_efficiency_percent=90,
    ) == 3.333


def test_other_projection_combines_configured_battery_gap_and_live_house_load():
    # 8 kWh pack gap at 80% efficiency plus 2 kW for two hours.
    assert estimate_other_free_window_import_kwh(
        battery_capacity_kwh=40,
        battery_soc_percent=70,
        battery_target_percent=90,
        battery_charge_efficiency_percent=80,
        house_load_kw=2,
        remaining_window_hours=2,
    ) == 14
