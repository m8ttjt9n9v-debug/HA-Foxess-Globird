"""Invented multi-block price/energy replay, independent of private site evidence."""

from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.charge_session import ChargeSessionState
from custom_components.home_energy_orchestrator.planner.export_session import ExportSessionState
from custom_components.home_energy_orchestrator.planner.foxess_recovery import (
    mark_foxess_source_unavailable,
)
from tests.test_price_export_policy import FORCED, NOW, SELF_USE, _advance, _context


def test_shared_source_recovery_cannot_erase_price_ownership():
    owned = ExportSessionState(
        "active", 10, authority_source="price", price_deadline=NOW + timedelta(minutes=5),
        price_actuator_entities=("select.mode", "number.charge", "number.discharge"),
    )
    recovery = mark_foxess_source_unavailable(ChargeSessionState(), owned, NOW)
    assert recovery.export_session == replace(owned, phase="recovering", last_command_at=NOW)
    assert recovery.save_export


@pytest.mark.parametrize("spend", ["daily_cap", "sellable"])
def test_repeated_spikes_cannot_regrant_spent_energy(spend):
    # A deliberately invented sequence: high, low, high, exact threshold,
    # then more high blocks. Both energy constraints are intentionally small.
    prices = [4, 0.4, 10, 3, 8, 0.3, 12, 12, 12, 12]
    budget = 2.0
    state = ExportSessionState()
    observation = SELF_USE
    exported = 0.0
    positive_starts = 0
    for block, price in enumerate(prices):
        start = NOW + timedelta(minutes=5 * block)
        end = start + timedelta(minutes=5)
        context = _context(
            now=start, price_interval_start=start, price_interval_end=end,
            price_export_enabled=price >= 3,
            available_after_reserve_kwh=(6 + budget - exported) if spend == "sellable" else 30,
            automatic_limit_kwh=budget if spend == "daily_cap" else 25,
            exported_kwh=exported, session=state,
        )
        policy, transition = _advance(context, observation)
        state = transition.state
        if state.phase == "stopping":
            _, stopped = _advance(replace(context, session=state), SELF_USE)
            state = stopped.state
            assert state == ExportSessionState()
            observation = SELF_USE
            policy, transition = _advance(replace(context, session=state), observation)
            state = transition.state
        if state.authority_source != "price":
            assert state.phase == "idle"
            assert not transition.plan.commands
            continue
        assert price >= 3
        positive_starts += 1
        assert state.price_deadline <= end
        seconds = (state.price_deadline - start).total_seconds()
        delivered = state.requested_power_kw * seconds / 3600
        assert delivered <= budget - exported + 1e-9
        exported += delivered
        observation = FORCED
        deadline_context = replace(context, now=state.price_deadline, session=state)
        expired, cleanup = _advance(deadline_context, observation)
        assert expired.finish_requested and cleanup.state.phase == "stopping"
        _, stopped = _advance(replace(deadline_context, session=cleanup.state), SELF_USE)
        state, observation = stopped.state, SELF_USE
    assert positive_starts >= 2
    assert 1.8 < exported < budget
    # Residual below the safe start horizon is withheld rather than oversold.
    final = _context(
        now=NOW + timedelta(hours=1),
        price_interval_start=NOW + timedelta(hours=1),
        price_interval_end=NOW + timedelta(hours=1, minutes=5),
        session=state, exported_kwh=exported,
        automatic_limit_kwh=budget if spend == "daily_cap" else 25,
        available_after_reserve_kwh=(6 + budget - exported) if spend == "sellable" else 30,
    )
    policy, transition = _advance(final)
    assert not policy.eligible and transition.state.phase == "idle"
