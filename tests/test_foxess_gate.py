"""Characterization tests for the pure automatic FoxESS gate evaluator."""

from dataclasses import FrozenInstanceError, replace

import pytest

from custom_components.home_energy_orchestrator.const import (
    FOXESS_CONTROL_OWNER_CLOUD,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from custom_components.home_energy_orchestrator.planner.foxess_gate import (
    FoxessGateContext,
    FoxessGateResult,
    evaluate_foxess_gate,
)


def _context(**overrides: object) -> FoxessGateContext:
    values: dict[str, object] = {
        "manual_test_active": False,
        "control_owner": FOXESS_CONTROL_OWNER_MODBUS,
        "master_enabled": True,
        "safety_lock": False,
        "electrical_verified": True,
        "actuator_mapping_complete": True,
        "telemetry_available": True,
        **overrides,
    }
    return FoxessGateContext(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {"manual_test_active": True},
            FoxessGateResult("manual_test_active", clear_actions=True),
        ),
        (
            {"control_owner": FOXESS_CONTROL_OWNER_CLOUD},
            FoxessGateResult(
                "foxcloud_scheduler_owns_inverter",
                clear_actions=True,
            ),
        ),
        (
            {"control_owner": "observer_only"},
            FoxessGateResult("foxess_observer_owner", clear_actions=True),
        ),
        (
            {"master_enabled": False},
            FoxessGateResult("automatic_control_disabled"),
        ),
        ({"safety_lock": True}, FoxessGateResult("rehearsal_mode")),
        (
            {"electrical_verified": False},
            FoxessGateResult("sign_conventions_unverified"),
        ),
        (
            {"actuator_mapping_complete": False},
            FoxessGateResult(
                "incomplete_foxess_mapping",
                warn_incomplete_mapping=True,
            ),
        ),
        (
            {"telemetry_available": False},
            FoxessGateResult("telemetry_unavailable"),
        ),
    ],
)
def test_gate_outcomes_freeze_reason_and_side_effect_metadata(
    overrides: dict[str, object],
    expected: FoxessGateResult,
) -> None:
    assert evaluate_foxess_gate(_context(**overrides)) == expected


def test_gate_precedence_matches_retained_controller_order() -> None:
    context = _context(
        manual_test_active=True,
        control_owner=FOXESS_CONTROL_OWNER_CLOUD,
        master_enabled=False,
        safety_lock=True,
        electrical_verified=False,
        actuator_mapping_complete=False,
        telemetry_available=False,
    )
    expected = (
        ("manual_test_active", True),
        ("foxcloud_scheduler_owns_inverter", True),
        ("automatic_control_disabled", False),
        ("rehearsal_mode", False),
        ("sign_conventions_unverified", False),
        ("incomplete_foxess_mapping", False),
        ("telemetry_unavailable", False),
        (None, False),
    )

    for reason, clear_actions in expected:
        result = evaluate_foxess_gate(context)
        assert (result.reason, result.clear_actions) == (reason, clear_actions)
        if reason == "manual_test_active":
            context = replace(context, manual_test_active=False)
        elif reason == "foxcloud_scheduler_owns_inverter":
            context = replace(context, control_owner=FOXESS_CONTROL_OWNER_MODBUS)
        elif reason == "automatic_control_disabled":
            context = replace(context, master_enabled=True)
        elif reason == "rehearsal_mode":
            context = replace(context, safety_lock=False)
        elif reason == "sign_conventions_unverified":
            context = replace(context, electrical_verified=True)
        elif reason == "incomplete_foxess_mapping":
            context = replace(context, actuator_mapping_complete=True)
        elif reason == "telemetry_unavailable":
            context = replace(context, telemetry_available=True)


def test_gate_context_and_result_are_immutable() -> None:
    context = _context()
    result = evaluate_foxess_gate(context)

    assert result.blocked is False
    with pytest.raises(FrozenInstanceError):
        context.master_enabled = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.reason = "changed"  # type: ignore[misc]
