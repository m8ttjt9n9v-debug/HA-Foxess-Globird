"""Publication gaps must not bounce an owned export between five-minute blocks."""

from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from tests import test_price_export_lifecycle as lifecycle
from tests.test_aemo_dispatch_feed import dispatch_report
from tests.test_price_export_active import MODE, NOW, seed_price_states

price_lifecycle = lifecycle.price_lifecycle


async def _refresh_measurements(harness, entry):
    seed_price_states(harness.hass)
    for entity in (MODE, "number.price_charge", "number.price_discharge"):
        state = harness.hass.states.get(entity)
        harness.hass.states.async_set(
            entity, state.state, dict(state.attributes), force_update=True,
        )
    await entry.runtime_data.async_refresh()


async def test_delayed_confirmed_blocks_continue_one_session_for_twenty_minutes(
    price_lifecycle, freezer,
):
    harness, entry, calls, feed = price_lifecycle
    active = entry.runtime_data.active_controller
    monitor = entry.runtime_data.market_monitor
    first_deadline = active.export_session.price_deadline
    calls.clear()
    for block in range(1, 5):
        boundary = NOW + timedelta(minutes=5 * block)
        # The next public report has not arrived. Repeated failures must not
        # create a new price clock or interrupt the still-bounded permission.
        freezer.move_to(boundary + timedelta(seconds=120))
        await _refresh_measurements(harness, entry)
        feed.side_effect = TimeoutError
        await monitor.async_refresh()
        await active.async_reconcile()
        assert active.export_session.phase == "active", active.last_reason
        assert (MODE, "Self Use") not in calls
        feed.side_effect = lambda: dispatch_report(dt_util.utcnow(), price=5000)
        await monitor.async_refresh()
        await active.async_reconcile()
        assert active.export_session.price_deadline > first_deadline
        first_deadline = active.export_session.price_deadline
    assert not any(entity == MODE for entity, _ in calls)
    feed.side_effect = lambda: dispatch_report(dt_util.utcnow(), price=2000, serial=2)
    await monitor.async_refresh()
    await active.async_reconcile()
    assert (MODE, "Self Use") in calls


@pytest.mark.parametrize("delay", [0, 1, 30, 60, 124, 149])
async def test_confirmed_low_during_grace_stops_without_waiting_for_timeout(
    price_lifecycle, freezer, delay,
):
    harness, entry, calls, feed = price_lifecycle
    freezer.move_to(NOW + timedelta(minutes=5, seconds=delay))
    await _refresh_measurements(harness, entry)
    calls.clear()
    feed.side_effect = lambda: dispatch_report(dt_util.utcnow(), price=2999.99)
    await entry.runtime_data.market_monitor.async_refresh()
    await entry.runtime_data.active_controller.async_reconcile()
    assert (MODE, "Self Use") in calls
    assert (MODE, "Force Discharge") not in calls


async def test_old_deadline_callback_cannot_stop_a_renewed_session(
    price_lifecycle, freezer, monkeypatch,
):
    harness, entry, calls, _ = price_lifecycle
    active = entry.runtime_data.active_controller
    callbacks = []

    def schedule(_hass, callback, _deadline):
        callbacks.append(callback)
        return lambda: None

    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.async_track_point_in_utc_time",
        schedule,
    )
    active._schedule_price_deadline()
    old_callback = callbacks[-1]
    old_deadline = active.export_session.price_deadline
    freezer.move_to(NOW + timedelta(minutes=6))
    await _refresh_measurements(harness, entry)
    await entry.runtime_data.market_monitor.async_refresh()
    await active.async_reconcile()
    assert active.export_session.price_deadline > old_deadline
    calls.clear()
    await old_callback(old_deadline)
    await harness.hass.async_block_till_done(wait_background_tasks=True)
    assert not calls


async def test_failure_grace_timer_stops_without_operator_or_successful_poll(
    price_lifecycle, freezer,
):
    harness, entry, calls, feed = price_lifecycle
    active = entry.runtime_data.active_controller
    deadline = active.export_session.price_deadline
    feed.side_effect = TimeoutError
    freezer.move_to(deadline - timedelta(seconds=1))
    await _refresh_measurements(harness, entry)
    calls.clear()
    freezer.move_to(deadline)
    async_fire_time_changed(harness.hass, dt_util.utcnow())
    await harness.hass.async_block_till_done(wait_background_tasks=True)
    assert (MODE, "Self Use") in calls
    assert (MODE, "Force Discharge") not in calls


