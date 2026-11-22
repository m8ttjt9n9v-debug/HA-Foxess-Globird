"""Delayed native publications through real HA setup, writers and stored recovery.

All inputs are synthetic. Modbus power never advances Tessie's measurement
clock, and a command acknowledgement never becomes measured vehicle current.
Every outage trace includes valid subsequent feedback and eventual progress.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from custom_components.home_energy_orchestrator.foxess_adapter import FoxessWriteBlocked
from tests.test_ev_dynamic_reservation_lifecycle import (
    stop_hass_after_dynamic_lifecycle as stop_hass_after_dynamic_lifecycle,
)
from tests.test_ev_export_handoff_lifecycle import (
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


def _vehicle_frame(rig, at, **values):
    """Publish actual limit with the complete measured native charge frame."""
    _vehicle(rig, at, **values)
    limit = rig.entry.runtime_data.ev_controller.target_limit_percent
    if limit is not None:
        rig.provider.data["charge_state_charge_limit_soc"] = limit
        previous = rig.hass.states.get("number.test_ev_limit")
        _set(rig.hass, previous.entity_id, limit, dict(previous.attributes), at=at)


def _positive_ev_commands(rig):
    return [
        call for call in rig.harness.service_calls
        if (
            call.service_data.get("entity_id") == "number.test_ev_current"
            and call.service_data.get("value", 0) > 0
        ) or (
            call.service_data.get("entity_id") == "switch.test_ev_charge"
            and call.service == "turn_on"
        )
    ]


def _bounded_target(rig):
    target = rig.entry.runtime_data.ev_controller.target_current_a
    settings = rig.entry.data
    assert target is not None and 0 < target <= settings["ev_max_current"]
    kw = target * settings["ev_voltage"] * settings["ev_phase_count"] / 1000
    assert kw <= (
        settings["inverter_discharge_limit_kw"] * settings["ev_outside_inverter_percent"] / 100
    )
    return target


async def _start_topup(rig, freezer, *, ev_first):
    at = _at(19, 1)
    freezer.move_to(at)
    _vehicle_frame(rig, at, soc=39)
    _electrical(rig, at)
    _set(rig.hass, LOCAL, "on", at=at)
    await _cycle(rig, at, ev_first=ev_first)
    target = _bounded_target(rig)
    at += timedelta(seconds=15)
    freezer.move_to(at)
    _vehicle_frame(rig, at, soc=39, current=target, request=target)
    _electrical(rig, at, current=target)
    _set(rig.hass, LOCAL, "on", at=at)
    await _cycle(rig, at, ev_first=ev_first)
    assert _bounded_target(rig) == target
    return at, target


async def _recover_topup(rig, freezer, at, *, ev_first):
    """Publish real stop/ramp measurements through the existing reconciliation."""
    for _ in range(6):
        at += timedelta(seconds=15)
        freezer.move_to(at)
        ev = rig.entry.runtime_data.ev_controller
        current = max(ev.target_current_a or 0, 0)
        _vehicle_frame(rig, at, soc=39, current=current, request=current or 6)
        _electrical(rig, at, current=current)
        _set(rig.hass, LOCAL, "on", at=at)
        await _cycle(rig, at, ev_first=ev_first)
        if (ev.target_current_a or 0) > 0 and ev.reconciliation.phase == "confirmed":
            assert _bounded_target(rig) == current
            assert ev.before_export_release_target() == 41
            assert not _calls(rig, entity=MODE, value="Force Discharge")
            return
    pytest.fail("Converged native/electrical publications did not restore the existing top-up")


def _save_reservation_mode(rig, mode):
    """Match native setting persistence without a reentrant reconciliation."""
    rig.hass.config_entries.async_update_entry(
        rig.entry, data={**rig.entry.data, "ev_reservation_mode": mode},
        options={key: value for key, value in rig.entry.options.items()
                 if key != "ev_reservation_mode"},
    )
    rig.entry.runtime_data.update_config_value("ev_reservation_mode", mode)


def _large_fixed_quota(rig):
    values = {"ev_pre_free_backfill_enabled": True, "ev_daily_backfill_energy_kwh": 100.0}
    rig.hass.config_entries.async_update_entry(rig.entry, data={**rig.entry.data, **values})
    for key, value in values.items():
        rig.entry.runtime_data.update_config_value(key, value)


async def _fixed_stays_unfunded_through_real_reload(rig, freezer, at, *, reload_first=False):
    order = (True, False, False) if reload_first else (False, False, True)
    for reload in order:
        at += timedelta(seconds=15)
        freezer.move_to(at)
        if reload and reload_first:
            # Restore the durable failed-checkpoint journal BEFORE publishing
            # anything that could let the old in-memory reducer finish it.
            rig.harness.clear_service_calls()
            await rig.harness.reload(rig.entry)
        _vehicle_frame(rig, at, soc=53, connected=False, home=False)
        _electrical(rig, at)
        _set(rig.hass, LOCAL, "off", at=at)
        if not (reload and reload_first):
            rig.harness.clear_service_calls()
        if reload and not reload_first:
            await rig.harness.reload(rig.entry)
        await _cycle(rig, at)
        coordinator = rig.entry.runtime_data
        assert coordinator.runtime_config.ev_preferences.reservation_mode == "fixed"
        assert coordinator.ev_controller.daily_backfill_protection_kwh(at) >= 100
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert not any(
            call.service_data.get("entity_id") == "number.test_force_discharge"
            and call.service_data.get("value", 0) > 0
            for call in rig.harness.service_calls
        )
    assert rig.entry.runtime_data.active_controller.export_session.phase == "idle"
    stored = await rig.harness.load_store(
        f"home_energy_orchestrator.{rig.entry.entry_id}.export_session",
    )
    assert stored["phase"] == "idle"
    return at


async def _explicit_dynamic_selection_can_progress(rig, freezer, at):
    _save_reservation_mode(rig, "dynamic")
    for _ in range(6):
        at += timedelta(seconds=15)
        freezer.move_to(at)
        _vehicle_frame(rig, at, soc=53, connected=False, home=False)
        _electrical(rig, at)
        _set(rig.hass, LOCAL, "off", at=at)
        rig.harness.clear_service_calls()
        await _cycle(rig, at)
        if _calls(rig, entity=MODE, value="Force Discharge"):
            assert not _positive_ev_commands(rig)
            return
    pytest.fail("Funded Dynamic selection did not recover after retiring old policy intent")


@pytest.mark.parametrize("ev_first", [False, True])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_fresh_delayed_actual_current_is_not_optimistic_request_or_modbus_power(
    hass, monkeypatch, freezer, ev_first,
):
    rig = await _site(hass, monkeypatch, reservation_mode="dynamic")
    try:
        at, target = await _start_topup(rig, freezer, ev_first=ev_first)
        for actual in (0, 3, target):
            at += timedelta(seconds=15)
            freezer.move_to(at)
            # Accepted request and local battery draw are already at target,
            # while the next genuine vehicle measurement reports a safe ramp.
            _vehicle_frame(rig, at, soc=39, current=actual, request=target, charging="Charging")
            _electrical(rig, at, current=target)
            _set(hass, LOCAL, "on", at=at)
            rig.harness.clear_service_calls()
            await _cycle(rig, at, ev_first=ev_first)
            assert _bounded_target(rig) == target
            status = hass.states.get("sensor.home_energy_ev_control_status")
            assert status.attributes["requested_current_a"] == target
            assert status.attributes["actual_current_a"] == actual
            measured_power = hass.states.get("sensor.home_energy_ev_charging_power")
            assert float(measured_power.state) == pytest.approx(actual * 0.23 * rig.phases)
            assert not any(call.service == "turn_off" for call in rig.harness.service_calls)
            assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert rig.entry.runtime_data.ev_controller.reconciliation.phase == "confirmed", (
            hass.states.get("sensor.home_energy_ev_control_status").attributes
        )
    finally:
        await _close(rig)


@pytest.mark.parametrize("ev_first", [False, True])
@pytest.mark.parametrize("first_publisher", ["modbus", "tessie"])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_staggered_publishers_refuse_partial_authority_then_progress_after_convergence(
    hass, monkeypatch, freezer, ev_first, first_publisher,
):
    rig = await _site(hass, monkeypatch, reservation_mode="dynamic")
    try:
        at, target = await _start_topup(rig, freezer, ev_first=ev_first)
        old_stamp = rig.provider.data["charge_state_timestamp"]
        at += timedelta(seconds=91)
        freezer.move_to(at)
        rig.harness.clear_service_calls()
        if first_publisher == "modbus":
            _electrical(rig, at, current=target)
            # A fresh HA request/current report is still not a native charge
            # measurement. The service-optimistic request has its own clock.
            for entity in ("number.test_ev_current", "sensor.test_ev_actual_current"):
                previous = hass.states.get(entity)
                _set(hass, entity, target, dict(previous.attributes), at=at)
            assert rig.provider.data["charge_state_timestamp"] == old_stamp
        else:
            _vehicle_frame(rig, at, soc=39, current=target, request=target)
        _set(hass, LOCAL, "on", at=at)
        await _cycle(rig, at, ev_first=ev_first)
        assert not _positive_ev_commands(rig)
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert rig.entry.runtime_data.ev_controller.target_current_a == 0
        # Both independent sources now converge; existing stop acknowledgement
        # and recovery may complete without changing policy or freshness limits.
        rig.harness.clear_service_calls()
        await _recover_topup(rig, freezer, at, ev_first=ev_first)
    finally:
        await _close(rig)


@pytest.mark.parametrize("ev_first", [False, True])
@pytest.mark.parametrize("fault", ["missing_actual", "invalid_actual", "provider_failed"])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_topup_missing_or_invalid_native_evidence_survives_reload_and_recovers(
    hass, monkeypatch, freezer, ev_first, fault,
):
    rig = await _site(hass, monkeypatch, reservation_mode="dynamic")
    try:
        at, target = await _start_topup(rig, freezer, ev_first=ev_first)
        at += timedelta(seconds=15)
        freezer.move_to(at)
        _electrical(rig, at, current=target)
        if fault == "missing_actual":
            hass.states.async_remove("sensor.test_ev_actual_current")
        elif fault == "invalid_actual":
            _set(hass, "sensor.test_ev_actual_current", "unavailable", at=at)
        else:
            rig.provider.last_update_success = False
        _set(hass, LOCAL, "on", at=at)
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=ev_first)
        assert not _positive_ev_commands(rig)
        assert rig.entry.runtime_data.ev_controller.target_current_a == 0
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        await rig.harness.reload(rig.entry)
        assert rig.entry.runtime_data.runtime_config.ev_preferences.reservation_mode == "dynamic"
        assert not _positive_ev_commands(rig)
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        rig.provider.last_update_success = True
        rig.harness.clear_service_calls()
        await _recover_topup(rig, freezer, at, ev_first=ev_first)
    finally:
        await _close(rig)


@pytest.mark.parametrize("ev_first", [False, True])
@pytest.mark.parametrize("fault", ["missing_soc", "invalid_soc", "provider_failed", "stale_grid"])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_export_reduces_for_lost_evidence_then_resumes_after_qualified_publication(
    hass, monkeypatch, freezer, ev_first, fault,
):
    rig = await _site(hass, monkeypatch, reservation_mode="dynamic")
    try:
        await _complete_and_leave(rig, freezer, ev_first=ev_first, departure_soc=53)
        at = _at(20, 40)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=ev_first)
        assert _calls(rig, entity=MODE, value="Force Discharge")
        at += timedelta(seconds=15)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        if fault == "missing_soc":
            hass.states.async_remove("sensor.test_ev_soc")
        elif fault == "invalid_soc":
            _set(hass, "sensor.test_ev_soc", "unavailable", at=at)
        elif fault == "provider_failed":
            rig.provider.last_update_success = False
        else:
            _set(hass, "sensor.test_grid_power", -15, {"unit_of_measurement": "kW"},
                 at=at - timedelta(seconds=91))
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=ev_first)
        assert _calls(rig, entity=MODE, value="Self Use")
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert not _positive_ev_commands(rig)
        rig.provider.last_update_success = True
        at += timedelta(seconds=15)
        freezer.move_to(at)
        _vehicle_frame(rig, at, soc=53, connected=False, home=False)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=ev_first)
        assert _calls(rig, entity=MODE, value="Force Discharge")
        assert not _positive_ev_commands(rig)
    finally:
        await _close(rig)


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_dynamic_to_unfunded_fixed_mode_during_checkpoint_vetoes_old_export_authority(
    hass, monkeypatch, freezer,
):
    rig = await _site(hass, monkeypatch, reservation_mode="dynamic")
    try:
        await _complete_and_leave(rig, freezer, departure_soc=53)
        coordinator = rig.entry.runtime_data
        _large_fixed_quota(rig)
        at = _at(20, 40)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        await coordinator.async_refresh()
        active = coordinator.active_controller
        repository_type = type(active._export_repository)
        save = repository_type.async_save
        changed = False

        async def mode_changes_during_save(self, value):
            nonlocal changed
            await save(self, value)
            if self is active._export_repository and not changed and value.phase == "starting":
                changed = True
                _save_reservation_mode(rig, "fixed")

        monkeypatch.setattr(repository_type, "async_save", mode_changes_during_save)
        rig.harness.clear_service_calls()
        try:
            await active.async_reconcile()
        except FoxessWriteBlocked:
            pass  # A guarded positive-command veto is an allowed reducing outcome.
        assert changed, "The test must cross the real export journal checkpoint"
        assert coordinator.ev_controller.daily_backfill_protection_kwh(at) >= 100
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert not any(
            call.service_data.get("entity_id") == "number.test_force_discharge"
            and call.service_data.get("value", 0) > 0
            for call in rig.harness.service_calls
        )
        # A later explicit return to the funded policy may progress through
        # the same writer after new physical feedback; refusal cannot strand it.
        at = await _fixed_stays_unfunded_through_real_reload(rig, freezer, at)
        await _explicit_dynamic_selection_can_progress(rig, freezer, at)
    finally:
        await _close(rig)


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_final_export_command_mode_edit_retires_old_intent_before_fixed_can_resume(
    hass, monkeypatch, freezer,
):
    rig = await _site(hass, monkeypatch, reservation_mode="dynamic")
    try:
        await _complete_and_leave(rig, freezer, departure_soc=53)
        _large_fixed_quota(rig)
        at = _at(20, 40)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        await rig.entry.runtime_data.async_refresh()
        changed = False

        def mode_changes_after_final_command(entity, value):
            nonlocal changed
            if entity == MODE and value == "Force Discharge" and not changed:
                changed = True
                _save_reservation_mode(rig, "fixed")

        rig.after_command = mode_changes_after_final_command
        rig.harness.clear_service_calls()
        try:
            await rig.entry.runtime_data.active_controller.async_reconcile()
        except FoxessWriteBlocked:
            pass
        assert changed
        modes = [call.service_data["option"] for call in _calls(rig, entity=MODE)]
        assert modes[0] == "Force Discharge"
        assert modes[-1] == "Self Use"
        assert _calls(rig, entity="number.test_force_discharge", value=0)
        assert hass.states.get(MODE).state == "Self Use"
        assert not _positive_ev_commands(rig)
        at = await _fixed_stays_unfunded_through_real_reload(rig, freezer, at)
        await _explicit_dynamic_selection_can_progress(rig, freezer, at)
    finally:
        await _close(rig)


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_failed_mode_retirement_checkpoint_cannot_resurrect_old_dynamic_intent_after_reload(
    hass, monkeypatch, freezer,
):
    rig = await _site(hass, monkeypatch, reservation_mode="dynamic")
    try:
        await _complete_and_leave(rig, freezer, departure_soc=53)
        _large_fixed_quota(rig)
        at = _at(20, 40)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        coordinator = rig.entry.runtime_data
        await coordinator.async_refresh()
        active = coordinator.active_controller
        repository_type = type(active._export_repository)
        save = repository_type.async_save
        changed, failed_retirement = False, False

        async def retirement_write_fails_once(self, value):
            nonlocal changed, failed_retirement
            if self is active._export_repository:
                if changed and value.phase in {"idle", "stopping"} and not failed_retirement:
                    failed_retirement = True
                    raise OSError("Synthetic retirement checkpoint outage")
                await save(self, value)
                if not changed and value.phase == "starting":
                    changed = True
                    _save_reservation_mode(rig, "fixed")
                return
            await save(self, value)

        monkeypatch.setattr(repository_type, "async_save", retirement_write_fails_once)
        rig.harness.clear_service_calls()
        try:
            await active.async_reconcile()
        except (FoxessWriteBlocked, OSError):
            pass
        assert changed and failed_retirement
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        stored = await rig.harness.load_store(
            f"home_energy_orchestrator.{rig.entry.entry_id}.export_session",
        )
        # The durable old starting intent really remains. A process-local
        # execution fence is insufficient; reload must not relatch its power
        # under a different, unfunded selected reservation policy.
        assert stored["phase"] == "starting"
        assert rig.entry.data["ev_reservation_mode"] == "fixed"
        at = await _fixed_stays_unfunded_through_real_reload(
            rig, freezer, at, reload_first=True,
        )
        await _explicit_dynamic_selection_can_progress(rig, freezer, at)
    finally:
        await _close(rig)


@pytest.mark.parametrize("fault", ["grid_unavailable", "battery_expired"])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_raw_modbus_loss_during_export_checkpoint_cannot_borrow_cached_ledger(
    hass, monkeypatch, freezer, fault,
):
    rig = await _site(hass, monkeypatch, reservation_mode="dynamic")
    try:
        await _complete_and_leave(rig, freezer, departure_soc=53)
        at = _at(20, 40)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        coordinator = rig.entry.runtime_data
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
        cached_telemetry = coordinator.telemetry
        assert cached_telemetry.grid_power.valid and cached_telemetry.grid_power.fresh
        assert cached_telemetry.battery_power.valid and cached_telemetry.battery_power.fresh
        active = coordinator.active_controller
        repository_type = type(active._export_repository)
        save = repository_type.async_save
        changed = False

        async def raw_modbus_changes_during_save(self, value):
            nonlocal changed
            await save(self, value)
            if self is not active._export_repository or changed or value.phase != "starting":
                return
            changed = True
            before_loss = coordinator.telemetry
            assert before_loss.grid_power.valid and before_loss.grid_power.fresh
            assert before_loss.battery_power.valid and before_loss.battery_power.fresh
            if fault == "grid_unavailable":
                _set(hass, "sensor.test_grid_power", "unavailable",
                     {"unit_of_measurement": "kW"}, at=at)
            else:
                previous = hass.states.get("sensor.test_battery_power")
                _set(hass, previous.entity_id, previous.state, dict(previous.attributes),
                     at=at - timedelta(seconds=91))
            # The asynchronous raw publication has NOT refreshed or replaced
            # the coordinator's earlier, valid normalized model. The writer's
            # next positive guard must requalify the independent source itself.
            assert coordinator.telemetry is before_loss
            assert before_loss.grid_power.valid and before_loss.grid_power.fresh
            assert before_loss.battery_power.valid and before_loss.battery_power.fresh

        monkeypatch.setattr(repository_type, "async_save", raw_modbus_changes_during_save)
        rig.harness.clear_service_calls()
        # Use HA's actual supported in-progress/coalesced-refresh ordering:
        # source listeners remain attached and async_request_refresh stays real.
        # The lock releases before explicit fresh publication/recovery below.
        async with coordinator._debounced_refresh.async_lock():
            try:
                await active.async_reconcile()
            except FoxessWriteBlocked:
                pass
        assert changed, "The raw-source loss must cross the actual durable export checkpoint"
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert not any(
            call.service_data.get("entity_id") == "number.test_force_discharge"
            and call.service_data.get("value", 0) > 0
            for call in rig.harness.service_calls
        )
        assert not _positive_ev_commands(rig)

        # Qualified subsequent Modbus AND vehicle frames plus the normal
        # coordinator refresh allow the existing controller to progress again.
        # No expiry, limit, policy or saved pending duty is relaxed to do so.
        for _ in range(3):
            at += timedelta(seconds=15)
            freezer.move_to(at)
            _vehicle_frame(rig, at, soc=53, connected=False, home=False)
            _electrical(rig, at)
            _set(hass, LOCAL, "off", at=at)
            rig.harness.clear_service_calls()
            await _cycle(rig, at)
            if _calls(rig, entity=MODE, value="Force Discharge"):
                assert not _positive_ev_commands(rig)
                break
        else:
            pytest.fail(
                "Converged Modbus/vehicle evidence did not recover checkpoint-vetoed export"
            )
    finally:
        await _close(rig)


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_coalesced_raw_source_loss_never_blocks_owned_export_cleanup_confirmation(
    hass, monkeypatch, freezer,
):
    rig = await _site(hass, monkeypatch, reservation_mode="dynamic")
    try:
        await _complete_and_leave(rig, freezer, departure_soc=53)
        at = _at(20, 40)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        await _cycle(rig, at)
        active = rig.entry.runtime_data.active_controller
        assert _calls(rig, entity=MODE, value="Force Discharge")
        at += timedelta(seconds=15)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        await _cycle(rig, at)
        assert active.export_session.phase == "active"

        # Existing configured end, not a new rule or manufactured idle state,
        # requires the real owned session to perform its normal reducing stop.
        at = _at(21, 1)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        coordinator = rig.entry.runtime_data
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
        repository_type = type(active._export_repository)
        save = repository_type.async_save
        changed = False

        async def raw_grid_lost_during_stop_save(self, value):
            nonlocal changed
            await save(self, value)
            if self is not active._export_repository or changed or value.phase != "stopping":
                return
            changed = True
            before_loss = coordinator.telemetry
            assert before_loss.grid_power.valid and before_loss.grid_power.fresh
            _set(hass, "sensor.test_grid_power", "unavailable",
                 {"unit_of_measurement": "kW"}, at=at)
            assert coordinator.telemetry is before_loss

        monkeypatch.setattr(repository_type, "async_save", raw_grid_lost_during_stop_save)
        rig.harness.clear_service_calls()
        async with coordinator._debounced_refresh.async_lock():
            await active.async_reconcile()
        assert changed
        assert _calls(rig, entity="number.test_force_discharge", value=0)
        assert _calls(rig, entity=MODE, value="Self Use")
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert not _positive_ev_commands(rig)

        # Native readback is separate from command acceptance and must allow
        # the retained stopping obligation to become durably idle.
        at += timedelta(seconds=15)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        rig.harness.clear_service_calls()
        await _cycle(rig, at)
        assert active.export_session.phase == "idle"
        stored = await rig.harness.load_store(
            f"home_energy_orchestrator.{rig.entry.entry_id}.export_session",
        )
        assert stored["phase"] == "idle"
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert not _positive_ev_commands(rig)
    finally:
        await _close(rig)
