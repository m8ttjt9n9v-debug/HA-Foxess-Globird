from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.ev import (
    AllowanceCeilingInputs,
    ChargeLimitInputs,
    DirectEvseObservation,
    DirectEvseReconciliationState,
    EvCommand,
    FreeWindowCurrentInputs,
    SmartSocketObservation,
    SmartSocketRecoveryObservation,
    SmartSocketRecoveryState,
    apply_daily_allowance_ceiling,
    direct_evse_response_matches,
    estimate_other_free_window_import_kwh,
    estimate_vehicle_energy_to_target_kwh,
    plan_charge_limit_target,
    plan_direct_evse_commands,
    plan_free_window_current,
    plan_smart_socket_commands,
    reconcile_direct_evse,
    reconcile_smart_socket_recovery,
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
def test_pilot_site_free_window_branch_order(changes, expected, phase):
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
    site_service_limit_a=80,
    site_voltage_v=230,
    site_phase_count=3,
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
    assert plan_smart_socket_commands(
        powered, in_free_window=True, **common
    ).commands == ()
    outside = plan_smart_socket_commands(
        powered, in_free_window=False, **common
    )
    assert [command.action for command in outside.commands] == [
        "turn_off_smart_socket"
    ]


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
    path_changed = _recover(
        latched, replace(RECOVERY, smart_path_selected=False), now
    )
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