async def test_failed_or_repeated_old_report_cannot_extend_150_second_grace(
    price_lifecycle, freezer,
):
    harness, entry, calls, feed = price_lifecycle
    monitor = entry.runtime_data.market_monitor
    active = entry.runtime_data.active_controller
    boundary = NOW + timedelta(minutes=5)
    deadline = boundary + timedelta(seconds=150)
    assert active.export_session.price_deadline == deadline
    calls.clear()
    for seconds in (1, 60, 120, 149):
        freezer.move_to(boundary + timedelta(seconds=seconds))
        await _refresh_measurements(harness, entry)
        feed.side_effect = lambda: dispatch_report(NOW, price=5000)
        await monitor.async_refresh()
        await active.async_reconcile()
        assert active.export_session.phase == "active"
        assert active.export_session.price_deadline == deadline
        assert not monitor.current_result.price_trigger_valid
    freezer.move_to(deadline)
    await _refresh_measurements(harness, entry)
    await active.async_reconcile()
    assert (MODE, "Self Use") in calls


async def test_grace_does_not_relax_electrical_measurement_freshness(
    price_lifecycle, freezer,
):
    harness, entry, calls, feed = price_lifecycle
    freezer.move_to(NOW + timedelta(minutes=6))
    feed.side_effect = TimeoutError
    calls.clear()
    await entry.runtime_data.market_monitor.async_refresh()
    await entry.runtime_data.active_controller.async_reconcile()
    assert (MODE, "Self Use") in calls
    assert (MODE, "Force Discharge") not in calls


async def test_restart_during_grace_cleans_up_without_restoring_history_as_permission(
    price_lifecycle, freezer,
):
    harness, entry, calls, feed = price_lifecycle
    await harness.unload(entry)
    freezer.move_to(NOW + timedelta(minutes=6))
    feed.side_effect = TimeoutError
    seed_price_states(harness.hass)
    calls.clear()
    await harness.setup(entry)
    await harness.hass.async_block_till_done(wait_background_tasks=True)
    assert (MODE, "Self Use") in calls
    assert (MODE, "Force Discharge") not in calls
    assert entry.runtime_data.market_monitor.export_result is None


@pytest.mark.parametrize("restriction", [
    {"APCFLAG": "1"}, {"INTERVENTION": "1"}, {"MARKETSUSPENDEDFLAG": "1"},
])
async def test_new_official_restriction_withdraws_grace_and_failure_cannot_restore_it(
    price_lifecycle, freezer, restriction,
):
    harness, entry, calls, feed = price_lifecycle
    freezer.move_to(NOW + timedelta(minutes=6))
    await _refresh_measurements(harness, entry)
    calls.clear()
    feed.side_effect = lambda: dispatch_report(dt_util.utcnow(), price=5000, **restriction)
    monitor = entry.runtime_data.market_monitor
    await monitor.async_refresh()
    await entry.runtime_data.active_controller.async_reconcile()
    assert (MODE, "Self Use") in calls
    assert monitor.export_result is None
    calls.clear()
    feed.side_effect = TimeoutError
    await monitor.async_refresh()
    await entry.runtime_data.active_controller.async_reconcile()
    assert (MODE, "Force Discharge") not in calls


async def test_confirmed_low_then_outage_cannot_resurrect_previous_high(
    price_lifecycle, freezer,
):
    harness, entry, calls, feed = price_lifecycle
    freezer.move_to(NOW + timedelta(minutes=6))
    await _refresh_measurements(harness, entry)
    feed.side_effect = lambda: dispatch_report(dt_util.utcnow(), price=2000)
    await entry.runtime_data.market_monitor.async_refresh()
    await entry.runtime_data.active_controller.async_reconcile()
    calls.clear()
    feed.side_effect = TimeoutError
    await entry.runtime_data.market_monitor.async_refresh()
    await entry.runtime_data.active_controller.async_reconcile()
    assert (MODE, "Force Discharge") not in calls
