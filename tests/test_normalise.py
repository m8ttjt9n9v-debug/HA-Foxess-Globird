import pytest

from custom_components.home_energy_orchestrator.normalise import (
    percent,
    power_to_kw,
    signed_grid_power_to_import_kw,
)


@pytest.mark.parametrize(
    ("value", "unit", "expected"), [(1000, "W", 1), (1, "kW", 1), (0.001, "MW", 1)]
)
def test_power_units_normalise_once(value, unit, expected):
    assert power_to_kw(value, unit) == expected


def test_unknown_power_unit_is_not_treated_as_zero():
    with pytest.raises(ValueError):
        power_to_kw(1, "A")


def test_grid_sign_is_explicit():
    assert signed_grid_power_to_import_kw(2, True) == 2
    assert signed_grid_power_to_import_kw(2, False) == -2


@pytest.mark.parametrize("value", [-1, 101])
def test_invalid_percent_is_rejected(value):
    with pytest.raises(ValueError):
        percent(value)
