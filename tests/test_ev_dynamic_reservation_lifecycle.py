"""Dynamic reservation availability and physical handoff through real HA reloads.

The upstream provider and hardware transport remain synthetic. These scenarios
exercise the actual config entry, both controllers, storage and public entities;
no planner context or controller ownership is fabricated by the tests.
"""

from datetime import UTC, timedelta

import pytest
from homeassistant.util import dt as dt_util

from custom_components.home_energy_orchestrator.const import DOMAIN
from tests.test_aemo_dispatch_feed import dispatch_report
from tests.test_ev_connected_sleep_handoff import (
    _completed,
    _publish,
)
from tests.test_ev_connected_sleep_handoff import local_cleanup as local_cleanup
from tests.test_ev_export_handoff_lifecycle import (
    DISCHARGE,
    FIELDS,
    LOCAL,
    MODE,
    _at,
    _calls,
    _close,
    _complete_and_leave,
    _cycle,
    _electrical,
    _set,
    _site,
    _vehicle,
)
from tests.test_ev_local_connection import Publisher, native

EV_SWITCH = "switch.test_ev_charge"
EV_CURRENT = "number.test_ev_current"


@pytest.fixture(autouse=True)
async def stop_hass_after_dynamic_lifecycle(hass):
    """Complete real HA shutdown and restore the process clock for the next case."""
    yield
    await hass.async_stop()
    await hass.async_block_till_done(wait_background_tasks=True)
    dt_util.set_default_time_zone(UTC)


def _public(rig):
    return rig.hass.states.get("sensor.home_energy_status").attributes


def _trace(rig):
    state = _public(rig)
    return "; ".join(
        f"{key}={state.get(key)}" for key in (
            "ev_decision_phase", "ev_last_control_reason", "ev_export_handoff_reason",
            "export_session_phase", "ev_target_current_a",
        )
    )


def _positive_ev_calls(rig):
    return [
        call for call in rig.harness.service_calls
        if (call.service_data.get("entity_id") == EV_SWITCH and call.service == "turn_on")
        or (call.service_data.get("entity_id") == EV_CURRENT
            and call.service_data.get("value", 0) > 0)
    ]


async def _ev_journal(rig):
    return await rig.harness.load_store(f"{DOMAIN}.{rig.entry.entry_id}.ev_control")


def _assert_public_budget(rig, expected_reserve):
    available = float(rig.hass.states.get("sensor.home_energy_available_energy").state)
    house = float(rig.hass.states.get("sensor.home_energy_remaining_house_energy").state)
    sellable = float(rig.hass.states.get("sensor.home_energy_zerohero_sellable_energy").state)
    # 40 kWh * (50%-10%) - 2 kWh reserve = 14 kWh DC, then 95% AC.
    assert available == pytest.approx(14.0)
    assert house >= 0
    assert _public(rig)["export_protected_ev_kwh"] == pytest.approx(expected_reserve)
    # Price admission independently protects five seconds of discharge at
    # the configured 15 kW maximum, even when all electrical frames are fresh.
    price_margin = 15 * 5 / 3600 * 0.95 if rig.entry.data["critical_event_sell_enabled"] else 0
    assert sellable == pytest.approx(
        max(13.3 - price_margin - house - expected_reserve, 0), abs=0.002,
    )


async def _sleeping_export(rig, freezer, *, soc, ev_first=False):
    """Complete genuine initial recovery, then publish one last away frame."""
    stamp = await _complete_and_leave(
        rig, freezer, ev_first=ev_first, departure_soc=soc,
    )
    # A final frame from 19:05 remains the sole vehicle measurement at 20:55.
    at = _at(20, 55)
    freezer.move_to(at)
    _electrical(rig, at)
    _set(rig.hass, LOCAL, "off", at=at)
    if rig.entry.data["critical_event_sell_enabled"]:
        rig.feed.side_effect = lambda: dispatch_report(at, price=5000)
        await rig.entry.runtime_data.market_monitor.async_refresh()
    rig.harness.clear_service_calls()
    await _cycle(rig, at, ev_first=ev_first)
    return stamp, at


