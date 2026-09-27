"""Faithful, adapter-neutral Tesla charging policy.

The base current planner is a direct port of the Working Single Phase Pilot Site three-minute
supervisory allocation.  Site-specific extensions, including the daily free
energy ceiling, are deliberately applied after that decision so they cannot
silently replace its branch order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil, floor, isfinite
from typing import Literal, cast

# The direct-path anti-pause guard may keep a fault-prone powered connector
# accepting its protected baseline, but it is never authority to charge above
# this operator safety ceiling. Charge to Full is the sole exception.
NON_OVERRIDE_CHARGE_LIMIT_MAX_PERCENT = 90.0

# Direct Tessie feedback can take time to converge, and some chargers briefly
# reject an otherwise valid request. Retrying is therefore elapsed-time based,
# not a fixed command-count latch. The sequence preserves prompt recovery for
# a transient cloud delay, then protects the vehicle API from flapping. Once
# the cap is reached, reconciliation continues at that safe cadence.
DIRECT_EVSE_RETRY_INTERVALS = (
    timedelta(seconds=30),
    timedelta(minutes=1),
    timedelta(minutes=2),
    timedelta(minutes=4),
    timedelta(minutes=8),
    timedelta(minutes=16),
    timedelta(minutes=30),
)
DIRECT_EVSE_FEEDBACK_SETTLE_INTERVAL = timedelta(seconds=30)
DIRECT_EVSE_RECONCILIATION_PHASES = frozenset(
    {
        "idle",
        "target_changed",
        "awaiting_feedback",
        "awaiting_stable_current_feedback",
        "confirmed",
        "blocked",
    }
)


@dataclass(frozen=True, slots=True)
class FreeWindowCurrentInputs:
    """Inputs used by the canonical pilot-site free-window current policy."""

    in_free_window: bool
    connected: bool
    ceiling_a: float
    effective_minimum_a: float
    protected_baseline_a: float
    requested_a: float
    service_limit_a: float
    service_headroom_a: float
    grid_average_a: float
    grid_average_valid: bool
    actual_ev_current_a: float
    ev_average_a: float
    ev_average_source_valid: bool
    battery_soc_percent: float | None
    battery_full_soc_percent: float
    battery_charge_power_kw: float | None
    battery_charge_target_kw: float
    site_phase_count: int
    voltage_v: float
    elapsed_minutes: float
    settle_minutes: float
    current_step_a: float
    ev_priority: bool
    charge_to_full: bool = False


@dataclass(frozen=True, slots=True)
class EvCurrentDecision:
    """One auditable EV current decision."""

    current_a: float
    phase: str


@dataclass(frozen=True, slots=True)
class FreeWindowTargetEvidence:
    """Primitive policy, telemetry and topology evidence from the HA facade."""

    ceiling_a: float
    physical_minimum_a: float
    current_step_a: float
    configured_baseline_a: float
    configured_minimum_a: float
    charge_to_full: bool
    configured_policy_limit_percent: float
    vehicle_soc_percent: float
    requested_current_a: float
    service_limit_a: float
    service_headroom_a: float
    grid_average_a: float | None
    grid_average_age_coverage_ratio: float
    grid_average_source_valid: bool
    actual_ev_current_a: float
    ev_average_a: float | None
    ev_average_source_valid: bool
    battery_soc_percent: float | None
    battery_full_soc_percent: float
    battery_charge_power_kw: float | None
    battery_charge_target_kw: float
    site_phase_count: int
    voltage_v: float
    elapsed_minutes: float
    settle_minutes: float
    ev_priority_selected: bool


@dataclass(frozen=True, slots=True)
class FreeWindowTargetEvaluation:
    """Canonical pre-allowance current selection and its composed policy."""

    decision: EvCurrentDecision
    base_decision: EvCurrentDecision
    protected_baseline_a: float
    effective_minimum_a: float
    policy_limit_percent: float
    below_policy_limit: bool


EvDecisionFingerprint = tuple[
    float | None,
    bool,
    str,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    bool,
    bool,
]


@dataclass(frozen=True, slots=True)
class EvDecisionCadenceEvidence:
    """Primitive evidence governing one EV target recalculation."""

    now: datetime
    last_decision_at: datetime | None
    previous_fingerprint: EvDecisionFingerprint | None
    vehicle_soc_percent: float | None
    charge_to_full_requested: bool
    free_window_priority: str
    current_minimum_a: float | None
    current_maximum_a: float | None
    current_step_a: float | None
    limit_minimum_percent: float | None
    limit_maximum_percent: float | None
    limit_step_percent: float | None
    configured_policy_limit_percent: float
    in_free_window: bool
    pre_free_active: bool
    current_target_available: bool
    allowance_guard_enabled: bool
    house_load_includes_ev: bool
    actual_ev_current_valid: bool
    requested_current_a: float
    actual_ev_current_a: float
    grid_current_valid: bool
    grid_current_a: float
    service_limit_a: float
    decision_interval: timedelta = timedelta(minutes=3)


@dataclass(frozen=True, slots=True)
class EvDecisionCadenceEvaluation:
    """Fingerprint and retained transition-hold/recalculation decision."""

    fingerprint: EvDecisionFingerprint
    decision_interval_elapsed: bool
    fingerprint_changed: bool
    only_vehicle_soc_changed: bool
    soc_remains_below_policy: bool
    current_transition_pending: bool
    service_overrun: bool
    defer_soc_redecision: bool
    should_decide: bool


def evaluate_ev_decision_cadence(
    evidence: EvDecisionCadenceEvidence,
) -> EvDecisionCadenceEvaluation:
    """Preserve the three-minute and converging-current decision boundaries."""
    fingerprint: EvDecisionFingerprint = (
        evidence.vehicle_soc_percent,
        evidence.charge_to_full_requested,
        evidence.free_window_priority,
        evidence.current_minimum_a,
        evidence.current_maximum_a,
        evidence.current_step_a,
        evidence.limit_minimum_percent,
        evidence.limit_maximum_percent,
        evidence.limit_step_percent,
        evidence.grid_current_valid,
        evidence.actual_ev_current_valid,
    )
    interval_elapsed = (
        evidence.last_decision_at is not None
        and evidence.now - evidence.last_decision_at >= evidence.decision_interval
    )
    fingerprint_changed = fingerprint != evidence.previous_fingerprint
    only_soc_changed = (
        evidence.previous_fingerprint is not None
        and fingerprint[0] != evidence.previous_fingerprint[0]
        and fingerprint[1:] == evidence.previous_fingerprint[1:]
    )
    try:
        previous_vehicle_soc = float(evidence.previous_fingerprint[0])
    except (TypeError, ValueError):
        previous_vehicle_soc = None
    policy_limit = (
        100.0
        if evidence.charge_to_full_requested
        else evidence.configured_policy_limit_percent
    )
    current_vehicle_soc = cast(float, evidence.vehicle_soc_percent)
    soc_remains_below_policy = (
        previous_vehicle_soc is not None
        and previous_vehicle_soc < policy_limit
        and current_vehicle_soc < policy_limit
    )
    current_transition_pending = (
        evidence.in_free_window
        and evidence.allowance_guard_enabled
        and evidence.house_load_includes_ev
        and evidence.actual_ev_current_valid
        and evidence.current_step_a is not None
        and abs(evidence.requested_current_a - evidence.actual_ev_current_a)
        > evidence.current_step_a / 2
    )
    service_overrun = (
        evidence.grid_current_valid
        and evidence.service_limit_a > 0
        and evidence.grid_current_a > evidence.service_limit_a
    )
    defer_soc_redecision = (
        only_soc_changed
        and soc_remains_below_policy
        and current_transition_pending
        and not service_overrun
        and not interval_elapsed
    )
    should_decide = not evidence.in_free_window or (
        evidence.pre_free_active
        or not evidence.current_target_available
        or evidence.last_decision_at is None
        or interval_elapsed
        or (fingerprint_changed and not defer_soc_redecision)
    )
    return EvDecisionCadenceEvaluation(
        fingerprint=fingerprint,
        decision_interval_elapsed=interval_elapsed,
        fingerprint_changed=fingerprint_changed,
        only_vehicle_soc_changed=only_soc_changed,
        soc_remains_below_policy=soc_remains_below_policy,
        current_transition_pending=current_transition_pending,
        service_overrun=service_overrun,
        defer_soc_redecision=defer_soc_redecision,
        should_decide=should_decide,
    )


def evaluate_free_window_target(
    evidence: FreeWindowTargetEvidence,
) -> FreeWindowTargetEvaluation:
    """Compose retained clamps, telemetry validity and branch selection."""
    baseline = min(
        max(
            evidence.configured_baseline_a,
            evidence.physical_minimum_a,
            evidence.current_step_a,
        ),
        evidence.ceiling_a,
    )
    effective_minimum = min(
        max(evidence.configured_minimum_a, evidence.physical_minimum_a),
        evidence.ceiling_a,
    )
    policy_limit = (
        100.0
        if evidence.charge_to_full
        else evidence.configured_policy_limit_percent
    )
    below_policy = evidence.vehicle_soc_percent < policy_limit
    base = plan_free_window_current(
        FreeWindowCurrentInputs(
            in_free_window=True,
            connected=True,
            ceiling_a=evidence.ceiling_a,
            effective_minimum_a=effective_minimum,
            protected_baseline_a=baseline,
            requested_a=evidence.requested_current_a,
            service_limit_a=evidence.service_limit_a,
            service_headroom_a=evidence.service_headroom_a,
            grid_average_a=evidence.grid_average_a or 0.0,
            grid_average_valid=(
                evidence.grid_average_a is not None
                and evidence.grid_average_age_coverage_ratio >= 0.67
                and evidence.grid_average_source_valid
            ),
            actual_ev_current_a=evidence.actual_ev_current_a,
            ev_average_a=evidence.ev_average_a or 0.0,
            ev_average_source_valid=evidence.ev_average_source_valid,
            battery_soc_percent=evidence.battery_soc_percent,
            battery_full_soc_percent=evidence.battery_full_soc_percent,
            battery_charge_power_kw=evidence.battery_charge_power_kw,
            battery_charge_target_kw=evidence.battery_charge_target_kw,
            site_phase_count=evidence.site_phase_count,
            voltage_v=evidence.voltage_v,
            elapsed_minutes=evidence.elapsed_minutes,
            settle_minutes=evidence.settle_minutes,
            current_step_a=evidence.current_step_a,
            ev_priority=below_policy and evidence.ev_priority_selected,
            charge_to_full=evidence.charge_to_full,
        )
    )
    decision = (
        base
        if below_policy or evidence.charge_to_full
        else EvCurrentDecision(baseline, "policy_limit_reached")
    )
    return FreeWindowTargetEvaluation(
        decision=decision,
        base_decision=base,
        protected_baseline_a=baseline,
        effective_minimum_a=effective_minimum,
        policy_limit_percent=policy_limit,
        below_policy_limit=below_policy,
    )


@dataclass(frozen=True, slots=True)
class EvCommand:
    """One ordered, adapter-neutral Tessie command."""

    action: str
    value: float | None = None


@dataclass(frozen=True, slots=True)
class EvCommandPlan:
    """Direct-EVSE commands that already passed physical and policy bounds."""

    commands: tuple[EvCommand, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class SmartSocketStageState:
    """Transient current-staging hold while a switched supply is off."""

    target_current_a: float | None = None
    started_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SmartSocketStageTransition:
    """Next staging hold and the command plan permitted for this cycle."""

    state: SmartSocketStageState
    plan: EvCommandPlan


@dataclass(frozen=True, slots=True)
class SmartPathResetDecision:
    """Smart-only latch state after selecting a commissioned charge path."""

    recovery: SmartSocketRecoveryState
    stage: SmartSocketStageState
    save_required: bool = False


def reset_smart_state_for_path(
    *,
    smart_path_selected: bool,
    recovery: SmartSocketRecoveryState,
    stage: SmartSocketStageState,
) -> SmartPathResetDecision:
    """Clear smart-only latches when Direct / EVSE becomes authoritative."""
    changed = not smart_path_selected and (
        recovery != SmartSocketRecoveryState() or stage != SmartSocketStageState()
    )
    if changed:
        return SmartPathResetDecision(
            SmartSocketRecoveryState(),
            SmartSocketStageState(),
            save_required=True,
        )
    return SmartPathResetDecision(recovery, stage)


@dataclass(frozen=True, slots=True)
class DirectEvseReconciliationState:
    """Restart-safe, rate-bounded command/feedback state for one direct EVSE."""

    target_current_a: float | None = None
    target_limit_percent: float | None = None
    attempts: int = 0
    last_command_at: datetime | None = None
    phase: str = "idle"


@dataclass(frozen=True, slots=True)
class DirectEvseReconciliation:
    """One reconciliation transition and any permitted command plan."""

    state: DirectEvseReconciliationState
    plan: EvCommandPlan


@dataclass(frozen=True, slots=True)
class DirectEvseRuntimeDecision:
    """Post-reconciliation ownership and retained persistence obligations."""

    reconciliation: DirectEvseReconciliation
    outside_control_active: bool
    save_reconciliation: bool = True
    save_ownership_release: bool = False


def finalize_direct_evse_reconciliation(
    reconciliation: DirectEvseReconciliation,
    *,
    in_free_window: bool,
    outside_enabled: bool,
    outside_control_active: bool,
    outside_target_active: bool,
) -> DirectEvseRuntimeDecision:
    """Decide whether confirmed idle feedback releases outside ownership."""
    release = (
        not reconciliation.plan.commands
        and not in_free_window
        and not outside_enabled
        and outside_control_active
        and not outside_target_active
        and reconciliation.state.phase == "confirmed"
    )
    return DirectEvseRuntimeDecision(
        reconciliation=reconciliation,
        outside_control_active=False if release else outside_control_active,
        save_ownership_release=release,
    )


@dataclass(frozen=True, slots=True)
class DirectEvseObservation:
    """Live Tessie actuator state and writable metadata."""

    requested_current_a: float
    charge_limit_percent: float
    charge_switch_on: bool
    current_minimum_a: float | None
    current_maximum_a: float | None
    current_step_a: float | None
    limit_minimum_percent: float | None
    limit_maximum_percent: float | None
    limit_step_percent: float | None
    requested_current_changed_at: datetime | None = None


def physical_charging_minimum_a(
    observation: DirectEvseObservation,
) -> float | None:
    """Retain the Tessie minimum-zero fallback to one actuator step."""
    minimum = observation.current_minimum_a
    step = observation.current_step_a
    if minimum is None or step is None or step <= 0:
        return None
    return minimum if minimum > 0 else step


def charging_path_ceiling_a(
    *,
    smart_path_selected: bool,
    smart_limit_a: float,
    direct_limit_a: float,
) -> float:
    """Return the commissioned current ceiling for the selected charge path."""
    return smart_limit_a if smart_path_selected else direct_limit_a


def outside_service_ceiling_a(
    *,
    physical_ceiling_a: float,
    current_step_a: float,
    service_limit_a: float,
    reserved_headroom_a: float,
    grid_current_a: float,
    grid_current_valid: bool,
    actual_ev_current_a: float,
    actual_ev_current_valid: bool,
) -> float:
    """Bound outside charging by commissioned per-phase service headroom."""
    if service_limit_a <= 0:
        return physical_ceiling_a
    if not grid_current_valid or not actual_ev_current_valid:
        return 0.0
    non_ev_current = max(grid_current_a - actual_ev_current_a, 0.0)
    available = max(
        service_limit_a - reserved_headroom_a - non_ev_current,
        0.0,
    )
    stepped = int(available / current_step_a) * current_step_a
    return round(min(physical_ceiling_a, stepped), 3)


def outside_service_feedback_required(*, service_limit_a: float) -> bool:
    """Return whether current feedback can affect the commissioned ceiling."""
    return service_limit_a > 0


@dataclass(frozen=True, slots=True)
class SmartSocketObservation:
    """Live state needed by the explicitly selected switchable supply."""

    requested_current_a: float | None
    charge_switch_on: bool | None
    socket_on: bool
    socket_on_seconds: float
    current_maximum_a: float | None
    current_step_a: float | None


@dataclass(frozen=True, slots=True)
class SmartSocketObservationEvidence:
    """Primitive feedback used to compose the switchable-supply view."""

    now: datetime
    requested_current_a: float | None
    charge_switch_on: bool | None
    socket_state: str | None
    socket_last_changed: datetime | None
    current_maximum_a: float | None
    current_step_a: float | None


@dataclass(frozen=True, slots=True)
class SmartSocketRecoveryObservation:
    """Coherent evidence consumed by the one-shot fault recovery."""

    charging_state: str | None
    charging_state_seconds: float
    home_control_active: bool
    cloud_evidence_stable: bool
    smart_path_selected: bool
    socket_on: bool | None
    cable_connected: bool
    charge_allowed: bool
    actuator_writable: bool
    target_current_a: float
    requested_current_a: float | None
    actual_current_a: float
    vehicle_soc_percent: float
    charge_limit_percent: float
    writable_maximum_a: float | None
    charge_switch_on: bool | None


@dataclass(frozen=True, slots=True)
class SmartSocketRecoveryEvidence:
    """Primitive coherent feedback used to compose recovery observation."""

    now: datetime
    stable_seconds: float
    charging_state: str | None
    charging_last_changed: datetime | None
    at_home_state: str | None
    at_home_last_changed: datetime | None
    cable_state: str | None
    cable_last_changed: datetime | None
    cloud_charge_switch_state: str | None
    cloud_charge_switch_last_changed: datetime | None
    home_control_active: bool
    smart_path_selected: bool
    socket_on: bool | None
    target_current_a: float | None
    physical_minimum_a: float
    requested_current_a: float | None
    actual_current_a: float
    actual_current_valid: bool
    vehicle_soc_percent: float | None
    charge_limit_percent: float
    writable_maximum_a: float | None
    charge_switch_on: bool | None


def evaluate_smart_socket_observation(
    evidence: SmartSocketObservationEvidence,
) -> SmartSocketObservation | None:
    """Compose the retained socket age and actuator observation."""
    if evidence.socket_state not in {"on", "off"} or evidence.socket_last_changed is None:
        return None
    socket_on = evidence.socket_state == "on"
    socket_on_seconds = (
        max((evidence.now - evidence.socket_last_changed).total_seconds(), 0.0)
        if socket_on
        else 0.0
    )
    return SmartSocketObservation(
        requested_current_a=evidence.requested_current_a,
        charge_switch_on=evidence.charge_switch_on,
        socket_on=socket_on,
        socket_on_seconds=socket_on_seconds,
        current_maximum_a=evidence.current_maximum_a,
        current_step_a=evidence.current_step_a,
    )


def evaluate_smart_socket_recovery_observation(
    evidence: SmartSocketRecoveryEvidence,
) -> SmartSocketRecoveryObservation:
    """Compose coherent recovery eligibility without platform dependencies."""
    cloud_feedback = (
        (evidence.at_home_state, evidence.at_home_last_changed),
        (evidence.cable_state, evidence.cable_last_changed),
        (
            evidence.cloud_charge_switch_state,
            evidence.cloud_charge_switch_last_changed,
        ),
    )
    evidence_age_stable = all(
        state is not None
        and last_changed is not None
        and 0 <= (evidence.now - last_changed).total_seconds()
        and (evidence.now - last_changed).total_seconds() >= evidence.stable_seconds
        for state, last_changed in cloud_feedback
    )
    cloud_stable = bool(
        evidence_age_stable
        and evidence.at_home_state in {"home", "on"}
        and evidence.cable_state == "on"
        and evidence.cloud_charge_switch_state in {"on", "off"}
    )
    target_current = evidence.target_current_a or 0.0
    return SmartSocketRecoveryObservation(
        charging_state=evidence.charging_state,
        charging_state_seconds=(
            max(
                (evidence.now - evidence.charging_last_changed).total_seconds(),
                0.0,
            )
            if evidence.charging_last_changed is not None
            else 0.0
        ),
        home_control_active=evidence.home_control_active,
        cloud_evidence_stable=cloud_stable,
        smart_path_selected=evidence.smart_path_selected,
        socket_on=evidence.socket_on,
        cable_connected=evidence.cable_state == "on",
        charge_allowed=target_current >= evidence.physical_minimum_a,
        actuator_writable=(
            evidence.writable_maximum_a is not None
            and evidence.writable_maximum_a > 0
            and evidence.charge_switch_on is not None
        ),
        target_current_a=target_current,
        requested_current_a=evidence.requested_current_a,
        actual_current_a=(
            evidence.actual_current_a if evidence.actual_current_valid else float("nan")
        ),
        vehicle_soc_percent=(
            evidence.vehicle_soc_percent
            if evidence.vehicle_soc_percent is not None
            else float("nan")
        ),
        charge_limit_percent=evidence.charge_limit_percent,
        writable_maximum_a=evidence.writable_maximum_a,
        charge_switch_on=evidence.charge_switch_on,
    )


@dataclass(frozen=True, slots=True)
class SmartSocketRecoveryState:
    """Restart-serializable progress for one continuous no-power episode."""

    attempted: bool = False
    phase: str = "idle"
    phase_started_at: datetime | None = None
    recovery_current_a: float | None = None


@dataclass(frozen=True, slots=True)
class SmartSocketRecoveryTransition:
    """One recovery transition and its ordered commands."""

    state: SmartSocketRecoveryState
    plan: EvCommandPlan


@dataclass(frozen=True, slots=True)
class SmartSocketRecoveryRuntimeDecision:
    """Controller-facing recovery activity and persistence decision."""

    transition: SmartSocketRecoveryTransition
    active: bool
    state_changed: bool
    persistence_transition: str
    save_required: bool


def finalize_smart_socket_recovery(
    transition: SmartSocketRecoveryTransition,
    *,
    previous_state: SmartSocketRecoveryState,
) -> SmartSocketRecoveryRuntimeDecision:
    """Derive recovery ownership and save intent without controller mutation."""
    active = transition.state.phase in {
        "confirming_current",
        "confirming_socket_off",
        "power_off_dwell",
        "confirming_socket_on",
        "post_power_settle",
        "awaiting_actuator",
        "confirming_charging",
    }
    changed = transition.state != previous_state
    return SmartSocketRecoveryRuntimeDecision(
        transition=transition,
        active=active,
        state_changed=changed,
        persistence_transition=(
            "smart_recovery_state_changed" if changed else "none"
        ),
        save_required=changed,
    )


def reconcile_smart_socket_recovery(
    state: SmartSocketRecoveryState,
    observation: SmartSocketRecoveryObservation,
    *,
    now: datetime,
    physical_minimum_a: float,
    physical_ceiling_a: float,
    current_tolerance_a: float,
    idle_current_threshold_a: float,
    no_power_confirm_seconds: float,
    current_confirm_seconds: float,
    socket_confirm_seconds: float,
    power_off_seconds: float,
    post_power_settle_seconds: float,
    charging_confirm_seconds: float,
    healthy_rearm_seconds: float,
) -> SmartSocketRecoveryTransition:
    """Port the one-attempt smart-socket recovery as an explicit state machine."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("recovery time must be timezone-aware")
    timings = (
        no_power_confirm_seconds,
        current_confirm_seconds,
        socket_confirm_seconds,
        power_off_seconds,
        post_power_settle_seconds,
        charging_confirm_seconds,
        healthy_rearm_seconds,
    )
    if not all(isfinite(value) and value >= 0 for value in timings):
        raise ValueError("recovery timings must be finite and non-negative")
    if (
        physical_minimum_a <= 0
        or physical_ceiling_a < physical_minimum_a
        or not isfinite(current_tolerance_a)
        or current_tolerance_a <= 0
        or not isfinite(idle_current_threshold_a)
        or idle_current_threshold_a < 0
    ):
        raise ValueError("recovery physical limits are invalid")

    if not observation.smart_path_selected or (
        observation.charging_state == "charging"
        and observation.charging_state_seconds >= healthy_rearm_seconds
    ):
        return SmartSocketRecoveryTransition(
            SmartSocketRecoveryState(), EvCommandPlan((), "recovery_rearmed")
        )
    if state.attempted and state.phase in {"recovered", "fault"}:
        return SmartSocketRecoveryTransition(state, EvCommandPlan((), "recovery_episode_latched"))

    if state.phase == "idle":
        reason = _smart_recovery_eligibility(
            observation,
            physical_minimum_a=physical_minimum_a,
            no_power_confirm_seconds=no_power_confirm_seconds,
            idle_current_threshold_a=idle_current_threshold_a,
        )
        if reason is not None:
            return SmartSocketRecoveryTransition(state, EvCommandPlan((), reason))
        recovery_current = _smart_recovery_current(
            observation,
            physical_minimum_a=physical_minimum_a,
            physical_ceiling_a=physical_ceiling_a,
        )
        if not _recovery_current_matches(
            observation.requested_current_a,
            recovery_current,
            current_tolerance_a,
            physical_minimum_a,
        ):
            return SmartSocketRecoveryTransition(
                SmartSocketRecoveryState(True, "confirming_current", now, recovery_current),
                EvCommandPlan(
                    (EvCommand("set_charge_current", recovery_current),),
                    "recovery_current_staged",
                ),
            )
        return SmartSocketRecoveryTransition(
            SmartSocketRecoveryState(True, "confirming_socket_off", now, recovery_current),
            EvCommandPlan(
                (EvCommand("turn_off_smart_socket"),),
                "recovery_power_off_requested",
            ),
        )

    elapsed = _recovery_phase_elapsed(state, now)
    if state.phase == "confirming_current":
        if _recovery_current_matches(
            observation.requested_current_a,
            state.recovery_current_a,
            current_tolerance_a,
            physical_minimum_a,
        ):
            return SmartSocketRecoveryTransition(
                SmartSocketRecoveryState(
                    True, "confirming_socket_off", now, state.recovery_current_a
                ),
                EvCommandPlan(
                    (EvCommand("turn_off_smart_socket"),),
                    "recovery_power_off_requested",
                ),
            )
        if elapsed >= current_confirm_seconds:
            return _smart_recovery_fault(state, "recovery_current_not_confirmed")
        return SmartSocketRecoveryTransition(
            state, EvCommandPlan((), "recovery_awaiting_current_confirmation")
        )
    if state.phase == "confirming_socket_off":
        if observation.socket_on is False:
            return SmartSocketRecoveryTransition(
                SmartSocketRecoveryState(True, "power_off_dwell", now, state.recovery_current_a),
                EvCommandPlan((), "recovery_socket_off_confirmed"),
            )
        if elapsed >= socket_confirm_seconds:
            return _smart_recovery_fault(state, "recovery_socket_off_not_confirmed")
        return SmartSocketRecoveryTransition(
            state, EvCommandPlan((), "recovery_awaiting_socket_off")
        )
    if state.phase == "power_off_dwell":
        if elapsed < power_off_seconds:
            return SmartSocketRecoveryTransition(
                state, EvCommandPlan((), "recovery_power_off_dwell")
            )
        if not _smart_recovery_permissions_hold(observation):
            return _smart_recovery_fault(state, "recovery_permissions_changed")
        return SmartSocketRecoveryTransition(
            SmartSocketRecoveryState(True, "confirming_socket_on", now, state.recovery_current_a),
            EvCommandPlan(
                (EvCommand("turn_on_smart_socket"),),
                "recovery_power_on_requested",
            ),
        )
    if state.phase == "confirming_socket_on":
        if observation.socket_on is True:
            return SmartSocketRecoveryTransition(
                SmartSocketRecoveryState(True, "post_power_settle", now, state.recovery_current_a),
                EvCommandPlan((), "recovery_socket_on_confirmed"),
            )
        if elapsed >= socket_confirm_seconds:
            return _smart_recovery_fault(state, "recovery_socket_on_not_confirmed")
        return SmartSocketRecoveryTransition(
            state, EvCommandPlan((), "recovery_awaiting_socket_on")
        )
    if state.phase == "post_power_settle":
        if elapsed < post_power_settle_seconds:
            return SmartSocketRecoveryTransition(
                state, EvCommandPlan((), "recovery_post_power_settle")
            )
        if not _smart_recovery_permissions_hold(observation) or observation.socket_on is not True:
            return _smart_recovery_fault(state, "recovery_permissions_changed")
        if not observation.actuator_writable:
            return SmartSocketRecoveryTransition(
                SmartSocketRecoveryState(True, "awaiting_actuator", now, state.recovery_current_a),
                EvCommandPlan((), "recovery_awaiting_actuator"),
            )
        return _smart_recovery_restart(
            state,
            observation,
            now=now,
            physical_minimum_a=physical_minimum_a,
            physical_ceiling_a=physical_ceiling_a,
            current_tolerance_a=current_tolerance_a,
        )
    if state.phase == "awaiting_actuator":
        if not _smart_recovery_permissions_hold(observation) or observation.socket_on is not True:
            return _smart_recovery_fault(state, "recovery_permissions_changed")
        if observation.actuator_writable:
            return _smart_recovery_restart(
                state,
                observation,
                now=now,
                physical_minimum_a=physical_minimum_a,
                physical_ceiling_a=physical_ceiling_a,
                current_tolerance_a=current_tolerance_a,
            )
        if elapsed >= current_confirm_seconds:
            return _smart_recovery_fault(state, "recovery_actuator_unavailable_after_power")
        return SmartSocketRecoveryTransition(state, EvCommandPlan((), "recovery_awaiting_actuator"))
    if state.phase == "confirming_charging":
        if observation.charging_state == "charging":
            return SmartSocketRecoveryTransition(
                SmartSocketRecoveryState(True, "recovered", now, state.recovery_current_a),
                EvCommandPlan((), "recovery_charging_confirmed"),
            )
        if elapsed >= charging_confirm_seconds:
            return _smart_recovery_fault(state, "recovery_charging_not_confirmed")
        return SmartSocketRecoveryTransition(state, EvCommandPlan((), "recovery_awaiting_charging"))
    return _smart_recovery_fault(state, "recovery_state_invalid")


