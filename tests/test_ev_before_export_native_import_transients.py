"""Publisher-clock and delayed-current regression for native Tessie feedback."""

from datetime import timedelta

import pytest

from tests.test_ev_backfill_timing import _fresh, _services
from tests.test_ev_before_export_await_cohort import _running
from tests.test_ev_before_export_source_clocks import (
    native_provider_cleanup as native_provider_cleanup,
)
from tests.test_ev_before_export_source_clocks import utc_clock as utc_clock


@pytest.mark.parametrize("actual", [0, 8])
async def test_native_current_lag_and_short_import_do_not_cancel_start(hass, freezer, actual):
    rig = _running(hass, freezer)
    calls = _services(hass)
    hass.states.async_set("switch.car_charge", "off")
    hass.states.async_set("sensor.car_charging", "stopped")
    rig.provider.data["charge_state_charging_state"] = "Stopped"
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.target_current_a == 8
    assert any(call[:2] == ("switch", "turn_on") for call in calls)
    # A matching request and switch may arrive before measured charging current.
    # Both still belong to one genuine, current native charge-state frame.
    for seconds, grid in [(30, 0.6), (40, -0.1), (60, 1.7), (70, 0)]:
        now = rig.now + timedelta(seconds=seconds)
        freezer.move_to(now)
        hass.states.async_set("switch.car_charge", "on")
        hass.states.async_set("sensor.car_charging", "charging")
        for state in hass.states.async_all():
            hass.states.async_set(state.entity_id, state.state, dict(state.attributes),
                                  force_update=True)
        hass.states.async_set("sensor.car_actual_current", str(actual),
                              {"unit_of_measurement": "A"})
        rig.provider.data = {
            **rig.provider.data,
            "charge_state_charging_state": "Charging",
            "charge_state_charger_actual_current": actual,
            "charge_state_timestamp": now.timestamp() * 1000,
        }
        _fresh(rig.coordinator, now, current_a=actual, grid_kw=grid)
        await rig.controller.async_reconcile(now)
        assert rig.controller.target_current_a == 8
        assert not rig.controller.daily_backfill_stop_pending
    assert not any(call[:2] == ("switch", "turn_off") for call in calls)


async def test_native_failed_publisher_is_not_hidden_by_import_filter(hass, freezer):
    rig = _running(hass, freezer)
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    now = rig.now + timedelta(seconds=30)
    freezer.move_to(now)
    _fresh(rig.coordinator, now, current_a=8, grid_kw=0.5)
    rig.provider.last_update_success = False
    await rig.controller.async_reconcile(now)
    assert rig.controller.target_current_a == 0
    assert any(call[:2] == ("switch", "turn_off") for call in calls)
