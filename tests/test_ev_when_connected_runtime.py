"""Prompt surplus uses the existing native daily and pre-free lifecycles."""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.planner.control_windows import (
    post_export_daily_planning_start,
)
from custom_components.home_energy_orchestrator.planner.ev_persistence import EvPersistenceState
from tests.test_ev_backfill_timing import _charging, _fresh, _services
from tests.test_ev_before_export_charging import _case
from tests.test_ev_before_export_import_transients import _tick
from tests.test_zerohero_active import _loaded_controller


@pytest.fixture(autouse=True)
def utc_clock(monkeypatch):
    """Synthetic tariff times and command-boundary checks use the same zone."""
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.ev_active.dt_util.now",
        lambda: datetime.now(UTC),
    )


def _at(hour=22, minute=0, second=0, day=7):
    return datetime(2026, 9, day, hour, minute, second, tzinfo=UTC)


def _prompt(hass, now, **changes):
    config = dict(
        ev_before_export_enabled=False,
        ev_pre_free_backfill_enabled=True,
        ev_pre_free_backfill_timing="when_connected",
    )
    config.update(changes)
    coordinator, controller = _case(hass, now, **config)
    coordinator.active_controller.opportunistic_price_export_requested = lambda at: False
    hass.states.async_set("sensor.car_soc", "50", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.car_energy", "30", {"unit_of_measurement": "kWh"})
    return coordinator, controller


async def _running(hass, freezer, **changes):
    now = _at()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _prompt(hass, now, **changes)
    await controller.async_reconcile(now)
    assert controller.target_current_a == 8
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=30))
    assert controller.reconciliation.phase == "confirmed"
    calls.clear()
    return now + timedelta(seconds=30), calls, coordinator, controller


@pytest.mark.parametrize("hour,minute,active", [(20, 59, False), (21, 0, False), (21, 1, True),
                                               (22, 0, True), (0, 0, True), (7, 59, True)])
async def test_prompt_starts_at_export_finish_above_export_minimum(
    hass, freezer, hour, minute, active,
):
    now = _at(hour, minute)
    freezer.move_to(now)
    calls = _services(hass)
    _, controller = _prompt(hass, now)
    await controller.async_reconcile(now)
    assert controller.daily_backfill_active is active
    assert any(call[:2] == ("switch", "turn_on") for call in calls) is active, (
        calls, controller.last_reason, controller.target_current_a,
        controller._when_connected_write_authorized(),
        controller._when_connected_energy_budget(now), controller._observation(),
        controller._when_connected_backfill_hold(now),
    )
    assert controller.when_connected_owned is active


@pytest.mark.parametrize("automatic_export", [False, True])
async def test_raw_sellable_charges_after_paid_export_cap_is_used(hass, freezer, automatic_export):
    now = _at()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _prompt(hass, now, automatic_export_enabled=automatic_export)
    coordinator.active_controller.export_plan = replace(
        coordinator.active_controller.export_plan, planned_export_energy_kwh=0,
    )
    coordinator.data.paid_export_kwh = 30
    await controller.async_reconcile(now)
    assert controller.daily_backfill_active
    assert controller.target_current_a == 8


async def test_tiny_budget_funds_only_supported_current_and_cannot_grow_session(hass, freezer):
    now = _at()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _prompt(hass, now, ev_surplus_rearm_energy_kwh=0)
    coordinator.active_controller.export_plan = replace(
        coordinator.active_controller.export_plan, sellable_energy_kwh=0.1,
    )
    await controller.async_reconcile(now)
    assert controller.target_current_a == 2  # 0.1 kWh funds 2 A for three minutes.
    assert controller.daily_backfill_session_target_kwh == 0.1
    assert controller.daily_backfill_plan.power_ceiling_kw == 1.38
    assert controller.daily_backfill_plan.duration_minutes == 4.3
    coordinator.active_controller.export_plan = replace(
        coordinator.active_controller.export_plan, sellable_energy_kwh=5,
    )
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=30), current=2)
    assert controller.daily_backfill_session_target_kwh <= 0.1
    assert controller.target_current_a <= 2


