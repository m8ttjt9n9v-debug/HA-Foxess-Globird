from custom_components.home_energy_orchestrator.models import SiteSnapshot
from custom_components.home_energy_orchestrator.planner.ledger import calculate_ledger


def snapshot(**changes):
    defaults = dict(
        battery_soc=60,
        battery_capacity_kwh=20,
        battery_floor_percent=10,
        reserve_kwh=2,
        grid_power_kw=1.2,
        house_load_kw=0.8,
        ev_max_current_a=32,
        ev_voltage_v=230,
    )
    defaults.update(changes)
    return SiteSnapshot(**defaults)


def test_floor_and_reserve_are_each_subtracted_once():
    ledger = calculate_ledger(snapshot())
    assert ledger.battery_energy_kwh == 12
    assert ledger.floor_energy_kwh == 2
    assert ledger.available_after_floor_kwh == 10
    assert ledger.available_after_reserve_kwh == 8


def test_energy_never_becomes_negative():
    ledger = calculate_ledger(snapshot(battery_soc=0, reserve_kwh=50))
    assert ledger.available_after_floor_kwh == 0
    assert ledger.available_after_reserve_kwh == 0


def test_grid_direction_and_configured_ev_cap_are_exposed():
    ledger = calculate_ledger(snapshot(grid_power_kw=-3.5))
    assert ledger.grid_import_kw == 0
    assert ledger.grid_export_kw == 3.5
    assert ledger.ev_max_power_kw == 7.36


def test_missing_required_soc_produces_a_reason_not_a_false_value():
    ledger = calculate_ledger(snapshot(battery_soc=None))
    assert ledger.available_after_reserve_kwh is None
    assert ledger.reason == "missing_battery_soc"