@pytest.mark.parametrize("phases", [1, 3])
@pytest.mark.parametrize("price", [False, True])
@pytest.mark.parametrize("soc,expected_reserve", [(35, 4.0), (53, 0.0)])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_dynamic_sleep_retains_budget_and_export_after_real_unload_setup(
    hass, monkeypatch, freezer, phases, price, soc, expected_reserve,
):
    rig = await _site(
        hass, monkeypatch, phases=phases, price=price, reservation_mode="dynamic",
    )
    try:
        stamp, at = await _sleeping_export(rig, freezer, soc=soc)
        clocks = {entity: hass.states.get(entity).last_reported for entity in FIELDS}
        # Independent arithmetic: 60 kWh * (41%-35%) / 90% = 4 kWh;
        # an above-target 53% vehicle reserves zero. Keepalive is configured 0 A.
        _assert_public_budget(rig, expected_reserve)
        assert _public(rig)["export_session_phase"] in {"starting", "active"}
        assert _calls(rig, entity=MODE, value="Force Discharge")
        assert not _positive_ev_calls(rig)
        before = await _ev_journal(rig)
        assert not before["before_export_recovery"]["pending"]

        await rig.harness.unload(rig.entry)
        at += timedelta(seconds=1)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        rig.harness.clear_service_calls()
        await rig.harness.setup(rig.entry)
        await _cycle(rig, at)

        _assert_public_budget(rig, expected_reserve)
        assert _public(rig)["export_session_phase"] in {"starting", "active"}
        assert hass.states.get(MODE).state == "Force Discharge"
        assert not _positive_ev_calls(rig)
        assert rig.provider.data["charge_state_timestamp"] == stamp.timestamp() * 1000
        assert clocks == {entity: hass.states.get(entity).last_reported for entity in FIELDS}
        after = await _ev_journal(rig)
        assert after["before_export_recovery"] == before["before_export_recovery"]
        export = await rig.harness.load_store(
            f"{DOMAIN}.{rig.entry.entry_id}.export_session",
        )
        assert export["phase"] in {"starting", "active"}
        assert export.get("authority_source", "zerohero") == ("price" if price else "zerohero")
        assert float(hass.states.get(DISCHARGE).state) == 15
    finally:
        await _close(rig)


