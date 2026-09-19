import pytest

from custom_components.home_energy_orchestrator.planner.ev_power_constraints import (
    inverter_backed_current_ceiling,
)


def _ceiling(**changes: float | int) -> float:
    values: dict[str, float | int] = {
        "inverter_output_limit_kw": 15,
        "outside_inverter_percent": 30,
        "voltage_v": 230,
        "phase_count": 3,
        "current_step_a": 1,
        "charger_maximum_a": 16,
    }
    values.update(changes)
    return inverter_backed_current_ceiling(**values)


def test_three_phase_constraint_uses_inverter_power_not_ev_current_percentage():
    assert _ceiling() == 6


def test_constraint_steps_down_and_obeys_physical_charger_ceiling():
    assert _ceiling(current_step_a=2) == 6
    assert _ceiling(charger_maximum_a=5) == 5


def test_zero_percent_fails_closed_to_zero_current():
    assert _ceiling(outside_inverter_percent=0) == 0


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("outside_inverter_percent", 101),
        ("voltage_v", 0),
        ("phase_count", 0),
        ("current_step_a", 0),
        ("charger_maximum_a", -1),
    ),
)
def test_invalid_constraint_inputs_are_rejected(name: str, value: float):
    with pytest.raises(ValueError):
        _ceiling(**{name: value})
