"""Tests for the pure protected export planner."""

from __future__ import annotations

import pytest

from custom_components.home_energy_orchestrator.planner.export import calculate_export_plan


def test_export_protects_house_and_ev_before_allowance() -> None:
    plan = calculate_export_plan(20, 4, 2, 10, 5)
    assert plan.sellable_energy_kwh == 14
    assert plan.planned_export_energy_kwh == 10
    assert plan.planned_duration_h == 2
    assert plan.reason == "ready"


def test_export_is_zero_when_protected_energy_consumes_budget() -> None:
    plan = calculate_export_plan(5, 4, 2, 10, 5)
    assert plan.planned_export_energy_kwh == 0
    assert plan.reason == "no_protected_energy"


def test_export_requires_positive_discharge_power() -> None:
    plan = calculate_export_plan(20, 0, 0, 10, 0)
    assert plan.planned_export_energy_kwh == 0
    assert plan.reason == "no_discharge_power"


def test_export_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError):
        calculate_export_plan(-1, 0, 0, 10, 5)
