from custom_components.home_energy_orchestrator.planner.safety import (
    RuntimeState,
    SafetyInputs,
    evaluate_runtime_state,
)


def test_invalid_telemetry_degrades_before_automatic_writes() -> None:
    assert evaluate_runtime_state(SafetyInputs(True, False, False)) == (
        RuntimeState.DEGRADED,
        "required_telemetry_invalid",
    )


def test_external_conflict_holds_even_during_recovery() -> None:
    assert evaluate_runtime_state(SafetyInputs(True, False, True, external_conflict=True)) == (
        RuntimeState.HELD,
        "external_actuator_conflict",
    )


def test_command_failure_has_highest_priority() -> None:
    assert evaluate_runtime_state(SafetyInputs(True, False, True, command_failed=True)) == (
        RuntimeState.FAULT,
        "command_failed",
    )


def test_disabled_system_observes_without_writes() -> None:
    assert evaluate_runtime_state(SafetyInputs(False, False, True)) == (
        RuntimeState.OBSERVE,
        "automatic_mode_disabled",
    )
