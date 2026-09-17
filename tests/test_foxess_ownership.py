"""Characterization tests for pure FoxESS ownership evaluation."""

from dataclasses import FrozenInstanceError

import pytest

from custom_components.home_energy_orchestrator.planner.foxess_ownership import (
    FoxessOwnershipContext,
    FoxessOwnershipResult,
    evaluate_foxess_ownership,
)


def _context(**overrides: object) -> FoxessOwnershipContext:
    values = {
        "mode": "Self Use",
        "charge_phase": "idle",
        "export_phase": "idle",
        "charge_storage_status": "valid",
        "export_storage_status": "valid",
        "manual_present": True,
        "manual_active": False,
        "manual_kind": None,
        "manual_storage_status": "valid",
        **overrides,
    }
    return FoxessOwnershipContext(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "context",
    [
        _context(mode="Force Charge", charge_phase="starting"),
        _context(mode="Force Charge", charge_phase="active"),
        _context(mode="Force Discharge", export_phase="stopping"),
        _context(mode="Force Discharge", export_phase="recovering"),
        _context(mode="Force Charge", manual_active=True, manual_kind="charge"),
        _context(
            mode="Force Discharge",
            manual_active=True,
            manual_kind="discharge",
        ),
    ],
)
def test_matching_retained_owner_allows_reconciliation(
    context: FoxessOwnershipContext,
) -> None:
    assert evaluate_foxess_ownership(context) == FoxessOwnershipResult(
        "verified_session"
    )


@pytest.mark.parametrize(
    "owned_phase",
    ["starting", "active", "stopping", "recovering"],
)
def test_self_use_preserves_retained_obligation_even_with_other_degraded_storage(
    owned_phase: str,
) -> None:
    result = evaluate_foxess_ownership(
        _context(
            charge_phase=owned_phase,
            export_storage_status="missing",
        )
    )

    assert result == FoxessOwnershipResult("verified_session")


def test_clean_self_use_is_verified_without_mutation() -> None:
    assert evaluate_foxess_ownership(_context()) == FoxessOwnershipResult("verified")


@pytest.mark.parametrize("degraded_status", ["missing", "malformed", "not_loaded"])
def test_self_use_reestablishes_safe_checkpoint_from_degraded_evidence(
    degraded_status: str,
) -> None:
    result = evaluate_foxess_ownership(
        _context(charge_storage_status=degraded_status)
    )

    assert result == FoxessOwnershipResult(
        "verified_safe_mode",
        reset_sessions=True,
        checkpoint_manual_idle=True,
        reason="ownership_reestablished_self_use",
        clear_actions=True,
    )


def test_self_use_without_manual_controller_skips_manual_checkpoint() -> None:
    result = evaluate_foxess_ownership(
        _context(
            manual_present=False,
            manual_storage_status="missing",
        )
    )

    assert result.reset_sessions is True
    assert result.checkpoint_manual_idle is False


def test_external_forced_mode_with_degraded_evidence_holds_unknown() -> None:
    result = evaluate_foxess_ownership(
        _context(mode="Force Discharge", manual_storage_status="missing")
    )

    assert result == FoxessOwnershipResult(
        "ownership_unknown",
        hold=True,
        reason="ownership_unknown",
        clear_actions=True,
    )


@pytest.mark.parametrize("mode", ["Force Charge", "Force Discharge", "Feed-in First"])
def test_clean_external_mode_is_recognized_without_adoption(mode: str) -> None:
    result = evaluate_foxess_ownership(_context(mode=mode))

    assert result == FoxessOwnershipResult(
        "verified_external_owner",
        hold=True,
        reason="external_forced_mode",
        clear_actions=True,
    )


def test_ownership_inputs_and_results_are_immutable() -> None:
    context = _context()
    result = evaluate_foxess_ownership(context)

    with pytest.raises(FrozenInstanceError):
        context.mode = "Force Charge"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.hold = True  # type: ignore[misc]