def _smart_recovery_eligibility(
    observation: SmartSocketRecoveryObservation,
    *,
    physical_minimum_a: float,
    no_power_confirm_seconds: float,
    idle_current_threshold_a: float,
) -> str | None:
    if observation.charging_state != "no_power":
        return "recovery_no_fault"
    if observation.charging_state_seconds < no_power_confirm_seconds:
        return "recovery_fault_not_sustained"
    if not observation.home_control_active or not observation.cloud_evidence_stable:
        return "recovery_home_evidence_unavailable"
    if not _smart_recovery_permissions_hold(observation):
        return "recovery_not_permitted"
    if observation.socket_on is not True or not observation.actuator_writable:
        return "recovery_actuator_unavailable"
    values = (
        observation.target_current_a,
        observation.actual_current_a,
        observation.vehicle_soc_percent,
        observation.charge_limit_percent,
    )
    if not all(isfinite(value) for value in values):
        return "recovery_telemetry_invalid"
    if (
        observation.target_current_a < physical_minimum_a
        or observation.actual_current_a >= idle_current_threshold_a
        or observation.vehicle_soc_percent >= observation.charge_limit_percent
    ):
        return "recovery_demand_not_confirmed"
    return None


def _smart_recovery_permissions_hold(observation: SmartSocketRecoveryObservation) -> bool:
    return (
        observation.home_control_active
        and observation.smart_path_selected
        and observation.cable_connected
        and observation.charge_allowed
    )


