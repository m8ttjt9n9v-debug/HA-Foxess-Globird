"""Characterization tests for pure FoxESS charge eligibility."""

from dataclasses import FrozenInstanceError, replace

import pytest

from custom_components.home_energy_orchestrator.planner.charge_session import (
    ChargeSessionState,
)
from custom_components.home_energy_orchestrator.planner.foxess_charge_policy import (
    FoxessChargePolicyContext,
    evaluate_foxess_charge_policy,
)


def _context(**overrides: object) -> FoxessChargePolicyContext:
    values = {
        "requested_enabled": True,
        "schedule_confirmed": True,
        "window_active": True,
        "configured_max_kw": 15.0,
        "observed_max_kw": 10.0,
        "source_capability_available": True,
        "mode": "Self Use",
        "battery_soc": 60.0,
        "target_soc_percent": 100.0,
        "free_energy_remaining_kwh": 20.0,
        "session": ChargeSessionState(),
        **overrides,
    }
    return FoxessChargePolicyContext(**values)  # type: ignore[arg-type]


def test_eligible_idle_charge_owns_tick_and_uses_bounded_maximum() -> None:
    result = evaluate_foxess_charge_policy(_context())

    assert result.enabled is True
    assert result.charge_max_kw == 10.0
    assert result.source_available is True
    assert result.allowance_available is True
    assert result.eligible_to_start is True
    assert result.latched is False
    assert result.charge_power_target_kw == 0.0
    assert result.terminal_reason is None
    assert result.owns_tick is True
    assert result.should_advance is True
    assert result.session_window_active is True
    assert result.finish_requested is False


@pytest.mark.parametrize(
    ("remaining", "reason"),
    [
        (0.0, "charge_allowance_exhausted"),
        (-1.0, "charge_allowance_exhausted"),
        (None, "charge_allowance_unavailable"),
    ],
)
def test_allowance_failures_retain_distinct_public_reasons(
    remaining: float | None,
    reason: str,
) -> None:
    result = evaluate_foxess_charge_policy(
        _context(free_energy_remaining_kwh=remaining)
    )

    assert result.allowance_available is False
    assert result.eligible_to_start is False
    assert result.terminal_reason == reason
    assert result.owns_tick is True
    assert result.should_advance is False
    assert result.session_window_active is False
    assert result.finish_requested is True


def test_unconfirmed_schedule_precedes_other_idle_failures() -> None:
    result = evaluate_foxess_charge_policy(
        _context(
            schedule_confirmed=False,
            mode="Force Discharge",
            free_energy_remaining_kwh=None,
        )
    )

    assert result.enabled is False
    assert result.terminal_reason == "charge_schedule_unconfirmed"
    assert result.owns_tick is True
    assert result.should_advance is False


def test_idle_start_requires_self_use_feedback() -> None:
    result = evaluate_foxess_charge_policy(_context(mode="Force Discharge"))

    assert result.eligible_to_start is True
    assert result.terminal_reason == "charge_start_mode_not_self_use"
    assert result.owns_tick is True
    assert result.should_advance is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"requested_enabled": False},
        {"window_active": False},
        {"battery_soc": 100.0},
        {"battery_soc": -1.0},
        {"configured_max_kw": 0.0},
        {"observed_max_kw": 0.0},
    ],
)
def test_ineligible_idle_charge_yields_without_owning_tick(
    overrides: dict[str, object],
) -> None:
    result = evaluate_foxess_charge_policy(_context(**overrides))

    assert result.terminal_reason is None
    assert result.owns_tick is False
    assert result.should_advance is False


def test_missing_mode_capability_is_delegated_to_session_reconciliation() -> None:
    result = evaluate_foxess_charge_policy(
        _context(source_capability_available=False)
    )

    assert result.source_available is False
    assert result.eligible_to_start is True
    assert result.owns_tick is True
    assert result.should_advance is True


def test_latched_session_advances_to_finish_even_after_policy_disables() -> None:
    result = evaluate_foxess_charge_policy(
        _context(
            requested_enabled=False,
            window_active=False,
            free_energy_remaining_kwh=0.0,
            session=ChargeSessionState("active", 8.5),
        )
    )

    assert result.enabled is False
    assert result.latched is True
    assert result.charge_power_target_kw == 8.5
    assert result.terminal_reason is None
    assert result.owns_tick is True
    assert result.should_advance is True
    assert result.session_window_active is False
    assert result.finish_requested is True


def test_latched_session_retains_target_but_marks_missing_source() -> None:
    result = evaluate_foxess_charge_policy(
        _context(
            observed_max_kw=0.0,
            session=ChargeSessionState("recovering", 7.0),
        )
    )

    assert result.source_available is False
    assert result.charge_power_target_kw is None
    assert result.owns_tick is True
    assert result.should_advance is True


def test_policy_input_and_result_are_immutable() -> None:
    context = _context()
    result = evaluate_foxess_charge_policy(context)

    with pytest.raises(FrozenInstanceError):
        context.window_active = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.owns_tick = False  # type: ignore[misc]
    assert evaluate_foxess_charge_policy(
        replace(context, configured_max_kw=-5.0)
    ).charge_max_kw == 0.0
