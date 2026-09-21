from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    OutsideChargeLimitEvidence,
    OutsideCurrentEnvelopeEvidence,
    PreFreeCurrentInputs,
    PreFreePlanInputs,
    PreFreePlanningEvidence,
    PreFreeSessionState,
    SolarSpillInputs,
    SolarSpillTelemetryEvidence,
    advance_pre_free_session,
    calculate_pre_free_plan,
    evaluate_outside_charge_limit,
    evaluate_outside_current_envelope,
    evaluate_pre_free_plan,
    evaluate_solar_spill_telemetry,
    plan_pre_free_current,
    plan_solar_spill_current,
    select_outside_window_current,
)

SOLAR = SolarSpillInputs(
    telemetry_valid=True,
    battery_soc_percent=100,
    battery_full_threshold_percent=100,
    connected=True,
    vehicle_soc_percent=60,
    vehicle_soft_limit_percent=90,
    in_boosted_export_window=False,
    ev_power_kw=0.239,
    grid_export_kw=2.0,
    battery_charge_kw=0.5,
    voltage_v=239,
    phase_count=1,
    current_step_a=1,
    charger_minimum_a=1,
    current_ceiling_a=15,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
TELEMETRY = SolarSpillTelemetryEvidence(
    now=NOW,
    grid_power_kw=-2.0,
    grid_reason=None,
    grid_source_updated_at=(NOW,),
    battery_power_kw=0.5,
    battery_reason=None,
    battery_source_updated_at=(NOW,),
    actual_ev_current_a=10,
    actual_ev_current_valid=True,
    actual_current_entity_present=True,
    battery_soc_entity_present=True,
    max_age_seconds=90,
    max_skew_seconds=30,
    voltage_v=230,
    phase_count=1,
)

OUTSIDE_ENVELOPE = OutsideCurrentEnvelopeEvidence(
    physical_ceiling_a=16,
    physical_minimum_a=1,
    current_step_a=1,
    service_ceiling_a=12,
    inverter_ceiling_a=6,
    configured_baseline_a=1,
)

OUTSIDE_LIMIT = OutsideChargeLimitEvidence(
    charge_to_full=False,
    outside_target_active=True,
    soft_limit_percent=80,
    learned_limit_percent=76,
    current_limit_percent=90,
    vehicle_soc_percent=60,
    protected_baseline_a=0,
    direct_limit_headroom_percent=2,
    minimum_percent=50,
    maximum_percent=100,
    step_percent=1,
)


@pytest.mark.parametrize(
    ("changes", "policy_limit", "target_limit"),
    [
        ({"charge_to_full": True}, 100, 100),
        ({}, 80, 80),
        ({"outside_target_active": False}, 76, 76),
        (
            {"outside_target_active": False, "learned_limit_percent": None},
            80,
            80,
        ),
        (
            {"vehicle_soc_percent": 89, "protected_baseline_a": 1},
            80,
            91,
        ),
    ],
)
def test_outside_charge_limit_preserves_policy_order_and_anti_pause_guard(
    changes,
    policy_limit,
    target_limit,
):
    evaluation = evaluate_outside_charge_limit(replace(OUTSIDE_LIMIT, **changes))

    assert evaluation.policy_limit_percent == policy_limit
    assert evaluation.target_limit_percent == target_limit


@pytest.mark.parametrize(
    ("changes", "configured", "baseline", "pre_free_ceiling", "service_supported"),
    [
        ({}, 1, 1, 6, True),
        ({"configured_baseline_a": -1}, 0, 0, 6, True),
        ({"configured_baseline_a": 0}, 0, 0, 6, True),
        ({"configured_baseline_a": 0.5, "current_step_a": 2}, 0.5, 2, 6, True),
        ({"configured_baseline_a": 20}, 20, 16, 16, True),
        ({"service_ceiling_a": 0}, 1, 1, 1, False),
        ({"service_ceiling_a": 0.5}, 1, 1, 1, False),
    ],
)
def test_outside_current_envelope_preserves_retained_clamps(
    changes,
    configured,
    baseline,
    pre_free_ceiling,
    service_supported,
):
    evaluation = evaluate_outside_current_envelope(
        replace(OUTSIDE_ENVELOPE, **changes)
    )

    assert evaluation.configured_baseline_a == configured
    assert evaluation.protected_baseline_a == baseline
    assert evaluation.pre_free_ceiling_a == pre_free_ceiling
    assert evaluation.service_supports_charging is service_supported


def test_solar_spill_telemetry_evaluation_preserves_inclusive_boundaries():
    evidence = replace(
        TELEMETRY,
        grid_source_updated_at=(NOW.replace(second=30, minute=58, hour=11),),
        battery_source_updated_at=(NOW.replace(hour=11, minute=59, second=0),),
    )

    evaluation = evaluate_solar_spill_telemetry(evidence)

    assert evaluation.telemetry_valid is True
    assert evaluation.ev_power_kw == 2.3
    assert evaluation.grid_export_kw == 2.0
    assert evaluation.battery_charge_kw == 0.5


@pytest.mark.parametrize(
    ("changes", "expected_grid_export", "expected_battery_charge"),
    [
        ({"grid_power_kw": None}, 0.0, 0.5),
        ({"battery_power_kw": None}, 2.0, 0.0),
        ({"actual_ev_current_valid": False}, 2.0, 0.5),
        ({"actual_current_entity_present": False}, 2.0, 0.5),
        ({"battery_soc_entity_present": False}, 2.0, 0.5),
        ({"grid_source_updated_at": (None,)}, 2.0, 0.5),
        (
            {"grid_source_updated_at": (NOW.replace(second=29, minute=58, hour=11),)},
            2.0,
            0.5,
        ),
        ({"grid_source_updated_at": (NOW.replace(second=1),)}, 2.0, 0.5),
        (
            {
                "grid_source_updated_at": (NOW.replace(second=29, minute=59),),
                "battery_source_updated_at": (NOW,),
            },
            2.0,
            0.5,
        ),
    ],
)
def test_solar_spill_telemetry_rejects_each_incoherent_evidence_term(
    changes,
    expected_grid_export,
    expected_battery_charge,
):
    evaluation = evaluate_solar_spill_telemetry(replace(TELEMETRY, **changes))

    assert evaluation.telemetry_valid is False
    assert evaluation.ev_power_kw == 2.3
    assert evaluation.grid_export_kw == expected_grid_export
    assert evaluation.battery_charge_kw == expected_battery_charge


def test_solar_spill_telemetry_fallback_uses_only_accepted_signed_source_clock():
    stale = NOW.replace(hour=10)
    evidence = replace(
        TELEMETRY,
        battery_reason="signed_fallback_pair_stale",
        battery_source_updated_at=(stale, stale, NOW),
    )
    assert evaluate_solar_spill_telemetry(evidence).telemetry_valid is True
    assert (
        evaluate_solar_spill_telemetry(
            replace(evidence, battery_reason="paired_magnitudes")
        ).telemetry_valid
        is False
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"grid_source_updated_at": ()},
        {"battery_source_updated_at": ()},
        {"grid_source_updated_at": (), "battery_source_updated_at": ()},
    ],
)
def test_solar_spill_telemetry_fails_closed_for_empty_provenance(changes):
    evaluation = evaluate_solar_spill_telemetry(replace(TELEMETRY, **changes))

    assert evaluation.telemetry_valid is False
    assert evaluation.ev_power_kw == 2.3
    assert evaluation.grid_export_kw == 2.0
    assert evaluation.battery_charge_kw == 0.5