@pytest.mark.parametrize("quota", [0, 3])
async def test_midnight_retains_cycle_and_ready_handoff_preserves_tomorrow_quota(
    hass, freezer, quota,
):
    now, calls, coordinator, controller = await _running(
        hass, freezer, ev_daily_backfill_energy_kwh=quota,
    )
    cycle = controller.daily_backfill_cycle_ready_at
    controller.daily_backfill_delivered_kwh = 1
    await _tick(hass, freezer, coordinator, controller, _at(0, day=8))
    assert controller.daily_backfill_cycle_ready_at == cycle
    assert controller.daily_backfill_delivered_kwh == 1
    calls.clear()
    await _tick(hass, freezer, coordinator, controller, _at(8, day=8))
    assert not controller.daily_backfill_active
    assert controller.pre_free_session.active
    assert controller.target_current_a == 8
    assert controller.daily_backfill_delivered_kwh == 0
    assert controller.daily_backfill_protection_kwh(_at(8, day=8)) == quota
    assert not any(call[:2] == ("switch", "turn_off") for call in calls)
    await _tick(hass, freezer, coordinator, controller, _at(8, 1, day=8))
    assert controller.daily_backfill_delivered_kwh == 0


@pytest.mark.parametrize("loss", ["budget", "reserve", "stale", "service", "target", "price"])
async def test_import_retention_never_masks_hard_authority_loss(hass, freezer, loss):
    now, calls, coordinator, controller = await _running(hass, freezer)
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=10), grid=0.5)
    at = now + timedelta(seconds=20)
    freezer.move_to(at)
    _fresh(coordinator, at, current_a=8, grid_kw=0.5)
    if loss == "budget":
        coordinator.active_controller.export_plan = replace(
            coordinator.active_controller.export_plan, sellable_energy_kwh=0,
        )
    elif loss == "reserve":
        hass.states.async_set("sensor.site_battery_soc", "20", {"unit_of_measurement": "%"})
    elif loss == "stale":
        coordinator.telemetry = replace(
            coordinator.telemetry,
            house_load=replace(coordinator.telemetry.house_load, fresh=False),
        )
    elif loss == "service":
        coordinator.telemetry = replace(
            coordinator.telemetry,
            site_grid_current=replace(coordinator.telemetry.site_grid_current, value=100),
        )
        hass.states.async_set("sensor.phase_current", "100", {"unit_of_measurement": "A"})
    elif loss == "target":
        hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
    else:
        coordinator.active_controller.opportunistic_price_export_requested = lambda at: True
    calls.clear()
    await controller.async_reconcile(at)
    assert controller.target_current_a == 0
    assert any(call[:2] == ("switch", "turn_off") for call in calls)


async def test_transient_import_retains_matching_current_until_original_deadline(hass, freezer):
    now, calls, coordinator, controller = await _running(hass, freezer)
    first = now + timedelta(seconds=10)
    for offset in (10, 30, 69):
        await _tick(
            hass, freezer, coordinator, controller, now + timedelta(seconds=offset), grid=0.5,
        )
        assert controller.target_current_a == 8
        assert controller.before_export_import.since == first
    assert not calls
    replacement = ActiveEvController(hass, coordinator)
    await replacement._async_restore()
    assert replacement.before_export_import.since == first
    await _tick(hass, freezer, coordinator, replacement, now + timedelta(seconds=70), grid=0.5)
    assert replacement.target_current_a == 0


async def test_import_at_arrival_never_starts_or_retries(hass, freezer):
    now = _at()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _prompt(hass, now)
    _fresh(coordinator, now, grid_kw=0.5)
    await controller.async_reconcile(now)
    assert not controller.daily_backfill_active
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


