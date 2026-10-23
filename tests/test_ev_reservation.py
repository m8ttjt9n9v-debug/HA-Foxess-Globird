"""One conserved house/EV/export pool, with current-SoC reservation only."""

from dataclasses import FrozenInstanceError, replace

import pytest

from custom_components.home_energy_orchestrator.planner.ev_reservation import (
    EvReservationInputs,
    calculate_ev_reservation_budget,
)
from custom_components.home_energy_orchestrator.planner.export import calculate_export_plan


def _inputs(**changes):
    return replace(EvReservationInputs(
        available_ac_after_reserve_kwh=20,
        protected_house_kwh=6,
        keepalive_kwh=2,
        mode="dynamic",
        fixed_remaining_kwh=5,
        soc_percent=30,
        minimum_soc_percent=40,
        buffer_soc_percent=2,
        normal_target_soc_percent=90,
        capacity_kwh=60,
        charge_efficiency_percent=90,
    ), **changes)


def test_dynamic_reservation_splits_one_pool_and_ev_can_use_its_own_share():
    inputs = _inputs()
    budget = calculate_ev_reservation_budget(inputs)
    assert budget.valid
    assert budget.target_soc_percent == 42
    assert budget.requested_reservation_kwh == 8
    assert budget.available_after_house_kwh == 14
    assert budget.ev_available_kwh == 12
    assert budget.funded_reservation_kwh == 8
    assert budget.protected_ev_kwh == 10
    assert budget.exportable_kwh == 4
    assert budget.reservation_shortfall_kwh == 0
    assert inputs.protected_house_kwh + inputs.keepalive_kwh + (
        budget.funded_reservation_kwh + budget.exportable_kwh
    ) == inputs.available_ac_after_reserve_kwh
    exported = calculate_export_plan(20, 6, budget.protected_ev_kwh, 100, 10)
    assert exported.sellable_energy_kwh == budget.exportable_kwh
    with pytest.raises(FrozenInstanceError):
        budget.ev_available_kwh = 20


@pytest.mark.parametrize("available,ev_available,funded,exportable,shortfall", [
    (30, 22, 8, 14, 0),
    (16, 8, 8, 0, 0),
    (12, 4, 4, 0, 4),
    (8, 0, 0, 0, 8),
    (7, 0, 0, 0, 8),
    (0, 0, 0, 0, 8),
])
def test_reservation_cannot_manufacture_energy_or_strand_its_funded_share(
    available, ev_available, funded, exportable, shortfall,
):
    budget = calculate_ev_reservation_budget(_inputs(available_ac_after_reserve_kwh=available))
    assert budget.valid
    assert budget.ev_available_kwh == ev_available
    assert budget.funded_reservation_kwh == funded
    assert budget.exportable_kwh == exportable
    assert budget.reservation_shortfall_kwh == shortfall
    if ev_available > 0 and exportable == 0:
        assert budget.ev_available_kwh == budget.funded_reservation_kwh


@pytest.mark.parametrize("soc,deficit", [
    (0, 42), (39.999, 2.001), (40, 2), (40.001, 1.999),
    (41.999, 0.001), (42, 0), (42.001, 0), (100, 0),
])
def test_dynamic_deficit_at_both_human_minimum_and_buffer_boundaries(soc, deficit):
    budget = calculate_ev_reservation_budget(_inputs(soc_percent=soc))
    assert budget.valid
    assert budget.requested_reservation_kwh == pytest.approx(60 * deficit / 90)
    assert budget.ev_available_kwh == 12
    assert budget.exportable_kwh == pytest.approx(max(12 - 60 * deficit / 90, 0))


def test_jitter_and_slow_drift_change_only_current_deficit_without_new_latches():
    readings = [39.9, 40, 40.1, 39.9, 40, 40.1, 41.9, 42, 42.1, 41.9, 42]
    budgets = [calculate_ev_reservation_budget(_inputs(soc_percent=soc)) for soc in readings]
    assert all(budget.valid for budget in budgets)
    for soc, budget in zip(readings, budgets, strict=True):
        # Recomputing after reconnect/restart needs current evidence, not a
        # retained budget or yesterday's delivered-energy deduction.
        assert budget == calculate_ev_reservation_budget(_inputs(soc_percent=soc))
    assert budgets[0] == budgets[3]
    assert budgets[6] == budgets[9]
    drifting = [calculate_ev_reservation_budget(_inputs(soc_percent=soc))
                for soc in range(30, 44)]
    assert all(left.requested_reservation_kwh >= right.requested_reservation_kwh
               for left, right in zip(drifting, drifting[1:]))
    assert all(left.exportable_kwh <= right.exportable_kwh
               for left, right in zip(drifting, drifting[1:]))