@pytest.mark.parametrize("phases", [1, 3])
@pytest.mark.parametrize("price", [False, True])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_dynamic_completed_connected_sleep_keeps_native_open_contactor_handoff(
    hass, monkeypatch, freezer, phases, price,
):
    local = native(hass)
    rig = await _site(
        hass, monkeypatch, phases=phases, price=price, reservation_mode="dynamic",
    )
    try:
        await _completed(rig, local, freezer)
        stamp = _at(19, 4)
        freezer.move_to(stamp)
        _vehicle(rig, stamp, soc=53, current=0)
        _publish(rig, local, stamp)
        await _cycle(rig, stamp)
        assert not (await _ev_journal(rig))["before_export_recovery"]["pending"]
        rig.provider.data["state"] = "asleep"
        clocks = {entity: hass.states.get(entity).last_reported for entity in FIELDS}

        at = _at(20, 55)
        freezer.move_to(at)
        _publish(rig, local, at)
        if price:
            rig.feed.side_effect = lambda: dispatch_report(at, price=5000)
            await rig.entry.runtime_data.market_monitor.async_refresh()
        rig.harness.clear_service_calls()
        await _cycle(rig, at)
        assert _public(rig)["export_protected_ev_kwh"] == 0
        # Dynamic has no requested recovery above the buffered target. The
        # established native contactor proof still qualifies the stopped car;
        # retained planning SoC does not itself qualify a physical handoff.
        assert _calls(rig, entity=MODE, value="Force Discharge"), _trace(rig)
        assert _public(rig)["ev_export_handoff_reason"] == "local_connected_stopped"
        assert not _positive_ev_calls(rig)

        await rig.harness.unload(rig.entry)
        rig.harness.clear_service_calls()
        await rig.harness.setup(rig.entry)
        await _cycle(rig, at)
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        local.provider.publish(Publisher.payload(True, False))
        await _cycle(rig, at)
        assert _calls(rig, entity=MODE, value="Force Discharge")
        assert _public(rig)["ev_export_handoff_reason"] == "local_connected_stopped"
        assert not _positive_ev_calls(rig)
        assert rig.provider.data["charge_state_timestamp"] == stamp.timestamp() * 1000
        assert clocks == {entity: hass.states.get(entity).last_reported for entity in FIELDS}
    finally:
        await _close(rig)


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_dynamic_nine_hour_connected_sleep_exports_in_next_day_window(
    hass, monkeypatch, freezer,
):
    local = native(hass)
    rig = await _site(hass, monkeypatch, reservation_mode="dynamic")
    try:
        # A configured overnight opportunity is independent of the car's
        # evening publication. End+the existing one-minute offset is 04:10.
        for key, value in (
            ("bonus_window_start", "03:00:00"),
            ("bonus_window_end", "04:09:00"),
            ("force_discharge_finish", "04:10:00"),
        ):
            rig.entry.runtime_data.update_config_value(key, value)
        await _completed(rig, local, freezer)
        stamp = _at(19, 4)
        freezer.move_to(stamp)
        _vehicle(rig, stamp, soc=53, current=0)
        _publish(rig, local, stamp)
        await _cycle(rig, stamp)
        assert not (await _ev_journal(rig))["before_export_recovery"]["pending"]
        rig.provider.data["state"] = "asleep"
        clocks = {entity: hass.states.get(entity).last_reported for entity in FIELDS}

        at = stamp + timedelta(hours=9)
        assert at.date() > stamp.date() and (at.hour, at.minute) == (4, 4)
        freezer.move_to(at)
        _publish(rig, local, at)
        rig.harness.clear_service_calls()
        await _cycle(rig, at)

        assert _public(rig)["export_protected_ev_kwh"] == 0
        assert _calls(rig, entity=MODE, value="Force Discharge"), _trace(rig)
        assert _public(rig)["ev_export_handoff_reason"] == "local_connected_stopped"
        assert not _positive_ev_calls(rig)
        assert rig.provider.data["charge_state_timestamp"] == stamp.timestamp() * 1000
        assert clocks == {entity: hass.states.get(entity).last_reported for entity in FIELDS}
        journal = await _ev_journal(rig)
        assert not journal["before_export_recovery"]["pending"]
    finally:
        await _close(rig)


@pytest.mark.parametrize("behavior,requested", [("last_known", False), ("timeout", True)])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_completed_recovery_fallback_keeps_current_outage_choice_and_original_clock(
    hass, monkeypatch, freezer, behavior, requested,
):
    local = native(hass)
    rig = await _site(hass, monkeypatch, reservation_mode="dynamic")
    try:
        values = {
            "ev_reservation_unavailable_behavior": behavior,
            "ev_reservation_unplugged_soc_max_age_minutes": 90,
        }
        hass.config_entries.async_update_entry(rig.entry, data={**rig.entry.data, **values})
        for key, value in values.items():
            rig.entry.runtime_data.update_config_value(key, value)
        await _completed(rig, local, freezer)
        stamp = _at(19, 4)
        freezer.move_to(stamp)
        _vehicle(rig, stamp, soc=53, current=0)
        _publish(rig, local, stamp)
        await _cycle(rig, stamp)
        saved = await _ev_journal(rig)
        assert not saved["before_export_recovery"]["pending"]
        assert saved["reservation_soc"]["value_percent"] == 53

        at = _at(20, 55)
        freezer.move_to(at)
        rig.provider.data["state"] = "offline"
        _set(hass, "sensor.test_ev_soc", "unavailable", {"unit_of_measurement": "%"}, at=at)
        _publish(rig, local, at)
        rig.harness.clear_service_calls()
        for reload in (False, True):
            if reload:
                await rig.harness.reload(rig.entry)
                local.provider.publish(Publisher.payload(True, False))
            await _cycle(rig, at)
            ev = rig.entry.runtime_data.ev_controller
            assert ev.dynamic_topup_requested(at) is requested
            assert not ev.before_export_recovery.pending
            # Retained planning SoC never qualifies a positive EV command or
            # a physical export handoff from a failed/offline native source.
            assert not _positive_ev_calls(rig)
            assert not _calls(rig, entity=MODE, value="Force Discharge")
            restored = await _ev_journal(rig)
            assert restored["reservation_soc"] == saved["reservation_soc"]
            assert rig.provider.data["charge_state_timestamp"] == stamp.timestamp() * 1000
    finally:
        await _close(rig)


