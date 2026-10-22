"""A stopped connected car may sleep without revoking local export proof."""

from datetime import timedelta

import pytest

from tests.test_ev_export_handoff_lifecycle import (
    DISCHARGE,
    FIELDS,
    LOCAL,
    MODE,
    _at,
    _calls,
    _close,
    _cycle,
    _electrical,
    _set,
    _site,
    _vehicle,
)
from tests.test_ev_local_connection import Publisher, native


@pytest.fixture(autouse=True)
async def local_cleanup(hass):
    from homeassistant.config_entries import ConfigEntryState

    yield
    for entry in hass.config_entries.async_entries("tesla_wall_connector"):
        entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    await hass.async_block_till_done()


def _publish(rig, local, at, *, connected=True, contactor=False):
    _electrical(rig, at)
    _set(rig.hass, LOCAL, "on" if connected else "off", at=at)
    local.provider.publish(Publisher.payload(connected, contactor))


async def _completed(rig, local, freezer, *, ev_first=False):
    """Full real buffered top-up and measured stop, with the cable kept in."""
    ev = rig.entry.runtime_data.ev_controller
    for minute, soc in ((0, 39), (1, 40), (2, 41)):
        at = _at(19, minute)
        freezer.move_to(at)
        amps = ev.target_current_a or 6
        _vehicle(rig, at, soc=soc, current=amps, request=amps)
        _publish(rig, local, at, contactor=True)
        await _cycle(rig, at, ev_first=ev_first)
    assert ev.before_export_release_target() is None
    assert ev.daily_backfill_stop_pending
    at = _at(19, 3)
    freezer.move_to(at)
    _vehicle(rig, at, soc=41, current=0, request=8)
    _publish(rig, local, at)
    await _cycle(rig, at, ev_first=ev_first)
    assert not ev.daily_backfill_stop_pending
    assert not ev.outside_stop_requested
    assert not ev.before_export_recovery.pending
    rig.provider.data["state"] = "asleep"
    return at


@pytest.mark.parametrize(
    "phases,ev_first,reload", [(1, False, False), (3, True, False), (3, False, True)]
)
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_topup_stop_still_connected_sleep_export_and_real_reload(
    hass,
    monkeypatch,
    freezer,
    phases,
    ev_first,
    reload,
):
    local = native(hass)
    rig = await _site(hass, monkeypatch, phases=phases)
    try:
        last = await _completed(rig, local, freezer, ev_first=ev_first)
        clocks = {entity: hass.states.get(entity).last_reported for entity in FIELDS}
        at = _at(20, 55)
        freezer.move_to(at)
        _publish(rig, local, at)
        if reload:
            await rig.harness.reload(rig.entry)
            await _cycle(rig, at, ev_first=ev_first)
            # Reload must not seed a cached native frame. Only a new genuine
            # local publication can restore the independent physical proof.
            assert (
                rig.entry.runtime_data.active_controller.ev_export_handoff_reason
                != "local_connected_stopped"
            )
            local.provider.publish(Publisher.payload(True, False))
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=ev_first)
        active = rig.entry.runtime_data.active_controller
        assert active.export_session.phase in {"starting", "active"}
        assert _calls(rig, entity=MODE, value="Force Discharge")
        assert active.ev_export_handoff_reason == "local_connected_stopped"
        assert rig.provider.data["charge_state_timestamp"] == last.timestamp() * 1000
        assert clocks == {entity: hass.states.get(entity).last_reported for entity in FIELDS}
        # Repeated local publications keep export stable without vehicle
        # wakeups, SoC writes or renewing the old Tessie measurement clock.
        for seconds in (30, 60, 120):
            now = at + timedelta(seconds=seconds)
            freezer.move_to(now)
            _publish(rig, local, now)
            rig.harness.clear_service_calls()
            await _cycle(rig, now, ev_first=ev_first)
            assert active.export_session.phase in {"starting", "active"}
            assert not _calls(rig, entity=MODE, value="Self Use")
            assert not any(call.domain == "switch" for call in rig.harness.service_calls)
    finally:
        await _close(rig)