@pytest.mark.parametrize(
    ("changes", "expected", "phase"),
    [
        ({}, 11, "solar_spill"),
        ({"telemetry_valid": False}, 0, "telemetry_unavailable"),
        ({"battery_soc_percent": 99}, 0, "battery_not_full"),
        ({"connected": False}, 0, "vehicle_not_eligible"),
        ({"vehicle_soc_percent": 90}, 0, "vehicle_not_eligible"),
        ({"in_boosted_export_window": True}, 0, "boosted_export_window"),
        (
            {"ev_power_kw": 0, "grid_export_kw": 0.1, "battery_charge_kw": 0},
            0,
            "below_charger_minimum",
        ),
        ({"grid_export_kw": 10}, 15, "solar_spill"),
    ],
)
def test_pilot_solar_spill_golden_branches(changes, expected, phase):
    decision = plan_solar_spill_current(replace(SOLAR, **changes))
    assert decision.current_a == expected
    assert decision.phase == phase


def test_solar_spill_removes_battery_discharge_and_preserves_existing_ev_power():
    decision = plan_solar_spill_current(
        replace(SOLAR, ev_power_kw=2.39, grid_export_kw=1, battery_charge_kw=-1)
    )
    assert decision.reconstructed_surplus_kw == 2.39
    assert decision.current_a == 10