@pytest.mark.parametrize("sleeping", [False, True])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_dynamic_planning_or_handoff_cannot_complete_pending_recovery(
    hass, monkeypatch, freezer, sleeping,
):
    local = native(hass)
    rig = await _site(hass, monkeypatch, reservation_mode="dynamic")
    try:
        # Setup genuinely observes below-minimum 39%, which arms the journal.
        assert (await _ev_journal(rig))["before_export_recovery"]["pending"]
        at = _at(19, 1) if sleeping else _at(20, 55)
        freezer.move_to(at)
        _vehicle(rig, at, soc=53, current=0)
        if sleeping:
            # A new above-target frame can arrive before EV reconciliation;
            # going asleep cannot manufacture a completed persistence step.
            rig.provider.data["state"] = "asleep"
            at = _at(20, 55)
            freezer.move_to(at)
        _publish(rig, local, at)
        rig.harness.clear_service_calls()
        coordinator = rig.entry.runtime_data
        await coordinator.async_refresh()
        # Explicit active-first boundary: read-only planning/physical proof
        # cannot acknowledge the other controller's outstanding journal.
        await coordinator.active_controller.async_reconcile()
        assert not _calls(rig, entity=MODE, value="Force Discharge"), _trace(rig)
        assert (await _ev_journal(rig))["before_export_recovery"]["pending"]
        if sleeping:
            await rig.harness.unload(rig.entry)
            await rig.harness.setup(rig.entry)
            local.provider.publish(Publisher.payload(True, False))
            await _cycle(rig, at)
            assert not _calls(rig, entity=MODE, value="Force Discharge")
            assert (await _ev_journal(rig))["before_export_recovery"]["pending"]

        # Qualified fresh evidence, processed by the EV checkpoint, completes
        # the obligation; then the existing stopped-car handoff can progress.
        at += timedelta(seconds=30)
        freezer.move_to(at)
        _vehicle(rig, at, soc=53, current=0)
        _publish(rig, local, at)
        await _cycle(rig, at, ev_first=True)
        at += timedelta(seconds=30)
        freezer.move_to(at)
        _vehicle(rig, at, soc=53, current=0)
        _publish(rig, local, at)
        await _cycle(rig, at, ev_first=True)
        assert not (await _ev_journal(rig))["before_export_recovery"]["pending"]
        assert _calls(rig, entity=MODE, value="Force Discharge"), _trace(rig)
        assert not _positive_ev_calls(rig)
    finally:
        await _close(rig)