async def test_exhausted_session_does_not_chatter_at_funded_minimum(hass, freezer):
    now = _at()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _prompt(hass, now)
    coordinator.active_controller.export_plan = replace(
        coordinator.active_controller.export_plan, sellable_energy_kwh=1,
    )
    await controller.async_reconcile(now)
    starts = 0
    for offset, budget in enumerate([0.0344, 0.0346] * 5, start=1):
        at = now + timedelta(seconds=30 * offset)
        freezer.move_to(at)
        for state in hass.states.async_all():
            hass.states.async_set(
                state.entity_id, state.state, dict(state.attributes), force_update=True,
            )
        # Native publisher confirms the previously requested physical state.
        running = controller.target_current_a or 0
        if running:
            _charging(hass, running)
        else:
            hass.states.async_set("switch.car_charge", "off")
            hass.states.async_set("sensor.car_charging", "stopped")
            hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "A"})
        _fresh(coordinator, at, current_a=running)
        coordinator.active_controller.export_plan = replace(
            coordinator.active_controller.export_plan, sellable_energy_kwh=budget,
        )
        calls.clear()
        await controller.async_reconcile(at)
        starts += sum(call[:2] == ("switch", "turn_on") for call in calls)
    assert starts == 0


@pytest.mark.parametrize(
    "active,budget,expected",
    [(False, 0.134499, 0), (False, 0.1345, 3), (False, 0.134501, 3),
     (True, 0.034499, 0), (True, 0.0345, 1), (True, 0.034501, 1)],
)
def test_rearm_and_continuation_have_explicit_funded_boundaries(hass, active, budget, expected):
    _, controller = _prompt(hass, _at())
    controller.daily_backfill_active = active
    controller._when_connected_issued_current_a = 8 if active else None
    current = controller._when_connected_current(
        _at(), budget=budget, room=10, baseline=0, ceiling=8,
        minimum=1, step=1, vehicle_soc=50, target_soc=80,
    )
    assert current == expected


@pytest.mark.parametrize("margin,expected", [(0, 2), (0.1, 0), (0.2, 0), (6, 0)])
def test_live_margin_edits_apply_to_admission_but_never_expand_active_funding(
    hass, margin, expected,
):
    coordinator, controller = _prompt(hass, _at())
    coordinator.update_config_value("ev_surplus_rearm_energy_kwh", margin)
    values = dict(budget=0.1, room=10, baseline=0, ceiling=8,
                  minimum=1, step=1, vehicle_soc=50, target_soc=80)
    assert controller._when_connected_current(_at(), **values) == expected
    controller.daily_backfill_active = True
    controller._when_connected_issued_current_a = 8
    assert controller._when_connected_current(_at(), **values) == (0 if margin == 6 else 2)


async def test_restart_and_ready_handoff_do_not_reapply_margin_to_owned_energy(hass, freezer):
    now, calls, coordinator, controller = await _running(hass, freezer)
    coordinator.active_controller.export_plan = replace(
        coordinator.active_controller.export_plan, sellable_energy_kwh=0.1,
    )
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=30))
    assert controller.daily_backfill_active
    assert controller.target_current_a == 2
    replacement = ActiveEvController(hass, coordinator)
    await controller._async_save()
    await replacement._async_restore()
    await _tick(hass, freezer, coordinator, replacement, _at(7, 59, 59, day=8), current=2)
    assert replacement.target_current_a == 2
    calls.clear()
    await _tick(hass, freezer, coordinator, replacement, _at(8, day=8), current=2)
    assert replacement.pre_free_session.active
    assert replacement.target_current_a == 2
    assert not any(call[:2] == ("switch", "turn_off") for call in calls)


@pytest.mark.parametrize("legacy_finish", ["20:00:00", "22:00:00"])
@pytest.mark.parametrize("minute,active", [(0, False), (1, True)])
async def test_prompt_uses_effective_export_finish_not_legacy_clock(
    hass, freezer, legacy_finish, minute, active,
):
    now = _at(21, minute)
    freezer.move_to(now)
    _services(hass)
    _, controller = _prompt(
        hass, now, force_discharge_finish=legacy_finish,
        bonus_window_end="21:00:00", force_discharge_offset_minutes=1,
    )
    await controller.async_reconcile(now)
    assert controller.daily_backfill_active is active