def _smart_recovery_restart(
    state: SmartSocketRecoveryState,
    observation: SmartSocketRecoveryObservation,
    *,
    now: datetime,
    physical_minimum_a: float,
    physical_ceiling_a: float,
    current_tolerance_a: float,
) -> SmartSocketRecoveryTransition:
    """Recompute the post-power command from the refreshed Tessie range."""
    recovery_current = _smart_recovery_current(
        observation,
        physical_minimum_a=physical_minimum_a,
        physical_ceiling_a=physical_ceiling_a,
    )
    commands: list[EvCommand] = []
    if not _recovery_current_matches(
        observation.requested_current_a,
        recovery_current,
        current_tolerance_a,
        physical_minimum_a,
    ):
        commands.append(EvCommand("set_charge_current", recovery_current))
    if observation.charge_switch_on is False:
        commands.append(EvCommand("start_charging"))
    if observation.charge_switch_on is None:
        return _smart_recovery_fault(state, "recovery_charge_switch_unavailable")
    return SmartSocketRecoveryTransition(
        SmartSocketRecoveryState(True, "confirming_charging", now, recovery_current),
        EvCommandPlan(tuple(commands), "recovery_charge_restart_requested"),
    )


def _smart_recovery_current(
    observation: SmartSocketRecoveryObservation,
    *,
    physical_minimum_a: float,
    physical_ceiling_a: float,
) -> float:
    writable = observation.writable_maximum_a
    accepted = (
        writable
        if writable is not None and isfinite(writable) and writable > 0
        else physical_ceiling_a
    )
    return round(
        max(min(observation.target_current_a, accepted, physical_ceiling_a), physical_minimum_a),
        3,
    )