@pytest.mark.parametrize("minimum,buffer,normal,target", [
    (40, 0, 90, 40), (40, 2, 41, 41), (40, 2, 38, 38),
    (99, 5, 100, 100), (100, 100, 100, 100), (0, 0, 0, 0),
])
def test_target_buffer_never_overrides_normal_soc_limit(minimum, buffer, normal, target):
    budget = calculate_ev_reservation_budget(_inputs(
        minimum_soc_percent=minimum, buffer_soc_percent=buffer,
        normal_target_soc_percent=normal,
    ))
    assert budget.valid and budget.target_soc_percent == target
    assert budget.requested_reservation_kwh == pytest.approx(60 * max(target - 30, 0) / 90)


@pytest.mark.parametrize("efficiency,expected", [(100, 7.2), (90, 8), (50, 14.4)])
def test_charge_losses_increase_wall_reservation_once(efficiency, expected):
    budget = calculate_ev_reservation_budget(_inputs(charge_efficiency_percent=efficiency))
    assert budget.valid and budget.requested_reservation_kwh == pytest.approx(expected)
    assert budget.ev_available_kwh == 12


@pytest.mark.parametrize("fixed", [0, 5, 100, None, float("nan")])
def test_dynamic_does_not_add_or_depend_on_old_fixed_allocation(fixed):
    budget = calculate_ev_reservation_budget(_inputs(fixed_remaining_kwh=fixed))
    assert budget.valid and budget.requested_reservation_kwh == 8
    assert budget.exportable_kwh == 4


def test_fixed_uses_only_already_reduced_ready_cycle_remainder():
    inputs = _inputs(mode="fixed", fixed_remaining_kwh=5, soc_percent=None, capacity_kwh=None)
    budget = calculate_ev_reservation_budget(inputs)
    assert budget.valid and budget.target_soc_percent is None
    assert budget.requested_reservation_kwh == 5
    assert budget.exportable_kwh == 7
    assert budget.ev_available_kwh == 12
    delivered = calculate_ev_reservation_budget(replace(inputs, fixed_remaining_kwh=3))
    assert delivered.requested_reservation_kwh == 3 and delivered.exportable_kwh == 9


def test_disabled_dynamic_caller_can_select_fixed_zero_without_inheriting_old_reserve():
    budget = calculate_ev_reservation_budget(_inputs(mode="fixed", fixed_remaining_kwh=0))
    assert budget.valid and budget.protected_ev_kwh == 2
    assert budget.requested_reservation_kwh == 0 and budget.exportable_kwh == 12


def test_explicit_extended_away_releases_reservation_but_not_house_or_keepalive():
    normal = calculate_ev_reservation_budget(_inputs())
    away = calculate_ev_reservation_budget(_inputs(
        extended_away=True, soc_percent=None, capacity_kwh=None,
    ))
    assert normal.requested_reservation_kwh == 8
    assert away.valid and away.reason == "extended_away"
    assert away.requested_reservation_kwh == 0
    assert away.protected_ev_kwh == 2
    assert away.ev_available_kwh == away.exportable_kwh == 12
    # Absence is not an input; only an explicitly resolved bypass can release
    # the reservation. The default keeps the same current-SoC protection while
    # the vehicle is away, disconnected or its automatic presence is unknown.
    assert calculate_ev_reservation_budget(_inputs()).requested_reservation_kwh == 8