async def test_qualified_price_yields_even_outside_prompt_window(hass, freezer):
    now = _at(16)
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _prompt(hass, now)
    _charging(hass, 8)
    controller.outside_control_active = controller.outside_target_active = True
    controller.target_current_a = 8
    controller.target_limit_percent = 80
    controller.decision_phase = "solar_spill"
    coordinator.active_controller.opportunistic_price_export_requested = lambda at: True
    await controller.async_reconcile(now)
    assert controller.target_current_a == 0
    assert any(call[:2] == ("switch", "turn_off") for call in calls)


@pytest.mark.parametrize("existing_owner", [False, True])
async def test_price_induced_cleanup_survives_mode_flip_and_real_restart(
    hass, freezer, existing_owner,
):
    now = _at(16)
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _prompt(hass, now)
    _charging(hass, 8)
    controller.outside_control_active = controller.outside_target_active = existing_owner
    controller.target_current_a = 8
    controller.target_limit_percent = 80
    controller.decision_phase = "solar_spill" if existing_owner else "idle"
    coordinator.active_controller.opportunistic_price_export_requested = lambda at: True

    async def observe_stop_checkpoint(call):
        payload = await controller._repository.store.async_load()
        assert payload["when_connected_owned"] is True
        assert payload["daily_backfill"]["stop_pending"] is True
        calls.append((call.domain, call.service, dict(call.data)))

    hass.services.async_register("switch", "turn_off", observe_stop_checkpoint)
    await controller.async_reconcile(now)
    assert controller.when_connected_owned
    assert controller.daily_backfill_stop_pending
    assert any(call[:2] == ("switch", "turn_off") for call in calls)
    coordinator.update_config_value("ev_pre_free_backfill_timing", "conservative")
    replacement = ActiveEvController(hass, coordinator)
    coordinator.ev_controller = replacement
    await replacement._async_restore()
    assert replacement.requires_export_handoff()
    fox = _loaded_controller(hass, coordinator)
    coordinator.active_controller = fox
    assert not fox._ev_before_export_handoff_ready(now)
    hass.states.async_set("switch.car_charge", "off")
    hass.states.async_set("sensor.car_charging", "stopped")
    hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "A"})
    await replacement.async_reconcile(now)
    assert not replacement.when_connected_owned
    assert not replacement.daily_backfill_stop_pending
    assert fox._ev_before_export_handoff_ready(now)


async def test_invalid_outer_journal_requires_proof_without_inventing_cleanup_owner(hass, freezer):
    now = _at()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _prompt(hass, now)
    await controller._repository.store.async_save([])
    coordinator.update_config_value("ev_pre_free_backfill_timing", "conservative")
    replacement = ActiveEvController(hass, coordinator)
    await replacement._async_restore()
    assert replacement._repository.last_restore_status == "invalid"
    assert replacement.requires_export_handoff()
    assert not replacement.when_connected_owned
    assert not replacement.daily_backfill_stop_pending
    assert calls == []


async def test_completed_minimum_recovery_transfers_without_crediting_topup_twice(hass, freezer):
    now = _at()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _prompt(
        hass, now, ev_before_export_enabled=True, ev_before_export_soc_buffer_percent=2,
    )
    hass.states.async_set("sensor.car_soc", "25", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.car_energy", "15", {"unit_of_measurement": "kWh"})
    await controller.async_reconcile(now)
    assert controller.decision_phase == "ev_before_export_charging"
    assert not controller.daily_backfill_active
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=30))
    assert controller.daily_backfill_delivered_kwh == 0
    hass.states.async_set("sensor.car_soc", "32", {"unit_of_measurement": "%"})
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=60))
    assert controller.daily_backfill_active
    assert controller.daily_backfill_delivered_kwh == 0
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=90))
    assert controller.daily_backfill_delivered_kwh == pytest.approx(0.046)


