"""Maximum afternoon capture through the sole EV writer and real budget gates.

All electrical/provider states are synthetic. The only service replacement is
the local transport recorder; policy, current qualification, budget, source and
per-command authorization are the actual production implementations.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from tests.test_ev_backfill_timing import _services
from tests.test_ev_before_export_source_clocks import _native
from tests.test_ev_before_export_source_clocks import (
    native_provider_cleanup as native_provider_cleanup,
)
from tests.test_ev_solar_soak import _ack, _now, _power, _rig


@pytest.fixture(autouse=True)
def utc_clock(monkeypatch):
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.ev_active.dt_util.now",
        lambda: datetime.now(UTC),
    )


def _max_rig(hass, now, **changes):
    config = {
        "ev_solar_soak_max_enabled": True,
        "ev_solar_soak_start_soc_percent": 95,
        "ev_solar_soak_stop_soc_percent": 90,
        "ev_solar_soak_average_minutes": 30,
    }
    config.update(changes)
    return _rig(hass, now, **config)


async def _tick(
    hass, freezer, coordinator, controller, now, *, soc=99, current=10,
    surplus=0.7, solar=None, grid=0, switch_on=None,
):
    freezer.move_to(now)
    _power(
        hass, coordinator, now, surplus=surplus, current=current,
        battery_soc=soc, solar=solar,
    )
    if grid:
        sample = coordinator.telemetry.grid_power
        grid_sample = replace(
            sample, value=grid,
            sources=tuple(replace(source, raw_value=grid) for source in sample.sources),
        )
        battery = surplus + grid - current * 230 * coordinator.config["ev_phase_count"] / 1000
        sample = coordinator.telemetry.battery_power
        battery_sample = replace(
            sample, value=battery,
            sources=tuple(replace(source, raw_value=battery) for source in sample.sources),
        )
        coordinator.telemetry = replace(
            coordinator.telemetry, grid_power=grid_sample, battery_power=battery_sample,
        )
        coordinator.snapshot = replace(coordinator.snapshot, grid_power_kw=grid)
        hass.states.async_set("sensor.site_grid", str(grid), {"unit_of_measurement": "kW"},
                              force_update=True)
        hass.states.async_set("sensor.battery_power", str(battery),
                              {"unit_of_measurement": "kW"}, force_update=True)
    if switch_on is not None:
        hass.states.async_set("switch.car_charge", "on" if switch_on else "off",
                              force_update=True)
        hass.states.async_set("sensor.car_charging", "charging" if switch_on else "stopped",
                              force_update=True)
    await controller.async_reconcile(now)


async def _running(hass, freezer, **config):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _max_rig(hass, now, **config)
    _power(hass, coordinator, now, surplus=0.7, battery_soc=99)
    await controller.async_reconcile(now)
    assert controller.target_current_a == 10
    _ack(hass, controller)
    now += timedelta(seconds=30)
    await _tick(hass, freezer, coordinator, controller, now)
    _ack(hass, controller)
    await controller.async_reconcile(now)
    assert controller.reconciliation.phase == "confirmed"
    calls.clear()
    return now, calls, coordinator, controller


def _positive_current_writes(calls):
    return [call for call in calls if call[:2] == ("number", "set_value")
            and call[2].get("entity_id") == "number.car_current"
            and call[2].get("value", 0) > 0]


@pytest.mark.parametrize("enabled,expected", [(False, 2), (True, 10)])
async def test_opt_in_maximum_replaces_mean_without_changing_the_legacy_default(
    hass, freezer, enabled, expected,
):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _max_rig(hass, now, ev_solar_soak_max_enabled=enabled)
    _power(hass, coordinator, now, surplus=0.7, battery_soc=99)
    await controller.async_reconcile(now)
    assert controller.target_current_a == expected
    assert not controller._charge_to_full_requested()


@pytest.mark.parametrize("soc,expected", [(94.999, 0), (95, 0), (95.001, 10)])
async def test_maximum_entry_is_strictly_above_the_configured_start(hass, freezer, soc, expected):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _max_rig(hass, now)
    _power(hass, coordinator, now, surplus=0.7, battery_soc=soc)
    await controller.async_reconcile(now)
    if expected:
        assert controller.target_current_a == expected
    else:
        # With no prior owner, preserving no intent is as restrictive as zero.
        assert controller.target_current_a in (None, 0)
        assert not _positive_current_writes(calls)
        assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize(
    "start,stop",
    [(95, 95), (90, 95), (float("nan"), 90), (95, float("inf")),
     (True, 0), (95, "corrupt"), (101, 90), (95, -1)],
)
async def test_invalid_selected_maximum_band_does_not_fall_back_to_legacy_mean(
    hass, freezer, start, stop,
):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _max_rig(
        hass, now, ev_solar_soak_start_soc_percent=start,
        ev_solar_soak_stop_soc_percent=stop,
    )
    # This healthy surplus would authorise legacy mean charging. Selecting a
    # malformed maximum policy must withdraw authority rather than choose it.
    _power(hass, coordinator, now, surplus=0.2, battery_soc=99)
    runtime = coordinator.runtime_config
    assert coordinator.config["ev_solar_soak_max_enabled"] is True
    assert runtime.ev_policy.solar_soak_max_enabled is False
    assert runtime.ev_numbers.value("ev_solar_soak_start_soc_percent", 95) == 100
    assert runtime.ev_numbers.value("ev_solar_soak_stop_soc_percent", 90) == 100
    await controller.async_reconcile(now)
    assert controller.target_current_a in (None, 0)
    assert not controller.solar_soak_maximum.active
    assert not _positive_current_writes(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize(
    "phases,inverter,percent,connector,expected",
    [(1, 10, 50, 15, 15), (3, 15, 55, 16, 11), (3, 8, 50, 16, 5),
     (1, 3, 40, 16, 5)],
)
async def test_maximum_keeps_existing_inverter_percentage_connector_and_site_limits(
    hass, freezer, phases, inverter, percent, connector, expected,
):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _max_rig(
        hass, now, ev_phase_count=phases, site_phase_count=phases,
        inverter_discharge_limit_kw=inverter, ev_outside_inverter_percent=percent,
        ev_max_current=connector,
    )
    _power(hass, coordinator, now, surplus=0.7, battery_soc=99)
    await controller.async_reconcile(now)
    assert controller.target_current_a == expected
    assert controller.target_current_a <= connector
    assert controller.target_current_a * 230 * phases / 1000 <= inverter * percent / 100


async def test_clouds_and_start_threshold_jitter_do_not_recompute_the_maximum(hass, freezer):
    now, calls, coordinator, controller = await _running(hass, freezer)
    for seconds, soc, solar in [(30, 95, 0.8), (60, 94.9, 0), (90, 95.1, 4),
                                (120, 93, 0), (150, 92, 0.5), (180, 91, 6)]:
        await _tick(
            hass, freezer, coordinator, controller, now + timedelta(seconds=seconds),
            soc=soc, solar=solar,
        )
        assert controller.target_current_a == 10, (seconds, controller.last_reason)
        _ack(hass, controller)
    assert not calls


async def test_stop_boundary_releases_and_recovery_band_does_not_rearm(hass, freezer):
    now, _, coordinator, controller = await _running(hass, freezer)
    for seconds, soc, expected in [(30, 90.5, 10), (60, 90, 0), (90, 89.9, 0),
                                   (120, 90.1, 0), (150, 94.9, 0), (180, 95, 0),
                                   (210, 95.1, 10)]:
        await _tick(
            hass, freezer, coordinator, controller, now + timedelta(seconds=seconds),
            soc=soc, current=controller.target_current_a or 0,
        )
        assert controller.target_current_a == expected, (seconds, soc, controller.last_reason)
        _ack(hass, controller)


@pytest.mark.parametrize("start,stop", [(80, 70), (96, 94), (95, 0)])
async def test_configured_maximum_thresholds_are_independent_of_legacy_mean_floor(
    hass, freezer, start, stop,
):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _max_rig(
        hass, now, ev_solar_soak_start_soc_percent=start,
        ev_solar_soak_stop_soc_percent=stop,
        ev_solar_soak_battery_soc_percent=99,
        ev_outside_battery_reserve_percent=0,
    )
    _power(hass, coordinator, now, surplus=0.7, battery_soc=start + 1)
    await controller.async_reconcile(now)
    assert controller.target_current_a == 10
    _ack(hass, controller)
    await _tick(
        hass, freezer, coordinator, controller, now + timedelta(seconds=30),
        soc=(start + stop) / 2,
    )
    assert controller.target_current_a == 10
    await _tick(
        hass, freezer, coordinator, controller, now + timedelta(seconds=60), soc=stop,
    )
    assert controller.target_current_a == 0


async def test_live_stop_floor_wins_over_a_lagging_high_battery_snapshot(hass, freezer):
    now, calls, coordinator, controller = await _running(hass, freezer)
    at = now + timedelta(seconds=30)
    freezer.move_to(at)
    _power(hass, coordinator, at, current=10, battery_soc=99)
    hass.states.async_set("sensor.site_battery_soc", "90", {"unit_of_measurement": "%"})
    assert coordinator.snapshot.battery_soc == 99
    assert not controller._solar_soak_write_authorized()
    await controller.async_reconcile(at)
    assert controller.target_current_a == 0
    assert not _positive_current_writes(calls)


async def test_remaining_energy_above_stop_floor_limits_the_next_control_tick(hass, freezer):
    now, _, coordinator, controller = await _running(hass, freezer)
    at = now + timedelta(seconds=30)
    await _tick(hass, freezer, coordinator, controller, at, soc=90.1)
    target = controller.target_current_a or 0
    available_above_floor_kwh = coordinator.snapshot.battery_capacity_kwh * 0.1 / 100
    assert target * 230 * 3 / 1000 * 30 / 3600 <= available_above_floor_kwh
    assert target < 10


@pytest.mark.parametrize("loss", ["budget", "solar_stale", "grid_stale", "battery_stale",
                                  "house_stale", "vehicle_limit"])
async def test_hard_authority_loss_is_not_hidden_by_hysteresis(hass, freezer, loss):
    now, calls, coordinator, controller = await _running(hass, freezer)
    at = now + timedelta(seconds=30)
    freezer.move_to(at)
    _power(hass, coordinator, at, current=10, battery_soc=94)
    if loss == "budget":
        coordinator.data.available_after_reserve_kwh = 0
    elif loss == "vehicle_limit":
        hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
    else:
        field = {"solar_stale": "solar_power", "grid_stale": "grid_power",
                 "battery_stale": "battery_power", "house_stale": "house_load"}[loss]
        coordinator.telemetry = replace(
            coordinator.telemetry,
            **{field: replace(getattr(coordinator.telemetry, field), fresh=False)},
        )
    await controller.async_reconcile(at)
    assert controller.target_current_a == 0
    assert not _positive_current_writes(calls)


async def test_stop_floor_lost_between_service_calls_cannot_start_the_ev(hass, freezer):
    now = _now()
    freezer.move_to(now)
    coordinator, controller = _max_rig(hass, now)
    _power(hass, coordinator, now, battery_soc=99, surplus=0.7)
    calls = []

    async def accept(call):
        calls.append((call.domain, call.service, dict(call.data)))
        hass.states.async_set("sensor.site_battery_soc", "90", {"unit_of_measurement": "%"})

    for domain, service in [("number", "set_value"), ("switch", "turn_on"),
                            ("switch", "turn_off")]:
        hass.services.async_register(domain, service, accept)
    await controller.async_reconcile(now)
    assert len(calls) == 1
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("delay,expected", [(30, 10), (91, 0)])
async def test_restart_keeps_only_recent_source_bound_maximum_intent(
    hass, freezer, delay, expected,
):
    now, _, coordinator, controller = await _running(hass, freezer)
    await controller._async_save(now)
    at = now + timedelta(seconds=delay)
    freezer.move_to(at)
    restored = ActiveEvController(hass, coordinator)
    await restored._async_restore()
    _power(hass, coordinator, at, current=10, battery_soc=94, surplus=0.7)
    await restored.async_reconcile(at)
    assert restored.target_current_a == expected


async def test_threshold_edit_invalidates_old_latch_before_another_positive_write(hass, freezer):
    now, calls, coordinator, controller = await _running(hass, freezer)
    coordinator.update_config_value("ev_solar_soak_start_soc_percent", 100)
    assert not controller._solar_soak_write_authorized()
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=30), soc=99)
    assert controller.target_current_a == 0
    assert not _positive_current_writes(calls)


async def test_issued_target_can_wait_for_delayed_current_without_solar_replanning(hass, freezer):
    now = _now()
    freezer.move_to(now)
    _services(hass)
    coordinator, controller = _max_rig(hass, now)
    _power(hass, coordinator, now, surplus=0.7, battery_soc=99)
    await controller.async_reconcile(now)
    assert controller.target_current_a == 10
    _ack(hass, controller)
    for seconds, current in [(30, 0), (60, 0), (90, 3), (120, 10)]:
        await _tick(
            hass, freezer, coordinator, controller, now + timedelta(seconds=seconds),
            current=current, soc=94, switch_on=True,
        )
        assert controller.target_current_a == 10
        _ack(hass, controller)


async def test_transient_import_retains_only_already_issued_matching_current(hass, freezer):
    now, calls, coordinator, controller = await _running(hass, freezer)
    for seconds, grid in [(10, 0.484), (20, 0), (30, 0.5), (40, 0)]:
        await _tick(
            hass, freezer, coordinator, controller, now + timedelta(seconds=seconds),
            grid=grid, soc=94,
        )
        assert controller.target_current_a == 10
    assert not calls


async def test_sustained_import_expires_without_rearming_in_the_soc_band(hass, freezer):
    now, calls, coordinator, controller = await _running(hass, freezer)
    for seconds in (10, 40, 69):
        await _tick(
            hass, freezer, coordinator, controller, now + timedelta(seconds=seconds),
            grid=0.5, soc=94,
        )
        assert controller.target_current_a == 10
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=70),
                grid=0.5, soc=94)
    assert controller.target_current_a == 0
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=100),
                grid=0, current=0, soc=94)
    assert controller.target_current_a == 0
    assert not _positive_current_writes(calls)


async def test_import_does_not_admit_a_new_maximum_or_positive_retry(hass, freezer):
    now = _now()
    freezer.move_to(now)
    calls = _services(hass)
    coordinator, controller = _max_rig(hass, now)
    await _tick(hass, freezer, coordinator, controller, now, grid=0.5, current=0)
    assert controller.target_current_a in (None, 0)
    assert not _positive_current_writes(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("requested,retained", [(10, True), (9, False)])
async def test_import_cannot_send_a_positive_retry_or_restore_an_external_override(
    hass, freezer, requested, retained,
):
    now, calls, coordinator, controller = await _running(hass, freezer)
    hass.states.async_set(
        "number.car_current", str(requested),
        {"min": 1, "max": 16, "step": 1, "unit_of_measurement": "A"},
    )
    await _tick(
        hass, freezer, coordinator, controller, now + timedelta(seconds=30),
        grid=0.5, current=9, soc=94,
    )
    assert (controller.target_current_a == 10) is retained
    assert not _positive_current_writes(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("external_limit", [100, 60])
async def test_import_confirmation_cannot_hide_an_external_charge_limit_change(
    hass, freezer, external_limit,
):
    now, calls, coordinator, controller = await _running(
        hass, freezer, ev_free_window_charge_limit_percent=70,
    )
    assert hass.states.get("sensor.car_soc").state == "25"
    assert controller.target_limit_percent == 70
    assert float(hass.states.get("number.car_limit").state) == 70
    hass.states.async_set(
        "number.car_limit", str(external_limit),
        {"min": 0, "max": 100, "step": 1, "unit_of_measurement": "%"},
        force_update=True,
    )
    await _tick(
        hass, freezer, coordinator, controller, now + timedelta(seconds=10),
        grid=0.5, current=10, soc=94,
    )
    assert not _positive_current_writes(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)
    limit_writes = [call[2]["value"] for call in calls
                    if call[:2] == ("number", "set_value")
                    and call[2].get("entity_id") == "number.car_limit"]
    stopped = any(call[:2] == ("switch", "turn_off") for call in calls)
    if external_limit > 70:
        # Do not leave an already-running car at an unbounded external limit
        # for the economic import-confirmation interval.
        assert stopped or 70 in limit_writes
    else:
        # A human's lower native limit must never be increased to restore an
        # old maximum-soak request while grid import is already happening.
        assert all(value <= external_limit for value in limit_writes)
        assert stopped or controller.target_limit_percent <= external_limit


@pytest.mark.parametrize("loss", ["safety_lock", "ev_disabled", "master_disabled",
                                  "away", "unplugged"])
async def test_maximum_does_not_write_through_control_or_connection_withdrawal(
    hass, freezer, loss,
):
    now, calls, coordinator, controller = await _running(hass, freezer)
    at = now + timedelta(seconds=30)
    freezer.move_to(at)
    _power(hass, coordinator, at, current=10, battery_soc=94)
    if loss in {"safety_lock", "ev_disabled", "master_disabled"}:
        key, value = {
            "safety_lock": ("rehearsal_mode", True),
            "ev_disabled": ("ev_automatic_control_enabled", False),
            "master_disabled": ("automatic_control_enabled", False),
        }[loss]
        coordinator.update_config_value(key, value)
    else:
        entity, state = {
            "away": ("device_tracker.car", "not_home"),
            "unplugged": ("binary_sensor.car_cable", "off"),
        }[loss]
        hass.states.async_set(entity, state, force_update=True)
    await controller.async_reconcile(at)
    if loss == "master_disabled":
        # The battery master is independent of EV reducing cleanup. It must
        # remove positive soak authority, not prevent an already-needed stop.
        assert controller.target_current_a == 0
        assert not controller.solar_soak_maximum.active
        assert not controller._solar_soak_write_authorized()
    else:
        assert not controller._writes_still_authorized()
    assert not _positive_current_writes(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("loss", ["safety_lock", "ev_disabled", "master_disabled",
                                  "away", "unplugged"])
async def test_withdrawal_is_saved_so_restart_cannot_resurrect_an_in_band_maximum(
    hass, freezer, loss,
):
    now, calls, coordinator, controller = await _running(hass, freezer)
    at = now + timedelta(seconds=30)
    freezer.move_to(at)
    _power(hass, coordinator, at, current=10, battery_soc=94)
    if loss in {"safety_lock", "ev_disabled", "master_disabled"}:
        key, bad, good = {
            "safety_lock": ("rehearsal_mode", True, False),
            "ev_disabled": ("ev_automatic_control_enabled", False, True),
            "master_disabled": ("automatic_control_enabled", False, True),
        }[loss]
        coordinator.update_config_value(key, bad)
    else:
        entity, bad, good = {
            "away": ("device_tracker.car", "not_home", "home"),
            "unplugged": ("binary_sensor.car_cable", "off", "on"),
        }[loss]
        hass.states.async_set(entity, bad, force_update=True)
    await controller.async_reconcile(at)
    assert not controller.solar_soak_maximum.active
    # Re-establish the original setting/binding before restoring. An old
    # active payload would now match again, so freshness alone cannot hide it.
    if loss in {"safety_lock", "ev_disabled", "master_disabled"}:
        coordinator.update_config_value(key, good)
    else:
        hass.states.async_set(entity, good, force_update=True)
    at += timedelta(seconds=30)
    freezer.move_to(at)
    restored = ActiveEvController(hass, coordinator)
    await restored._async_restore()
    assert not restored.solar_soak_maximum.active
    calls.clear()
    _power(hass, coordinator, at, current=10, battery_soc=94)
    await restored.async_reconcile(at)
    assert restored.target_current_a in (None, 0)
    assert not _positive_current_writes(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("fault", ["old_frame", "future_frame", "failed", "actual_mismatch"])
async def test_fresh_ha_reports_do_not_hide_invalid_native_vehicle_evidence(
    hass, freezer, fault,
):
    rig = _native(hass, freezer, old_seconds=0)
    for key, value in {
        "ev_before_export_enabled": False, "configure_solar": True,
        "solar_power_entity": "sensor.solar", "ev_solar_spill_enabled": True,
        "ev_outside_inverter_percent": 50, "ev_solar_soak_max_enabled": True,
        "ev_solar_soak_start_soc_percent": 95, "ev_solar_soak_stop_soc_percent": 90,
    }.items():
        rig.coordinator.update_config_value(key, value)
    calls = _services(hass)
    _power(hass, rig.coordinator, rig.now, battery_soc=99, surplus=0.7)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.target_current_a == 10
    _ack(hass, rig.controller)
    at = rig.now + timedelta(seconds=30)
    freezer.move_to(at)
    _power(hass, rig.coordinator, at, current=10, battery_soc=94, surplus=0.7)
    rig.provider.data.update({
        "charge_state_timestamp": at.timestamp() * 1000,
        "charge_state_charging_state": "Charging",
        "charge_state_charger_actual_current": 10,
        "charge_state_charge_current_request": 10,
        "charge_state_charge_limit_soc": rig.controller.target_limit_percent,
        "charge_state_charge_enable_request": True,
    })
    await rig.controller.async_reconcile(at)
    assert rig.controller.target_current_a == 10
    calls.clear()
    at += timedelta(seconds=30)
    freezer.move_to(at)
    _power(hass, rig.coordinator, at, current=10, battery_soc=94, surplus=0.7)
    rig.provider.data["charge_state_timestamp"] = at.timestamp() * 1000
    if fault == "old_frame":
        rig.provider.data["charge_state_timestamp"] = (
            at - timedelta(seconds=91)
        ).timestamp() * 1000
    elif fault == "future_frame":
        rig.provider.data["charge_state_timestamp"] = (
            at + timedelta(seconds=1)
        ).timestamp() * 1000
    elif fault == "failed":
        rig.provider.last_update_success = False
    else:
        rig.provider.data["charge_state_charger_actual_current"] = 9
    await rig.controller.async_reconcile(at)
    assert (rig.controller.target_current_a or 0) == 0
    assert not _positive_current_writes(calls)
    assert not any(call[:2] == ("switch", "turn_on") for call in calls)


@pytest.mark.parametrize("owner", ["full", "free", "before_export"])
async def test_existing_higher_priority_policies_preempt_maximum_soak(hass, freezer, owner):
    now, _, coordinator, controller = await _running(hass, freezer)
    delta = {
        "full": {"ev_charge_to_full_enabled": True},
        "free": {"free_charge_window_start": "16:00:00", "free_charge_window_end": "17:00:00"},
        "before_export": {"ev_before_export_enabled": True,
                          "ev_before_export_soc_target_percent": 40},
    }[owner]
    for key, value in delta.items():
        coordinator.update_config_value(key, value)
    await _tick(hass, freezer, coordinator, controller, now + timedelta(seconds=30), soc=94)
    assert controller.decision_phase != "solar_spill"

