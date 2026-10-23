"""Both real writers arbitrate prompt surplus against qualified price export.

The synthetic native provider reports actual measurements separately from
optimistic service acknowledgements. No live system or external API is used.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tests import test_ev_export_handoff_lifecycle as lifecycle
from tests.test_aemo_dispatch_feed import dispatch_report


async def _site(hass, monkeypatch, *, minimum_enabled=False, baseline=0):
    original_data = lifecycle._ev_entry_data
    original_vehicle = lifecycle._vehicle

    def data(**values):
        return original_data(**{
            **values,
            "ev_pre_free_backfill_enabled": True,
            "ev_pre_free_backfill_timing": "when_connected",
            "ev_daily_ready_time": "07:00:00",
            "ev_daily_backfill_energy_kwh": 0,
            "ev_before_export_enabled": minimum_enabled,
            "ev_protected_baseline_a": baseline,
            "free_charge_window_start": "12:00:00",
            "free_charge_window_end": "15:00:00",
        })

    def vehicle(rig, at, **values):
        values.setdefault("soc", 45)
        return original_vehicle(rig, at, **values)

    monkeypatch.setattr(lifecycle, "_ev_entry_data", data)
    monkeypatch.setattr(lifecycle, "_vehicle", vehicle)
    return await lifecycle._site(hass, monkeypatch, price=True)


async def _publish(rig, at, *, current=0, request=6, soc=45):
    lifecycle._vehicle(rig, at, soc=soc, current=current, request=request)
    lifecycle._electrical(rig, at, current=current)
    lifecycle._set(rig.hass, lifecycle.LOCAL, "on", at=at)


async def _price(rig, *, high, serial):
    rig.feed.side_effect = lambda: dispatch_report(
        datetime.now(UTC), price=5000 if high else 1000, serial=serial,
    )
    await rig.entry.runtime_data.market_monitor.async_refresh()
    await rig.hass.async_block_till_done(wait_background_tasks=True)


def _force_calls(rig):
    return lifecycle._calls(rig, entity=lifecycle.MODE, value="Force Discharge")


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
@pytest.mark.parametrize("ev_first", [False, True])
@pytest.mark.parametrize("minimum_enabled", [False, True])
@pytest.mark.parametrize("baseline", [0, 1])
async def test_prompt_charge_yields_but_price_waits_for_measured_physical_handoff(
    hass, monkeypatch, freezer, ev_first, minimum_enabled, baseline,
):
    rig = await _site(hass, monkeypatch, minimum_enabled=minimum_enabled, baseline=baseline)
    try:
        at = lifecycle._at(22)
        freezer.move_to(at)
        await _publish(rig, at, current=baseline, request=max(baseline, 1))
        await lifecycle._cycle(rig, at, ev_first=ev_first)
        # EV-first startup may have to wait for the first inverter energy
        # publication and its baseline acknowledgement. Supply a genuine next
        # frame; a second control tick must be sufficient, not a latest start.
        at += timedelta(seconds=30)
        freezer.move_to(at)
        await _publish(rig, at, current=baseline, request=max(baseline, 1))
        await lifecycle._cycle(rig, at, ev_first=ev_first)
        coordinator = rig.entry.runtime_data
        ev, active = coordinator.ev_controller, coordinator.active_controller
        assert ev.target_current_a > baseline, (ev.decision_phase, ev.last_reason)
        current = ev.target_current_a
        assert current * 0.23 * rig.phases <= 7.5

        at += timedelta(seconds=30)
        freezer.move_to(at)
        await _publish(rig, at, current=current, request=current)
        await lifecycle._cycle(rig, at, ev_first=ev_first)
        rig.harness.clear_service_calls()
        await _price(rig, high=True, serial=2)
        assert active.opportunistic_price_export_requested(at)
        # Qualified intent exists even though physical current is still high.
        assert not active._ev_before_export_handoff_ready(at)
        assert not _force_calls(rig)
        await lifecycle._cycle(rig, at, ev_first=ev_first)
        assert ev.target_current_a <= baseline, (ev.decision_phase, ev.last_reason)
        assert not _force_calls(rig)
        assert active.export_session.phase == "idle"
        # A cache/service acknowledgement did not measure the physical result.
        assert float(hass.states.get("sensor.test_ev_actual_current").state) == current

        at += timedelta(seconds=30)
        freezer.move_to(at)
        await _publish(rig, at, current=baseline, request=max(baseline, 1))
        rig.harness.clear_service_calls()
        await lifecycle._cycle(rig, at, ev_first=ev_first)
        # Depending on callback order, a checkpoint may need its ordinary next
        # reconciliation, but never another physical event or a forced start.
        await coordinator.active_controller.async_reconcile()
        assert _force_calls(rig)
        assert active.export_session.authority_source == "price"
    finally:
        await lifecycle._close(rig)


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_saved_prompt_selection_requires_handoff_before_ev_restore_without_minimum(
    hass, monkeypatch, freezer,
):
    rig = await _site(hass, monkeypatch)
    try:
        at = lifecycle._at(22)
        freezer.move_to(at)
        await _publish(rig, at, current=8, request=8)
        coordinator = rig.entry.runtime_data
        await coordinator.async_refresh()
        ev = coordinator.ev_controller
        coordinator.ev_controller = None
        try:
            # Startup ordering cannot make the physical current disappear.
            assert not coordinator.active_controller._ev_before_export_handoff_ready(at)
        finally:
            coordinator.ev_controller = ev
    finally:
        await lifecycle._close(rig)


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
@pytest.mark.parametrize("ev_first", [False, True])
async def test_low_price_during_pending_stop_cannot_strand_prompt_charging(
    hass, monkeypatch, freezer, ev_first,
):
    rig = await _site(hass, monkeypatch)
    try:
        at = lifecycle._at(22)
        freezer.move_to(at)
        await _publish(rig, at)
        await lifecycle._cycle(rig, at, ev_first=ev_first)
        ev = rig.entry.runtime_data.ev_controller
        current = ev.target_current_a
        assert current > 0
        at += timedelta(seconds=30)
        freezer.move_to(at)
        await _publish(rig, at, current=current, request=current)
        await _price(rig, high=True, serial=2)
        await lifecycle._cycle(rig, at, ev_first=ev_first)
        assert not _force_calls(rig)
        at += timedelta(seconds=30)
        freezer.move_to(at)
        await _publish(rig, at)
        await _price(rig, high=False, serial=3)
        rig.harness.clear_service_calls()
        await lifecycle._cycle(rig, at, ev_first=ev_first)
        assert not rig.entry.runtime_data.active_controller.opportunistic_price_export_requested(at)
        assert not _force_calls(rig)
        assert ev.target_current_a > 0, (ev.decision_phase, ev.last_reason)
    finally:
        await lifecycle._close(rig)


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
@pytest.mark.parametrize("reason", ["cap", "reserve", "ev_minimum", "stale", "lock", "manual"])
async def test_high_price_without_full_existing_authority_is_not_a_yield_request(
    hass, monkeypatch, freezer, reason,
):
    rig = await _site(hass, monkeypatch, minimum_enabled=reason == "ev_minimum")
    try:
        at = lifecycle._at(22)
        freezer.move_to(at)
        await _publish(rig, at, current=8, request=8)
        coordinator = rig.entry.runtime_data
        await coordinator.async_refresh()
        await _price(rig, high=True, serial=2)
        if reason == "cap":
            coordinator.data = replace(coordinator.data, paid_export_kwh=30)
        elif reason == "reserve":
            lifecycle._electrical(rig, at, current=8, battery_soc=11)
            await coordinator.async_refresh()
        elif reason == "ev_minimum":
            await _publish(rig, at, current=8, request=8, soc=35)
            await coordinator.async_refresh()
        elif reason == "stale":
            lifecycle._set(
                hass, "sensor.test_grid_power", 0, {"unit_of_measurement": "kW"},
                at=at - timedelta(minutes=10),
            )
            await coordinator.async_refresh()
        elif reason == "lock":
            coordinator.update_config_value("rehearsal_mode", True)
        if reason == "manual":
            with monkeypatch.context() as patch:
                patch.setattr(coordinator, "manual_test", SimpleNamespace(is_active=True))
                assert not coordinator.active_controller.opportunistic_price_export_requested(at)
        else:
            assert not coordinator.active_controller.opportunistic_price_export_requested(at)
    finally:
        await lifecycle._close(rig)


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_changed_timing_cannot_hide_owned_current_before_ev_journal_restore(
    hass, monkeypatch, freezer,
):
    """The old prompt owner is unknown until its real persisted journal loads."""
    from custom_components.home_energy_orchestrator.ev_active import ActiveEvController

    rig = await _site(hass, monkeypatch)
    try:
        at = lifecycle._at(22)
        freezer.move_to(at)
        await _publish(rig, at, current=8, request=8)
        await lifecycle._cycle(rig, at)
        coordinator = rig.entry.runtime_data
        previous = coordinator.ev_controller
        assert previous.when_connected_owned
        await previous.async_stop()
        coordinator.update_config_value("ev_pre_free_backfill_timing", "conservative")
        replacement = ActiveEvController(hass, coordinator)
        coordinator.ev_controller = replacement
        assert not replacement._before_export_state_loaded
        rig.harness.clear_service_calls()
        await _price(rig, high=True, serial=2)
        active = coordinator.active_controller
        assert active.opportunistic_price_export_requested(at)
        await active.async_reconcile()
        assert not _force_calls(rig)
        assert active.export_session.phase == "idle"

        await replacement._async_restore()
        assert replacement._before_export_state_loaded
        assert replacement.when_connected_owned
        assert replacement.requires_export_handoff()
        await active.async_reconcile()
        assert not _force_calls(rig)

        at += timedelta(seconds=30)
        freezer.move_to(at)
        await _publish(rig, at, current=0, request=8)
        await lifecycle._cycle(rig, at)
        await active.async_reconcile()
        assert _force_calls(rig)
    finally:
        await lifecycle._close(rig)


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
@pytest.mark.parametrize("parent_enabled", [False, True])
async def test_inactive_prompt_parent_preserves_legacy_handoff_without_old_owner(
    hass, monkeypatch, freezer, parent_enabled,
):
    """The enabled choice protects independent daytime EV charging as well."""
    rig = await _site(hass, monkeypatch)
    try:
        coordinator = rig.entry.runtime_data
        coordinator.update_config_value("ev_pre_free_backfill_enabled", parent_enabled)
        at = lifecycle._at(16)
        freezer.move_to(at)
        await _publish(rig, at, current=8, request=8)
        await coordinator.async_refresh()
        ev = coordinator.ev_controller
        assert ev._before_export_state_loaded
        assert not ev.when_connected_owned
        assert coordinator.active_controller._ev_before_export_handoff_ready(at) is (
            not parent_enabled
        )
    finally:
        await lifecycle._close(rig)