async def test_each_command_rechecks_authority_after_the_previous_await(hass, freezer):
    now = _at()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _prompt(hass, now)

    async def remove_energy(call):
        calls.append((call.domain, call.service, dict(call.data)))
        coordinator.active_controller.export_plan = replace(
            coordinator.active_controller.export_plan, sellable_energy_kwh=0,
        )

    hass.services.async_register("number", "set_value", remove_energy)
    await controller.async_reconcile(now)
    assert len(calls) == 1
    assert calls[0][2]["entity_id"] == "number.car_limit"
    assert controller.last_reason == "ev_write_gate_closed"


@pytest.mark.parametrize("loss", ["budget", "reserve", "config"])
async def test_confirmed_target_rechecks_hard_authority_after_saved_import_clock(
    hass, freezer, monkeypatch, loss,
):
    now, calls, coordinator, controller = await _running(hass, freezer)
    original_save = controller._async_save
    changed = False

    async def withdraw_after_checkpoint(*args, **kwargs):
        nonlocal changed
        await original_save(*args, **kwargs)
        if controller.before_export_import.since is not None and not changed:
            changed = True
            if loss == "budget":
                coordinator.active_controller.export_plan = replace(
                    coordinator.active_controller.export_plan, sellable_energy_kwh=0,
                )
            elif loss == "reserve":
                hass.states.async_set(
                    "sensor.site_battery_soc", "20", {"unit_of_measurement": "%"},
                )
            else:
                coordinator.update_config_value("ev_pre_free_backfill_timing", "conservative")

    monkeypatch.setattr(controller, "_async_save", withdraw_after_checkpoint)
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=10), grid=0.5)
    assert changed
    assert controller.target_current_a == 0
    assert any(call[:2] == ("switch", "turn_off") for call in calls)
    assert controller.when_connected_owned


async def test_unplug_reconnect_reuses_intent_but_only_the_current_energy(hass, freezer):
    now, calls, coordinator, controller = await _running(hass, freezer)
    at = now + timedelta(seconds=30)
    freezer.move_to(at)
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("switch.car_charge", "off")
    hass.states.async_set("sensor.car_charging", "disconnected")
    hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "A"})
    _fresh(coordinator, at)
    await controller.async_reconcile(at)
    assert not controller.daily_backfill_active
    assert controller.when_connected_backfill_selected()
    at += timedelta(seconds=30)
    freezer.move_to(at)
    for state in hass.states.async_all():
        hass.states.async_set(
            state.entity_id, state.state, dict(state.attributes), force_update=True,
        )
    hass.states.async_set("binary_sensor.car_cable", "on")
    hass.states.async_set("sensor.car_charging", "stopped")
    coordinator.active_controller.export_plan = replace(
        coordinator.active_controller.export_plan, sellable_energy_kwh=0,
    )
    _fresh(coordinator, at)
    calls.clear()
    await controller.async_reconcile(at)
    assert not controller.daily_backfill_active
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)
    coordinator.active_controller.export_plan = replace(
        coordinator.active_controller.export_plan, sellable_energy_kwh=5,
    )
    at += timedelta(seconds=30)
    freezer.move_to(at)
    for state in hass.states.async_all():
        hass.states.async_set(
            state.entity_id, state.state, dict(state.attributes), force_update=True,
        )
    _fresh(coordinator, at)
    await controller.async_reconcile(at)
    assert controller.daily_backfill_active


async def test_free_window_takes_over_without_stale_prompt_stop(hass, freezer):
    now = _at(11, 59)
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _prompt(hass, now)
    await controller.async_reconcile(now)
    assert controller.pre_free_session.active
    calls.clear()
    await _tick(hass, freezer, coordinator, controller, _at(12, 1), current=8)
    assert controller.policy_route.route == "free_window"
    assert not controller.daily_backfill_active
    assert not controller.pre_free_session.active
    assert not controller.daily_backfill_stop_pending
    assert not any(call[:2] == ("switch", "turn_off") for call in calls)


