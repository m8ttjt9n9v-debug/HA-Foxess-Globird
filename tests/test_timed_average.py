from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.timed_average import (
    TimedAverageWindow,
)

START = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def test_average_step_and_coverage_match_three_minute_feedback_semantics():
    window = TimedAverageWindow(timedelta(minutes=3))
    window.observe(START, 10, source_valid=True)
    window.observe(START + timedelta(minutes=1), 20, source_valid=True)
    window.observe(START + timedelta(minutes=2), 30, source_valid=True)
    result = window.result(START + timedelta(minutes=3))
    assert result.value == 20
    assert result.age_coverage_ratio == 1
    assert result.source_value_valid is True


def test_partial_window_reports_coverage_instead_of_claiming_full_history():
    window = TimedAverageWindow(timedelta(minutes=3))
    window.observe(START, 12, source_valid=True)
    result = window.result(START + timedelta(minutes=2))
    assert result.value == 12
    assert result.age_coverage_ratio == pytest.approx(2 / 3, abs=1e-6)


def test_latest_source_validity_is_separate_from_retained_average():
    window = TimedAverageWindow(timedelta(minutes=3))
    window.observe(START, 12, source_valid=True)
    window.observe(START + timedelta(minutes=2), 0, source_valid=False)
    result = window.result(START + timedelta(minutes=3))
    assert result.value == 8
    assert result.source_value_valid is False


def test_restart_payload_restores_coverage_and_anchor_sample():
    original = TimedAverageWindow(timedelta(minutes=3))
    original.observe(START, 10, source_valid=True)
    original.observe(START + timedelta(minutes=1), 20, source_valid=True)

    restored = TimedAverageWindow(timedelta(minutes=3))
    restored.restore(original.to_payload(), START + timedelta(minutes=2))
    restored.observe(START + timedelta(minutes=2), 30, source_valid=True)
    assert restored.result(START + timedelta(minutes=3)).value == 20


def test_corrupt_or_future_storage_fails_closed():
    window = TimedAverageWindow(timedelta(minutes=3))
    window.restore(
        {
            "samples": [
                {
                    "at": (START + timedelta(minutes=1)).isoformat(),
                    "value": 10,
                    "source_valid": True,
                }
            ]
        },
        START,
    )
    assert window.samples == []


def test_out_of_order_live_sample_is_rejected():
    window = TimedAverageWindow(timedelta(minutes=3))
    window.observe(START, 10, source_valid=True)
    with pytest.raises(ValueError):
        window.observe(START - timedelta(seconds=1), 10, source_valid=True)
