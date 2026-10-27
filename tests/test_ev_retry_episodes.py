"""Sanitized retry, physical-ACK and additive-store lifecycle regressions."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.ev import (
    DirectEvseCurrentFeedback,
    DirectEvseCurrentProof,
    DirectEvseObservation,
    DirectEvseReconciliationState,
    DirectEvseRetryState,
    EvCommand,
    reconcile_direct_evse,
    record_direct_evse_current_completion,
    settle_direct_evse_dispatch,
)
from custom_components.home_energy_orchestrator.planner.ev_persistence import (
    DailyBackfillPersistenceState,
    EvPersistenceState,
)

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)
OBSERVATION = DirectEvseObservation(3, 78, True, 0, 16, 1, 50, 100, 1)
BINDING = "sanitized-vehicle-and-actuator-binding"


def run(state, *, seconds=0, requested=3, actual=None, stamp=None, binding=BINDING,
        observation=None, target=1, limit=78, ceiling=15, **kwargs):
    now = NOW + timedelta(seconds=seconds)
    observation = observation or replace(OBSERVATION, requested_current_a=requested)
    feedback = None if actual is None else DirectEvseCurrentFeedback(
        binding, stamp or now, requested, actual,
    )
    return reconcile_direct_evse(
        state, observation, target_current_a=target, target_limit_percent=limit,
        physical_ceiling_a=ceiling, now=now, current_feedback=feedback,
        current_feedback_max_age_seconds=90, **kwargs,
    )


def pending(*, attempts=7, age=60, target=1, limit=78, start_attempts=0):
    last = NOW - timedelta(seconds=age)
    return DirectEvseReconciliationState(
        target, limit, attempts, last, "awaiting_feedback",
        DirectEvseRetryState(target, attempts, last), DirectEvseRetryState(limit),
        DirectEvseRetryState(1, start_attempts, last if start_attempts else None),
        (target, 0, 1),
    )


def armed():
    state = record_direct_evse_current_completion(
        pending(age=120), completed_at=NOW - timedelta(seconds=90), binding=BINDING,
    )
    first = run(state, seconds=-60, requested=1, actual=1)
    second = run(first.state, seconds=-30, requested=1, actual=1)
    assert second.state.current_proof.armed
    return second.state


@pytest.mark.parametrize("limit", [79, 80, 90, 95, 100])
def test_limit_edits_do_not_rearm_the_current_channel(limit):
    state = pending()
    result = run(state, limit=limit)
    assert result.plan.commands == (EvCommand("set_charge_limit", limit),)
    assert result.state.current_retry == state.current_retry
    assert result.state.limit_retry.attempts == 1


@pytest.mark.parametrize("seconds", [1, 29, 30, 60, 1799])
def test_optimistic_matching_publications_never_reset_current_history(seconds):
    state = pending(age=0)
    echo = run(state, seconds=seconds, requested=1)
    assert echo.state.phase == "confirmed"  # Setting status, not a physical ACK.
    assert echo.state.current_retry == state.current_retry
    assert not echo.state.current_proof.armed
    reverted = run(echo.state, seconds=seconds, requested=3)
    assert not reverted.plan.commands


def test_requested_confirmation_at_capped_interval_does_not_reset_history():
    state = pending(age=1800)
    echo = run(state, requested=1)
    reverted = run(echo.state)
    assert reverted.state.current_retry.attempts == 8


@pytest.mark.parametrize("target,ceiling", [(20, 15), (21, 15), (21, 16)])
def test_unchanged_effective_current_ceiling_does_not_reset(target, ceiling):
    state = run(DirectEvseReconciliationState(), requested=1, target=20, ceiling=16).state
    result = run(state, seconds=1, requested=1, target=target, ceiling=ceiling)
    if ceiling == 15:
        assert result.state.current_retry.target == 15
    else:
        assert result.state.current_retry.target == 16
        assert result.state.current_retry.attempts == 1
        assert not result.plan.commands


def test_legacy_raw_current_and_limit_migrate_by_effective_targets():
    legacy = DirectEvseReconciliationState(20, 91, 7, NOW, "confirmed")
    obs = replace(OBSERVATION, current_maximum_a=15, limit_step_percent=5)
    result = run(legacy, observation=obs, target=21, limit=92)
    assert result.state.current_retry == DirectEvseRetryState(15, 7, NOW)
    assert result.state.limit_retry == DirectEvseRetryState(95, 7, NOW)
    assert not result.plan.commands
    assert not result.state.current_proof.armed


def test_source_measurement_must_follow_completed_current_service():
    state = record_direct_evse_current_completion(pending(), completed_at=NOW, binding=BINDING)
    at_receipt = run(state, requested=1, actual=1)
    repeat = run(at_receipt.state, seconds=30, requested=1, actual=1, stamp=NOW)
    assert not repeat.state.current_proof.armed
    first = run(repeat.state, seconds=31, requested=1, actual=1)
    before_boundary = run(first.state, seconds=60, requested=1, actual=1)
    assert not before_boundary.state.current_proof.armed
    boundary = run(before_boundary.state, seconds=61, requested=1, actual=1)
    assert boundary.state.current_proof.armed


def test_genuine_new_override_gets_one_prompt_reducing_correction():
    state = armed()
    result = run(state, requested=3, actual=2)
    assert result.plan.commands == (EvCommand("set_charge_current", 1),)
    assert result.state.current_retry.attempts == 1
    assert result.state.current_proof == DirectEvseCurrentProof()
    waiting = run(result.state, seconds=1, requested=3, actual=2)
    assert not waiting.plan.commands
    next_retry = run(waiting.state, seconds=30, requested=3, actual=2)
    assert next_retry.state.current_retry.attempts == 2


def test_new_override_does_not_wait_for_ha_number_settle_clock():
    obs = replace(OBSERVATION, requested_current_changed_at=NOW)
    result = run(armed(), actual=2, observation=obs)
    assert result.plan.commands == (EvCommand("set_charge_current", 1),)


@pytest.mark.parametrize("requested,actual", [(1, 2), (1, 3), (3, 2)])
def test_stuck_physical_current_never_earns_repeated_rapid_rearms(requested, actual):
    state = record_direct_evse_current_completion(pending(age=0), completed_at=NOW, binding=BINDING)
    for seconds in range(30, 1800, 30):
        result = run(state, seconds=seconds, requested=requested, actual=actual)
        assert not result.plan.commands
        assert not result.state.current_proof.armed
        state = result.state
    result = run(state, seconds=1800, requested=requested, actual=actual)
    assert result.plan.commands == (EvCommand("set_charge_current", 1),)
    assert result.state.current_retry.attempts == 8


def test_lower_requested_override_or_physical_taper_never_accelerates_increase():
    state = armed()
    result = run(state, requested=0, actual=0)
    assert not result.plan.commands
    assert result.state.current_retry.attempts == 7


def test_repeated_measurement_and_out_of_order_divergence_cannot_consume_token():
    state = armed()
    old = run(state, requested=3, actual=2, stamp=NOW - timedelta(seconds=31))
    assert not old.plan.commands
    assert old.state.current_proof.armed
    current = run(old.state, requested=3, actual=2)
    assert current.plan.commands == (EvCommand("set_charge_current", 1),)


@pytest.mark.parametrize("change", [
    {"binding": "different-vehicle"}, {"measured_at": NOW + timedelta(seconds=1)},
    {"measured_at": NOW.replace(tzinfo=None)}, {"actual_current_a": True},
    {"actual_current_a": float("nan")}, {"actual_current_a": float("inf")},
    {"actual_current_a": 10**400}, {"requested_current_a": 2}, {"binding": ""},
])
def test_invalid_or_rebound_source_cannot_bypass_backoff(change):
    feedback = replace(DirectEvseCurrentFeedback(BINDING, NOW, 3, 2), **change)
    result = reconcile_direct_evse(
        armed(), OBSERVATION, target_current_a=1, target_limit_percent=78,
        physical_ceiling_a=15, now=NOW, current_feedback=feedback,
        current_feedback_max_age_seconds=90,
    )
    assert not result.plan.commands
    assert result.state.current_retry.attempts == 7


def test_gapped_candidate_needs_another_full_stable_span():
    state = record_direct_evse_current_completion(
        pending(age=120), completed_at=NOW - timedelta(seconds=90), binding=BINDING,
    )
    first = run(state, seconds=-60, requested=1, actual=1)
    after_gap = run(first.state, seconds=31, requested=1, actual=1)
    assert not after_gap.state.current_proof.armed
    settled = run(after_gap.state, seconds=61, requested=1, actual=1)
    assert settled.state.current_proof.armed


def test_limit_changes_preserve_genuine_current_acknowledgement():
    state = armed()
    limited = run(state, requested=1, actual=1, limit=90)
    assert limited.plan.commands == (EvCommand("set_charge_limit", 90),)
    assert limited.state.current_proof.armed
    assert limited.state.current_retry == state.current_retry
    override = run(limited.state, seconds=1, requested=3, actual=2, limit=90)
    assert override.plan.commands == (EvCommand("set_charge_current", 1),)


@pytest.mark.parametrize("binding", [None, "", "x" * 257])
def test_completion_without_exact_binding_cannot_arm(binding):
    state = record_direct_evse_current_completion(pending(), completed_at=NOW, binding=binding)
    one = run(state, seconds=30, requested=1, actual=1)
    two = run(one.state, seconds=60, requested=1, actual=1)
    assert not two.state.current_proof.armed


def test_current_attempt_invalidates_old_completion_before_dispatch():
    state = armed()
    result = run(state, requested=3, actual=2)
    # An interrupted/failed dispatch has no receipt, despite later cached values.
    one = run(result.state, seconds=30, requested=1, actual=1)
    two = run(one.state, seconds=60, requested=1, actual=1)
    assert not two.state.current_proof.armed


def test_off_start_retry_does_not_reset_on_percentage_changes():
    state = pending(age=10, start_attempts=7)
    obs = replace(OBSERVATION, requested_current_a=1, charge_switch_on=False)
    result = run(state, observation=obs, limit=90)
    assert result.plan.commands == (EvCommand("set_charge_limit", 90),)
    assert result.state.start_retry == state.start_retry
    assert result.state.current_retry == state.current_retry
    assert not result.state.current_proof.armed


def test_genuine_running_to_off_earns_one_prompt_start_not_repeated_starts():
    state = replace(armed(), start_retry=DirectEvseRetryState(1, 7, NOW))
    obs = replace(OBSERVATION, requested_current_a=1, charge_switch_on=False)
    first = run(state, requested=1, actual=0, observation=obs)
    assert first.plan.commands == (EvCommand("start_charging"),)
    second = run(first.state, seconds=1, observation=obs)
    assert not second.plan.commands
    assert second.state.start_retry.attempts == 1


def test_optimistic_off_echo_does_not_reset_start_retry():
    state = replace(armed(), start_retry=DirectEvseRetryState(1, 7, NOW))
    obs = replace(OBSERVATION, requested_current_a=1, charge_switch_on=False)
    result = run(state, observation=obs)
    assert not result.plan.commands
    assert result.state.start_retry == state.start_retry
    assert not result.state.current_proof.armed


@pytest.mark.parametrize("restore_after", [None, "off", "first_on"])
def test_start_only_preserves_receipt_but_requires_new_running_dwell(restore_after):
    state = replace(armed(), start_retry=DirectEvseRetryState(1, 7, NOW))
    obs = replace(OBSERVATION, requested_current_a=1, charge_switch_on=False)
    stopped = run(state, requested=1, actual=0, observation=obs)
    assert stopped.plan.commands == (EvCommand("start_charging"),)
    assert stopped.state.current_retry == state.current_retry
    proof = stopped.state.current_proof
    assert proof.binding == BINDING
    assert proof.completed_at == state.current_proof.completed_at
    assert proof.seen_at == NOW
    assert not proof.armed and proof.stable_since is None and proof.acknowledged_at is None
    if restore_after == "off":
        stopped = replace(stopped, state=EvPersistenceState.from_payload(
            EvPersistenceState(restored_at=NOW, reconciliation=stopped.state).to_payload(), NOW,
        ).reconciliation)
    # An ON report of the same provider frame does not backdate the new dwell.
    echoed_on = run(stopped.state, seconds=29, requested=1, actual=1, stamp=NOW)
    assert echoed_on.state.current_proof.stable_since is None
    first_on = run(echoed_on.state, seconds=30, requested=1, actual=1)
    assert not first_on.state.current_proof.armed
    if restore_after == "first_on":
        first_on = replace(first_on, state=EvPersistenceState.from_payload(
            EvPersistenceState(
                restored_at=NOW + timedelta(seconds=30), reconciliation=first_on.state,
            ).to_payload(), NOW + timedelta(seconds=30),
        ).reconciliation)
    before = run(first_on.state, seconds=59, requested=1, actual=1)
    assert not before.state.current_proof.armed
    settled = run(before.state, seconds=60, requested=1, actual=1)
    assert settled.state.current_proof.armed
    override = run(settled.state, seconds=61, requested=3, actual=2)
    assert override.plan.commands == (EvCommand("set_charge_current", 1),)
    assert override.state.current_retry.attempts == 1


def test_repeated_connected_off_frames_preserve_receipt_without_rearming_start():
    state = replace(armed(), start_retry=DirectEvseRetryState(1, 7, NOW))
    obs = replace(OBSERVATION, requested_current_a=1, charge_switch_on=False)
    first = run(state, requested=1, actual=0, observation=obs)
    repeated = run(first.state, seconds=1, requested=1, actual=0, stamp=NOW, observation=obs)
    assert not repeated.plan.commands
    assert repeated.state.current_proof == first.state.current_proof
    later = run(repeated.state, seconds=2, requested=1, actual=0, observation=obs)
    assert not later.plan.commands
    assert later.state.start_retry == first.state.start_retry
    assert later.state.current_proof.completed_at == state.current_proof.completed_at
    assert later.state.current_proof.seen_at == NOW + timedelta(seconds=2)


def test_same_clock_optimistic_off_cannot_rearm_start():
    state = replace(armed(), start_retry=DirectEvseRetryState(1, 7, NOW))
    obs = replace(OBSERVATION, requested_current_a=1, charge_switch_on=False)
    result = run(
        state, requested=1, actual=0, observation=obs,
        stamp=state.current_proof.seen_at,
    )
    assert not result.plan.commands
    assert result.state.start_retry == state.start_retry
    assert not result.state.current_proof.armed


def all_actions():
    state = pending(age=1800, start_attempts=7)
    obs = replace(OBSERVATION, charge_switch_on=False)
    result = run(state, observation=obs, limit=90)
    assert result.plan.commands == (
        EvCommand("set_charge_limit", 90), EvCommand("set_charge_current", 1),
        EvCommand("start_charging"),
    )
    return state, result


def test_failed_limit_does_not_consume_known_uninvoked_current_or_start():
    previous, result = all_actions()
    settled = settle_direct_evse_dispatch(result, invoked_actions=("set_charge_limit",))
    assert settled.current_retry == previous.current_retry
    assert settled.start_retry == previous.start_retry
    assert settled.limit_retry == DirectEvseRetryState(90, 1, NOW)
    assert settled.attempts == 7 and settled.last_command_at == NOW
    # Partial delivery of the current plan is not completion of a current call.
    assert settled.current_proof.completed_at is None


def test_invoked_current_timeout_retains_cooldown_but_uninvoked_start_does_not():
    previous, result = all_actions()
    settled = settle_direct_evse_dispatch(
        result, invoked_actions=("set_charge_limit", "set_charge_current"),
    )
    assert settled.current_retry == DirectEvseRetryState(1, 8, NOW)
    assert settled.limit_retry == DirectEvseRetryState(90, 1, NOW)
    assert settled.start_retry == previous.start_retry
    assert settled.current_proof == DirectEvseCurrentProof()


def test_crash_before_known_dispatch_outcome_retains_all_prepaid_attempts():
    _, result = all_actions()
    persisted = EvPersistenceState(restored_at=NOW, reconciliation=result.state)
    restored = EvPersistenceState.from_payload(persisted.to_payload(), NOW).reconciliation
    # The ephemeral suffix-refund evidence is never a persisted new permission.
    assert restored == result.state
    assert restored.current_retry == DirectEvseRetryState(1, 8, NOW)
    assert restored.limit_retry == DirectEvseRetryState(90, 1, NOW)
    assert restored.start_retry == DirectEvseRetryState(1, 8, NOW)
    assert not run(restored, seconds=1, limit=90).plan.commands


def test_completed_current_survives_subsequent_start_failure():
    _, result = all_actions()
    settled = settle_direct_evse_dispatch(result, invoked_actions=(
        "set_charge_limit", "set_charge_current", "start_charging",
    ))
    completed = record_direct_evse_current_completion(
        settled, completed_at=NOW + timedelta(seconds=1), binding=BINDING,
    )
    assert completed.current_retry == result.state.current_retry
    assert completed.start_retry == result.state.start_retry
    assert completed.current_proof.completed_at == NOW + timedelta(seconds=1)
    assert not completed.current_proof.armed


def test_known_no_invocation_retains_normalized_target_without_old_history():
    # This is a legitimate effective-target change, not a retry of the old 1 A.
    previous = pending(age=1800, start_attempts=7)
    result = run(previous, target=2, requested=3, limit=90)
    settled = settle_direct_evse_dispatch(result, invoked_actions=())
    assert settled.current_retry == DirectEvseRetryState(2)
    assert settled.limit_retry == DirectEvseRetryState(90)
    assert settled.start_retry == previous.start_retry
    assert settled.current_proof == DirectEvseCurrentProof()


def test_uninvoked_prompt_correction_does_not_resurrect_consumed_ack():
    result = run(armed(), requested=3, actual=2, limit=90)
    assert result.plan.commands == (
        EvCommand("set_charge_limit", 90), EvCommand("set_charge_current", 1),
    )
    settled = settle_direct_evse_dispatch(result, invoked_actions=("set_charge_limit",))
    assert settled.current_retry == DirectEvseRetryState(1)
    assert not settled.current_proof.armed
    # The untouched correction is immediately eligible when the next gate opens.
    assert run(settled, seconds=1, requested=3, actual=2, limit=90).plan.commands == (
        EvCommand("set_charge_current", 1),
    )


@pytest.mark.parametrize("invoked", [
    None, [], ("set_charge_current",), ("unknown",),
    ("set_charge_limit", "start_charging"),
    ("set_charge_limit", "set_charge_current", "start_charging", "start_charging"),
])
def test_unknown_or_nonprefix_delivery_never_refunds_attempts(invoked):
    _, result = all_actions()
    assert settle_direct_evse_dispatch(result, invoked_actions=invoked) is result.state


def test_substep_actual_mismatch_does_not_invent_a_command_or_consume_token():
    state = armed()
    result = run(state, requested=1, actual=1.1)
    assert not result.plan.commands
    assert result.state.current_retry == state.current_retry
    assert result.state.current_proof.armed
    # The separate export handoff still has to reject actual current > baseline.


def test_earned_ack_span_survives_missing_candidate_and_restart():
    missing = run(armed(), requested=1)
    assert missing.state.current_proof.armed
    assert missing.state.current_proof.stable_since is None
    persisted = EvPersistenceState(restored_at=NOW, reconciliation=missing.state)
    restored = EvPersistenceState.from_payload(persisted.to_payload(), NOW).reconciliation
    assert restored.current_proof == missing.state.current_proof
    assert run(restored, actual=2).plan.commands == (EvCommand("set_charge_current", 1),)


def test_waiting_current_must_not_start_with_unsafe_retained_current():
    state = pending()
    obs = replace(OBSERVATION, charge_switch_on=False)
    result = run(state, observation=obs)
    assert not result.plan.commands
    assert result.state.start_retry.attempts == 0


def test_limit_backoff_does_not_block_reduction_but_blocks_increase_and_start():
    state = replace(pending(attempts=0), limit_retry=DirectEvseRetryState(78, 7, NOW))
    obs = replace(OBSERVATION, charge_limit_percent=90, charge_switch_on=False)
    reduction = run(state, observation=obs)
    assert reduction.plan.commands == (EvCommand("set_charge_current", 1),)
    increase = run(state, observation=replace(obs, requested_current_a=0))
    assert not increase.plan.commands
    assert increase.state.start_retry.attempts == 0


def test_retry_channels_and_ack_survive_restart_without_renewing_clocks():
    state = armed()
    persisted = EvPersistenceState(restored_at=NOW, reconciliation=state)
    restored = EvPersistenceState.from_payload(persisted.to_payload(), NOW).reconciliation
    assert restored == state
    result = run(restored, requested=3, actual=2)
    assert result.plan.commands == (EvCommand("set_charge_current", 1),)
    echo_only = run(restored, requested=3)
    assert not echo_only.plan.commands


def persistent_payload():
    return EvPersistenceState(
        restored_at=NOW, reconciliation=armed(), outside_control_active=True,
        when_connected_owned=True,
        daily_backfill=DailyBackfillPersistenceState(
            stop_pending=True, stop_attempts=8, last_stop_at=NOW,
        ),
    ).to_payload()


@pytest.mark.parametrize("corruption", [None, [], {}, "bad", {"version": 99},
                                        {"version": True}, {"version": 1}])
def test_malformed_optional_extension_retains_pending_ownership_and_old_cooldown(corruption):
    payload = persistent_payload()
    payload["reconciliation"]["retry_channels"] = corruption
    state = EvPersistenceState.from_payload(payload, NOW)
    assert state.outside_control_active and state.when_connected_owned
    assert state.daily_backfill.stop_pending and state.daily_backfill.stop_attempts == 8
    assert state.reconciliation.attempts == 7
    assert not state.reconciliation.current_proof.armed
    assert not run(state.reconciliation).plan.commands


@pytest.mark.parametrize("section,key,value", [
    ("current", "attempts", True), ("current", "attempts", -1),
    ("start", "target", 0), ("limit", "target", 101),
    ("limit", "last_command_at", NOW.replace(tzinfo=None).isoformat()),
    ("start", "last_command_at", (NOW + timedelta(seconds=1)).isoformat()),
    ("current_proof", "armed", "true"),
    ("current_proof", "completed_at", NOW.replace(tzinfo=None).isoformat()),
    ("current_proof", "acknowledged_at", (NOW + timedelta(seconds=1)).isoformat()),
])
def test_malformed_channel_or_ack_never_discards_other_duties(section, key, value):
    payload = deepcopy(persistent_payload())
    payload["reconciliation"]["retry_channels"][section][key] = value
    state = EvPersistenceState.from_payload(payload, NOW)
    assert state.outside_control_active and state.when_connected_owned
    assert state.daily_backfill.stop_pending
    assert state.reconciliation.attempts == 7
    assert not state.reconciliation.current_proof.armed


def test_current_receipt_older_than_its_pending_attempt_cannot_earn_ack():
    payload = persistent_payload()
    proof = payload["reconciliation"]["retry_channels"]["current_proof"]
    proof["completed_at"] = (NOW - timedelta(days=1)).isoformat()
    current = payload["reconciliation"]["retry_channels"]["current"]
    current["last_command_at"] = NOW.isoformat()
    # The older ack must not acknowledge the newer pending current command.
    state = EvPersistenceState.from_payload(payload, NOW)
    assert not state.reconciliation.current_proof.armed
    assert state.reconciliation.current_retry.attempts == 7
    assert state.daily_backfill.stop_pending and state.outside_control_active


def test_old_reader_payload_has_original_five_fields_and_conservative_clock():
    payload = EvPersistenceState(restored_at=NOW, reconciliation=pending()).to_payload()
    raw = payload["reconciliation"]
    assert {key: raw[key] for key in ("target_current_a", "target_limit_percent", "attempts",
                                    "last_command_at", "phase")} == {
        "target_current_a": 1, "target_limit_percent": 78, "attempts": 7,
        "last_command_at": (NOW - timedelta(seconds=60)).isoformat(),
        "phase": "awaiting_feedback",
    }
