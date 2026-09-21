"""Characterization for immutable EV stage candidates."""

from dataclasses import FrozenInstanceError, replace

import pytest

from custom_components.home_energy_orchestrator.planner.ev_candidates import (
    EvConnectionDecision,
    EvPolicyAvailabilityEvidence,
    EvStageCandidate,
    OutsideStageCandidateInputs,
    build_ev_stage_candidate,
    build_outside_stage_candidates,
    ev_home_presence_required,
    evaluate_ev_connection_evidence,
    evaluate_ev_home_control,
    evaluate_ev_policy_availability,
    reject_ev_stage_candidate,
    select_ev_eligibility_route,
    select_ev_policy_route,
    select_outside_stage_candidate,
)

POLICY_AVAILABILITY = EvPolicyAvailabilityEvidence(
    smart_path=False,
    configured_baseline_a=0,
    charge_switch_on=False,
    daily_backfill_enabled=False,
    charge_to_full_requested=False,
    daily_stop_pending=False,
    modbus_outside_stages_authorized=False,
    solar_spill_enabled=False,
    pre_free_enabled=False,
)


@pytest.mark.parametrize(
    ("changes", "unexpected", "outside_enabled"),
    (
        ({}, False, False),
        ({"configured_baseline_a": 1}, False, True),
        ({"charge_switch_on": True}, True, True),
        ({"charge_switch_on": True, "smart_path": True}, False, False),
        ({"daily_backfill_enabled": True}, False, True),
        ({"charge_to_full_requested": True}, False, True),
        ({"daily_stop_pending": True}, False, True),
        (
            {
                "modbus_outside_stages_authorized": True,
                "solar_spill_enabled": True,
            },
            False,
            True,
        ),
        (
            {
                "modbus_outside_stages_authorized": True,
                "pre_free_enabled": True,
            },
            False,
            True,
        ),
        ({"solar_spill_enabled": True}, False, False),
    ),
)
def test_policy_availability_preserves_every_outside_authority(
    changes,
    unexpected,
    outside_enabled,
) -> None:
    result = evaluate_ev_policy_availability(
        replace(POLICY_AVAILABILITY, **changes)
    )

    assert result.unexpected_direct_charge is unexpected
    assert result.outside_enabled is outside_enabled


def test_ev_home_control_retains_explicit_location_mode_semantics():
    assert ev_home_presence_required(location_mode="auto") is True
    assert ev_home_presence_required(location_mode="home") is False
    assert evaluate_ev_home_control(
        location_mode="away",
        at_home_state="home",
    ) == EvConnectionDecision(False, "ev_location_away")
    assert evaluate_ev_home_control(
        location_mode="home",
        at_home_state=None,
    ) == EvConnectionDecision(True, "ev_connected_at_home")
    assert evaluate_ev_home_control(
        location_mode="auto",
        at_home_state="unavailable",
    ) == EvConnectionDecision(False, "ev_location_not_confirmed_home")


def test_ev_connection_evidence_retains_cable_before_vehicle_state_order():
    home = EvConnectionDecision(True, "ev_connected_at_home")
    assert evaluate_ev_connection_evidence(
        home,
        cable_state="off",
        charging_state="charging",
    ) == EvConnectionDecision(False, "ev_cable_not_connected")
    assert evaluate_ev_connection_evidence(
        home,
        cable_state="on",
        charging_state=None,
    ) == EvConnectionDecision(False, "ev_connection_state_unavailable")
    assert evaluate_ev_connection_evidence(
        home,
        cable_state="on",
        charging_state="stopped",
    ) == EvConnectionDecision(True, "ev_connected_at_home")


def test_stage_candidate_is_lossless_and_immutable() -> None:
    candidate = EvStageCandidate(
        stage="free_window",
        eligible=True,
        reason="ev_priority",
        target_current_a=16,
        target_limit_percent=92,
        command_intent=("reconcile_current", "reconcile_charge_limit"),
        persistence_transition="none",
    )

    assert candidate == EvStageCandidate(
        "free_window",
        True,
        "ev_priority",
        16,
        92,
        ("reconcile_current", "reconcile_charge_limit"),
        "none",
    )
    with pytest.raises(FrozenInstanceError):
        candidate.reason = "changed"  # type: ignore[misc]


def test_rejected_candidate_has_no_target_command_or_persistence_intent() -> None:
    assert reject_ev_stage_candidate("free_window", "ev_soc_unavailable") == (
        EvStageCandidate("free_window", False, "ev_soc_unavailable")
    )


def test_outside_builder_preserves_simultaneous_stage_eligibility() -> None:
    candidates = build_outside_stage_candidates(
        OutsideStageCandidateInputs(
            charge_to_full=True,
            service_ceiling_a=16,
            daily_enabled=True,
            daily_active=True,
            daily_reason="charge_now",
            daily_current_a=6,
            daily_stop_pending=False,
            solar_current_a=10,
            solar_reason="solar_spill",
            pre_free_active=True,
            pre_free_reason="started",
            pre_free_current_a=12,
            protected_baseline_a=1,
            physical_minimum_a=1,
        )
    )

    assert tuple(candidate.stage for candidate in candidates) == (
        "charge_to_full",
        "daily_ready",
        "solar_spill",
        "pre_free",
        "protected_baseline",
    )
    assert all(candidate.eligible for candidate in candidates)
    assert tuple(candidate.target_current_a for candidate in candidates) == (
        16,
        6,
        10,
        12,
        1,
    )
    assert candidates[1].persistence_transition == "daily_backfill_active"
    assert candidates[3].persistence_transition == "pre_free_session_active"


