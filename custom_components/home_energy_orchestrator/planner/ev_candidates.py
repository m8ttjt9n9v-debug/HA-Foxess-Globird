"""Immutable EV stage candidates composed from retained policy decisions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvStageCandidate:
    """One stage's eligibility, target intent and persistence obligation."""

    stage: str
    eligible: bool
    reason: str
    target_current_a: float | None = None
    target_limit_percent: float | None = None
    command_intent: tuple[str, ...] = ()
    persistence_transition: str = "none"


@dataclass(frozen=True, slots=True)
class EvStageSelection:
    """One selected stage and its resulting current intent."""

    stage: str
    reason: str
    target_current_a: float


@dataclass(frozen=True, slots=True)
class EvCycleRoute:
    """One selected controller route before stage reconciliation."""

    route: str
    reason: str


@dataclass(frozen=True, slots=True)
class EvConnectionDecision:
    """Mapped location/cable/vehicle evidence for current-write eligibility."""

    connected: bool
    reason: str


@dataclass(frozen=True, slots=True)
class EvPolicyAvailabilityEvidence:
    """Primitive intent and ownership evidence for outside-stage routing."""

    smart_path: bool
    configured_baseline_a: float
    charge_switch_on: bool
    daily_backfill_enabled: bool
    charge_to_full_requested: bool
    daily_stop_pending: bool
    modbus_outside_stages_authorized: bool
    solar_spill_enabled: bool
    pre_free_enabled: bool


@dataclass(frozen=True, slots=True)
class EvPolicyAvailability:
    """Whether retained-current cleanup or an outside policy owns this cycle."""

    unexpected_direct_charge: bool
    outside_enabled: bool


def evaluate_ev_policy_availability(
    evidence: EvPolicyAvailabilityEvidence,
) -> EvPolicyAvailability:
    """Compose the retained outside-policy and direct auto-start authority."""
    unexpected_direct_charge = (
        not evidence.smart_path
        and evidence.configured_baseline_a <= 0
        and evidence.charge_switch_on
    )
    outside_enabled = (
        evidence.configured_baseline_a > 0
        or unexpected_direct_charge
        or evidence.daily_backfill_enabled
        or evidence.charge_to_full_requested
        or evidence.daily_stop_pending
        or (
            evidence.modbus_outside_stages_authorized
            and (evidence.solar_spill_enabled or evidence.pre_free_enabled)
        )
    )
    return EvPolicyAvailability(unexpected_direct_charge, outside_enabled)


def ev_home_presence_required(*, location_mode: str) -> bool:
    """Return whether the selected location mode requires tracker evidence."""
    return location_mode == "auto"


def evaluate_ev_home_control(
    *,
    location_mode: str,
    at_home_state: str | None,
) -> EvConnectionDecision:
    """Evaluate the retained Home / Auto / Away current-write scope."""
    if location_mode == "away":
        return EvConnectionDecision(False, "ev_location_away")
    active = location_mode == "home" or (
        location_mode == "auto" and at_home_state in {"home", "on"}
    )
    return EvConnectionDecision(
        active,
        "ev_connected_at_home" if active else "ev_location_not_confirmed_home",
    )


def evaluate_ev_connection_evidence(
    home: EvConnectionDecision,
    *,
    cable_state: str | None,
    charging_state: str | None,
) -> EvConnectionDecision:
    """Apply cable and vehicle-state evidence after home control is allowed."""
    if not home.connected:
        return home
    if cable_state != "on":
        return EvConnectionDecision(False, "ev_cable_not_connected")
    if charging_state is None or charging_state == "disconnected":
        return EvConnectionDecision(False, "ev_connection_state_unavailable")
    return EvConnectionDecision(True, "ev_connected_at_home")


@dataclass(frozen=True, slots=True)
class OutsideStageCandidateInputs:
    """Retained outside-stage results required to describe every candidate."""

    charge_to_full: bool
    service_ceiling_a: float
    daily_enabled: bool
    daily_active: bool
    daily_reason: str
    daily_current_a: float
    daily_stop_pending: bool
    solar_current_a: float
    solar_reason: str
    pre_free_active: bool
    pre_free_reason: str
    pre_free_current_a: float
    protected_baseline_a: float
    physical_minimum_a: float


def build_ev_stage_candidate(
    stage: str,
    *,
    eligible: bool,
    reason: str,
    target_current_a: float | None = None,
    target_limit_percent: float | None = None,
    command_intent: tuple[str, ...] = (),
    persistence_transition: str = "none",
) -> EvStageCandidate:
    """Build one immutable description without policy or side effects."""
    return EvStageCandidate(
        stage=stage,
        eligible=eligible,
        reason=reason,
        target_current_a=target_current_a,
        target_limit_percent=target_limit_percent,
        command_intent=command_intent,
        persistence_transition=persistence_transition,
    )


def reject_ev_stage_candidate(stage: str, reason: str) -> EvStageCandidate:
    """Build the common unavailable-input candidate."""
    return build_ev_stage_candidate(stage, eligible=False, reason=reason)