def _recovery_current_matches(
    requested_current_a: float | None,
    recovery_current_a: float | None,
    tolerance_a: float,
    physical_minimum_a: float,
) -> bool:
    return (
        requested_current_a is not None
        and recovery_current_a is not None
        and isfinite(requested_current_a)
        and requested_current_a >= physical_minimum_a
        and abs(requested_current_a - recovery_current_a) < tolerance_a
    )


def _recovery_phase_elapsed(state: SmartSocketRecoveryState, now: datetime) -> float:
    if state.phase_started_at is None or state.phase_started_at > now:
        return 0.0
    return (now - state.phase_started_at).total_seconds()


def _smart_recovery_fault(
    state: SmartSocketRecoveryState, reason: str
) -> SmartSocketRecoveryTransition:
    return SmartSocketRecoveryTransition(
        SmartSocketRecoveryState(
            attempted=True,
            phase="fault",
            phase_started_at=state.phase_started_at,
            recovery_current_a=state.recovery_current_a,
        ),
        EvCommandPlan((), reason),
    )


def plan_smart_socket_commands(
    observation: SmartSocketObservation,
    *,
    target_current_a: float,
    physical_minimum_a: float,
    physical_ceiling_a: float,
    settle_seconds: float,
    charge_allowed: bool,
    in_free_window: bool,
    connected_for_planning: bool,
    power_switching_enabled: bool,
) -> EvCommandPlan:
    """Port the pilot site's staged smart-socket sequence one tick at a time.

    The explicitly configured physical rating remains authoritative when an
    unpowered connector reports a misleading or missing writable maximum.
    """
    numeric = (
        target_current_a,
        physical_minimum_a,
        physical_ceiling_a,
        settle_seconds,
        observation.socket_on_seconds,
    )
    if not all(isfinite(value) for value in numeric):
        raise ValueError("smart-socket inputs must be finite")
    if (
        target_current_a < 0
        or physical_minimum_a <= 0
        or physical_ceiling_a < physical_minimum_a
        or settle_seconds < 0
        or observation.socket_on_seconds < 0
    ):
        raise ValueError("smart-socket physical limits are invalid")
    step = observation.current_step_a
    if step is None or not isfinite(step) or step <= 0:
        return EvCommandPlan((), "smart_socket_current_step_unavailable")
    requested = observation.requested_current_a
    if requested is not None and not isfinite(requested):
        return EvCommandPlan((), "smart_socket_current_feedback_invalid")

    command_permitted = charge_allowed and target_current_a >= physical_minimum_a
    if not command_permitted:
        remove_power = (
            observation.socket_on
            and not in_free_window
            and (power_switching_enabled or not connected_for_planning)
        )
        commands = (EvCommand("turn_off_smart_socket"),) if remove_power else ()
        return EvCommandPlan(commands, "smart_socket_no_charge_command")

    writable_max = observation.current_maximum_a
    transport_cap = (
        writable_max
        if writable_max is not None and isfinite(writable_max) and writable_max > 0
        else physical_ceiling_a
    )
    transport_cap = min(transport_cap, physical_ceiling_a)
    bounded = min(target_current_a, transport_cap)

    if not observation.socket_on:
        if bounded < physical_minimum_a:
            return EvCommandPlan((), "smart_socket_staging_below_minimum")
        commands: list[EvCommand] = []
        if requested is None or abs(requested - bounded) >= step:
            commands.append(EvCommand("set_charge_current", round(bounded, 3)))
        # The source wait accepts equal or lower existing feedback after the
        # ordered set request, provided it is service-valid and within the
        # configured physical ceiling.
        if requested is not None and physical_minimum_a <= requested <= bounded:
            commands.append(EvCommand("turn_on_smart_socket"))
            return EvCommandPlan(tuple(commands), "smart_socket_staged_current_confirmed")
        if commands:
            return EvCommandPlan(tuple(commands), "smart_socket_stage_current_before_power")
        return EvCommandPlan((), "smart_socket_staged_current_unconfirmed")

    if observation.socket_on_seconds < settle_seconds:
        return EvCommandPlan((), "smart_socket_settling")
    if bounded < physical_minimum_a:
        return EvCommandPlan(
            (EvCommand("turn_off_smart_socket"),),
            "smart_socket_command_invalid_after_settle",
        )
    commands: list[EvCommand] = []
    if requested is None or abs(requested - bounded) >= step:
        commands.append(EvCommand("set_charge_current", round(bounded, 3)))
    if observation.charge_switch_on is False:
        commands.append(EvCommand("start_charging"))
    if observation.charge_switch_on is None:
        return EvCommandPlan((), "smart_socket_charge_switch_unavailable")
    return EvCommandPlan(tuple(commands), "smart_socket_ready")