@pytest.mark.parametrize(
    "failure",
    [
        "closed",
        "unavailable",
        "stale_local",
        "failed_local",
        "unloaded_local",
        "soc_below",
        "soc_invalid",
        "soc_restored",
        "soc_mismatch",
        "future_vehicle",
        "failed_vehicle",
        "unloaded_vehicle",
        "charging_frame",
        "optimistic_stop",
        "raised_minimum",
        "pending_recovery",
        "pending_stop",
        "disabled",
        "owner",
    ],
)
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_sleeping_connected_export_retracts_on_invalid_evidence_or_authority(
    hass,
    monkeypatch,
    freezer,
    failure,
):
    from homeassistant.config_entries import ConfigEntryState

    local = native(hass)
    rig = await _site(hass, monkeypatch)
    try:
        await _completed(rig, local, freezer)
        at = _at(20, 55)
        freezer.move_to(at)
        _publish(rig, local, at)
        await _cycle(rig, at)
        active = rig.entry.runtime_data.active_controller
        assert active.export_session.phase in {"starting", "active"}
        at += timedelta(seconds=30)
        freezer.move_to(at)
        _publish(rig, local, at)
        ev = rig.entry.runtime_data.ev_controller
        if failure == "closed":
            local.provider.publish(Publisher.payload(True, True))
        elif failure == "unavailable":
            _set(hass, LOCAL, "unavailable", at=at)
        elif failure == "stale_local":
            freezer.move_to(at + timedelta(seconds=91))
            at += timedelta(seconds=91)
            _electrical(rig, at)
            local.provider.publish(local.provider.data)  # Cache cannot renew.
        elif failure == "failed_local":
            local.provider.last_update_success = False
        elif failure == "unloaded_local":
            local.entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
        elif failure in {"soc_below", "soc_invalid", "soc_restored", "soc_mismatch"}:
            soc = (
                39 if failure == "soc_below" else "unavailable" if failure == "soc_invalid" else 41
            )
            _set(
                hass,
                "sensor.test_ev_soc",
                soc,
                {"unit_of_measurement": "%", "restored": failure == "soc_restored"},
                at=at,
            )
            if failure == "soc_below":
                rig.provider.data["charge_state_usable_battery_level"] = soc
            elif failure == "soc_mismatch":
                rig.provider.data["charge_state_usable_battery_level"] = 42
        elif failure == "future_vehicle":
            rig.provider.data["charge_state_timestamp"] = (
                at + timedelta(seconds=1)
            ).timestamp() * 1000
        elif failure == "failed_vehicle":
            rig.provider.last_update_success = False
        elif failure == "unloaded_vehicle":
            rig.provider_entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
        elif failure == "charging_frame":
            _vehicle(rig, at, soc=41, current=8, request=8)
        elif failure == "optimistic_stop":
            rig.provider.data["charge_state_charging_state"] = False
        elif failure == "raised_minimum":
            rig.entry.runtime_data.update_config_value("ev_before_export_soc_target_percent", 42)
        elif failure == "pending_recovery":
            from dataclasses import replace

            ev.before_export_recovery = replace(ev.before_export_recovery, pending=True)
        elif failure == "pending_stop":
            ev.daily_backfill_stop_pending = True
            ev.outside_stop_requested = True
        elif failure == "disabled":
            rig.entry.runtime_data.update_config_value("automatic_control_enabled", False)
        elif failure == "owner":
            rig.entry.runtime_data.update_config_value("foxess_control_owner", "foxcloud_scheduler")
        rig.harness.clear_service_calls()
        await _cycle(rig, at)
        assert not _calls(rig, entity=MODE, value="Force Discharge"), failure
        assert not _calls(rig, entity=DISCHARGE, value=15), failure
        if failure not in {"disabled", "owner"}:
            assert _calls(rig, entity=MODE, value="Self Use"), failure
    finally:
        await _close(rig)


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_connected_sleep_disconnect_reconnect_requires_new_vehicle_measurement(
    hass,
    monkeypatch,
    freezer,
):
    local = native(hass)
    rig = await _site(hass, monkeypatch)
    try:
        await _completed(rig, local, freezer)
        at = _at(20, 55)
        freezer.move_to(at)
        _publish(rig, local, at)
        await _cycle(rig, at)
        active = rig.entry.runtime_data.active_controller
        assert active.export_session.phase in {"starting", "active"}
        # Observed unplug/reconnect cannot carry the previous car frame into
        # a new connected session, even if the local contactor is still open.
        at += timedelta(seconds=1)
        freezer.move_to(at)
        _publish(rig, local, at, connected=False)
        at += timedelta(seconds=1)
        freezer.move_to(at)
        _publish(rig, local, at)
        rig.harness.clear_service_calls()
        await _cycle(rig, at)
        assert _calls(rig, entity=MODE, value="Self Use")
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        at += timedelta(seconds=30)
        freezer.move_to(at)
        _vehicle(rig, at, soc=39)
        _publish(rig, local, at)
        await _cycle(rig, at, ev_first=True)
        assert rig.entry.runtime_data.ev_controller.before_export_release_target() == 41
        assert not _calls(rig, entity=MODE, value="Force Discharge")
    finally:
        await _close(rig)


@pytest.mark.parametrize("loss", ["closed", "failed", "remapped"])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_connected_stopped_proof_rechecked_between_positive_export_commands(
    hass,
    monkeypatch,
    freezer,
    loss,
):
    from custom_components.home_energy_orchestrator.foxess_adapter import FoxessWriteBlocked

    local = native(hass)
    rig = await _site(hass, monkeypatch)
    try:
        await _completed(rig, local, freezer)
        at = _at(20, 55)
        freezer.move_to(at)
        _publish(rig, local, at)

        def retract(entity, value):
            if entity != DISCHARGE or value <= 0:
                return
            if loss == "closed":
                local.provider.publish(Publisher.payload(True, True))
            elif loss == "failed":
                local.provider.last_update_success = False
            else:
                rig.entry.runtime_data.update_config_value("ev_local_connection_entity", None)

        rig.after_command = retract
        rig.harness.clear_service_calls()
        with pytest.raises(FoxessWriteBlocked):
            await _cycle(rig, at)
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        rig.after_command = None
        await _cycle(rig, at)
        assert _calls(rig, entity=DISCHARGE, value=0)
    finally:
        await _close(rig)
