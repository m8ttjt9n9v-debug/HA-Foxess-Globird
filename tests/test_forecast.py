from __future__ import annotations

from datetime import date

import pytest

from custom_components.home_energy_orchestrator.planner.forecast import (
    ForecastFeedbackState,
    calculate_optimistic_cost_forecast,
    update_cost_bias,
    update_export_realisation_fraction,
)


def test_optimistic_forecast_assumes_credit_and_tariffed_export() -> None:
    forecast = calculate_optimistic_cost_forecast(
        measured_gross_cost=2.0,
        measured_export_revenue=0.2,
        assumed_zerohero_credit=1.0,
        planned_remaining_export_kwh=20.0,
        export_realisation_fraction=0.75,
        forecast_additional_export_revenue=1.5,
        learned_cost_bias=0.1,
    )

    assert forecast.forecast_remaining_export_kwh == 15.0
    assert forecast.raw_net_cost == pytest.approx(-0.7)
    assert forecast.calibrated_net_cost == pytest.approx(-0.6)


def test_export_realisation_learning_is_bounded_per_day() -> None:
    assert update_export_realisation_fraction(
        0.75, planned_export_kwh=20, realised_export_kwh=20
    ) == pytest.approx(0.77)
    assert update_export_realisation_fraction(
        0.75, planned_export_kwh=20, realised_export_kwh=5
    ) == pytest.approx(0.73)


def test_export_realisation_learning_rejects_missing_plan() -> None:
    with pytest.raises(ValueError):
        update_export_realisation_fraction(
            0.75, planned_export_kwh=0, realised_export_kwh=0
        )


def test_cost_bias_moves_slowly_toward_retailer_error() -> None:
    assert update_cost_bias(
        0.0,
        forecast_cost=-1.0,
        actual_cost=0.5,
        zerohero_achieved=True,
    ) == pytest.approx(0.1)
    assert update_cost_bias(
        0.0,
        forecast_cost=1.0,
        actual_cost=0.5,
        zerohero_achieved=True,
    ) == pytest.approx(-0.1)


def test_failed_zerohero_is_scored_but_does_not_train_cost_bias() -> None:
    assert update_cost_bias(
        0.25,
        forecast_cost=-1.0,
        actual_cost=0.5,
        zerohero_achieved=False,
    ) == pytest.approx(0.25)


def test_feedback_state_persists_plan_and_learns_realisation_at_rollover() -> None:
    state = ForecastFeedbackState.restore(None, today=date(2026, 9, 15))
    state.observe_export(planned_total_kwh=20, realised_kwh=14)
    state.freeze(
        calculate_optimistic_cost_forecast(
            measured_gross_cost=2,
            measured_export_revenue=0,
            assumed_zerohero_credit=1,
            planned_remaining_export_kwh=20,
            export_realisation_fraction=0.75,
            forecast_additional_export_revenue=1.5,
            learned_cost_bias=0,
        )
    )

    assert state.roll_to(date(2026, 9, 16))
    assert state.export_realisation_fraction == pytest.approx(0.74)
    record = state.record_for(date(2026, 9, 15))
    assert record is not None
    assert record.export_realisation_ratio == pytest.approx(0.7)


def test_retailer_match_scores_once_and_skips_bias_for_failed_credit() -> None:
    state = ForecastFeedbackState.restore(None, today=date(2026, 9, 15))
    state.freeze(
        calculate_optimistic_cost_forecast(
            measured_gross_cost=2,
            measured_export_revenue=0,
            assumed_zerohero_credit=1,
            planned_remaining_export_kwh=0,
            export_realisation_fraction=0.75,
            forecast_additional_export_revenue=0,
            learned_cost_bias=0,
        )
    )
    state.roll_to(date(2026, 9, 16))

    assert state.match_retailer(
        result_date=date(2026, 9, 15),
        actual_cost=2,
        zerohero_status="not_achieved",
    ) == "matched_credit_not_achieved"
    assert state.learned_cost_bias == 0
    assert state.match_retailer(
        result_date=date(2026, 9, 15),
        actual_cost=2,
        zerohero_status="not_achieved",
    ) == "matched_credit_not_achieved"
    assert state.learned_cost_bias == 0


def test_feedback_restore_rejects_malformed_state_without_crashing() -> None:
    state = ForecastFeedbackState.restore(
        {
            "current": {"date": "bad"},
            "export_realisation_fraction": "nan",
            "history": [{"date": "also-bad"}],
        },
        today=date(2026, 9, 16),
    )
    assert state.current.local_date == date(2026, 9, 16)
    assert state.export_realisation_fraction == pytest.approx(0.75)