def reconcile_smart_socket_stage(
    state: SmartSocketStageState,
    plan: EvCommandPlan,
    observation: SmartSocketObservation,
    *,
    now: datetime,
    current_confirm_seconds: float,
    retry_seconds: float,
) -> SmartSocketStageTransition:
    """Hold repeated staging writes while awaiting unpowered-current feedback."""
    stage_only = (
        not observation.socket_on
        and len(plan.commands) == 1
        and plan.commands[0].action == "set_charge_current"
    )
    if not stage_only:
        next_state = (
            SmartSocketStageState()
            if any(command.action == "turn_on_smart_socket" for command in plan.commands)
            else state
        )
        return SmartSocketStageTransition(next_state, plan)

    target = plan.commands[0].value
    if target != state.target_current_a or state.started_at is None:
        return SmartSocketStageTransition(SmartSocketStageState(target, now), plan)

    elapsed = (now - state.started_at).total_seconds()
    if elapsed >= retry_seconds:
        # Preserve the pilot's five-minute retry without repeating the current
        # write on every 30-second controller tick.
        return SmartSocketStageTransition(SmartSocketStageState(target, now), plan)
    reason = (
        "smart_socket_awaiting_staged_current"
        if elapsed < current_confirm_seconds
        else "smart_socket_staged_current_not_confirmed"
    )
    return SmartSocketStageTransition(state, EvCommandPlan((), reason))


def plan_direct_evse_commands(
    observation: DirectEvseObservation,
    *,
    target_current_a: float,
    target_limit_percent: float,
    physical_ceiling_a: float,
    start_allowed: bool,
    rehearsal: bool = False,
) -> EvCommandPlan:
    """Port the pilot site's direct path without adding stop/pause behavior."""
    _validate_direct_observation(
        observation, target_current_a, target_limit_percent, physical_ceiling_a
    )
    if rehearsal:
        return EvCommandPlan((), "rehearsal_mode")
    metadata = (
        observation.current_minimum_a,
        observation.current_maximum_a,
        observation.current_step_a,
        observation.limit_minimum_percent,
        observation.limit_maximum_percent,
        observation.limit_step_percent,
    )
    if any(value is None for value in metadata):
        return EvCommandPlan((), "actuator_metadata_unavailable")
    current_minimum = float(observation.current_minimum_a)
    current_maximum = float(observation.current_maximum_a)
    current_step = float(observation.current_step_a)
    limit_minimum = float(observation.limit_minimum_percent)
    limit_maximum = float(observation.limit_maximum_percent)
    limit_step = float(observation.limit_step_percent)
    if (
        current_minimum < 0
        or limit_minimum < 0
        or current_maximum <= 0
        or limit_maximum <= 0
        or current_step <= 0
        or limit_step <= 0
        or current_minimum > current_maximum
        or limit_minimum > limit_maximum
    ):
        return EvCommandPlan((), "actuator_metadata_invalid")
    bounded_current = min(target_current_a, physical_ceiling_a, current_maximum)
    bounded_current = floor(bounded_current / current_step) * current_step
    if not start_allowed or bounded_current < current_minimum:
        return EvCommandPlan((), "direct_path_not_allowed")
    bounded_limit = _clip(
        ceil(target_limit_percent / limit_step) * limit_step,
        limit_minimum,
        limit_maximum,
    )
    commands: list[EvCommand] = []
    if abs(observation.charge_limit_percent - bounded_limit) >= limit_step:
        commands.append(EvCommand("set_charge_limit", bounded_limit))
    if abs(observation.requested_current_a - bounded_current) >= current_step:
        commands.append(EvCommand("set_charge_current", round(bounded_current, 3)))
    if not observation.charge_switch_on:
        commands.append(EvCommand("start_charging"))
    return EvCommandPlan(tuple(commands), "direct_path_ready")


def direct_evse_response_matches(
    observation: DirectEvseObservation,
    *,
    target_current_a: float,
    target_limit_percent: float,
    physical_ceiling_a: float,
) -> bool:
    """Confirm current, limit and charge-switch feedback after a direct write."""
    plan = plan_direct_evse_commands(
        observation,
        target_current_a=target_current_a,
        target_limit_percent=target_limit_percent,
        physical_ceiling_a=physical_ceiling_a,
        start_allowed=True,
    )
    return plan.reason == "direct_path_ready" and not plan.commands


def direct_evse_retry_interval(attempts: int) -> timedelta:
    """Return the next write delay for a failed direct-EVSE command episode."""
    if attempts < 0:
        raise ValueError("reconciliation attempts must be non-negative")
    if attempts == 0:
        return timedelta(0)
    return DIRECT_EVSE_RETRY_INTERVALS[
        min(attempts - 1, len(DIRECT_EVSE_RETRY_INTERVALS) - 1)
    ]


