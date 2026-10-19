"""Price admission reuses protected export arithmetic and the same session store."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.export_session import (
    ExportSessionState,
    advance_export_session,
)
from custom_components.home_energy_orchestrator.planner.foxess import FoxessObservation
from custom_components.home_energy_orchestrator.planner.foxess_export_policy import (
    FoxessExportPolicyContext,
    evaluate_foxess_export_policy,
)

NOW = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)
END = NOW + timedelta(minutes=5)
SELF_USE = FoxessObservation("Self Use", 0, 0)
FORCED = FoxessObservation("Force Discharge", 0, 10)


def _context(**changes):
    return FoxessExportPolicyContext(**{
        "requested_enabled": False,
        "before_export_enabled": False,
        "ev_soc_percent": None,
        "before_export_target_percent": 40,
        "now": NOW,
        "start_at": NOW + timedelta(hours=3),
        "finish_at": NOW + timedelta(hours=6),
        "source_capability_available": True,
        "configured_max_kw": 10,
        "observed_max_kw": 15,
        "exported_kwh": 2,
        "automatic_limit_kwh": 20,
        "protected_house_kwh": 4,
        "protected_ev_kwh": 2,
        "available_after_reserve_kwh": 30,
        "discharge_efficiency_percent": 100,
        "session": ExportSessionState(),
        "price_export_enabled": True,
        "price_interval_start": NOW,
        "price_interval_end": END,
        **changes,
    })


def _advance(context, observation=SELF_USE):
    policy = evaluate_foxess_export_policy(context)
    transition = advance_export_session(
        context.session,
        observation,
        now=context.now,
        source_available=policy.source_available,
        window_active=policy.session_window_active,
        eligible=policy.eligible,
        requested_discharge_power_kw=policy.requested_power_kw,
        discharge_power_max_kw=policy.discharge_max_kw,
        finish_requested=policy.finish_requested,
        authority_source=policy.authority_source,
        price_deadline=policy.price_deadline,
        price_permission_end=context.price_interval_end if policy.authority_source == "price"
        else None,
    )
    return policy, transition


def _owned(phase="active", **changes):
    return ExportSessionState(
        phase=phase, requested_power_kw=10,
        authority_source="price", price_deadline=END - timedelta(seconds=5),
        price_actuator_entities=("select.test_mode", "number.test_charge", "number.test_discharge"),
        **changes,
    )


def test_price_starts_immediately_outside_zerohero_with_identical_protections():
    policy, transition = _advance(_context())
    assert policy.authority_source == "price"
    assert policy.planned_start == NOW and policy.eligible
    assert policy.export_plan.sellable_energy_kwh == 24
    assert policy.export_plan.planned_export_energy_kwh <= 18
    assert policy.price_deadline == END
    assert transition.state.authority_source == "price"
    assert transition.state.price_deadline == policy.price_deadline
    assert transition.state.requested_power_kw == 10
    assert [command.action for command in transition.plan.commands] == [
        "set_discharge_power", "select_mode",
    ]


@pytest.mark.parametrize("changes", [
    {"price_export_enabled": False},
    {"price_interval_start": None},
    {"price_interval_end": None},
    {"price_interval_start": NOW.replace(tzinfo=None)},
    {"price_interval_end": NOW},
    {"price_interval_start": NOW + timedelta(seconds=1)},
])
def test_missing_expired_future_or_withdrawn_price_never_starts(changes):
    policy, transition = _advance(_context(**changes))
    assert not policy.eligible
    assert transition.state.phase == "idle" and not transition.plan.commands


@pytest.mark.parametrize("changes", [
    {"price_export_enabled": False},
    {"price_interval_end": None},
    {"price_interval_end": NOW},
    {"available_after_reserve_kwh": None},
    {"available_after_reserve_kwh": 6},
    {"exported_kwh": 20},
    {"protected_house_kwh": None},
    {"before_export_enabled": True, "ev_soc_percent": 20},
])
def test_live_price_or_sellable_loss_restores_owned_session(changes):
    policy, transition = _advance(_context(session=_owned(), **changes), FORCED)
    assert policy.authority_source == "price" and policy.finish_requested
    assert transition.state.phase == "stopping"
    assert transition.state.authority_source == "price"
    assert transition.state.price_deadline is not None
    assert transition.plan.commands[0].value == "Self Use"


def test_price_fall_cannot_inherit_zerohero_latch_before_ordinary_latest_start():
    context = _context(
        requested_enabled=True, session=_owned(), price_export_enabled=False,
        start_at=NOW - timedelta(minutes=1), finish_at=NOW + timedelta(hours=3),
        available_after_reserve_kwh=7,
    )
    policy, stopping = _advance(context, FORCED)
    assert policy.finish_requested and stopping.state.authority_source == "price"
    again = replace(context, session=stopping.state, price_export_enabled=True)
    _, cannot_restart = _advance(again, FORCED)
    assert cannot_restart.state.phase == "stopping"
    _, completed = _advance(replace(again, session=cannot_restart.state), SELF_USE)
    assert completed.state == ExportSessionState()
    ordinary = evaluate_foxess_export_policy(replace(
        context, session=completed.state, price_export_enabled=False,
    ))
    assert ordinary.authority_source == "zerohero" and not ordinary.eligible


def test_existing_normal_latch_ignores_price_changes_exactly_as_before():
    normal = ExportSessionState("active", 10)
    baseline = _context(
        requested_enabled=True, session=normal,
        start_at=NOW - timedelta(minutes=1), finish_at=NOW + timedelta(hours=3),
        price_export_enabled=False, available_after_reserve_kwh=6,
    )
    off, normal_off = _advance(baseline, FORCED)
    on, normal_on = _advance(replace(baseline, price_export_enabled=True), FORCED)
    assert off == on
    assert normal_off == normal_on
    assert normal_on.state == normal and normal_on.reason == "latched"


def test_new_block_renews_live_session_but_still_shrinks_to_remaining_cap():
    first, start = _advance(_context(available_after_reserve_kwh=10, automatic_limit_kwh=3))
    assert first.export_plan.sellable_energy_kwh == 4
    active = replace(start.state, phase="active", attempts=0)
    second_context = _context(
        now=END, price_interval_start=END,
        price_interval_end=END + timedelta(minutes=5), session=active,
        available_after_reserve_kwh=9, exported_kwh=2.8, automatic_limit_kwh=3,
    )
    # Real runtime passes an interval-end + 150s permission boundary.
    active = replace(active, price_deadline=END + timedelta(seconds=150))
    context = replace(second_context, session=active)
    renewed, transition = _advance(context, FORCED)
    assert renewed.export_plan.sellable_energy_kwh == 3
    assert renewed.automatic_remaining_kwh == pytest.approx(0.2)
    assert renewed.export_plan.planned_export_energy_kwh == pytest.approx(0.2)
    assert transition.state.authority_source == "price"
    assert transition.state.phase == "active" and not transition.plan.commands
    assert transition.state.price_deadline < context.price_interval_end


def test_same_block_cannot_extend_a_resource_shortened_deadline():
    policy, started = _advance(_context(available_after_reserve_kwh=6.5))
    owned = replace(started.state, phase="active", attempts=0)
    later, transition = _advance(_context(
        now=NOW + timedelta(seconds=30), session=owned, available_after_reserve_kwh=30,
    ), FORCED)
    assert later.price_deadline == transition.state.price_deadline == policy.price_deadline


def test_a_new_block_cannot_revive_an_already_expired_or_stopping_session():
    _, started = _advance(_context())
    for phase in ("active", "stopping", "recovering"):
        state = replace(started.state, phase=phase)
        _, transition = _advance(_context(
            now=END, price_interval_start=END, price_interval_end=END + timedelta(minutes=5),
            session=state,
        ), FORCED)
        assert transition.state.phase == "stopping"
        assert transition.state.price_deadline == state.price_deadline


def test_permission_boundary_round_trip_and_invalid_values_fail_closed():
    _, transition = _advance(_context())
    state = replace(transition.state, price_actuator_entities=("select.x", "number.y", "number.z"))
    payload = state.to_payload()
    assert payload["price_permission_end"] == END.isoformat()
    assert ExportSessionState.from_payload(payload) == state
    for invalid in (NOW.isoformat(), END.replace(tzinfo=None).isoformat(), "bad"):
        with pytest.raises(ValueError):
            ExportSessionState.from_payload({**payload, "price_permission_end": invalid})


@pytest.mark.parametrize("sellable", [0, 0.001, 0.05, 0.1])
def test_tiny_sellable_cannot_start_a_maximum_power_session(sellable):
    policy, transition = _advance(_context(available_after_reserve_kwh=6 + sellable))
    assert not policy.eligible and policy.planned_start is None
    assert transition.state.phase == "idle" and not transition.plan.commands


def test_resource_horizon_shortens_deadline_instead_of_renewing_owned_energy():
    policy, _ = _advance(_context(available_after_reserve_kwh=6.5))
    assert policy.price_deadline == NOW + timedelta(seconds=175)
    owned = ExportSessionState(
        "active", 10, authority_source="price", price_deadline=policy.price_deadline,
    )
    later = evaluate_foxess_export_policy(_context(
        now=NOW + timedelta(seconds=30), session=owned, available_after_reserve_kwh=10,
    ))
    assert later.price_deadline == owned.price_deadline


def test_outage_retains_price_authority_and_return_after_deadline_cleans_up():
    context = _context(session=_owned(), source_capability_available=False)
    _, lost = _advance(context, FORCED)
    assert lost.state.phase == "recovering" and lost.state.authority_source == "price"
    returned = replace(
        context, session=lost.state, now=END, source_capability_available=True,
        price_interval_start=END, price_interval_end=END + timedelta(minutes=5),
    )
    _, cleanup = _advance(returned, FORCED)
    assert cleanup.state.phase == "stopping"
    assert cleanup.plan.commands[0].value == "Self Use"


def test_source_return_within_lease_requires_current_sellable_before_reassertion():
    recovering = _owned("recovering", attempts=1, last_command_at=NOW)
    _, resumed = _advance(_context(
        session=recovering, now=NOW + timedelta(seconds=30),
    ), SELF_USE)
    assert resumed.state.phase == "starting" and resumed.state.authority_source == "price"
    _, withheld = _advance(_context(
        session=recovering, now=NOW + timedelta(seconds=30), available_after_reserve_kwh=6,
    ), FORCED)
    assert withheld.state.phase == "stopping"


def test_price_cleanup_retries_progressively_without_terminal_latch():
    state = _owned("stopping", attempts=1, last_command_at=NOW)
    context = _context(session=state, price_export_enabled=False, now=NOW + timedelta(seconds=30))
    for delay, attempt in ((30, 2), (60, 3), (120, 4), (240, 5), (300, 6), (300, 7)):
        context = replace(
            context, now=state.last_command_at + timedelta(seconds=delay), session=state
        )
        _, retry = _advance(context, FORCED)
        state = retry.state
        assert state.phase == "stopping" and state.attempts == attempt
        assert retry.plan.commands[0].value == "Self Use"
    _, confirmed = _advance(replace(context, session=state), SELF_USE)
    assert confirmed.state == ExportSessionState()


def test_legacy_payload_shape_remains_unchanged_and_price_fields_round_trip():
    old = {"phase": "active", "requested_power_kw": 10, "attempts": 0, "last_command_at": None}
    normal = ExportSessionState.from_payload(old)
    assert normal.authority_source == "zerohero" and normal.price_deadline is None
    assert normal.to_payload() == old
    for phase in ("starting", "active", "stopping", "recovering"):
        state = _owned(phase)
        assert ExportSessionState.from_payload(state.to_payload()) == state


@pytest.mark.parametrize("fields", [
    {"authority_source": "unknown", "price_deadline": END.isoformat()},
    {"authority_source": "price", "price_deadline": None},
    {"authority_source": "price", "price_deadline": END.replace(tzinfo=None).isoformat()},
    {"authority_source": "zerohero", "price_deadline": END.isoformat()},
])
def test_invalid_price_authority_fails_closed_on_decode(fields):
    payload = {"phase": "active", "requested_power_kw": 10, "attempts": 0,
               "last_command_at": None, **fields}
    with pytest.raises(ValueError):
        ExportSessionState.from_payload(payload)


def test_expired_starting_feedback_cannot_be_adopted_as_active_price_session():
    started = _owned("starting", attempts=1, last_command_at=NOW)
    _, expired = _advance(_context(session=started, now=END), FORCED)
    assert expired.state.phase == "stopping"
    assert expired.plan.commands[0].value == "Self Use"
    assert expired.state.authority_source == "price"


def test_price_does_not_adopt_an_unknown_external_forced_mode():
    _, external = _advance(_context(), FORCED)
    assert external.state == ExportSessionState()
    assert external.reason == "price_external_owner"
    assert not external.plan.commands


def test_smaller_commissioned_maximum_curtails_but_larger_maximum_cannot_raise_latch():
    _, reduced = _advance(_context(session=_owned(), configured_max_kw=8), FORCED)
    assert reduced.state.requested_power_kw == 8
    assert reduced.state.authority_source == "price"
    assert any(command.value == 8 for command in reduced.plan.commands)
    _, unchanged = _advance(_context(session=_owned(), configured_max_kw=15), FORCED)
    assert unchanged.state.requested_power_kw == 10
    assert not unchanged.plan.commands


@pytest.mark.parametrize("power", [0, float("nan"), float("inf")])
def test_nonpositive_or_nonfinite_price_power_cannot_restore_as_a_valid_journal(power):
    payload = _owned().to_payload()
    payload["requested_power_kw"] = power
    with pytest.raises(ValueError):
        ExportSessionState.from_payload(payload)


@pytest.mark.parametrize("mapping", [None, [], ["one"], ["one", "one", "two"], ["one", "two", 3]])
def test_price_journal_missing_or_ambiguous_original_actuators_fails_closed(mapping):
    payload = _owned().to_payload()
    payload["price_actuator_entities"] = mapping
    with pytest.raises(ValueError):
        ExportSessionState.from_payload(payload)


def test_price_mapping_is_retained_through_cleanup_and_cleared_only_at_idle():
    state = _owned()
    _, stopping = _advance(_context(session=state, price_export_enabled=False), FORCED)
    assert stopping.state.price_actuator_entities == state.price_actuator_entities
    saved = ExportSessionState.from_payload(stopping.state.to_payload())
    assert saved.price_actuator_entities == state.price_actuator_entities
    _, cleaned = _advance(_context(session=saved, price_export_enabled=False), SELF_USE)
    assert cleaned.state.price_actuator_entities is None


@pytest.mark.parametrize("fields", [
    {"last_command_at": NOW.replace(tzinfo=None).isoformat()},
    {"last_command_at": (END + timedelta(minutes=10)).isoformat()},
    {"attempts": 1.5},
    {"attempts": True},
])
def test_malformed_price_timing_and_retry_counters_fail_closed(fields):
    payload = _owned().to_payload()
    payload.update(fields)
    with pytest.raises(ValueError):
        ExportSessionState.from_payload(payload)


def test_price_cleanup_after_expiry_keeps_valid_late_command_timestamp():
    state = _owned("stopping", attempts=2, last_command_at=END + timedelta(minutes=1))
    assert ExportSessionState.from_payload(state.to_payload()) == state


@pytest.mark.parametrize("phase", ["active", "stopping", "recovering"])
def test_future_price_command_timestamp_cannot_delay_reducing_cleanup(phase):
    state = _owned(phase, attempts=2, last_command_at=NOW + timedelta(seconds=20))
    _, reduced = _advance(_context(session=state), FORCED)
    assert reduced.state.phase == "stopping"
    assert reduced.plan.commands[0].value == "Self Use"
    assert reduced.state.last_command_at == NOW


def test_legacy_naive_timestamp_and_coercible_counter_decode_is_unchanged():
    payload = {
        "phase": "active", "requested_power_kw": 10,
        "attempts": "2", "last_command_at": NOW.replace(tzinfo=None).isoformat(),
    }
    state = ExportSessionState.from_payload(payload)
    assert state.authority_source == "zerohero" and state.attempts == 2
    assert state.last_command_at.tzinfo is None
