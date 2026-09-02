from __future__ import annotations

import pytest

from custom_components.home_energy_orchestrator.planner.ev import (
    EvCommand,
    EvObservation,
    ev_charge_should_stop,
    plan_ev_start,
    plan_ev_stop,
)


def observation(**overrides: object) -> EvObservation:
    values = {
        "soc_percent": 29.0,
        "cable_connected": True,
        "limit_min_percent": 50.0,
        "limit_max_percent": 100.0,
    }
    values.update(overrides)
    return EvObservation(**values)


def test_start_sets_entity_minimum_then_turns_on() -> None:
    plan = plan_ev_start(40, observation())
    assert plan.reason == "ready"
    assert plan.commands == (
        EvCommand("set_charge_limit", 50.0),
        EvCommand("turn_on_charge"),
    )


def test_start_rejects_disconnected_or_unknown_vehicle() -> None:
    assert plan_ev_start(40, observation(cable_connected=False)).commands == ()
    assert plan_ev_start(40, observation(soc_percent=None)).reason == "soc_unknown"


def test_start_rejects_target_above_mapped_maximum() -> None:
    plan = plan_ev_start(90, observation(limit_max_percent=80))
    assert plan.commands == ()
    assert plan.reason == "target_exceeds_charge_limit"


def test_start_is_noop_at_or_above_target() -> None:
    assert plan_ev_start(40, observation(soc_percent=40)).reason == "target_reached"


def test_stop_always_turns_off_charge() -> None:
    assert plan_ev_stop(observation()).commands == (EvCommand("turn_off_charge"),)
    assert plan_ev_stop(observation(cable_connected=False)).commands == (
        EvCommand("turn_off_charge"),
    )


def test_stop_guard_handles_disconnect_and_target() -> None:
    assert ev_charge_should_stop(40, soc_percent=35, cable_connected=False, armed=True)
    assert ev_charge_should_stop(40, soc_percent=40, cable_connected=True, armed=True)
    assert not ev_charge_should_stop(40, soc_percent=None, cable_connected=True, armed=True)
    assert not ev_charge_should_stop(40, soc_percent=99, cable_connected=True, armed=False)


@pytest.mark.parametrize(
    "target, expected",
    [(-1, "target_soc_percent"), (101, "target_soc_percent"), (float("nan"), "target_soc_percent")],
)
def test_start_rejects_invalid_target(target: float, expected: str) -> None:
    with pytest.raises(ValueError, match=expected):
        plan_ev_start(target, observation())