def reconcile_direct_evse(
    state: DirectEvseReconciliationState,
    observation: DirectEvseObservation,
    *,
    target_current_a: float,
    target_limit_percent: float,
    physical_ceiling_a: float,
    now: datetime,
    feedback_settle_interval: timedelta = DIRECT_EVSE_FEEDBACK_SETTLE_INTERVAL,
) -> DirectEvseReconciliation:
    """Rate-bound feedback retries without abandoning a valid target."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("reconciliation time must be timezone-aware")
    if feedback_settle_interval < timedelta(0):
        raise ValueError("feedback settle interval must be non-negative")
    target_changed = (
        state.target_current_a != target_current_a
        or state.target_limit_percent != target_limit_percent
    )
    if target_changed:
        state = DirectEvseReconciliationState(
            target_current_a=target_current_a,
            target_limit_percent=target_limit_percent,
            phase="target_changed",
        )
    elif (
        state.attempts > 0
        and state.last_command_at is not None
        and state.phase == "confirmed"
        and now - state.last_command_at >= DIRECT_EVSE_RETRY_INTERVALS[-1]
    ):
        # A target that remained confirmed for the full capped interval starts
        # a fresh episode if another writer later changes it.
        state = DirectEvseReconciliationState(
            target_current_a=target_current_a,
            target_limit_percent=target_limit_percent,
            phase="cooldown_rearmed",
        )
    if direct_evse_response_matches(
        observation,
        target_current_a=target_current_a,
        target_limit_percent=target_limit_percent,
        physical_ceiling_a=physical_ceiling_a,
    ):
        return DirectEvseReconciliation(
            DirectEvseReconciliationState(
                target_current_a,
                target_limit_percent,
                state.attempts,
                state.last_command_at,
                "confirmed",
            ),
            EvCommandPlan((), "feedback_confirmed"),
        )
    retry_interval = direct_evse_retry_interval(state.attempts)
    if state.last_command_at is not None and now - state.last_command_at < retry_interval:
        return DirectEvseReconciliation(
            DirectEvseReconciliationState(
                target_current_a,
                target_limit_percent,
                state.attempts,
                state.last_command_at,
                "awaiting_feedback",
            ),
            EvCommandPlan((), "awaiting_feedback"),
        )
    plan = plan_direct_evse_commands(
        observation,
        target_current_a=target_current_a,
        target_limit_percent=target_limit_percent,
        physical_ceiling_a=physical_ceiling_a,
        start_allowed=True,
    )
    current_feedback_changed_after_command = (
        state.attempts > 0
        and state.last_command_at is not None
        and observation.requested_current_changed_at is not None
        and observation.requested_current_changed_at <= now
        and observation.requested_current_changed_at > state.last_command_at
    )
    current_feedback_is_settling = (
        current_feedback_changed_after_command
        and now - observation.requested_current_changed_at < feedback_settle_interval
        and any(command.action == "set_charge_current" for command in plan.commands)
    )
    if current_feedback_is_settling:
        return DirectEvseReconciliation(
            DirectEvseReconciliationState(
                target_current_a,
                target_limit_percent,
                state.attempts,
                state.last_command_at,
                "awaiting_stable_current_feedback",
            ),
            EvCommandPlan((), "awaiting_stable_current_feedback"),
        )
    if not plan.commands:
        return DirectEvseReconciliation(
            DirectEvseReconciliationState(
                target_current_a,
                target_limit_percent,
                state.attempts,
                state.last_command_at,
                "blocked",
            ),
            plan,
        )
    return DirectEvseReconciliation(
        DirectEvseReconciliationState(
            target_current_a,
            target_limit_percent,
            state.attempts + 1,
            now,
            "awaiting_feedback",
        ),
        plan,
    )


def plan_free_window_current(inputs: FreeWindowCurrentInputs) -> EvCurrentDecision:
    """Allocate free-window current without making FoxESS yield to the EV.

    FoxESS already enforces its physical import limit by reducing its own
    battery charge.  A grid-only EV controller therefore observes a healthy
    site current after the inverter has yielded and cannot deliver a genuine
    house-battery priority.  Below the configured battery-full threshold, use
    the missing battery charge power as an explicit claim on the shared import
    capacity.  At and above that threshold, release the claim so the EV can
    absorb capacity freed by the battery's normal BMS taper.
    """
    _validate_free_window_inputs(inputs)
    ceiling = inputs.ceiling_a
    baseline = min(inputs.protected_baseline_a, ceiling)
    bounded_request = max(min(inputs.requested_a, ceiling), baseline)
    house_hold = min(max(bounded_request, inputs.effective_minimum_a), ceiling)
    grid_target = max(inputs.service_limit_a - inputs.service_headroom_a, 0.0)
    grid_error = grid_target - inputs.grid_average_a
    ev_average_valid = inputs.ev_average_source_valid and inputs.actual_ev_current_a > 0
    raw_aligned = inputs.ev_average_a + grid_error
    stepped_aligned = floor(raw_aligned / inputs.current_step_a) * inputs.current_step_a
    bounded_aligned = max(min(stepped_aligned, ceiling), baseline)

    if not inputs.in_free_window or not inputs.connected or ceiling <= 0:
        return _decision(baseline, "inactive")
    if inputs.grid_average_a > inputs.service_limit_a:
        if ev_average_valid:
            return _decision(bounded_aligned, "service_limit_correction")
        return _decision(baseline, "service_limit_feedback_unavailable")
    if inputs.charge_to_full:
        return _decision(ceiling, "charge_to_full_priority")
    if inputs.ev_priority:
        return _decision(ceiling, "ev_priority_maximum")
    if inputs.elapsed_minutes < inputs.settle_minutes:
        return _decision(inputs.effective_minimum_a, "settling_foxess")
    if not inputs.grid_average_valid or inputs.service_limit_a <= 0:
        return _decision(inputs.effective_minimum_a, "telemetry_fallback_minimum")
    if not ev_average_valid:
        return _decision(house_hold, "ev_feedback_hold")
    battery_evidence_valid = (
        inputs.battery_soc_percent is not None
        and inputs.battery_charge_power_kw is not None
        and inputs.battery_charge_target_kw > 0
    )
    if not battery_evidence_valid:
        return _decision(
            inputs.effective_minimum_a,
            "battery_telemetry_fallback_minimum",
        )
    if inputs.battery_soc_percent >= inputs.battery_full_soc_percent:
        return _decision(ceiling, "house_battery_taper_handoff")

    accepted_battery_kw = max(inputs.battery_charge_power_kw, 0.0)
    battery_shortfall_kw = max(
        inputs.battery_charge_target_kw - accepted_battery_kw,
        0.0,
    )
    # Small conversion/loss differences should not move a whole charger step.
    battery_shortfall_kw = 0.0 if battery_shortfall_kw <= 0.25 else battery_shortfall_kw
    battery_shortfall_a = (
        battery_shortfall_kw * 1000 / (inputs.voltage_v * inputs.site_phase_count)
    )
    raw_battery_first_a = inputs.ev_average_a + grid_error - battery_shortfall_a
    stepped_battery_first_a = (
        floor(raw_battery_first_a / inputs.current_step_a) * inputs.current_step_a
    )
    bounded_battery_first_a = max(
        min(stepped_battery_first_a, ceiling),
        inputs.effective_minimum_a,
    )
    if battery_shortfall_kw == 0.0 and abs(grid_error) <= 0.5:
        return _decision(house_hold, "service_deadband_hold")
    return _decision(
        bounded_battery_first_a,
        "house_battery_priority",
    )


@dataclass(frozen=True, slots=True)
class ChargeLimitInputs:
    """Inputs for the separate policy-limit and anti-pause actuator target."""

    connected: bool
    policy_limit_percent: float
    current_limit_percent: float
    vehicle_soc_percent: float | None
    protected_baseline_required: bool
    direct_limit_headroom_percent: float
    minimum_percent: float
    maximum_percent: float
    step_percent: float
    charge_to_full: bool = False


@dataclass(frozen=True, slots=True)
class GeneralChargeLimitEvidence:
    """Policy, actuator and retry evidence for limit-only reconciliation."""

    charge_to_full: bool
    learned_limit_percent: float
    current_limit_percent: float
    vehicle_soc_percent: float
    protected_baseline_required: bool
    direct_limit_headroom_percent: float
    minimum_percent: float
    maximum_percent: float
    step_percent: float
    previous_write_fingerprint: tuple[float, float] | None


@dataclass(frozen=True, slots=True)
class GeneralChargeLimitDecision:
    """One limit-only target, command and deferred fingerprint transition."""

    target_limit_percent: float
    reason: str
    command_plan: EvCommandPlan
    proposed_write_fingerprint: tuple[float, float] | None
    fingerprint_transition: Literal["clear", "retain", "set_on_execute"]


def plan_charge_limit_target(inputs: ChargeLimitInputs) -> float:
    """Preserve anti-pause headroom without overriding the 90% safety ceiling."""
    _validate_charge_limit_inputs(inputs)
    maximum = (
        inputs.maximum_percent
        if inputs.charge_to_full
        else min(inputs.maximum_percent, NON_OVERRIDE_CHARGE_LIMIT_MAX_PERCENT)
    )
    if not inputs.connected:
        return round(min(inputs.current_limit_percent, maximum), 3)
    policy = _clip(inputs.policy_limit_percent, inputs.minimum_percent, maximum)
    if not inputs.protected_baseline_required or inputs.vehicle_soc_percent is None:
        return round(min(policy, maximum), 3)
    raw_guard = inputs.vehicle_soc_percent + inputs.direct_limit_headroom_percent
    stepped_guard = ceil(raw_guard / inputs.step_percent) * inputs.step_percent
    guard = _clip(stepped_guard, inputs.minimum_percent, maximum)
    return round(min(max(policy, guard), maximum), 3)


def evaluate_general_charge_limit(
    evidence: GeneralChargeLimitEvidence,
) -> GeneralChargeLimitDecision:
    """Plan one general-limit write without mutating the facade retry latch."""
    policy = (
        evidence.maximum_percent
        if evidence.charge_to_full
        else evidence.learned_limit_percent
    )
    target = plan_charge_limit_target(
        ChargeLimitInputs(
            connected=True,
            policy_limit_percent=policy,
            current_limit_percent=evidence.current_limit_percent,
            vehicle_soc_percent=evidence.vehicle_soc_percent,
            protected_baseline_required=evidence.protected_baseline_required,
            direct_limit_headroom_percent=evidence.direct_limit_headroom_percent,
            minimum_percent=evidence.minimum_percent,
            maximum_percent=evidence.maximum_percent,
            step_percent=evidence.step_percent,
            charge_to_full=evidence.charge_to_full,
        )
    )
    if abs(target - evidence.current_limit_percent) < evidence.step_percent:
        return GeneralChargeLimitDecision(
            target,
            "outside_window_general_limit_confirmed",
            EvCommandPlan((), "outside_window_general_limit_confirmed"),
            None,
            "clear",
        )
    fingerprint = (target, evidence.current_limit_percent)
    if fingerprint == evidence.previous_write_fingerprint:
        return GeneralChargeLimitDecision(
            target,
            "outside_window_general_limit_awaiting_feedback",
            EvCommandPlan((), "outside_window_general_limit_awaiting_feedback"),
            fingerprint,
            "retain",
        )
    return GeneralChargeLimitDecision(
        target,
        "general_limit",
        EvCommandPlan((EvCommand("set_charge_limit", target),), "general_limit"),
        fingerprint,
        "set_on_execute",
    )


@dataclass(frozen=True, slots=True)
class AllowanceCeilingInputs:
    """Configurable whole-site allowance extension applied after base policy."""

    base_current_a: float
    protected_baseline_a: float
    minimum_charge_a: float
    current_step_a: float
    voltage_v: float
    phase_count: int
    site_service_limit_a: float
    site_voltage_v: float
    site_phase_count: int
    remaining_window_hours: float
    allowance_kwh: float
    imported_in_window_kwh: float | None
    projected_other_import_kwh: float
    projected_ev_energy_kwh: float
    safety_margin_kwh: float = 0.0


@dataclass(frozen=True, slots=True)
class AllowanceProjectionInputs:
    """Primitive evidence and policy used by the whole-site allowance guard."""

    base_current_a: float
    protected_baseline_a: float
    minimum_charge_a: float
    current_step_a: float
    stored_energy_kwh: float | None
    vehicle_soc_percent: float | None
    vehicle_target_soc_percent: float
    vehicle_charge_efficiency_percent: float
    battery_capacity_kwh: float
    battery_soc_percent: float | None
    battery_target_percent: float
    battery_charge_efficiency_percent: float
    house_load_kw: float | None
    house_load_includes_ev: bool
    actual_ev_current_a: float
    actual_ev_current_valid: bool
    ev_voltage_v: float
    ev_phase_count: int
    site_service_limit_a: float
    site_phase_count: int
    remaining_window_hours: float
    allowance_kwh: float
    imported_in_window_kwh: float | None
    safety_margin_kwh: float


@dataclass(frozen=True, slots=True)
class AllowanceProjectionResult:
    """Allowance decision plus the diagnostics underpinning its projection."""

    decision: EvCurrentDecision | None
    house_load_kw: float | None
    ev_power_kw: float | None


def evaluate_allowance_projection(
    inputs: AllowanceProjectionInputs,
) -> AllowanceProjectionResult:
    """Compose retained EV, battery and house projections without HA state."""
    if (
        inputs.stored_energy_kwh is None
        or inputs.vehicle_soc_percent is None
        or inputs.battery_soc_percent is None
        or inputs.house_load_kw is None
    ):
        return AllowanceProjectionResult(None, None, None)

    house_load_kw = inputs.house_load_kw
    ev_power_kw = None
    if inputs.house_load_includes_ev:
        if not inputs.actual_ev_current_valid:
            return AllowanceProjectionResult(None, None, None)
        try:
            house_load_kw = house_load_excluding_ev_kw(
                house_load_kw=inputs.house_load_kw,
                actual_ev_current_a=inputs.actual_ev_current_a,
                ev_voltage_v=inputs.ev_voltage_v,
                ev_phase_count=inputs.ev_phase_count,
            )
        except ValueError:
            return AllowanceProjectionResult(None, None, None)
        ev_power_kw = round(
            inputs.actual_ev_current_a
            * inputs.ev_voltage_v
            * inputs.ev_phase_count
            / 1000,
            3,
        )

    try:
        ev_need = estimate_vehicle_energy_to_target_kwh(
            stored_energy_kwh=inputs.stored_energy_kwh,
            current_soc_percent=inputs.vehicle_soc_percent,
            target_soc_percent=inputs.vehicle_target_soc_percent,
            charge_efficiency_percent=inputs.vehicle_charge_efficiency_percent,
        )
        other = estimate_other_free_window_import_kwh(
            battery_capacity_kwh=inputs.battery_capacity_kwh,
            battery_soc_percent=inputs.battery_soc_percent,
            battery_target_percent=inputs.battery_target_percent,
            battery_charge_efficiency_percent=(
                inputs.battery_charge_efficiency_percent
            ),
            house_load_kw=house_load_kw,
            remaining_window_hours=inputs.remaining_window_hours,
        )
        decision = apply_daily_allowance_ceiling(
            AllowanceCeilingInputs(
                base_current_a=inputs.base_current_a,
                protected_baseline_a=min(
                    inputs.protected_baseline_a,
                    inputs.base_current_a,
                ),
                minimum_charge_a=inputs.minimum_charge_a,
                current_step_a=inputs.current_step_a,
                voltage_v=inputs.ev_voltage_v,
                phase_count=inputs.ev_phase_count,
                site_service_limit_a=inputs.site_service_limit_a,
                site_voltage_v=inputs.ev_voltage_v,
                site_phase_count=inputs.site_phase_count,
                remaining_window_hours=inputs.remaining_window_hours,
                allowance_kwh=inputs.allowance_kwh,
                imported_in_window_kwh=inputs.imported_in_window_kwh,
                projected_other_import_kwh=other,
                projected_ev_energy_kwh=ev_need,
                safety_margin_kwh=inputs.safety_margin_kwh,
            )
        )
    except ValueError:
        decision = None
    return AllowanceProjectionResult(decision, house_load_kw, ev_power_kw)


def apply_daily_allowance_ceiling(inputs: AllowanceCeilingInputs) -> EvCurrentDecision:
    """Cap only sessions projected to exceed the configured whole-site allowance.

    This is intentionally not an even-spread charging algorithm.  If the
    projected house, battery and EV energy fits, the canonical current passes
    through unchanged.  Pacing begins only when the complete projection would
    exceed the configured allowance.
    """
    _validate_allowance_inputs(inputs)
    baseline = min(inputs.protected_baseline_a, inputs.base_current_a)
    if inputs.imported_in_window_kwh is None:
        return _decision(baseline, "allowance_meter_unavailable")
    maximum_remaining_site_import = (
        inputs.site_service_limit_a
        * inputs.site_voltage_v
        * inputs.site_phase_count
        / 1000
        * inputs.remaining_window_hours
    )
    if (
        inputs.imported_in_window_kwh + maximum_remaining_site_import + inputs.safety_margin_kwh
        <= inputs.allowance_kwh
    ):
        return _decision(inputs.base_current_a, "allowance_physically_unreachable")
    projected_total = (
        inputs.imported_in_window_kwh
        + inputs.projected_other_import_kwh
        + inputs.projected_ev_energy_kwh
        + inputs.safety_margin_kwh
    )
    if projected_total <= inputs.allowance_kwh:
        return _decision(inputs.base_current_a, "allowance_not_constraining")

    ev_budget = max(
        inputs.allowance_kwh
        - inputs.imported_in_window_kwh
        - inputs.projected_other_import_kwh
        - inputs.safety_margin_kwh,
        0.0,
    )
    if inputs.remaining_window_hours <= 0 or ev_budget <= 0:
        return _decision(baseline, "allowance_exhausted")
    average_power_kw = ev_budget / inputs.remaining_window_hours
    raw_cap_a = average_power_kw * 1000 / (inputs.voltage_v * inputs.phase_count)
    stepped_cap_a = floor(raw_cap_a / inputs.current_step_a) * inputs.current_step_a
    cap = min(stepped_cap_a, inputs.base_current_a)
    if cap < inputs.minimum_charge_a:
        return _decision(baseline, "allowance_below_charger_minimum")
    return _decision(max(cap, baseline), "allowance_pacing")


def estimate_vehicle_energy_to_target_kwh(
    *,
    stored_energy_kwh: float,
    current_soc_percent: float,
    target_soc_percent: float,
    charge_efficiency_percent: float,
) -> float:
    """Port the pilot site's live-capacity model and estimate wall energy to target."""
    _validate_energy_projection(
        stored_energy_kwh,
        current_soc_percent,
        target_soc_percent,
        charge_efficiency_percent,
    )
    if current_soc_percent <= 0:
        raise ValueError("vehicle SOC must be positive to infer usable capacity")
    if target_soc_percent <= current_soc_percent:
        return 0.0
    usable_capacity = stored_energy_kwh / (current_soc_percent / 100)
    pack_energy = usable_capacity * (target_soc_percent - current_soc_percent) / 100
    return round(pack_energy / (charge_efficiency_percent / 100), 3)


