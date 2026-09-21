"""Characterization tests for pure FoxESS export policy evaluation."""

from datetime import UTC, datetime

from custom_components.home_energy_orchestrator.planner.export import ExportPlan
from custom_components.home_energy_orchestrator.planner.export_session import (
    ExportSessionState,
)
from custom_components.home_energy_orchestrator.planner.foxess_export_policy import (
    FoxessExportPolicyBaseContext,
    FoxessExportPolicyContext,
    evaluate_automatic_export_remaining,
    evaluate_foxess_export_policy,
    evaluate_foxess_export_policy_base,
)

START = datetime(2026, 9, 5, 18, 0, tzinfo=UTC)
FINISH = datetime(2026, 9, 5, 21, 0, tzinfo=UTC)


def test_automatic_export_remaining_retains_partial_publication_contract() -> None:
    healthy = evaluate_automatic_export_remaining(
        exported_kwh=5,
        automatic_limit_kwh=20,
        previous_remaining_kwh=7,
    )
    missing = evaluate_automatic_export_remaining(
        exported_kwh=None,
        automatic_limit_kwh=20,
        previous_remaining_kwh=7,
    )
    malformed = evaluate_automatic_export_remaining(
        exported_kwh="invalid",
        automatic_limit_kwh=20,
        previous_remaining_kwh=7,
    )

    assert (healthy.remaining_kwh, healthy.valid) == (15, True)
    assert (missing.remaining_kwh, missing.valid) == (None, True)
    assert (malformed.remaining_kwh, malformed.valid) == (7, False)


def _context(**overrides: object) -> FoxessExportPolicyContext:
    values = {
        "requested_enabled": True,
        "before_export_enabled": False,
        "ev_soc_percent": None,
        "before_export_target_percent": 40.0,
        "now": datetime(2026, 9, 5, 19, 45, tzinfo=UTC),
        "start_at": START,
        "finish_at": FINISH,
        "source_capability_available": True,
        "configured_max_kw": 15.0,
        "observed_max_kw": 15.0,
        "exported_kwh": 0.0,
        "automatic_limit_kwh": 20.0,
        "protected_house_kwh": 4.0,
        "protected_ev_kwh": 0.0,
        "available_after_reserve_kwh": 30.0,
        "discharge_efficiency_percent": 100.0,
        "session": ExportSessionState(),
        **overrides,
    }
    return FoxessExportPolicyContext(**values)  # type: ignore[arg-type]


def _base_context(**overrides: object) -> FoxessExportPolicyBaseContext:
    full = _context(**overrides)
    return FoxessExportPolicyBaseContext(
        requested_enabled=full.requested_enabled,
        before_export_enabled=full.before_export_enabled,
        ev_soc_percent=full.ev_soc_percent,
        before_export_target_percent=full.before_export_target_percent,
        now=full.now,
        start_at=full.start_at,
        finish_at=full.finish_at,
        source_capability_available=full.source_capability_available,
        configured_max_kw=full.configured_max_kw,
        observed_max_kw=full.observed_max_kw,
        session=full.session,
    )


def test_base_policy_retains_safe_session_inputs_without_energy_plan() -> None:
    result = evaluate_foxess_export_policy_base(_base_context())

    assert result.before_export_decision.export_allowed is True
    assert result.effective_enabled is True
    assert result.within_session_window is True
    assert result.source_available is True
    assert result.discharge_max_kw == 15
    assert result.requested_power_kw == 15
    assert result.latched is False
    assert result.should_advance is False
    assert result.session_window_active is True
    assert result.finish_requested is False


def test_base_policy_advances_latched_session_to_safe_finish() -> None:
    result = evaluate_foxess_export_policy_base(
        _base_context(
            before_export_enabled=True,
            ev_soc_percent=25,
            now=FINISH,
            session=ExportSessionState("active", 10),
        )
    )

    assert result.effective_enabled is False
    assert result.within_session_window is False
    assert result.latched is True
    assert result.should_advance is True
    assert result.session_window_active is False
    assert result.finish_requested is True