@pytest.mark.parametrize("reservation_mode", ["dynamic", "fixed"])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_dynamic_recovery_ceiling_completes_checkpoint_without_changing_fixed_minimum(
    hass, monkeypatch, freezer, reservation_mode,
):
    rig = await _site(
        hass, monkeypatch, reservation_mode=reservation_mode, minimum_soc=95,
    )
    try:
        at = _at(19, 1)
        freezer.move_to(at)
        current = _public(rig)["ev_target_current_a"] or 6
        _vehicle(rig, at, soc=89, current=current, request=current)
        _electrical(rig, at, current=current)
        _set(hass, LOCAL, "on", at=at)
        await _cycle(rig, at)
        assert (await _ev_journal(rig))["before_export_recovery"]["pending"]
        assert _public(rig)["ev_target_current_a"] > 0, _trace(rig)
        assert not _calls(rig, entity=MODE, value="Force Discharge")

        # The normal configured ceiling is 90%. Dynamic's energy budget and
        # its real recovery checkpoint must agree on that permitted target;
        # a raw 95% export preference grants no authority to charge above it.
        at += timedelta(minutes=1)
        freezer.move_to(at)
        _vehicle(rig, at, soc=90, current=current, request=current)
        _electrical(rig, at, current=current)
        _set(hass, LOCAL, "on", at=at)
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=True)
        expected_pending = reservation_mode == "fixed"
        assert (await _ev_journal(rig))["before_export_recovery"]["pending"] is expected_pending
        assert _public(rig)["ev_target_current_a"] == 0
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert not _positive_ev_calls(rig)

        # Real measured zero follows the stop acknowledgement. Then let the
        # ordinary export window reach its latest-start opportunity.
        at += timedelta(seconds=30)
        freezer.move_to(at)
        _vehicle(rig, at, soc=90, current=0)
        _electrical(rig, at)
        _set(hass, LOCAL, "on", at=at)
        await _cycle(rig, at, ev_first=True)
        at = _at(20, 55)
        freezer.move_to(at)
        _vehicle(rig, at, soc=90, current=0)
        _electrical(rig, at)
        _set(hass, LOCAL, "on", at=at)
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=True)
        assert bool(_calls(rig, entity=MODE, value="Force Discharge")) is not expected_pending
        before = await _ev_journal(rig)
        assert before["before_export_recovery"]["pending"] is expected_pending

        await rig.harness.unload(rig.entry)
        rig.harness.clear_service_calls()
        await rig.harness.setup(rig.entry)
        await _cycle(rig, at, ev_first=True)
        after = await _ev_journal(rig)
        assert after["before_export_recovery"] == before["before_export_recovery"]
        assert (hass.states.get(MODE).state == "Force Discharge") is not expected_pending
        assert not _positive_ev_calls(rig)
    finally:
        await _close(rig)