def test_three_phase_extension_changes_only_power_to_current_conversion():
    decision = plan_solar_spill_current(
        replace(
            SOLAR,
            ev_power_kw=0,
            grid_export_kw=6.9,
            battery_charge_kw=0,
            voltage_v=230,
            phase_count=3,
            current_ceiling_a=16,
        )
    )
    assert decision.current_a == 10


def test_pre_free_plan_is_back_loaded_from_exact_free_boundary():
    free_start = datetime(2026, 9, 8, 11, 1, tzinfo=UTC)
    plan = calculate_pre_free_plan(
        PreFreePlanInputs(
            discretionary_ac_kwh=8,
            vehicle_wall_room_kwh=5,
            baseline_a=1,
            current_ceiling_a=11,
            voltage_v=230,
            phase_count=1,
            free_window_start=free_start,
        )
    )
    assert plan.planned_energy_kwh == 5
    assert plan.maximum_additional_power_kw == 2.3
    assert plan.planned_duration_minutes == 130.4
    assert plan.planned_start == datetime(2026, 9, 8, 8, 50, 36, tzinfo=UTC)


def test_pre_free_plan_protects_baseline_by_using_only_additional_power():
    plan = calculate_pre_free_plan(
        PreFreePlanInputs(
            discretionary_ac_kwh=2,
            vehicle_wall_room_kwh=2,
            baseline_a=1,
            current_ceiling_a=1,
            voltage_v=230,
            phase_count=1,
            free_window_start=datetime(2026, 9, 8, 11, 1, tzinfo=UTC),
        )
    )
    assert plan.maximum_additional_power_kw == 0
    assert plan.planned_start is None


PRE_FREE_PLANNING = PreFreePlanningEvidence(
    planned_export_energy_kwh=8,
    stored_vehicle_energy_kwh=40,
    vehicle_soc_percent=50,
    vehicle_target_soc_percent=75,
    charge_efficiency_percent=90,
    in_pre_free_window=True,
    baseline_a=1,
    current_ceiling_a=11,
    voltage_v=230,
    phase_count=1,
    free_window_start=datetime(2026, 9, 8, 11, 1, tzinfo=UTC),
)


def test_pre_free_planning_composes_vehicle_room_and_export_budget():
    evaluation = evaluate_pre_free_plan(PRE_FREE_PLANNING)

    assert evaluation.plan is not None
    assert evaluation.plan.planned_energy_kwh == 8
    assert evaluation.plan.maximum_additional_power_kw == 2.3
    assert evaluation.planned_energy_kwh == evaluation.plan.planned_energy_kwh
    assert evaluation.planned_start == evaluation.plan.planned_start


@pytest.mark.parametrize(
    "changes",
    (
        {"planned_export_energy_kwh": None},
        {"stored_vehicle_energy_kwh": None},
    ),
)
def test_pre_free_planning_withholds_plan_without_required_energy_evidence(changes):
    evaluation = evaluate_pre_free_plan(replace(PRE_FREE_PLANNING, **changes))

    assert evaluation.plan is None
    assert evaluation.planned_energy_kwh == 0
    assert evaluation.planned_start is None


def test_pre_free_planning_outside_window_retains_empty_diagnostic_plan():
    evaluation = evaluate_pre_free_plan(
        replace(PRE_FREE_PLANNING, in_pre_free_window=False)
    )

    assert evaluation.plan is not None
    assert evaluation.planned_energy_kwh == 0
    assert evaluation.planned_start is None