def estimate_other_free_window_import_kwh(
    *,
    battery_capacity_kwh: float,
    battery_soc_percent: float,
    battery_target_percent: float,
    battery_charge_efficiency_percent: float,
    house_load_kw: float,
    remaining_window_hours: float,
) -> float:
    """Estimate remaining non-EV import from explicit battery and house inputs."""
    _validate_energy_projection(
        battery_capacity_kwh,
        battery_soc_percent,
        battery_target_percent,
        battery_charge_efficiency_percent,
        house_load_kw,
        remaining_window_hours,
    )
    if battery_soc_percent > 100 or battery_target_percent > 100:
        raise ValueError("battery SOC and target cannot exceed 100 percent")
    pack_gap = battery_capacity_kwh * max(battery_target_percent - battery_soc_percent, 0.0) / 100
    battery_wall_energy = pack_gap / (battery_charge_efficiency_percent / 100)
    house_energy = house_load_kw * remaining_window_hours
    return round(battery_wall_energy + house_energy, 3)


def house_load_excluding_ev_kw(
    *,
    house_load_kw: float,
    actual_ev_current_a: float,
    ev_voltage_v: float,
    ev_phase_count: int,
) -> float:
    """Remove measured EV power once from a whole-house load reading."""
    values = (house_load_kw, actual_ev_current_a, ev_voltage_v, ev_phase_count)
    if not all(isfinite(value) for value in values):
        raise ValueError("house and EV topology inputs must be finite")
    if house_load_kw < 0 or actual_ev_current_a < 0 or ev_voltage_v <= 0:
        raise ValueError("house and EV topology inputs are invalid")
    if ev_phase_count not in {1, 2, 3}:
        raise ValueError("EV phase count must be 1, 2, or 3")
    ev_power_kw = actual_ev_current_a * ev_voltage_v * ev_phase_count / 1000
    return round(max(house_load_kw - ev_power_kw, 0.0), 3)