@pytest.mark.parametrize("phases,ev_first", [(1, False), (3, True)])
@pytest.mark.parametrize("price", [False, True])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_dynamic_return_finishes_export_then_preserves_buffer_across_reload(
    hass, monkeypatch, freezer, phases, ev_first, price,
):
    rig = await _site(
        hass, monkeypatch, phases=phases, price=price, reservation_mode="dynamic",
    )
    try:
        stamp, at = await _sleeping_export(rig, freezer, soc=35, ev_first=ev_first)
        assert _calls(rig, entity=MODE, value="Force Discharge")
        assert _public(rig)["export_protected_ev_kwh"] == pytest.approx(4.0)

        # The local plug event precedes the sleeping vehicle's wake. Its old
        # planning frame cannot start EV charging or preserve forced export.
        at += timedelta(seconds=1)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "on", at=at)
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=ev_first)
        assert _calls(rig, entity=MODE, value="Self Use")
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert not _positive_ev_calls(rig)
        assert rig.provider.data["charge_state_timestamp"] == stamp.timestamp() * 1000

        # Fresh below-minimum vehicle evidence and settled inverter cleanup
        # must eventually restore the existing EV recovery writer.
        for _ in range(2):
            at += timedelta(seconds=30)
            freezer.move_to(at)
            _vehicle(rig, at, soc=39)
            _electrical(rig, at, mode="Self Use")
            _set(hass, LOCAL, "on", at=at)
            await _cycle(rig, at, ev_first=ev_first)
        assert _positive_ev_calls(rig)
        trace = list(rig.harness.service_calls)
        assert trace.index(_calls(rig, entity=MODE, value="Self Use")[0]) < trace.index(
            _positive_ev_calls(rig)[0],
        )
        assert trace.index(_calls(rig, entity=DISCHARGE, value=0)[0]) < trace.index(
            _positive_ev_calls(rig)[0],
        )
        assert _public(rig)["ev_decision_phase"] == "ev_before_export_charging"
        assert _public(rig)["ev_target_current_a"] > 0
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert hass.states.get(MODE).state == "Self Use"
        journal = await _ev_journal(rig)
        assert journal["before_export_recovery"]["pending"]

        # Reaching the 40% admission threshold must not clear a 41% recovery.
        at += timedelta(seconds=30)
        freezer.move_to(at)
        current = _public(rig)["ev_target_current_a"]
        _vehicle(rig, at, soc=40, current=current, request=current)
        _electrical(rig, at, current=current, mode="Self Use")
        _set(hass, LOCAL, "on", at=at)
        await _cycle(rig, at, ev_first=ev_first)
        before = await _ev_journal(rig)
        assert before["before_export_recovery"]["pending"]
        await rig.harness.unload(rig.entry)
        rig.harness.clear_service_calls()
        await rig.harness.setup(rig.entry)
        await _cycle(rig, at, ev_first=ev_first)
        restored = await _ev_journal(rig)
        assert restored["before_export_recovery"] == before["before_export_recovery"]
        assert not _calls(rig, entity=MODE, value="Force Discharge")

        # Unload requests a real stop. Its optimistic acknowledgement cannot
        # prove the current has fallen; supply subsequent measured stop frames
        # before expecting resumed buffered charging after startup.
        for _ in range(2):
            at += timedelta(seconds=1)
            freezer.move_to(at)
            _vehicle(rig, at, soc=40, current=0)
            _electrical(rig, at, mode="Self Use")
            _set(hass, LOCAL, "on", at=at)
            await _cycle(rig, at, ev_first=ev_first)
            assert (await _ev_journal(rig))["before_export_recovery"]["pending"]
            assert not _calls(rig, entity=MODE, value="Force Discharge")

        for soc in (40, 40.9):
            at += timedelta(seconds=30)
            freezer.move_to(at)
            current = _public(rig)["ev_target_current_a"]
            _vehicle(rig, at, soc=soc, current=current, request=current)
            _electrical(rig, at, current=current, mode="Self Use")
            _set(hass, LOCAL, "on", at=at)
            await _cycle(rig, at, ev_first=ev_first)
            assert (await _ev_journal(rig))["before_export_recovery"]["pending"]
            assert _public(rig)["ev_target_current_a"] > 0, _trace(rig)
            assert not _calls(rig, entity=MODE, value="Force Discharge")

        # Even at the buffered target, actual charging current still requires
        # a measured stop before the inverter may resume forced export.
        at += timedelta(seconds=30)
        freezer.move_to(at)
        current = _public(rig)["ev_target_current_a"]
        _vehicle(rig, at, soc=41, current=current, request=current)
        _electrical(rig, at, current=current, mode="Self Use")
        _set(hass, LOCAL, "on", at=at)
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=ev_first)
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert _public(rig)["ev_target_current_a"] == 0

        at += timedelta(seconds=30)
        freezer.move_to(at)
        _vehicle(rig, at, soc=41, current=0)
        _electrical(rig, at, mode="Self Use")
        _set(hass, LOCAL, "on", at=at)
        await _cycle(rig, at, ev_first=ev_first)
        assert not (await _ev_journal(rig))["before_export_recovery"]["pending"]
        assert _calls(rig, entity=MODE, value="Force Discharge")
        assert _public(rig)["export_protected_ev_kwh"] == 0
        assert _public(rig)["ev_target_current_a"] == 0
    finally:
        await _close(rig)