def test_ready_export_uses_maximum_and_latest_bounded_start() -> None:
    result = evaluate_foxess_export_policy(_context())

    assert result.effective_enabled is True
    assert result.within_session_window is True
    assert result.source_available is True
    assert result.discharge_max_kw == 15.0
    assert result.requested_power_kw == 15.0
    assert result.automatic_remaining_kwh == 20.0
    assert result.protected_ev_kwh == 0.0
    assert result.export_plan == ExportPlan(26.0, 20.0, 1.333, "ready")
    assert result.planned_start == datetime(
        2026, 9, 5, 19, 40, 1, 200000, tzinfo=UTC
    )
    assert result.eligible is True
    assert result.latched is False
    assert result.should_advance is True
    assert result.session_window_active is True
    assert result.finish_requested is False


def test_ev_priority_withholds_idle_export_but_keeps_candidate_plan() -> None:
    result = evaluate_foxess_export_policy(
        _context(
            before_export_enabled=True,
            ev_soc_percent=25.0,
            before_export_target_percent=40.0,
        )
    )

    assert result.before_export_decision.reason == "ev_below_target"
    assert result.effective_enabled is False
    assert result.export_plan is not None
    assert result.eligible is True
    assert result.should_advance is False
    assert result.session_window_active is False
    assert result.finish_requested is True


def test_latched_export_advances_to_finish_when_ev_priority_changes() -> None:
    result = evaluate_foxess_export_policy(
        _context(
            before_export_enabled=True,
            ev_soc_percent=25.0,
            session=ExportSessionState("active", 10.0),
        )
    )

    assert result.effective_enabled is False
    assert result.latched is True
    assert result.should_advance is True
    assert result.finish_requested is True


def test_invalid_export_counter_preserves_both_previous_publications() -> None:
    result = evaluate_foxess_export_policy(
        _context(
            exported_kwh="invalid",
            previous_automatic_remaining_kwh=7.0,
            previous_protected_ev_kwh=3.0,
        )
    )

    assert result.automatic_remaining_kwh == 7.0
    assert result.protected_ev_kwh == 3.0
    assert result.export_plan is None
    assert result.planned_start is None
    assert result.eligible is False
    assert result.should_advance is False


def test_later_invalid_input_keeps_new_partial_publications() -> None:
    result = evaluate_foxess_export_policy(
        _context(
            protected_house_kwh="invalid",
            protected_ev_kwh=2.0,
            previous_automatic_remaining_kwh=7.0,
            previous_protected_ev_kwh=3.0,
        )
    )

    assert result.automatic_remaining_kwh == 20.0
    assert result.protected_ev_kwh == 2.0
    assert result.export_plan is None
    assert result.planned_start is None


def test_missing_planning_input_retains_known_accounting_without_plan() -> None:
    result = evaluate_foxess_export_policy(
        _context(available_after_reserve_kwh=None)
    )

    assert result.automatic_remaining_kwh == 20.0
    assert result.protected_ev_kwh == 0.0
    assert result.export_plan is None
    assert result.eligible is False
    assert result.should_advance is False


def test_missing_mode_capability_is_delegated_to_session_reconciliation() -> None:
    result = evaluate_foxess_export_policy(
        _context(source_capability_available=False)
    )

    assert result.source_available is False
    assert result.export_plan is not None
    assert result.eligible is True
    assert result.should_advance is True


def test_window_and_power_boundaries_preserve_session_inputs() -> None:
    result = evaluate_foxess_export_policy(
        _context(
            now=FINISH,
            configured_max_kw=-1.0,
            observed_max_kw=10.0,
            session=ExportSessionState("recovering", 8.0),
        )
    )

    assert result.within_session_window is False
    assert result.discharge_max_kw == 0.0
    assert result.source_available is True
    assert result.export_plan is None
    assert result.latched is True
    assert result.should_advance is True
    assert result.session_window_active is False
    assert result.finish_requested is True
