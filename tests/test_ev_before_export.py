"""Tests for the deliberately small EV-before-export arbitration layer."""

from custom_components.home_energy_orchestrator.planner.ev_before_export import (
    decide_ev_before_export,
)


def test_disabled_policy_never_changes_export_even_without_ev_telemetry():
    decision = decide_ev_before_export(
        enabled=False,
        ev_soc_percent=None,
        target_soc_percent=40,
    )

    assert decision.export_allowed is True
    assert decision.reason == "disabled"


def test_enabled_policy_withholds_export_below_target():
    decision = decide_ev_before_export(
        enabled=True,
        ev_soc_percent=39,
        target_soc_percent=40,
    )

    assert decision.export_allowed is False
    assert decision.reason == "ev_below_target"


def test_target_is_an_inclusive_boundary():
    decision = decide_ev_before_export(
        enabled=True,
        ev_soc_percent=40,
        target_soc_percent=40,
    )

    assert decision.export_allowed is True
    assert decision.reason == "target_met"


def test_enabled_policy_fails_closed_without_valid_soc():
    missing = decide_ev_before_export(
        enabled=True,
        ev_soc_percent=None,
        target_soc_percent=40,
    )
    invalid = decide_ev_before_export(
        enabled=True,
        ev_soc_percent=101,
        target_soc_percent=40,
    )

    assert (missing.export_allowed, missing.reason) == (False, "ev_soc_unavailable")
    assert (invalid.export_allowed, invalid.reason) == (False, "ev_soc_invalid")


def test_invalid_target_fails_closed():
    decision = decide_ev_before_export(
        enabled=True,
        ev_soc_percent=50,
        target_soc_percent=float("nan"),
    )

    assert decision.export_allowed is False
    assert decision.reason == "target_invalid"
