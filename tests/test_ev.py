from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.ev import (
    AllowanceCeilingInputs,
    AllowanceProjectionInputs,
    ChargeLimitInputs,
    DirectEvseObservation,
    DirectEvseReconciliation,
    DirectEvseReconciliationState,
    EvCommand,
    EvCommandPlan,
    EvDecisionCadenceEvidence,
    FreeWindowCurrentInputs,
    FreeWindowTargetEvidence,
    GeneralChargeLimitEvidence,
    SmartSocketObservation,
    SmartSocketObservationEvidence,
    SmartSocketRecoveryEvidence,
    SmartSocketRecoveryObservation,
    SmartSocketRecoveryState,
    SmartSocketStageState,
    apply_daily_allowance_ceiling,
    charging_path_ceiling_a,
    direct_evse_response_matches,
    estimate_other_free_window_import_kwh,
    estimate_vehicle_energy_to_target_kwh,
    evaluate_allowance_projection,
    evaluate_ev_decision_cadence,
    evaluate_free_window_target,
    evaluate_general_charge_limit,
    evaluate_smart_socket_observation,
    evaluate_smart_socket_recovery_observation,
    finalize_direct_evse_reconciliation,
    finalize_smart_socket_recovery,
    house_load_excluding_ev_kw,
    outside_service_ceiling_a,
    outside_service_feedback_required,
    physical_charging_minimum_a,
    plan_charge_limit_target,
    plan_direct_evse_commands,
    plan_free_window_current,
    plan_smart_socket_commands,
    reconcile_direct_evse,
    reconcile_smart_socket_recovery,
    reconcile_smart_socket_stage,
    reset_smart_state_for_path,
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

FREE_WINDOW_TARGET = FreeWindowTargetEvidence(
    ceiling_a=16,
    physical_minimum_a=1,
    current_step_a=1,
    configured_baseline_a=0,
    configured_minimum_a=1,
    charge_to_full=False,
    configured_policy_limit_percent=90,
    vehicle_soc_percent=90,
    requested_current_a=6,
    service_limit_a=63,
    service_headroom_a=1,
    grid_average_a=None,
    grid_average_age_coverage_ratio=0,
    grid_average_source_valid=False,
    actual_ev_current_a=0,
    ev_average_a=None,
    ev_average_source_valid=False,
    elapsed_minutes=0,
    settle_minutes=5,
    ev_priority_selected=True,
)

CADENCE_NOW = datetime(2026, 9, 7, 12, 29, 15, tzinfo=UTC)
CADENCE = EvDecisionCadenceEvidence(
    now=CADENCE_NOW,
    last_decision_at=CADENCE_NOW - timedelta(seconds=58),
    previous_fingerprint=(80, False, "ev", 1, 16, 1, 50, 100, 1),
    vehicle_soc_percent=81,
    charge_to_full_requested=False,
    free_window_priority="ev",
    current_minimum_a=1,
    current_maximum_a=16,
    current_step_a=1,
    limit_minimum_percent=50,
    limit_maximum_percent=100,
    limit_step_percent=1,
    configured_policy_limit_percent=100,
    in_free_window=True,
    pre_free_active=False,
    current_target_available=True,
    allowance_guard_enabled=True,
    house_load_includes_ev=True,
    actual_ev_current_valid=True,
    requested_current_a=16,
    actual_ev_current_a=3,
    grid_current_valid=True,
    grid_current_a=38,
    service_limit_a=80,
)


def test_ev_decision_cadence_holds_only_soc_change_during_current_convergence():
    evaluation = evaluate_ev_decision_cadence(CADENCE)

    assert evaluation.only_vehicle_soc_changed is True
    assert evaluation.soc_remains_below_policy is True
    assert evaluation.current_transition_pending is True
    assert evaluation.service_overrun is False
    assert evaluation.defer_soc_redecision is True
    assert evaluation.should_decide is False


@pytest.mark.parametrize(
    ("changes", "expected_defer"),
    (
        ({"grid_current_a": 81}, False),
        ({"vehicle_soc_percent": 100}, False),
        ({"allowance_guard_enabled": False}, False),
        ({"last_decision_at": CADENCE_NOW - timedelta(minutes=3)}, False),
        ({"pre_free_active": True}, True),
        ({"in_free_window": False}, False),
    ),
)
def test_ev_decision_cadence_never_hides_safety_policy_or_time_boundaries(
    changes,
    expected_defer,
):
    evaluation = evaluate_ev_decision_cadence(replace(CADENCE, **changes))

    assert evaluation.defer_soc_redecision is expected_defer
    assert evaluation.should_decide is True


def test_free_window_target_composes_policy_limit_and_physical_baseline():
    evaluation = evaluate_free_window_target(FREE_WINDOW_TARGET)

    assert evaluation.protected_baseline_a == 1
    assert evaluation.effective_minimum_a == 1
    assert evaluation.policy_limit_percent == 90
    assert evaluation.below_policy_limit is False
    assert evaluation.decision.current_a == 1
    assert evaluation.decision.phase == "policy_limit_reached"


def test_free_window_target_charge_to_full_replaces_policy_limit_and_settle():
    evaluation = evaluate_free_window_target(
        replace(FREE_WINDOW_TARGET, charge_to_full=True)
    )

    assert evaluation.policy_limit_percent == 100
    assert evaluation.below_policy_limit is True
    assert evaluation.decision.current_a == 16
    assert evaluation.decision.phase == "charge_to_full_priority"


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
def test_pilot_site_free_window_branch_order(changes, expected, phase):
    decision = plan_free_window_current(replace(BASE, **changes))
    assert decision.current_a == expected
    assert decision.phase == phase


@pytest.mark.parametrize(
    ("changes", "expected", "phase"),
    [
        (
            {"grid_average_a": 65, "charge_to_full": True, "ev_priority": True},
            9,
            "service_limit_correction",
        ),
        (
            {"charge_to_full": True, "ev_priority": True, "elapsed_minutes": 0},
            32,
            "charge_to_full_priority",
        ),
        (
            {"ev_priority": True, "elapsed_minutes": 0},
            32,
            "ev_priority_maximum",
        ),
        (
            {"elapsed_minutes": 0, "grid_average_valid": False},
            6,
            "settling_foxess",
        ),
        (
            {"grid_average_valid": False, "actual_ev_current_a": 0},
            6,
            "telemetry_fallback_minimum",
        ),
    ],
)
def test_free_window_priority_collisions(changes, expected, phase) -> None:
    """Freeze the commissioned order when multiple branches are eligible."""
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
    """Topology belongs to the extension, not the pilot-site current branches."""
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
    assert plan_charge_limit_target(replace(base, connected=True, vehicle_soc_percent=60)) == 80


GENERAL_LIMIT = GeneralChargeLimitEvidence(
    charge_to_full=False,
    learned_limit_percent=76,
    current_limit_percent=80,
    vehicle_soc_percent=60,
    protected_baseline_required=False,
    direct_limit_headroom_percent=2,
    minimum_percent=50,
    maximum_percent=100,
    step_percent=1,
    previous_write_fingerprint=None,
)


def test_general_limit_plans_one_deferred_write():
    decision = evaluate_general_charge_limit(GENERAL_LIMIT)

    assert decision.target_limit_percent == 76
    assert decision.reason == "general_limit"
    assert decision.command_plan.commands == (EvCommand("set_charge_limit", 76),)
    assert decision.proposed_write_fingerprint == (76, 80)
    assert decision.fingerprint_transition == "set_on_execute"


def test_general_limit_retains_duplicate_write_while_feedback_is_pending():
    decision = evaluate_general_charge_limit(
        replace(GENERAL_LIMIT, previous_write_fingerprint=(76, 80))
    )

    assert decision.reason == "outside_window_general_limit_awaiting_feedback"
    assert decision.command_plan.commands == ()
    assert decision.proposed_write_fingerprint == (76, 80)
    assert decision.fingerprint_transition == "retain"


def test_general_limit_confirmation_clears_fingerprint_and_charge_to_full_wins():
    decision = evaluate_general_charge_limit(
        replace(
            GENERAL_LIMIT,
            charge_to_full=True,
            current_limit_percent=100,
            previous_write_fingerprint=(100, 80),
        )
    )

    assert decision.target_limit_percent == 100
    assert decision.reason == "outside_window_general_limit_confirmed"
    assert decision.command_plan.commands == ()
    assert decision.proposed_write_fingerprint is None
    assert decision.fingerprint_transition == "clear"


ALLOWANCE = AllowanceCeilingInputs(
    base_current_a=16,
    protected_baseline_a=1,
    minimum_charge_a=1,
    current_step_a=1,
    voltage_v=230,
    phase_count=3,
    site_service_limit_a=80,
    site_voltage_v=230,
    site_phase_count=3,
    remaining_window_hours=2,
    allowance_kwh=50,
    imported_in_window_kwh=10,
    projected_other_import_kwh=25,
    projected_ev_energy_kwh=5,
)

ALLOWANCE_PROJECTION = AllowanceProjectionInputs(
    base_current_a=16,
    protected_baseline_a=1,
    minimum_charge_a=1,
    current_step_a=1,
    stored_energy_kwh=5,
    vehicle_soc_percent=50,
    vehicle_target_soc_percent=60,
    vehicle_charge_efficiency_percent=90,
    battery_capacity_kwh=40,
    battery_soc_percent=100,
    battery_target_percent=100,
    battery_charge_efficiency_percent=90,
    house_load_kw=12,
    house_load_includes_ev=False,
    actual_ev_current_a=16,
    actual_ev_current_valid=True,
    ev_voltage_v=230,
    ev_phase_count=3,
    site_service_limit_a=63,
    site_phase_count=3,
    remaining_window_hours=2,
    allowance_kwh=50,
    imported_in_window_kwh=25,
    safety_margin_kwh=0,
)


def test_allowance_projection_preserves_explicit_house_load_topologies():
    exclusive = evaluate_allowance_projection(ALLOWANCE_PROJECTION)
    whole_house = evaluate_allowance_projection(
        replace(ALLOWANCE_PROJECTION, house_load_includes_ev=True)
    )

    assert exclusive.decision is not None
    assert exclusive.decision.current_a == 1
    assert exclusive.decision.phase == "allowance_below_charger_minimum"
    assert exclusive.house_load_kw == 12
    assert exclusive.ev_power_kw is None
    assert whole_house.decision is not None
    assert whole_house.decision.current_a == 16
    assert whole_house.decision.phase == "allowance_not_constraining"
    assert whole_house.house_load_kw == 0.96
    assert whole_house.ev_power_kw == 11.04


def test_allowance_projection_whole_house_fails_closed_without_ev_current():
    result = evaluate_allowance_projection(
        replace(
            ALLOWANCE_PROJECTION,
            house_load_includes_ev=True,
            actual_ev_current_valid=False,
        )
    )

    assert result.decision is None
    assert result.house_load_kw is None
    assert result.ev_power_kw is None


@pytest.mark.parametrize(
    "changes",
    [
        {"stored_energy_kwh": None},
        {"vehicle_soc_percent": None},
        {"battery_soc_percent": None},
        {"house_load_kw": None},
    ],
)
def test_allowance_projection_requires_all_energy_evidence(changes):
    result = evaluate_allowance_projection(replace(ALLOWANCE_PROJECTION, **changes))

    assert result.decision is None
    assert result.house_load_kw is None
    assert result.ev_power_kw is None


def test_allowance_projection_keeps_missing_meter_as_baseline_decision():
    result = evaluate_allowance_projection(
        replace(ALLOWANCE_PROJECTION, imported_in_window_kwh=None)
    )

    assert result.decision is not None
    assert result.decision.current_a == 1
    assert result.decision.phase == "allowance_meter_unavailable"
    assert result.house_load_kw == 12
    assert result.ev_power_kw is None


def test_normal_small_session_is_not_evenly_spread_or_throttled():
    decision = apply_daily_allowance_ceiling(ALLOWANCE)
    assert decision.current_a == 16
    assert decision.phase == "allowance_not_constraining"


def test_pilot_site_service_envelope_cannot_reach_configured_allowance():
    decision = apply_daily_allowance_ceiling(
        replace(
            ALLOWANCE,
            site_service_limit_a=63,
            site_voltage_v=230,
            site_phase_count=1,
            remaining_window_hours=2.9,
            imported_in_window_kwh=0,
            projected_other_import_kwh=40,
            projected_ev_energy_kwh=30,
        )
    )
    assert decision.current_a == 16
    assert decision.phase == "allowance_physically_unreachable"


def test_higher_capacity_site_continues_to_projection_check():
    decision = apply_daily_allowance_ceiling(
        replace(
            ALLOWANCE,
            projected_other_import_kwh=35,
            projected_ev_energy_kwh=20,
        )
    )
    assert decision.current_a == 3
    assert decision.phase == "allowance_pacing"


def test_projected_overrun_activates_topology_aware_allowance_pacing():
    decision = apply_daily_allowance_ceiling(replace(ALLOWANCE, projected_ev_energy_kwh=30))
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
    decision = apply_daily_allowance_ceiling(replace(ALLOWANCE, imported_in_window_kwh=None))
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
    assert (
        estimate_vehicle_energy_to_target_kwh(
            stored_energy_kwh=45,
            current_soc_percent=60,
            target_soc_percent=80,
            charge_efficiency_percent=90,
        )
        == 16.667
    )


def test_small_vehicle_top_up_projection_is_not_a_fixed_site_value():
    assert (
        estimate_vehicle_energy_to_target_kwh(
            stored_energy_kwh=72,
            current_soc_percent=96,
            target_soc_percent=100,
            charge_efficiency_percent=90,
        )
        == 3.333
    )


def test_other_projection_combines_configured_battery_gap_and_live_house_load():
    # 8 kWh pack gap at 80% efficiency plus 2 kW for two hours.
    assert (
        estimate_other_free_window_import_kwh(
            battery_capacity_kwh=40,
            battery_soc_percent=70,
            battery_target_percent=90,
            battery_charge_efficiency_percent=80,
            house_load_kw=2,
            remaining_window_hours=2,
        )
        == 14
    )


def test_whole_house_topology_subtracts_three_phase_ev_once():
    assert (
        house_load_excluding_ev_kw(
            house_load_kw=12,
            actual_ev_current_a=16,
            ev_voltage_v=230,
            ev_phase_count=3,
        )
        == 0.96
    )


def test_whole_house_topology_clamps_small_meter_difference_to_zero():
    assert (
        house_load_excluding_ev_kw(
            house_load_kw=10,
            actual_ev_current_a=16,
            ev_voltage_v=230,
            ev_phase_count=3,
        )
        == 0
    )


DIRECT = DirectEvseObservation(
    requested_current_a=6,
    charge_limit_percent=80,
    charge_switch_on=False,
    current_minimum_a=1,
    current_maximum_a=16,
    current_step_a=1,
    limit_minimum_percent=50,
    limit_maximum_percent=100,
    limit_step_percent=1,
)


def test_physical_minimum_and_path_ceiling_retain_commissioned_bounds():
    zero_minimum = replace(DIRECT, current_minimum_a=0, current_step_a=2)
    assert physical_charging_minimum_a(zero_minimum) == 2
    assert physical_charging_minimum_a(
        replace(DIRECT, current_minimum_a=1, current_step_a=2)
    ) == 1
    assert physical_charging_minimum_a(
        replace(DIRECT, current_minimum_a=0, current_step_a=0)
    ) is None
    assert charging_path_ceiling_a(
        smart_path_selected=True,
        smart_limit_a=10,
        direct_limit_a=16,
    ) == 10
    assert charging_path_ceiling_a(
        smart_path_selected=False,
        smart_limit_a=10,
        direct_limit_a=16,
    ) == 16


def test_outside_service_ceiling_retains_headroom_feedback_and_step_rules():
    common = {
        "physical_ceiling_a": 16.0,
        "current_step_a": 2.0,
        "service_limit_a": 20.0,
        "reserved_headroom_a": 1.0,
        "grid_current_a": 12.0,
        "grid_current_valid": True,
        "actual_ev_current_a": 4.0,
        "actual_ev_current_valid": True,
    }
    assert outside_service_ceiling_a(**common) == 10.0
    assert outside_service_ceiling_a(
        **{**common, "grid_current_valid": False}
    ) == 0.0
    assert outside_service_ceiling_a(
        **{
            **common,
            "service_limit_a": 0.0,
            "grid_current_valid": False,
            "actual_ev_current_valid": False,
        }
    ) == 16.0
    assert outside_service_feedback_required(service_limit_a=20.0) is True
    assert outside_service_feedback_required(service_limit_a=0.0) is False


SMART = SmartSocketObservation(
    requested_current_a=12,
    charge_switch_on=False,
    socket_on=False,
    socket_on_seconds=0,
    current_maximum_a=24,
    current_step_a=1,
)


def test_smart_socket_stages_configured_physical_cap_before_power():
    plan = plan_smart_socket_commands(
        SMART,
        target_current_a=14,
        physical_minimum_a=1,
        physical_ceiling_a=10,
        settle_seconds=15,
        charge_allowed=True,
        in_free_window=True,
        connected_for_planning=True,
        power_switching_enabled=False,
    )
    assert [(command.action, command.value) for command in plan.commands] == [
        ("set_charge_current", 10)
    ]
    assert plan.reason == "smart_socket_stage_current_before_power"


def test_smart_socket_energises_only_after_staged_current_feedback():
    plan = plan_smart_socket_commands(
        replace(SMART, requested_current_a=10),
        target_current_a=14,
        physical_minimum_a=1,
        physical_ceiling_a=10,
        settle_seconds=15,
        charge_allowed=True,
        in_free_window=True,
        connected_for_planning=True,
        power_switching_enabled=False,
    )
    assert [command.action for command in plan.commands] == ["turn_on_smart_socket"]


def test_smart_socket_waits_for_configured_settle_period():
    plan = plan_smart_socket_commands(
        replace(SMART, requested_current_a=10, socket_on=True, socket_on_seconds=14),
        target_current_a=10,
        physical_minimum_a=1,
        physical_ceiling_a=10,
        settle_seconds=15,
        charge_allowed=True,
        in_free_window=True,
        connected_for_planning=True,
        power_switching_enabled=False,
    )
    assert plan.commands == ()
    assert plan.reason == "smart_socket_settling"


def test_smart_socket_starts_after_settle_without_exceeding_physical_cap():
    plan = plan_smart_socket_commands(
        replace(SMART, requested_current_a=6, socket_on=True, socket_on_seconds=15),
        target_current_a=14,
        physical_minimum_a=1,
        physical_ceiling_a=10,
        settle_seconds=15,
        charge_allowed=True,
        in_free_window=True,
        connected_for_planning=True,
        power_switching_enabled=False,
    )
    assert [(command.action, command.value) for command in plan.commands] == [
        ("set_charge_current", 10),
        ("start_charging", None),
    ]


def test_smart_socket_zero_demand_power_policy_is_outside_window_only():
    common = dict(
        target_current_a=0,
        physical_minimum_a=1,
        physical_ceiling_a=10,
        settle_seconds=15,
        charge_allowed=False,
        connected_for_planning=True,
        power_switching_enabled=True,
    )
    powered = replace(SMART, socket_on=True, socket_on_seconds=60)
    assert plan_smart_socket_commands(powered, in_free_window=True, **common).commands == ()
    outside = plan_smart_socket_commands(powered, in_free_window=False, **common)
    assert [command.action for command in outside.commands] == ["turn_off_smart_socket"]


def test_smart_socket_rating_is_configuration_not_a_literal():
    plan = plan_smart_socket_commands(
        SMART,
        target_current_a=20,
        physical_minimum_a=2,
        physical_ceiling_a=16,
        settle_seconds=12,
        charge_allowed=True,
        in_free_window=True,
        connected_for_planning=True,
        power_switching_enabled=False,
    )
    assert plan.commands == (
        EvCommand("set_charge_current", 16),
        EvCommand("turn_on_smart_socket"),
    )


RECOVERY = SmartSocketRecoveryObservation(
    charging_state="no_power",
    charging_state_seconds=120,
    home_control_active=True,
    cloud_evidence_stable=True,
    smart_path_selected=True,
    socket_on=True,
    cable_connected=True,
    charge_allowed=True,
    actuator_writable=True,
    target_current_a=10,
    requested_current_a=6,
    actual_current_a=0,
    vehicle_soc_percent=40,
    charge_limit_percent=80,
    writable_maximum_a=24,
    charge_switch_on=False,
)


def test_smart_socket_observation_preserves_age_and_availability_boundaries():
    now = datetime(2026, 9, 7, 8, tzinfo=UTC)
    evidence = SmartSocketObservationEvidence(
        now=now,
        requested_current_a=6,
        charge_switch_on=False,
        socket_state="on",
        socket_last_changed=now - timedelta(seconds=15),
        current_maximum_a=16,
        current_step_a=1,
    )

    assert evaluate_smart_socket_observation(evidence) == SmartSocketObservation(
        6, False, True, 15, 16, 1
    )
    assert evaluate_smart_socket_observation(
        replace(evidence, socket_last_changed=now + timedelta(seconds=5))
    ).socket_on_seconds == 0
    assert evaluate_smart_socket_observation(
        replace(evidence, socket_state="off")
    ).socket_on_seconds == 0
    assert evaluate_smart_socket_observation(
        replace(evidence, socket_state=None)
    ) is None


def test_smart_recovery_observation_preserves_stable_cloud_evidence_boundary():
    now = datetime(2026, 9, 7, 8, tzinfo=UTC)
    stable_at = now - timedelta(seconds=120)
    evidence = SmartSocketRecoveryEvidence(
        now=now,
        stable_seconds=120,
        charging_state="no_power",
        charging_last_changed=stable_at,
        at_home_state="home",
        at_home_last_changed=stable_at,
        cable_state="on",
        cable_last_changed=stable_at,
        cloud_charge_switch_state="off",
        cloud_charge_switch_last_changed=stable_at,
        home_control_active=True,
        smart_path_selected=True,
        socket_on=True,
        target_current_a=10,
        physical_minimum_a=1,
        requested_current_a=6,
        actual_current_a=0,
        actual_current_valid=True,
        vehicle_soc_percent=40,
        charge_limit_percent=80,
        writable_maximum_a=24,
        charge_switch_on=False,
    )

    observation = evaluate_smart_socket_recovery_observation(evidence)
    assert observation == RECOVERY
    assert evaluate_smart_socket_recovery_observation(
        replace(evidence, at_home_last_changed=stable_at + timedelta(seconds=1))
    ).cloud_evidence_stable is False
    assert evaluate_smart_socket_recovery_observation(
        replace(evidence, cable_last_changed=now + timedelta(seconds=1))
    ).cloud_evidence_stable is False


def test_smart_recovery_observation_fails_closed_for_missing_numeric_evidence():
    now = datetime(2026, 9, 7, 8, tzinfo=UTC)
    stable_at = now - timedelta(seconds=120)
    evidence = SmartSocketRecoveryEvidence(
        now=now,
        stable_seconds=120,
        charging_state="no_power",
        charging_last_changed=None,
        at_home_state=None,
        at_home_last_changed=stable_at,
        cable_state="on",
        cable_last_changed=stable_at,
        cloud_charge_switch_state="off",
        cloud_charge_switch_last_changed=stable_at,
        home_control_active=True,
        smart_path_selected=True,
        socket_on=True,
        target_current_a=None,
        physical_minimum_a=1,
        requested_current_a=6,
        actual_current_a=0,
        actual_current_valid=False,
        vehicle_soc_percent=None,
        charge_limit_percent=80,
        writable_maximum_a=None,
        charge_switch_on=None,
    )

    observation = evaluate_smart_socket_recovery_observation(evidence)
    assert observation.charging_state_seconds == 0
    assert observation.cloud_evidence_stable is False
    assert observation.charge_allowed is False
    assert observation.actuator_writable is False
    assert observation.cable_connected is True
    assert observation.actual_current_a != observation.actual_current_a
    assert observation.vehicle_soc_percent != observation.vehicle_soc_percent


def _recover(state, observation, now):
    return reconcile_smart_socket_recovery(
        state,
        observation,
        now=now,
        physical_minimum_a=1,
        physical_ceiling_a=10,
        current_tolerance_a=1,
        idle_current_threshold_a=0.5,
        no_power_confirm_seconds=120,
        current_confirm_seconds=60,
        socket_confirm_seconds=15,
        power_off_seconds=30,
        post_power_settle_seconds=20,
        charging_confirm_seconds=180,
        healthy_rearm_seconds=120,
    )


def test_smart_socket_recovery_preserves_ordered_one_shot_sequence():
    now = datetime(2026, 9, 7, 8, tzinfo=UTC)
    transition = _recover(SmartSocketRecoveryState(), RECOVERY, now)
    assert transition.state.attempted is True
    assert transition.state.phase == "confirming_current"
    assert transition.plan.commands == (EvCommand("set_charge_current", 10),)

    transition = _recover(
        transition.state, replace(RECOVERY, requested_current_a=10), now + timedelta(seconds=1)
    )
    assert transition.state.phase == "confirming_socket_off"
    assert transition.plan.commands == (EvCommand("turn_off_smart_socket"),)

    transition = _recover(
        transition.state,
        replace(RECOVERY, requested_current_a=10, socket_on=False),
        now + timedelta(seconds=2),
    )
    assert transition.state.phase == "power_off_dwell"
    assert transition.plan.commands == ()

    transition = _recover(
        transition.state,
        replace(RECOVERY, requested_current_a=10, socket_on=False),
        now + timedelta(seconds=32),
    )
    assert transition.state.phase == "confirming_socket_on"
    assert transition.plan.commands == (EvCommand("turn_on_smart_socket"),)

    transition = _recover(
        transition.state,
        replace(RECOVERY, requested_current_a=10, socket_on=True),
        now + timedelta(seconds=33),
    )
    assert transition.state.phase == "post_power_settle"

    transition = _recover(
        transition.state,
        replace(RECOVERY, requested_current_a=10, socket_on=True),
        now + timedelta(seconds=53),
    )
    assert transition.state.phase == "confirming_charging"
    assert transition.plan.commands == (EvCommand("start_charging"),)

    transition = _recover(
        transition.state,
        replace(
            RECOVERY,
            charging_state="charging",
            charging_state_seconds=1,
            requested_current_a=10,
        ),
        now + timedelta(seconds=54),
    )
    assert transition.state.phase == "recovered"


def test_smart_socket_recovery_latch_survives_failure_and_blocks_second_cycle():
    now = datetime(2026, 9, 7, 8, tzinfo=UTC)
    transition = _recover(SmartSocketRecoveryState(), RECOVERY, now)
    transition = _recover(transition.state, RECOVERY, now + timedelta(seconds=60))
    assert transition.state.phase == "fault"
    assert transition.plan.reason == "recovery_current_not_confirmed"

    repeated = _recover(transition.state, RECOVERY, now + timedelta(minutes=5))
    assert repeated.state == transition.state
    assert repeated.plan.commands == ()
    assert repeated.plan.reason == "recovery_episode_latched"


def test_smart_socket_recovery_runtime_decision_preserves_activity_and_save_intent():
    now = datetime(2026, 9, 7, 8, tzinfo=UTC)
    previous = SmartSocketRecoveryState()
    active_transition = _recover(previous, RECOVERY, now)

    active = finalize_smart_socket_recovery(
        active_transition,
        previous_state=previous,
    )
    assert active.transition is active_transition
    assert active.active is True
    assert active.state_changed is True
    assert active.persistence_transition == "smart_recovery_state_changed"
    assert active.save_required is True

    unchanged_transition = _recover(
        active_transition.state,
        RECOVERY,
        now + timedelta(seconds=1),
    )
    unchanged = finalize_smart_socket_recovery(
        unchanged_transition,
        previous_state=active_transition.state,
    )
    assert unchanged.active is True
    assert unchanged.state_changed is False
    assert unchanged.persistence_transition == "none"
    assert unchanged.save_required is False

    idle_transition = _recover(
        previous,
        replace(RECOVERY, charging_state="disconnected"),
        now,
    )
    idle = finalize_smart_socket_recovery(
        idle_transition,
        previous_state=previous,
    )
    assert idle.active is False
    assert idle.save_required is False


def test_smart_socket_recovery_waits_for_post_power_actuator_like_pilot():
    now = datetime(2026, 9, 7, 8, tzinfo=UTC)
    post_power = SmartSocketRecoveryState(
        attempted=True,
        phase="post_power_settle",
        phase_started_at=now - timedelta(seconds=20),
        recovery_current_a=10,
    )

    waiting = _recover(
        post_power,
        replace(RECOVERY, actuator_writable=False, charge_switch_on=None),
        now,
    )
    assert waiting.state.phase == "awaiting_actuator"
    assert waiting.plan.reason == "recovery_awaiting_actuator"

    still_waiting = _recover(
        waiting.state,
        replace(RECOVERY, actuator_writable=False, charge_switch_on=None),
        now + timedelta(seconds=59),
    )
    assert still_waiting.state.phase == "awaiting_actuator"

    writable = _recover(
        waiting.state,
        replace(RECOVERY, requested_current_a=10),
        now + timedelta(seconds=30),
    )
    assert writable.state.phase == "confirming_charging"
    assert writable.plan.commands == (EvCommand("start_charging"),)


def test_smart_socket_recovery_rearms_only_after_sustained_health_or_path_change():
    latched = SmartSocketRecoveryState(
        attempted=True,
        phase="recovered",
        phase_started_at=datetime(2026, 9, 7, 8, tzinfo=UTC),
        recovery_current_a=10,
    )
    now = datetime(2026, 9, 7, 9, tzinfo=UTC)
    transient = _recover(
        latched,
        replace(RECOVERY, charging_state="charging", charging_state_seconds=119),
        now,
    )
    assert transient.state == latched
    healthy = _recover(
        latched,
        replace(RECOVERY, charging_state="charging", charging_state_seconds=120),
        now,
    )
    assert healthy.state == SmartSocketRecoveryState()
    path_changed = _recover(latched, replace(RECOVERY, smart_path_selected=False), now)
    assert path_changed.state == SmartSocketRecoveryState()


def test_smart_socket_recovery_requires_sustained_coherent_home_evidence():
    now = datetime(2026, 9, 7, 8, tzinfo=UTC)
    short_fault = _recover(
        SmartSocketRecoveryState(),
        replace(RECOVERY, charging_state_seconds=119),
        now,
    )
    assert short_fault.plan.reason == "recovery_fault_not_sustained"
    stale = _recover(
        SmartSocketRecoveryState(),
        replace(RECOVERY, cloud_evidence_stable=False),
        now,
    )
    assert stale.plan.reason == "recovery_home_evidence_unavailable"


def test_smart_socket_stage_transition_preserves_hold_retry_and_reset_semantics():
    now = datetime(2026, 9, 7, 8, tzinfo=UTC)
    observation = SmartSocketObservation(None, False, False, 0, 16, 1)
    staged = EvCommandPlan((EvCommand("set_charge_current", 10),), "stage")

    first = reconcile_smart_socket_stage(
        SmartSocketStageState(),
        staged,
        observation,
        now=now,
        current_confirm_seconds=60,
        retry_seconds=300,
    )
    assert first.state == SmartSocketStageState(10, now)
    assert first.plan == staged

    awaiting = reconcile_smart_socket_stage(
        first.state,
        staged,
        observation,
        now=now + timedelta(seconds=59),
        current_confirm_seconds=60,
        retry_seconds=300,
    )
    assert awaiting.state == first.state
    assert awaiting.plan == EvCommandPlan((), "smart_socket_awaiting_staged_current")

    unconfirmed = reconcile_smart_socket_stage(
        first.state,
        staged,
        observation,
        now=now + timedelta(seconds=60),
        current_confirm_seconds=60,
        retry_seconds=300,
    )
    assert unconfirmed.state == first.state
    assert unconfirmed.plan == EvCommandPlan((), "smart_socket_staged_current_not_confirmed")

    retry = reconcile_smart_socket_stage(
        first.state,
        staged,
        observation,
        now=now + timedelta(seconds=300),
        current_confirm_seconds=60,
        retry_seconds=300,
    )
    assert retry.state == SmartSocketStageState(10, now + timedelta(seconds=300))
    assert retry.plan == staged

    powered = EvCommandPlan((EvCommand("turn_on_smart_socket"),), "confirmed")
    reset = reconcile_smart_socket_stage(
        retry.state,
        powered,
        observation,
        now=now + timedelta(seconds=301),
        current_confirm_seconds=60,
        retry_seconds=300,
    )
    assert reset.state == SmartSocketStageState()
    assert reset.plan == powered


def test_smart_socket_stage_transition_retains_hold_for_unrelated_plan():
    now = datetime(2026, 9, 7, 8, tzinfo=UTC)
    state = SmartSocketStageState(10, now)
    unrelated = EvCommandPlan((), "smart_socket_no_charge_command")
    transition = reconcile_smart_socket_stage(
        state,
        unrelated,
        SmartSocketObservation(None, False, False, 0, 16, 1),
        now=now + timedelta(seconds=1),
        current_confirm_seconds=60,
        retry_seconds=300,
    )
    assert transition.state == state
    assert transition.plan == unrelated


def test_smart_path_reset_clears_only_when_direct_path_becomes_authoritative():
    now = datetime(2026, 9, 7, 8, tzinfo=UTC)
    recovery = SmartSocketRecoveryState(True, "fault", now, 10)
    stage = SmartSocketStageState(10, now)

    retained = reset_smart_state_for_path(
        smart_path_selected=True,
        recovery=recovery,
        stage=stage,
    )
    assert retained.recovery is recovery
    assert retained.stage is stage
    assert retained.save_required is False

    reset = reset_smart_state_for_path(
        smart_path_selected=False,
        recovery=recovery,
        stage=stage,
    )
    assert reset.recovery == SmartSocketRecoveryState()
    assert reset.stage == SmartSocketStageState()
    assert reset.save_required is True

    unchanged = reset_smart_state_for_path(
        smart_path_selected=False,
        recovery=reset.recovery,
        stage=reset.stage,
    )
    assert unchanged.save_required is False


def test_direct_path_orders_limit_current_then_start():
    plan = plan_direct_evse_commands(
        DIRECT,
        target_current_a=14,
        target_limit_percent=90,
        physical_ceiling_a=15,
        start_allowed=True,
    )
    assert [(command.action, command.value) for command in plan.commands] == [
        ("set_charge_limit", 90),
        ("set_charge_current", 14),
        ("start_charging", None),
    ]


def test_live_transport_max_bounds_write_but_does_not_change_physical_rating():
    plan = plan_direct_evse_commands(
        DIRECT,
        target_current_a=15,
        target_limit_percent=80,
        physical_ceiling_a=32,
        start_allowed=True,
    )
    assert ("set_charge_current", 15) in [
        (command.action, command.value) for command in plan.commands
    ]
    lowered_transport = plan_direct_evse_commands(
        replace(DIRECT, current_maximum_a=10),
        target_current_a=15,
        target_limit_percent=80,
        physical_ceiling_a=32,
        start_allowed=True,
    )
    assert ("set_charge_current", 10) in [
        (command.action, command.value) for command in lowered_transport.commands
    ]


def test_direct_path_never_emits_stop_when_policy_is_not_allowed():
    plan = plan_direct_evse_commands(
        replace(DIRECT, charge_switch_on=True),
        target_current_a=0,
        target_limit_percent=80,
        physical_ceiling_a=16,
        start_allowed=False,
    )
    assert plan.commands == ()
    assert plan.reason == "direct_path_not_allowed"


def test_missing_live_writable_range_fails_closed_without_fallback_current():
    plan = plan_direct_evse_commands(
        replace(DIRECT, current_maximum_a=None),
        target_current_a=15,
        target_limit_percent=80,
        physical_ceiling_a=32,
        start_allowed=True,
    )
    assert plan.commands == ()
    assert plan.reason == "actuator_metadata_unavailable"


def test_direct_feedback_match_requires_current_limit_and_switch():
    matched = replace(
        DIRECT,
        requested_current_a=14,
        charge_limit_percent=90,
        charge_switch_on=True,
    )
    assert direct_evse_response_matches(
        matched,
        target_current_a=14,
        target_limit_percent=90,
        physical_ceiling_a=15,
    )
    assert not direct_evse_response_matches(
        replace(matched, charge_switch_on=False),
        target_current_a=14,
        target_limit_percent=90,
        physical_ceiling_a=15,
    )


def test_direct_reconciliation_retries_are_bounded_and_fault_visible():
    now = datetime(2026, 9, 7, 12, 1, tzinfo=UTC)
    state = DirectEvseReconciliationState()
    for attempt in range(3):
        transition = reconcile_direct_evse(
            state,
            DIRECT,
            target_current_a=14,
            target_limit_percent=90,
            physical_ceiling_a=15,
            now=now + timedelta(seconds=30 * attempt),
        )
        assert transition.plan.commands
        state = transition.state
    fault = reconcile_direct_evse(
        state,
        DIRECT,
        target_current_a=14,
        target_limit_percent=90,
        physical_ceiling_a=15,
        now=now + timedelta(seconds=90),
    )
    assert fault.plan.commands == ()
    assert fault.plan.reason == "maximum_attempts_reached"
    assert fault.state.phase == "fault_maximum_attempts"
    assert fault.state.attempts == 3


def test_confirmed_attempt_budget_rearms_after_thirty_minutes():
    now = datetime(2026, 9, 7, 20, tzinfo=UTC)
    matched = replace(
        DIRECT,
        requested_current_a=1,
        charge_limit_percent=78,
        charge_switch_on=True,
    )
    stale = DirectEvseReconciliationState(
        1,
        78,
        3,
        now - timedelta(minutes=30),
        "confirmed",
    )

    rearmed = reconcile_direct_evse(
        stale,
        matched,
        target_current_a=1,
        target_limit_percent=78,
        physical_ceiling_a=15,
        now=now,
    )

    assert rearmed.plan.reason == "feedback_confirmed"
    assert rearmed.state.phase == "confirmed"
    assert rearmed.state.attempts == 0
    assert rearmed.state.last_command_at is None


def test_maximum_attempts_rearm_after_thirty_minutes():
    now = datetime(2026, 9, 7, 20, tzinfo=UTC)
    coerced = replace(
        DIRECT,
        requested_current_a=5,
        charge_limit_percent=78,
        charge_switch_on=True,
    )
    exhausted = DirectEvseReconciliationState(
        1,
        78,
        3,
        now - timedelta(minutes=30),
        "fault_maximum_attempts",
    )

    rearmed = reconcile_direct_evse(
        exhausted,
        coerced,
        target_current_a=1,
        target_limit_percent=78,
        physical_ceiling_a=15,
        now=now,
    )

    assert rearmed.plan.commands == (EvCommand("set_charge_current", 1),)
    assert rearmed.state.phase == "awaiting_feedback"
    assert rearmed.state.attempts == 1


def test_maximum_attempts_remain_latched_during_cooldown():
    now = datetime(2026, 9, 7, 20, tzinfo=UTC)
    exhausted = DirectEvseReconciliationState(
        1,
        78,
        3,
        now - timedelta(minutes=29, seconds=59),
        "fault_maximum_attempts",
    )

    retained = reconcile_direct_evse(
        exhausted,
        replace(
            DIRECT,
            requested_current_a=5,
            charge_limit_percent=78,
            charge_switch_on=True,
        ),
        target_current_a=1,
        target_limit_percent=78,
        physical_ceiling_a=15,
        now=now,
    )

    assert retained.plan.commands == ()
    assert retained.plan.reason == "maximum_attempts_reached"
    assert retained.state.phase == "fault_maximum_attempts"


def test_direct_reconciliation_waits_for_feedback_between_attempts():
    now = datetime(2026, 9, 7, 12, 1, tzinfo=UTC)
    first = reconcile_direct_evse(
        DirectEvseReconciliationState(),
        DIRECT,
        target_current_a=14,
        target_limit_percent=90,
        physical_ceiling_a=15,
        now=now,
    )
    waiting = reconcile_direct_evse(
        first.state,
        DIRECT,
        target_current_a=14,
        target_limit_percent=90,
        physical_ceiling_a=15,
        now=now + timedelta(seconds=10),
    )
    assert waiting.plan.commands == ()
    assert waiting.plan.reason == "awaiting_feedback"
    assert waiting.state.attempts == 1


def test_direct_reconciliation_waits_for_overwritten_current_to_settle():
    """Do not phase-lock retries to a connector that reasserts its start current."""
    first_at = datetime(2026, 9, 17, 19, 26, 34, tzinfo=UTC)
    first = reconcile_direct_evse(
        DirectEvseReconciliationState(),
        replace(
            DIRECT,
            requested_current_a=5,
            charge_limit_percent=78,
            charge_switch_on=True,
            requested_current_changed_at=first_at - timedelta(seconds=25),
        ),
        target_current_a=1,
        target_limit_percent=78,
        physical_ceiling_a=15,
        now=first_at,
    )
    assert first.plan.commands == (EvCommand("set_charge_current", 1),)

    overwritten_at = first_at + timedelta(seconds=5)
    premature = reconcile_direct_evse(
        first.state,
        replace(
            DIRECT,
            requested_current_a=5,
            charge_limit_percent=78,
            charge_switch_on=True,
            requested_current_changed_at=overwritten_at,
        ),
        target_current_a=1,
        target_limit_percent=78,
        physical_ceiling_a=15,
        now=first_at + timedelta(seconds=30),
    )
    assert premature.plan.commands == ()
    assert premature.plan.reason == "awaiting_stable_current_feedback"
    assert premature.state.attempts == 1

    settled = reconcile_direct_evse(
        premature.state,
        replace(
            DIRECT,
            requested_current_a=5,
            charge_limit_percent=78,
            charge_switch_on=True,
            requested_current_changed_at=overwritten_at,
        ),
        target_current_a=1,
        target_limit_percent=78,
        physical_ceiling_a=15,
        now=overwritten_at + timedelta(seconds=30),
    )
    assert settled.plan.commands == (EvCommand("set_charge_current", 1),)
    assert settled.state.attempts == 2


def test_new_target_rearms_bounded_reconciliation():
    now = datetime(2026, 9, 7, 12, 1, tzinfo=UTC)
    exhausted = DirectEvseReconciliationState(14, 90, 3, now, "fault_maximum_attempts")
    changed = reconcile_direct_evse(
        exhausted,
        DIRECT,
        target_current_a=10,
        target_limit_percent=90,
        physical_ceiling_a=15,
        now=now + timedelta(seconds=1),
    )
    assert changed.plan.commands
    assert changed.state.attempts == 1


def test_matching_feedback_confirms_without_rearming_same_target():
    now = datetime(2026, 9, 7, 12, 1, tzinfo=UTC)
    matched = replace(
        DIRECT,
        requested_current_a=14,
        charge_limit_percent=90,
        charge_switch_on=True,
    )
    result = reconcile_direct_evse(
        DirectEvseReconciliationState(14, 90, 2, now, "awaiting_feedback"),
        matched,
        target_current_a=14,
        target_limit_percent=90,
        physical_ceiling_a=15,
        now=now + timedelta(seconds=30),
    )
    assert result.plan.reason == "feedback_confirmed"
    assert result.state.phase == "confirmed"
    assert result.state.attempts == 2


def test_direct_runtime_releases_outside_ownership_only_after_confirmed_idle():
    confirmed = DirectEvseReconciliation(
        DirectEvseReconciliationState(0, 80, 1, None, "confirmed"),
        EvCommandPlan((), "feedback_confirmed"),
    )
    released = finalize_direct_evse_reconciliation(
        confirmed,
        in_free_window=False,
        outside_enabled=False,
        outside_control_active=True,
        outside_target_active=False,
    )
    assert released.reconciliation is confirmed
    assert released.outside_control_active is False
    assert released.save_reconciliation is True
    assert released.save_ownership_release is True

    for changes in (
        {"in_free_window": True},
        {"outside_enabled": True},
        {"outside_target_active": True},
        {"outside_control_active": False},
    ):
        inputs = {
            "in_free_window": False,
            "outside_enabled": False,
            "outside_control_active": True,
            "outside_target_active": False,
        }
        inputs.update(changes)
        retained = finalize_direct_evse_reconciliation(confirmed, **inputs)
        assert retained.outside_control_active == inputs["outside_control_active"]
        assert retained.save_reconciliation is True
        assert retained.save_ownership_release is False

    commanding = finalize_direct_evse_reconciliation(
        DirectEvseReconciliation(
            confirmed.state,
            EvCommandPlan((EvCommand("set_charge_current", 1),), "direct_path_ready"),
        ),
        in_free_window=False,
        outside_enabled=False,
        outside_control_active=True,
        outside_target_active=False,
    )
    assert commanding.outside_control_active is True
    assert commanding.save_ownership_release is False


def test_competing_writer_cannot_rearm_by_briefly_accepting_same_target():
    now = datetime(2026, 9, 7, 12, 1, tzinfo=UTC)
    matched = replace(
        DIRECT,
        requested_current_a=14,
        charge_limit_percent=90,
        charge_switch_on=True,
    )
    state = DirectEvseReconciliationState()
    for attempt in range(3):
        sent = reconcile_direct_evse(
            state,
            DIRECT,
            target_current_a=14,
            target_limit_percent=90,
            physical_ceiling_a=15,
            now=now + timedelta(seconds=60 * attempt),
        )
        assert sent.plan.commands
        confirmed = reconcile_direct_evse(
            sent.state,
            matched,
            target_current_a=14,
            target_limit_percent=90,
            physical_ceiling_a=15,
            now=now + timedelta(seconds=60 * attempt + 30),
        )
        assert confirmed.state.phase == "confirmed"
        assert confirmed.state.attempts == attempt + 1
        state = confirmed.state
    fault = reconcile_direct_evse(
        state,
        DIRECT,
        target_current_a=14,
        target_limit_percent=90,
        physical_ceiling_a=15,
        now=now + timedelta(seconds=180),
    )
    assert fault.plan.reason == "maximum_attempts_reached"
    assert fault.state.phase == "fault_maximum_attempts"