def test_pre_free_latch_freezes_start_and_clears_when_budget_disappears():
    start = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
    waiting = advance_pre_free_session(
        PreFreeSessionState(),
        now=datetime(2026, 9, 8, 8, 59, tzinfo=UTC),
        in_pre_free_window=True,
        connected=True,
        export_session_active=False,
        planned_energy_kwh=5,
        vehicle_soc_percent=40,
        vehicle_soft_limit_percent=90,
        planned_start=start,
    )
    assert waiting.phase == "waiting_latest_start"
    started = advance_pre_free_session(
        waiting.state,
        now=start,
        in_pre_free_window=True,
        connected=True,
        export_session_active=False,
        planned_energy_kwh=5,
        vehicle_soc_percent=40,
        vehicle_soft_limit_percent=90,
        planned_start=start,
    )
    assert started.state == PreFreeSessionState(True, start)
    active = advance_pre_free_session(
        started.state,
        now=datetime(2026, 9, 8, 9, 5, tzinfo=UTC),
        in_pre_free_window=True,
        connected=True,
        export_session_active=False,
        planned_energy_kwh=4,
        vehicle_soc_percent=41,
        vehicle_soft_limit_percent=90,
        planned_start=datetime(2026, 9, 8, 9, 30, tzinfo=UTC),
    )
    assert active.state.frozen_start == start
    cleared = advance_pre_free_session(
        active.state,
        now=datetime(2026, 9, 8, 9, 6, tzinfo=UTC),
        in_pre_free_window=True,
        connected=True,
        export_session_active=False,
        planned_energy_kwh=0,
        vehicle_soc_percent=41,
        vehicle_soft_limit_percent=90,
        planned_start=None,
    )
    assert cleared.state == PreFreeSessionState()


def test_export_session_blocks_pre_free_latch():
    transition = advance_pre_free_session(
        PreFreeSessionState(),
        now=datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
        in_pre_free_window=True,
        connected=True,
        export_session_active=True,
        planned_energy_kwh=5,
        vehicle_soc_percent=40,
        vehicle_soft_limit_percent=90,
        planned_start=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
    )
    assert transition.phase == "not_eligible"
    assert transition.state.active is False


def test_contradictory_persisted_pre_free_phase_is_rejected():
    with pytest.raises(ValueError, match="frozen start"):
        advance_pre_free_session(
            PreFreeSessionState(active=True),
            now=datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
            in_pre_free_window=True,
            connected=True,
            export_session_active=False,
            planned_energy_kwh=5,
            vehicle_soc_percent=40,
            vehicle_soft_limit_percent=90,
            planned_start=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        )


def test_active_pre_free_current_jumps_directly_to_live_safe_whole_amp():
    base = PreFreeCurrentInputs(
        session_active=True,
        planned_energy_kwh=4,
        hours_until_free=2,
        voltage_v=230,
        phase_count=1,
        current_step_a=1,
        baseline_a=1,
        current_ceiling_a=15,
        vehicle_soc_percent=40,
        vehicle_soft_limit_percent=90,
    )
    assert plan_pre_free_current(base).current_a == 9
    assert plan_pre_free_current(replace(base, planned_energy_kwh=2)).current_a == 5


def test_three_phase_pre_free_extension_uses_configured_phase_count():
    decision = plan_pre_free_current(
        PreFreeCurrentInputs(
            session_active=True,
            planned_energy_kwh=6.9,
            hours_until_free=1,
            voltage_v=230,
            phase_count=3,
            current_step_a=1,
            baseline_a=1,
            current_ceiling_a=16,
            vehicle_soc_percent=40,
            vehicle_soft_limit_percent=90,
        )
    )
    assert decision.current_a == 11


def test_outside_branch_order_takes_maximum_of_active_backfill_and_spill():
    decision = select_outside_window_current(
        baseline_a=1,
        current_ceiling_a=15,
        charger_minimum_a=1,
        pre_free_active=True,
        pre_free_current_a=5,
        solar_spill_current_a=8,
    )
    assert decision.current_a == 8
    assert decision.phase == "pre_free_or_solar_spill"


def test_outside_branch_falls_back_to_protected_baseline():
    decision = select_outside_window_current(
        baseline_a=1,
        current_ceiling_a=15,
        charger_minimum_a=1,
        pre_free_active=False,
        pre_free_current_a=1,
        solar_spill_current_a=0,
    )
    assert decision.current_a == 1
    assert decision.phase == "protected_baseline"