@pytest.mark.parametrize("field", [
    "available_ac_after_reserve_kwh", "protected_house_kwh", "keepalive_kwh",
])
@pytest.mark.parametrize("bad", [None, -1, True, float("nan"), float("inf")])
@pytest.mark.parametrize("extended_away", [False, True])
def test_missing_or_invalid_base_energy_never_grants_export_or_ev_authority(
    field, bad, extended_away,
):
    budget = calculate_ev_reservation_budget(_inputs(**{field: bad}, extended_away=extended_away))
    assert not budget.valid
    assert budget.ev_available_kwh == budget.exportable_kwh == 0


@pytest.mark.parametrize("field", [
    "soc_percent", "minimum_soc_percent", "buffer_soc_percent", "normal_target_soc_percent",
])
@pytest.mark.parametrize("bad", [None, -0.001, 100.001, True, float("nan"), float("inf")])
def test_invalid_current_soc_or_target_fails_closed_instead_of_guessing_reservation(field, bad):
    budget = calculate_ev_reservation_budget(_inputs(**{field: bad}))
    assert not budget.valid and budget.reason == "vehicle_soc_or_target_invalid"
    assert budget.ev_available_kwh == budget.exportable_kwh == 0


@pytest.mark.parametrize("bad", [None, 0, -1, 1000.001, True, float("nan"), float("inf")])
def test_invalid_capacity_fails_closed_even_if_current_target_has_been_reached(bad):
    budget = calculate_ev_reservation_budget(_inputs(capacity_kwh=bad, soc_percent=100))
    assert not budget.valid and budget.reason == "vehicle_capacity_invalid"
    assert budget.ev_available_kwh == budget.exportable_kwh == 0


@pytest.mark.parametrize("bad", [None, 0, -1, 100.001, True, float("nan"), float("inf")])
def test_invalid_efficiency_fails_closed(bad):
    budget = calculate_ev_reservation_budget(_inputs(charge_efficiency_percent=bad))
    assert not budget.valid and budget.reason == "charge_efficiency_invalid"
    assert budget.ev_available_kwh == budget.exportable_kwh == 0


@pytest.mark.parametrize("bad", [None, -1, True, float("nan"), float("inf")])
def test_invalid_selected_fixed_reservation_cannot_release_export(bad):
    budget = calculate_ev_reservation_budget(_inputs(mode="fixed", fixed_remaining_kwh=bad))
    assert not budget.valid and budget.reason == "fixed_reservation_invalid"
    assert budget.ev_available_kwh == budget.exportable_kwh == 0


@pytest.mark.parametrize("mode,extended_away", [
    ("unknown", False), ("unknown", True), ("dynamic", 1), (None, False), ([], False),
])
def test_invalid_mode_or_non_boolean_bypass_cannot_enable_control(mode, extended_away):
    budget = calculate_ev_reservation_budget(_inputs(mode=mode, extended_away=extended_away))
    assert not budget.valid and budget.ev_available_kwh == budget.exportable_kwh == 0


def test_setting_changes_and_withdrawn_evidence_are_applied_without_delay():
    initial = calculate_ev_reservation_budget(_inputs())
    edited = calculate_ev_reservation_budget(_inputs(buffer_soc_percent=5))
    invalid = calculate_ev_reservation_budget(_inputs(soc_percent=None))
    assert initial.requested_reservation_kwh == 8
    assert edited.requested_reservation_kwh == 10
    assert not invalid.valid and invalid.ev_available_kwh == invalid.exportable_kwh == 0
    assert calculate_ev_reservation_budget(_inputs()) == initial


def test_overflowing_reservation_cannot_become_positive_energy_authority():
    budget = calculate_ev_reservation_budget(_inputs(charge_efficiency_percent=1e-308))
    assert not budget.valid and budget.reason == "reservation_energy_invalid"
    assert budget.ev_available_kwh == budget.exportable_kwh == 0


def test_unrepresentable_integer_energy_fails_closed_without_an_exception():
    budget = calculate_ev_reservation_budget(_inputs(available_ac_after_reserve_kwh=10 ** 1000))
    assert not budget.valid and budget.ev_available_kwh == budget.exportable_kwh == 0


def test_tiny_deficit_is_not_rounded_away_before_export_protection():
    budget = calculate_ev_reservation_budget(_inputs(soc_percent=41.9999))
    assert budget.valid and 0 < budget.requested_reservation_kwh < 0.001
    assert budget.exportable_kwh < budget.ev_available_kwh