def build_outside_stage_candidates(
    inputs: OutsideStageCandidateInputs,
) -> tuple[EvStageCandidate, ...]:
    """Describe retained outside stages without selecting among them."""
    command_intent = ("reconcile_current", "reconcile_charge_limit")
    solar_eligible = inputs.solar_current_a >= inputs.physical_minimum_a
    return (
        build_ev_stage_candidate(
            "charge_to_full",
            eligible=inputs.charge_to_full,
            reason=(
                "charge_to_full_paid_grid_override"
                if inputs.charge_to_full
                else "disabled"
            ),
            target_current_a=(
                inputs.service_ceiling_a if inputs.charge_to_full else None
            ),
            command_intent=command_intent if inputs.charge_to_full else (),
        ),
        build_ev_stage_candidate(
            "daily_ready",
            eligible=inputs.daily_active,
            reason=(inputs.daily_reason if inputs.daily_enabled else "disabled"),
            target_current_a=(inputs.daily_current_a if inputs.daily_active else None),
            command_intent=command_intent if inputs.daily_active else (),
            persistence_transition=(
                "daily_backfill_active"
                if inputs.daily_active
                else "daily_backfill_stop_pending"
                if inputs.daily_stop_pending
                else "none"
            ),
        ),
        build_ev_stage_candidate(
            "solar_spill",
            eligible=solar_eligible,
            reason=inputs.solar_reason,
            target_current_a=(inputs.solar_current_a if solar_eligible else None),
            command_intent=command_intent if solar_eligible else (),
        ),
        build_ev_stage_candidate(
            "pre_free",
            eligible=inputs.pre_free_active,
            reason=inputs.pre_free_reason,
            target_current_a=(
                inputs.pre_free_current_a if inputs.pre_free_active else None
            ),
            command_intent=command_intent if inputs.pre_free_active else (),
            persistence_transition=(
                "pre_free_session_active" if inputs.pre_free_active else "none"
            ),
        ),
        build_ev_stage_candidate(
            "protected_baseline",
            eligible=inputs.protected_baseline_a > 0,
            reason=(
                "protected_baseline"
                if inputs.protected_baseline_a > 0
                else "disabled"
            ),
            target_current_a=(
                inputs.protected_baseline_a
                if inputs.protected_baseline_a > 0
                else None
            ),
            command_intent=(
                command_intent if inputs.protected_baseline_a > 0 else ()
            ),
        ),
    )


def select_outside_stage_candidate(
    candidates: tuple[EvStageCandidate, ...],
    *,
    current_ceiling_a: float,
) -> EvStageSelection:
    """Shadow the retained outside-window branch and source ordering."""
    by_stage = {candidate.stage: candidate for candidate in candidates}

    def current(stage: str) -> float:
        candidate = by_stage[stage]
        return candidate.target_current_a or 0.0

    charge_to_full = by_stage["charge_to_full"]
    if charge_to_full.eligible:
        return EvStageSelection(
            charge_to_full.stage,
            charge_to_full.reason,
            current("charge_to_full"),
        )
    daily = by_stage["daily_ready"]
    if daily.eligible:
        return EvStageSelection(
            daily.stage,
            "daily_ready_backfill",
            current("daily_ready"),
        )
    pre_free = by_stage["pre_free"]
    solar = by_stage["solar_spill"]
    if pre_free.eligible:
        return EvStageSelection(
            "pre_free_or_solar_spill",
            "pre_free_or_solar_spill",
            round(
                min(
                    max(current("pre_free"), current("solar_spill")),
                    current_ceiling_a,
                ),
                3,
            ),
        )
    if solar.eligible:
        return EvStageSelection(
            solar.stage,
            "solar_spill",
            round(min(current("solar_spill"), current_ceiling_a), 3),
        )
    return EvStageSelection(
        "protected_baseline",
        "protected_baseline",
        round(current("protected_baseline"), 3),
    )


def select_ev_eligibility_route(
    *,
    connected: bool,
    connection_reason: str,
    observation_available: bool,
    smart_path: bool,
    home_control_active: bool,
) -> EvCycleRoute:
    """Preserve disconnected cleanup and actuator-feedback gate ordering."""
    if not connected:
        if smart_path and observation_available and home_control_active:
            return EvCycleRoute("disconnected_smart_socket", connection_reason)
        return EvCycleRoute("blocked", connection_reason)
    if not observation_available:
        return EvCycleRoute("blocked", "ev_actuator_feedback_unavailable")
    return EvCycleRoute("eligible", "ev_connected_at_home")


def select_ev_policy_route(
    *,
    in_free_window: bool,
    outside_enabled: bool,
    outside_control_active: bool,
) -> EvCycleRoute:
    """Preserve free-window, general-limit and outside-control routing."""
    if in_free_window:
        return EvCycleRoute("free_window", "free_window_active")
    if outside_enabled or outside_control_active:
        return EvCycleRoute("outside_window", "outside_policy_active")
    return EvCycleRoute("general_limit", "outside_window_general_limit_only")