@pytest.mark.parametrize("change", ["budget", "margin", "source"])
async def test_awaited_save_cannot_turn_planned_active_into_margin_bypass(
    hass, freezer, monkeypatch, change,
):
    now = _at()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _prompt(hass, now, ev_max_current=1)
    original_save = controller._async_save
    changed = False

    async def change_after_save(*args, **kwargs):
        nonlocal changed
        await original_save(*args, **kwargs)
        if controller.when_connected_owned and not changed:
            changed = True
            if change == "budget":
                coordinator.active_controller.export_plan = replace(
                    coordinator.active_controller.export_plan, sellable_energy_kwh=0.1,
                )
            elif change == "margin":
                coordinator.update_config_value("ev_surplus_rearm_energy_kwh", 0.2)
            else:
                coordinator.update_config_value("grid_power_entity", "sensor.new_grid")

    monkeypatch.setattr(controller, "_async_save", change_after_save)
    await controller.async_reconcile(now)
    assert changed
    assert calls == []
    assert controller.target_current_a == 0


@pytest.mark.parametrize("baseline", [0, 1])
async def test_policy_edit_and_restart_keep_cleanup_until_real_baseline(hass, freezer, baseline):
    now, calls, coordinator, controller = await _running(
        hass, freezer, ev_protected_baseline_a=baseline,
    )
    coordinator.update_config_value("ev_pre_free_backfill_timing", "conservative")
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=10))
    assert controller.when_connected_owned
    replacement = ActiveEvController(hass, coordinator)
    await replacement._async_restore()
    assert replacement.requires_export_handoff()
    assert replacement.when_connected_owned
    at = now + timedelta(seconds=40)
    freezer.move_to(at)
    for state in hass.states.async_all():
        hass.states.async_set(
            state.entity_id, state.state, dict(state.attributes), force_update=True,
        )
    if baseline:
        _charging(hass, baseline)
    else:
        hass.states.async_set("switch.car_charge", "off")
        hass.states.async_set("sensor.car_charging", "stopped")
        hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "A"})
    _fresh(coordinator, at, current_a=baseline)
    await replacement.async_reconcile(at)
    if baseline:
        await replacement.async_reconcile(at)
    assert not replacement.when_connected_owned


@pytest.mark.parametrize("month,day", [(4, 5), (10, 4)])
def test_prompt_planning_opening_is_chronological_across_dst(month, day):
    zone = ZoneInfo("Australia/Sydney")
    ready = datetime(2026, month, day, 8, tzinfo=zone)
    free = ready.replace(hour=12)
    start = post_export_daily_planning_start(
        ready_at=ready, next_free_start=free, discharge_finish=time(21, 1),
    )
    assert start.date() == (ready - timedelta(days=1)).date()
    assert start.hour == 21
    assert start.astimezone(UTC) < ready.astimezone(UTC) < free.astimezone(UTC)


@pytest.mark.parametrize("finish", [time(8), time(10), time(12)])
def test_ambiguous_prompt_window_never_becomes_full_day(finish):
    with pytest.raises(ValueError):
        post_export_daily_planning_start(
            ready_at=_at(8), next_free_start=_at(12), discharge_finish=finish,
        )


@pytest.mark.parametrize("stored,expected", [(None, False), (False, False), (True, True),
                                            ("false", True), (0, True)])
def test_additive_owner_codec_preserves_legacy_and_fails_closed(stored, expected):
    payload = EvPersistenceState(_at()).to_payload()
    if stored is not None:
        payload["when_connected_owned"] = stored
    restored = EvPersistenceState.from_payload(payload, _at())
    assert restored.when_connected_owned is expected
    assert restored.to_payload().get("when_connected_owned", False) is expected