def test_outside_builder_distinguishes_disabled_from_unavailable_daily_stage() -> None:
    common = dict(
        charge_to_full=False,
        service_ceiling_a=16,
        daily_active=False,
        daily_reason="inputs_unavailable",
        daily_current_a=0,
        daily_stop_pending=False,
        solar_current_a=0,
        solar_reason="disabled",
        pre_free_active=False,
        pre_free_reason="disabled",
        pre_free_current_a=0,
        protected_baseline_a=0,
        physical_minimum_a=1,
    )

    disabled = build_outside_stage_candidates(
        OutsideStageCandidateInputs(daily_enabled=False, **common)
    )
    unavailable = build_outside_stage_candidates(
        OutsideStageCandidateInputs(daily_enabled=True, **common)
    )

    assert disabled[1].reason == "disabled"
    assert unavailable[1].reason == "inputs_unavailable"
    assert not any(candidate.eligible for candidate in disabled)


@pytest.mark.parametrize(
    (
        "eligible",
        "currents",
        "expected_stage",
        "expected_reason",
        "expected_current",
    ),
    [
        (
            (True, True, True, True, True),
            (16, 6, 10, 12, 1),
            "charge_to_full",
            "charge_to_full_paid_grid_override",
            16,
        ),
        (
            (False, True, True, True, True),
            (0, 6, 10, 12, 1),
            "daily_ready",
            "daily_ready_backfill",
            6,
        ),
        (
            (False, False, True, True, True),
            (0, 0, 10, 12, 1),
            "pre_free_or_solar_spill",
            "pre_free_or_solar_spill",
            12,
        ),
        (
            (False, False, True, True, True),
            (0, 0, 10, 8, 1),
            "pre_free_or_solar_spill",
            "pre_free_or_solar_spill",
            10,
        ),
        (
            (False, False, True, False, True),
            (0, 0, 10, 0, 1),
            "solar_spill",
            "solar_spill",
            10,
        ),
        (
            (False, False, False, False, True),
            (0, 0, 0, 0, 1),
            "protected_baseline",
            "protected_baseline",
            1,
        ),
        (
            (False, False, False, False, False),
            (0, 0, 0, 0, 0),
            "protected_baseline",
            "protected_baseline",
            0,
        ),
    ],
)
def test_outside_selector_shadows_retained_collision_order(
    eligible,
    currents,
    expected_stage,
    expected_reason,
    expected_current,
) -> None:
    stages = (
        "charge_to_full",
        "daily_ready",
        "solar_spill",
        "pre_free",
        "protected_baseline",
    )
    candidates = tuple(
        build_ev_stage_candidate(
            stage,
            eligible=is_eligible,
            reason=(
                "charge_to_full_paid_grid_override"
                if stage == "charge_to_full"
                else stage
            ),
            target_current_a=current if is_eligible else None,
        )
        for stage, is_eligible, current in zip(stages, eligible, currents, strict=True)
    )

    selected = select_outside_stage_candidate(candidates, current_ceiling_a=16)

    assert selected.stage == expected_stage
    assert selected.reason == expected_reason
    assert selected.target_current_a == expected_current


@pytest.mark.parametrize(
    (
        "connected",
        "observation_available",
        "smart_path",
        "home_control_active",
        "expected_route",
        "expected_reason",
    ),
    [
        (False, True, True, True, "disconnected_smart_socket", "disconnected"),
        (False, True, True, False, "blocked", "disconnected"),
        (False, False, False, True, "blocked", "disconnected"),
        (True, False, True, True, "blocked", "ev_actuator_feedback_unavailable"),
        (True, True, False, True, "eligible", "ev_connected_at_home"),
    ],
)
def test_eligibility_route_preserves_disconnected_cleanup_order(
    connected,
    observation_available,
    smart_path,
    home_control_active,
    expected_route,
    expected_reason,
) -> None:
    selected = select_ev_eligibility_route(
        connected=connected,
        connection_reason="disconnected",
        observation_available=observation_available,
        smart_path=smart_path,
        home_control_active=home_control_active,
    )

    assert selected.route == expected_route
    assert selected.reason == expected_reason


@pytest.mark.parametrize(
    ("in_window", "outside_enabled", "outside_active", "expected"),
    [
        (True, True, True, "free_window"),
        (True, False, False, "free_window"),
        (False, True, False, "outside_window"),
        (False, False, True, "outside_window"),
        (False, False, False, "general_limit"),
    ],
)
def test_policy_route_preserves_free_outside_and_general_limit_order(
    in_window,
    outside_enabled,
    outside_active,
    expected,
) -> None:
    selected = select_ev_policy_route(
        in_free_window=in_window,
        outside_enabled=outside_enabled,
        outside_control_active=outside_active,
    )

    assert selected.route == expected