def _decision(current_a: float, phase: str) -> EvCurrentDecision:
    return EvCurrentDecision(round(max(current_a, 0.0), 3), phase)


def _validate_free_window_inputs(inputs: FreeWindowCurrentInputs) -> None:
    values = (
        inputs.ceiling_a,
        inputs.effective_minimum_a,
        inputs.protected_baseline_a,
        inputs.requested_a,
        inputs.service_limit_a,
        inputs.service_headroom_a,
        inputs.actual_ev_current_a,
        inputs.ev_average_a,
        inputs.battery_full_soc_percent,
        inputs.battery_charge_target_kw,
        inputs.site_phase_count,
        inputs.voltage_v,
        inputs.elapsed_minutes,
        inputs.settle_minutes,
        inputs.current_step_a,
    )
    if not all(isfinite(value) for value in (*values, inputs.grid_average_a)):
        raise ValueError("EV current inputs must be finite")
    if any(value < 0 for value in values) or inputs.current_step_a <= 0:
        raise ValueError("EV current inputs must be non-negative with a positive step")
    optional_values = (inputs.battery_soc_percent, inputs.battery_charge_power_kw)
    if not all(value is None or isfinite(value) for value in optional_values):
        raise ValueError("battery-priority inputs must be finite when supplied")
    if not 0 <= inputs.battery_full_soc_percent <= 100:
        raise ValueError("battery-full threshold must be between zero and 100")
    if inputs.battery_soc_percent is not None and not 0 <= inputs.battery_soc_percent <= 100:
        raise ValueError("battery SoC must be between zero and 100")
    if inputs.site_phase_count not in {1, 2, 3} or inputs.voltage_v <= 0:
        raise ValueError("site phase count and voltage must describe a valid supply")
    if inputs.protected_baseline_a > inputs.ceiling_a:
        raise ValueError("protected baseline cannot exceed the physical ceiling")
    if inputs.effective_minimum_a > inputs.ceiling_a:
        raise ValueError("effective minimum cannot exceed the physical ceiling")


def _validate_charge_limit_inputs(inputs: ChargeLimitInputs) -> None:
    values = (
        inputs.policy_limit_percent,
        inputs.current_limit_percent,
        inputs.direct_limit_headroom_percent,
        inputs.minimum_percent,
        inputs.maximum_percent,
        inputs.step_percent,
    )
    if inputs.vehicle_soc_percent is not None:
        values += (inputs.vehicle_soc_percent,)
    if not all(isfinite(value) for value in values):
        raise ValueError("charge-limit inputs must be finite")
    if inputs.step_percent <= 0 or inputs.minimum_percent > inputs.maximum_percent:
        raise ValueError("charge-limit range must be ordered with a positive step")


def _validate_allowance_inputs(inputs: AllowanceCeilingInputs) -> None:
    values = (
        inputs.base_current_a,
        inputs.protected_baseline_a,
        inputs.minimum_charge_a,
        inputs.current_step_a,
        inputs.voltage_v,
        inputs.site_service_limit_a,
        inputs.site_voltage_v,
        inputs.remaining_window_hours,
        inputs.allowance_kwh,
        inputs.projected_other_import_kwh,
        inputs.projected_ev_energy_kwh,
        inputs.safety_margin_kwh,
    )
    if inputs.imported_in_window_kwh is not None:
        values += (inputs.imported_in_window_kwh,)
    if not all(isfinite(value) for value in values) or any(value < 0 for value in values):
        raise ValueError("allowance inputs must be finite and non-negative")
    if (
        inputs.current_step_a <= 0
        or inputs.voltage_v <= 0
        or inputs.phase_count < 1
        or inputs.site_service_limit_a <= 0
        or inputs.site_voltage_v <= 0
        or inputs.site_phase_count < 1
    ):
        raise ValueError("allowance topology and current step must be positive")
    if inputs.protected_baseline_a > inputs.base_current_a:
        raise ValueError("allowance baseline cannot exceed the base current")


def _validate_energy_projection(*values: float) -> None:
    if not all(isfinite(value) for value in values) or any(value < 0 for value in values):
        raise ValueError("energy projection inputs must be finite and non-negative")
    efficiency = values[3]
    if efficiency <= 0 or efficiency > 100:
        raise ValueError("charge efficiency must be above zero and at most 100 percent")


def _validate_direct_observation(
    observation: DirectEvseObservation,
    target_current_a: float,
    target_limit_percent: float,
    physical_ceiling_a: float,
) -> None:
    required = (
        observation.requested_current_a,
        observation.charge_limit_percent,
        target_current_a,
        target_limit_percent,
        physical_ceiling_a,
    )
    optional = (
        observation.current_minimum_a,
        observation.current_maximum_a,
        observation.current_step_a,
        observation.limit_minimum_percent,
        observation.limit_maximum_percent,
        observation.limit_step_percent,
    )
    if not all(isfinite(value) for value in required) or any(value < 0 for value in required):
        raise ValueError("direct-EVSE values must be finite and non-negative")
    if not all(value is None or isfinite(value) for value in optional):
        raise ValueError("direct-EVSE metadata must be finite when present")


def _clip(value: float, minimum: float, maximum: float) -> float:
    return round(max(min(value, maximum), minimum), 3)
