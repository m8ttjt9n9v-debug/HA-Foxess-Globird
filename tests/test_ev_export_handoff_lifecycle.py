"""EV departure/sleep must not make local battery export depend on a car cloud.

These synthetic raw publications run the real HA entry, canonical telemetry,
ledgers, EV and inverter controllers, storage, and public projections. Service
acks never advance a vehicle measurement clock. At the export boundary only
electrical measurements and the separately mapped local cable sensor publish;
the genuine last Tessie charge frame and all its HA clocks remain old.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.aemo_monitor import AemoMarketMonitor
from custom_components.home_energy_orchestrator.const import DOMAIN
from custom_components.home_energy_orchestrator.foxess_adapter import FoxessWriteBlocked
from tests.helpers.lifecycle import LifecycleHarness
from tests.test_aemo_dispatch_feed import dispatch_report
from tests.test_lifecycle_harness import _ev_entry_data

VIN = "LIFECYCLEVEHICLE1"
LOCAL = "binary_sensor.local_ev_connected"
MODE = "select.test_work_mode"
CHARGE = "number.test_force_charge"
DISCHARGE = "number.test_force_discharge"
FIELDS = {
    "sensor.test_ev_soc": "charge_state_usable_battery_level",
    "sensor.test_ev_actual_current": "charge_state_charger_actual_current",
    "sensor.test_ev_charging": "charge_state_charging_state",
    "binary_sensor.test_ev_cable": "charge_state_conn_charge_cable",
    "number.test_ev_current": "charge_state_charge_current_request",
    "number.test_ev_limit": "charge_state_charge_limit_soc",
    "switch.test_ev_charge": "charge_state_charge_enable_request",
}


def _at(hour=19, minute=0, second=0):
    return datetime(2026, 9, 17, hour, minute, second, tzinfo=UTC)


def _set(hass, entity, state, attributes=None, *, at):
    hass.states.async_set(
        entity,
        str(state),
        attributes or {},
        timestamp=at.timestamp(),
        force_update=True,
    )


def _vehicle(rig, at, *, soc=39, current=0, request=6, connected=True, home=True, charging=None):
    """A genuine complete vehicle measurement, not a command acknowledgement."""
    state = charging or ("Charging" if current else "Stopped")
    if not connected:
        state = "Disconnected"
    rig.provider.data.update(
        {
            "state": "online",
            "charge_state_timestamp": at.timestamp() * 1000,
            "charge_state_usable_battery_level": soc,
            "charge_state_charger_actual_current": current,
            "charge_state_charging_state": state,
            "charge_state_conn_charge_cable": "IEC" if connected else "<invalid>",
            "charge_state_charge_current_request": request,
            "charge_state_charge_limit_soc": 90,
        }
    )
    values = (
        ("sensor.test_ev_soc", soc, {"unit_of_measurement": "%"}),
        ("sensor.test_ev_energy", soc * 0.6, {"unit_of_measurement": "kWh"}),
        ("sensor.test_ev_actual_current", current, {"unit_of_measurement": "A"}),
        ("sensor.test_ev_charging", state.lower(), {}),
        ("binary_sensor.test_ev_cable", "on" if connected else "off", {}),
        ("device_tracker.test_ev", "home" if home else "not_home", {}),
        (
            "number.test_ev_current",
            request,
            {"min": 1, "max": 16, "step": 1, "unit_of_measurement": "A"},
        ),
        ("number.test_ev_limit", 90, {"min": 50, "max": 100, "step": 1}),
        ("switch.test_ev_charge", "on" if state == "Charging" else "off", {}),
    )
    for entity, value, attributes in values:
        _set(rig.hass, entity, value, attributes, at=at)


def _electrical(rig, at, *, battery_soc=50, grid=0, current=0, mode=None):
    """Publish local electrical evidence only; never touch vehicle clocks."""
    values = (
        ("sensor.test_battery_soc", battery_soc, "%"),
        ("sensor.test_grid_power", grid, "kW"),
        ("sensor.test_battery_power", -0.2 - current * 0.23 * rig.phases, "kW"),
        ("sensor.test_house_load", 0.2, "kW"),
        ("sensor.test_site_current", 0, "A"),
    )
    for entity, value, unit in values:
        _set(rig.hass, entity, value, {"unit_of_measurement": unit}, at=at)
    previous = rig.hass.states.get(MODE)
    _set(
        rig.hass,
        MODE,
        mode or (previous.state if previous else "Self Use"),
        {"options": ["Self Use", "Force Discharge", "Force Charge"]},
        at=at,
    )
    for entity in (CHARGE, DISCHARGE):
        state = rig.hass.states.get(entity)
        _set(
            rig.hass,
            entity,
            state.state if state else 0,
            {"min": 0, "max": 15, "step": 0.1, "unit_of_measurement": "kW"},
            at=at,
        )


async def _cycle(rig, at, *, ev_first=False):
    coordinator = rig.entry.runtime_data
    await coordinator.async_refresh()
    controllers = (
        (coordinator.ev_controller, coordinator.active_controller)
        if ev_first
        else (coordinator.active_controller, coordinator.ev_controller)
    )
    for controller in controllers:
        if controller is coordinator.ev_controller:
            await controller.async_reconcile(at)
        else:
            await controller.async_reconcile()
    coordinator.async_update_listeners()
    await rig.hass.async_block_till_done(wait_background_tasks=True)


async def _site(hass, monkeypatch, *, phases=3, price=False, mapped=True):
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.coordinator.dt_util.now",
        lambda: datetime.now(UTC),
    )
    harness = LifecycleHarness(hass)
    for domain in ("number", "select", "switch"):
        await async_setup_component(hass, domain, {})
    provider_entry = MockConfigEntry(domain="tessie")
    provider_entry.add_to_hass(hass)
    provider_entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    provider = SimpleNamespace(config_entry=provider_entry, last_update_success=True, data={})
    vehicle = SimpleNamespace(vin=VIN, data_coordinator=provider)
    provider_entry.runtime_data = SimpleNamespace(vehicles=[vehicle])
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=provider_entry.entry_id,
        identifiers={("tessie", VIN)},
    )
    for entity, field in FIELDS.items():
        domain, name = entity.split(".")
        row = er.async_get(hass).async_get_or_create(
            domain,
            "tessie",
            f"{VIN}-{field}",
            config_entry=provider_entry,
            device_id=device.id,
            suggested_object_id=name,
        )
        assert row.entity_id == entity
    rig = SimpleNamespace(
        hass=hass,
        harness=harness,
        provider=provider,
        provider_entry=provider_entry,
        phases=phases,
        entry=None,
    )
    _vehicle(rig, _at())
    _electrical(rig, _at())
    _set(hass, LOCAL, "on", at=_at())
    feed = AsyncMock(side_effect=lambda: dispatch_report(datetime.now(UTC), price=1000))
    monkeypatch.setattr(AemoMarketMonitor, "_async_fetch_summary", feed)

    async def apply(call):
        harness.record_service_call(call.domain, call.service, dict(call.data))
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            entity = entity[0]
        previous = hass.states.get(entity)
        if call.domain in {"number", "select"}:
            value = call.data.get("value", call.data.get("option"))
        else:
            value = "on" if call.service == "turn_on" else "off"
        _set(hass, entity, value, dict(previous.attributes), at=datetime.now(UTC))
        # Native Tessie acks update only the commanded field; they do not
        # advance charge_state_timestamp or report actual charger current.
        if entity in {"number.test_ev_current", "number.test_ev_limit"}:
            provider.data[FIELDS[entity]] = value
        elif entity == "switch.test_ev_charge":
            provider.data["charge_state_charging_state"] = value == "on"
        after_command = getattr(rig, "after_command", None)
        if after_command is not None:
            after_command(entity, value)

    async def no_wait(_seconds):
        return None

    for domain, service in (
        ("number", "set_value"),
        ("select", "select_option"),
        ("switch", "turn_on"),
        ("switch", "turn_off"),
    ):
        hass.services.async_register(domain, service, apply)
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep",
        no_wait,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic local connection handoff",
        version=6,
        data=_ev_entry_data(
            automatic_control_enabled=True,
            foxess_control_owner="local_modbus",
            automatic_charge_enabled=False,
            automatic_export_enabled=not price,
            battery_power_entity="sensor.test_battery_power",
            battery_capacity_kwh=40,
            battery_floor_percent=10,
            reserve_kwh=2,
            house_learning_fallback_kwh=4,
            house_away_fallback_kwh=4,
            house_load_includes_ev=False,
            configure_solar=False,
            inverter_discharge_limit_kw=15,
            inverter_charge_limit_kw=15,
            export_limit_kw=15,
            automatic_export_limit_kwh=30,
            ev_before_export_enabled=True,
            ev_before_export_soc_target_percent=40,
            ev_before_export_soc_buffer_percent=1,
            ev_outside_inverter_percent=50,
            ev_outside_battery_reserve_percent=20,
            ev_allowance_guard_enabled=False,
            ev_capacity_source="configured",
            ev_capacity_fallback_kwh=60,
            ev_phase_count=phases,
            site_phase_count=phases,
            ev_local_connection_entity=LOCAL if mapped else None,
            bonus_window_start="18:00:00",
            bonus_window_end="21:00:00",
            force_discharge_finish="21:01:00",
            force_discharge_offset_minutes=1,
            aemo_monitor_enabled=price,
            critical_event_sell_enabled=price,
            aemo_region="NSW1",
            aemo_export_threshold_per_kwh=3,
        ),
    )
    rig.entry = entry
    rig.feed = feed
    entry.add_to_hass(hass)
    await harness.setup(entry)
    return rig


async def _close(rig):
    await rig.harness.unload(rig.entry)
    rig.provider_entry._async_set_state(rig.hass, ConfigEntryState.NOT_LOADED, None)
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    rig.harness.close()


def _calls(rig, *, entity=None, value=None):
    return [
        call
        for call in rig.harness.service_calls
        if (entity is None or call.service_data.get("entity_id") == entity)
        and (
            value is None
            or call.service_data.get("value", call.service_data.get("option")) == value
        )
    ]


async def _complete_and_leave(
    rig,
    freezer,
    *,
    ev_first=False,
    departure_soc=43,
    retained_current=0,
):
    """Drive the real recovery journal through both thresholds and a measured stop."""
    ev = rig.entry.runtime_data.ev_controller
    # Setup may already have requested a start. Supply its genuine subsequent
    # vehicle report rather than treating the optimistic service ack as one.
    _vehicle(rig, _at(), current=0, request=6)
    await _cycle(rig, _at(), ev_first=ev_first)
    assert ev.before_export_release_target() == 41
    assert ev.target_current_a > 0, f"{ev.decision_phase}: {ev.last_reason}"
    assert ev.target_current_a * 0.23 * rig.phases <= 7.5
    for minute, soc in ((1, 40), (2, 40.9), (3, 41)):
        now = _at(19, minute)
        freezer.move_to(now)
        _vehicle(rig, now, soc=soc, current=ev.target_current_a, request=ev.target_current_a)
        _electrical(rig, now, current=ev.target_current_a)
        _set(rig.hass, LOCAL, "on", at=now)
        await _cycle(rig, now, ev_first=ev_first)
        if soc < 41:
            assert ev.before_export_release_target() == 41
            assert ev.target_current_a > 0
        else:
            assert ev.before_export_release_target() is None
            assert ev.target_current_a == 0
    # A service ack is not the measured stop. Publish the actual off frame.
    now = _at(19, 4)
    freezer.move_to(now)
    _vehicle(rig, now, soc=41, current=0, request=8)
    _electrical(rig, now)
    _set(rig.hass, LOCAL, "on", at=now)
    await _cycle(rig, now, ev_first=ev_first)
    assert not ev.before_export_recovery.pending
    assert not ev.outside_stop_requested
    now = _at(19, 5)
    freezer.move_to(now)
    _vehicle(
        rig,
        now,
        soc=departure_soc,
        current=retained_current,
        request=8,
        connected=False,
        home=False,
    )
    _electrical(rig, now)
    _set(rig.hass, LOCAL, "off", at=now)
    await _cycle(rig, now, ev_first=ev_first)
    rig.provider.data["state"] = "asleep"
    return now


@pytest.mark.parametrize(
    "phases,ev_first,retained_current",
    [
        (1, False, 0),
        (3, True, 0),
        (3, False, 16),
    ],
)
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_full_charge_stop_depart_sleep_then_scheduled_export(
    hass,
    monkeypatch,
    freezer,
    phases,
    ev_first,
    retained_current,
):
    rig = await _site(hass, monkeypatch, phases=phases)
    try:
        last_vehicle = await _complete_and_leave(
            rig,
            freezer,
            ev_first=ev_first,
            retained_current=retained_current,
        )
        vehicle_clocks = {entity: hass.states.get(entity).last_reported for entity in FIELDS}
        at = _at(20, 55)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        if retained_current:
            # A publisher re-emits a retained positive raw value, but its
            # genuinely old vehicle frame has not measured any new current.
            _set(
                hass,
                "sensor.test_ev_actual_current",
                retained_current,
                {"unit_of_measurement": "A"},
                at=at,
            )
            vehicle_clocks["sensor.test_ev_actual_current"] = at
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=ev_first)
        assert rig.provider.data["charge_state_timestamp"] == last_vehicle.timestamp() * 1000
        assert vehicle_clocks == {
            entity: hass.states.get(entity).last_reported for entity in FIELDS
        }
        assert rig.entry.runtime_data.active_controller.export_session.phase in {
            "starting",
            "active",
        }
        assert _calls(rig, entity=MODE, value="Force Discharge")
        assert not any(call.domain == "switch" for call in rig.harness.service_calls)
        fleet = hass.states.get("sensor.home_energy_fleet_summary")
        assert fleet.attributes["export_status"] != "withheld_ev_handoff_pending"
        status = hass.states.get("sensor.home_energy_status")
        assert status.attributes["ev_export_handoff_source"] == "entity_report"
        assert status.attributes["ev_export_handoff_reason"] == "local_disconnected"
    finally:
        await _close(rig)


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_completed_departure_survives_real_reload_before_price_opportunity(
    hass,
    monkeypatch,
    freezer,
):
    rig = await _site(hass, monkeypatch, price=True)
    try:
        await _complete_and_leave(rig, freezer)
        at = _at(22)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        rig.feed.side_effect = lambda: dispatch_report(datetime.now(UTC), price=5000)
        rig.harness.clear_service_calls()
        await rig.harness.reload(rig.entry)
        await rig.hass.async_block_till_done(wait_background_tasks=True)
        await _cycle(rig, at)
        active = rig.entry.runtime_data.active_controller
        assert not rig.entry.runtime_data.ev_controller.before_export_recovery.pending
        assert active.export_session.authority_source == "price"
        assert _calls(rig, entity=MODE, value="Force Discharge")
        assert (
            rig.provider.data["charge_state_timestamp"]
            < (at - timedelta(minutes=90)).timestamp() * 1000
        )
        # Current low price still withdraws export immediately. Local unplug
        # proof is not an independent source of market permission.
        rig.feed.side_effect = lambda: dispatch_report(datetime.now(UTC), price=1000, serial=2)
        rig.harness.clear_service_calls()
        await rig.entry.runtime_data.market_monitor.async_refresh()
        await rig.hass.async_block_till_done(wait_background_tasks=True)
        assert _calls(rig, entity=MODE, value="Self Use")
        assert not _calls(rig, entity=MODE, value="Force Discharge")
    finally:
        await _close(rig)


@pytest.mark.parametrize("reload", [False, True])
@pytest.mark.parametrize("ev_first", [False, True])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_departure_and_sleep_cannot_complete_pending_buffer_or_stop(
    hass,
    monkeypatch,
    freezer,
    reload,
    ev_first,
):
    rig = await _site(hass, monkeypatch)
    try:
        ev = rig.entry.runtime_data.ev_controller
        at = _at(19, 1)
        freezer.move_to(at)
        _vehicle(rig, at, soc=40, current=8, request=8)
        _electrical(rig, at, current=8)
        _set(hass, LOCAL, "on", at=at)
        await _cycle(rig, at, ev_first=ev_first)
        assert ev.before_export_release_target() == 41
        at = _at(19, 2)
        freezer.move_to(at)
        _vehicle(rig, at, soc=40, connected=False, home=False)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        await _cycle(rig, at, ev_first=ev_first)
        rig.provider.data["state"] = "asleep"
        at = _at(20, 55)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        if reload:
            await rig.harness.reload(rig.entry)
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=ev_first)
        ev = rig.entry.runtime_data.ev_controller
        assert ev.before_export_recovery.pending
        assert ev.before_export_release_target() == 41
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        stored = await rig.harness.load_store(f"{DOMAIN}.{rig.entry.entry_id}.ev_control")
        assert stored is not None
        assert stored["before_export_recovery"]["pending"]
        # Return with fresh measurements can resume the same buffered recovery;
        # no new recovery record or replacement energy pool is manufactured.
        at += timedelta(seconds=30)
        freezer.move_to(at)
        _vehicle(rig, at, soc=40)
        _electrical(rig, at)
        _set(hass, LOCAL, "on", at=at)
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=ev_first)
        assert ev.before_export_release_target() == 41
        assert ev.decision_phase == "ev_before_export_charging"
        assert not _calls(rig, entity=MODE, value="Force Discharge")
    finally:
        await _close(rig)


@pytest.mark.parametrize(
    "failure",
    [
        "unmapped",
        "local_unknown",
        "local_unavailable",
        "local_restored",
        "local_stale",
        "local_connected",
        "soc_invalid",
        "soc_restored",
        "soc_future",
        "raised_minimum",
        "corrupt_recovery",
        "fresh_home_connected",
        "fresh_charging_away",
        "stale_grid",
        "stale_battery",
        "stale_house",
        "safety_lock",
        "wrong_owner",
        "unverified_sign",
        "no_paid_allowance",
    ],
)
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_local_absence_never_excuses_conflicts_or_other_export_protections(
    hass,
    monkeypatch,
    freezer,
    failure,
):
    rig = await _site(
        hass,
        monkeypatch,
        mapped=failure != "unmapped",
        price=failure in {"stale_battery", "stale_house"},
    )
    try:
        await _complete_and_leave(rig, freezer)
        at = _at(20, 55)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        if failure in {"local_unknown", "local_unavailable", "local_connected"}:
            state = {
                "local_unknown": "unknown",
                "local_unavailable": "unavailable",
                "local_connected": "on",
            }[failure]
            _set(hass, LOCAL, state, at=at)
        elif failure == "local_restored":
            _set(hass, LOCAL, "off", {"restored": True}, at=at)
        elif failure == "local_stale":
            _set(hass, LOCAL, "off", at=at - timedelta(seconds=91))
        elif failure in {"soc_invalid", "soc_restored"}:
            _set(
                hass,
                "sensor.test_ev_soc",
                "unavailable" if failure == "soc_invalid" else "43",
                {"unit_of_measurement": "%", "restored": failure == "soc_restored"},
                at=at,
            )
        elif failure == "soc_future":
            _set(
                hass,
                "sensor.test_ev_soc",
                "43",
                {"unit_of_measurement": "%"},
                at=at + timedelta(seconds=1),
            )
        elif failure == "raised_minimum":
            rig.entry.runtime_data.update_config_value("ev_before_export_soc_target_percent", 44)
        elif failure == "corrupt_recovery":
            key = f"{DOMAIN}.{rig.entry.entry_id}.ev_control"
            stored = await rig.harness.load_store(key)
            stored["before_export_recovery"] = {"pending": True, "binding": []}
            # Unload legitimately checkpoints the current process. Place the
            # corrupt restart input afterward, between real unload/setup,
            # exactly as a persisted fault occurs.
            await rig.harness.unload(rig.entry)
            await rig.harness.save_store(key, stored)
            await rig.harness.setup(rig.entry)
        elif failure == "fresh_home_connected":
            _vehicle(rig, at, soc=43)
        elif failure == "fresh_charging_away":
            # A delayed location report cannot make affirmative charging data
            # harmless: fresh charging conflicts with local disconnection.
            _vehicle(rig, at, soc=43, current=8, request=8, home=False)
        elif failure.startswith("stale_"):
            entity = {
                "stale_grid": "sensor.test_grid_power",
                "stale_battery": "sensor.test_battery_power",
                "stale_house": "sensor.test_house_load",
            }[failure]
            previous = hass.states.get(entity)
            _set(
                hass,
                entity,
                previous.state,
                dict(previous.attributes),
                at=at - timedelta(seconds=91),
            )
        elif failure == "safety_lock":
            rig.entry.runtime_data.update_config_value("rehearsal_mode", True)
        elif failure == "wrong_owner":
            rig.entry.runtime_data.update_config_value("foxess_control_owner", "foxcloud_scheduler")
        elif failure == "unverified_sign":
            rig.entry.runtime_data.update_config_value("sign_conventions_verified", False)
        elif failure == "no_paid_allowance":
            rig.entry.runtime_data.update_config_value("automatic_export_limit_kwh", 0)
        rig.harness.clear_service_calls()
        if failure in {"stale_battery", "stale_house"}:
            # Normal ZEROHERO retains its original battery-power/learned-house
            # contract. The independently stricter price path needs live power.
            rig.feed.side_effect = lambda: dispatch_report(datetime.now(UTC), price=5000)
            await rig.entry.runtime_data.async_refresh()
            await rig.entry.runtime_data.market_monitor.async_refresh()
        await _cycle(rig, at)
        assert not _calls(rig, entity=MODE, value="Force Discharge"), failure
        assert not _calls(rig, entity=DISCHARGE, value=15), failure
    finally:
        await _close(rig)


@pytest.mark.parametrize("ev_first", [False, True])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_reconnect_retracts_local_absence_and_export_cleans_up_before_ev_topup(
    hass,
    monkeypatch,
    freezer,
    ev_first,
):
    rig = await _site(hass, monkeypatch)
    try:
        await _complete_and_leave(rig, freezer, ev_first=ev_first, departure_soc=40)
        at = _at(20, 55)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        await _cycle(rig, at, ev_first=ev_first)
        assert rig.entry.runtime_data.active_controller.export_session.phase in {
            "starting",
            "active",
        }
        # Local plug detection arrives before cloud wake. It retracts absence
        # immediately and cannot fall back to the old disconnected frame.
        at += timedelta(seconds=1)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "on", at=at)
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=ev_first)
        assert _calls(rig, entity=MODE, value="Self Use")
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert not any(
            call.domain == "switch" and call.service == "turn_on"
            for call in rig.harness.service_calls
        )
        # A new current, coherent vehicle frame below the minimum re-arms the
        # normal recovery after the inverter's reducing cleanup has settled.
        at += timedelta(seconds=30)
        freezer.move_to(at)
        _vehicle(rig, at, soc=39)
        _electrical(rig, at, mode="Self Use")
        _set(hass, LOCAL, "on", at=at)
        await _cycle(rig, at, ev_first=ev_first)
        at += timedelta(seconds=30)
        freezer.move_to(at)
        _vehicle(rig, at, soc=39)
        _electrical(rig, at, mode="Self Use")
        _set(hass, LOCAL, "on", at=at)
        await _cycle(rig, at, ev_first=ev_first)
        assert rig.entry.runtime_data.ev_controller.before_export_release_target() == 41
        assert rig.entry.runtime_data.ev_controller.decision_phase == "ev_before_export_charging"
        assert not _calls(rig, entity=MODE, value="Force Discharge")
    finally:
        await _close(rig)


@pytest.mark.parametrize("reload", [False, True])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_local_unplug_does_not_acknowledge_a_genuine_unconfirmed_stop(
    hass,
    monkeypatch,
    freezer,
    reload,
):
    rig = await _site(hass, monkeypatch)
    try:
        # Vehicle measurements reach the release boundary while still drawing
        # current; the real EV controller requests stop and journals that duty.
        at = _at(19, 1)
        freezer.move_to(at)
        _vehicle(rig, at, soc=41, current=8, request=8)
        _electrical(rig, at, current=8)
        _set(hass, LOCAL, "on", at=at)
        await _cycle(rig, at)
        ev = rig.entry.runtime_data.ev_controller
        assert ev.before_export_release_target() is None
        assert ev.outside_stop_requested
        assert ev.daily_backfill_stop_pending
        assert any(
            call.domain == "switch" and call.service == "turn_off"
            for call in rig.harness.service_calls
        )
        # The switch command ack is optimistic. No genuine stopped vehicle
        # report follows; an independent unplug cannot certify its completion.
        old_measurement = rig.provider.data["charge_state_timestamp"]
        rig.provider.data["state"] = "asleep"
        at = _at(20, 55)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        if reload:
            await rig.harness.reload(rig.entry)
        rig.harness.clear_service_calls()
        await _cycle(rig, at)
        assert rig.entry.runtime_data.ev_controller.daily_backfill_stop_pending
        assert rig.provider.data["charge_state_timestamp"] == old_measurement
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        stored = await rig.harness.load_store(f"{DOMAIN}.{rig.entry.entry_id}.ev_control")
        assert stored["daily_backfill"]["stop_pending"]
    finally:
        await _close(rig)


@pytest.mark.parametrize("missing", [
    "sensor.test_ev_soc", "number.test_ev_current", "number.test_ev_limit",
    "device_tracker.test_ev",
])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_measured_stop_is_not_blocked_by_unrelated_policy_fields(
    hass, monkeypatch, freezer, missing,
):
    rig = await _site(hass, monkeypatch)
    try:
        at = _at(19, 1)
        freezer.move_to(at)
        _vehicle(rig, at, soc=41, current=8, request=8)
        _electrical(rig, at, current=8)
        _set(hass, LOCAL, "on", at=at)
        await _cycle(rig, at)
        ev = rig.entry.runtime_data.ev_controller
        assert ev.daily_backfill_stop_pending
        at += timedelta(seconds=10)
        freezer.move_to(at)
        _vehicle(rig, at, soc=41, current=0, request=8)
        _set(hass, missing, "unavailable", at=at)
        # Use the real stop reconciler and journal; policy input availability
        # grants no new authority and must not prevent acknowledging this stop.
        await ev._async_reconcile_outside_stop(at, None, gate="ready")
        assert not ev.daily_backfill_stop_pending
        assert not ev.outside_stop_requested
        stored = await rig.harness.load_store(f"{DOMAIN}.{rig.entry.entry_id}.ev_control")
        assert not stored["daily_backfill"]["stop_pending"]
    finally:
        await _close(rig)


@pytest.mark.parametrize("reload", [False, True])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_republished_disconnected_cache_cannot_clear_a_durable_stop(
    hass, monkeypatch, freezer, reload,
):
    rig = await _site(hass, monkeypatch)
    try:
        at = _at(19, 1)
        freezer.move_to(at)
        _vehicle(rig, at, soc=41, current=8, request=8)
        _electrical(rig, at, current=8)
        _set(hass, LOCAL, "on", at=at)
        await _cycle(rig, at)
        assert rig.entry.runtime_data.ev_controller.daily_backfill_stop_pending
        at += timedelta(seconds=1)
        freezer.move_to(at)
        _vehicle(rig, at, soc=41, current=16, connected=False, home=False)
        old_measurement = rig.provider.data["charge_state_timestamp"]
        rig.provider.data["state"] = "asleep"
        at = _at(20, 55)
        freezer.move_to(at)
        # A new HA cache publication is not a new physical measurement.
        for entity in FIELDS:
            state = hass.states.get(entity)
            _set(hass, entity, state.state, dict(state.attributes), at=at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        if reload:
            await rig.harness.reload(rig.entry)
        rig.harness.clear_service_calls()
        await _cycle(rig, at)
        assert rig.entry.runtime_data.ev_controller.daily_backfill_stop_pending
        assert rig.provider.data["charge_state_timestamp"] == old_measurement
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        stored = await rig.harness.load_store(f"{DOMAIN}.{rig.entry.entry_id}.ev_control")
        assert stored["daily_backfill"]["stop_pending"]
    finally:
        await _close(rig)


@pytest.mark.parametrize("reload", [False, True])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_genuine_disconnected_measurement_can_clear_stop_with_unchanged_ha_clocks(
    hass, monkeypatch, freezer, reload,
):
    rig = await _site(hass, monkeypatch)
    try:
        at = _at(19, 1)
        freezer.move_to(at)
        _vehicle(rig, at, soc=41, current=8, request=8)
        _electrical(rig, at, current=8)
        _set(hass, LOCAL, "on", at=at)
        await _cycle(rig, at)
        assert rig.entry.runtime_data.ev_controller.daily_backfill_stop_pending
        at += timedelta(seconds=1)
        freezer.move_to(at)
        _vehicle(rig, at, soc=41, current=16, connected=False, home=False)
        old_ha_clock = hass.states.get("binary_sensor.test_ev_cable").last_reported
        at = _at(20, 55)
        freezer.move_to(at)
        # The unchanged HA states remain old. Only the provider's genuine
        # native charge measurement advances, just as an unchanged entity may.
        rig.provider.data["charge_state_timestamp"] = at.timestamp() * 1000
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        if reload:
            await rig.harness.reload(rig.entry)
        await _cycle(rig, at)
        ev = rig.entry.runtime_data.ev_controller
        assert not ev.daily_backfill_stop_pending
        assert not ev.outside_stop_requested
        assert hass.states.get("binary_sensor.test_ev_cable").last_reported == old_ha_clock
        stored = await rig.harness.load_store(f"{DOMAIN}.{rig.entry.entry_id}.ev_control")
        assert not stored["daily_backfill"]["stop_pending"]
    finally:
        await _close(rig)


@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_local_unplug_cannot_extend_expired_price_export_permission(
    hass,
    monkeypatch,
    freezer,
):
    rig = await _site(hass, monkeypatch, price=True)
    try:
        await _complete_and_leave(rig, freezer)
        at = _at(22)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)
        rig.feed.side_effect = lambda: dispatch_report(datetime.now(UTC), price=5000)
        await rig.entry.runtime_data.async_refresh()
        await rig.entry.runtime_data.market_monitor.async_refresh()
        await _cycle(rig, at)
        active = rig.entry.runtime_data.active_controller
        assert active.export_session.authority_source == "price"
        original_deadline = active.export_session.price_deadline
        assert original_deadline is not None
        after = original_deadline + timedelta(seconds=1)
        freezer.move_to(after)
        _electrical(rig, after)
        _set(hass, LOCAL, "off", at=after)
        rig.feed.side_effect = lambda: dispatch_report(at, price=5000)
        rig.harness.clear_service_calls()
        await _cycle(rig, after)
        assert _calls(rig, entity=MODE, value="Self Use")
        assert _calls(rig, entity=DISCHARGE, value=0)
        assert not _calls(rig, entity=MODE, value="Force Discharge")
    finally:
        await _close(rig)


@pytest.mark.parametrize("loss", ["connected", "unavailable", "remapped"])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_local_absence_rechecked_between_positive_export_commands(
    hass,
    monkeypatch,
    freezer,
    loss,
):
    rig = await _site(hass, monkeypatch)
    try:
        await _complete_and_leave(rig, freezer)
        at = _at(20, 55)
        freezer.move_to(at)
        _electrical(rig, at)
        _set(hass, LOCAL, "off", at=at)

        def change_connection(entity, value):
            if entity != DISCHARGE or value <= 0:
                return
            if loss == "remapped":
                rig.entry.runtime_data.update_config_value("ev_local_connection_entity", None)
            else:
                _set(hass, LOCAL, "on" if loss == "connected" else "unavailable", at=at)

        rig.after_command = change_connection
        rig.harness.clear_service_calls()
        with pytest.raises(FoxessWriteBlocked):
            await _cycle(rig, at)
        assert _calls(rig, entity=DISCHARGE, value=15)
        assert not _calls(rig, entity=MODE, value="Force Discharge")
        assert hass.states.get(MODE).state == "Self Use"
        assert rig.entry.runtime_data.active_controller.export_session.phase == "starting"
        stored = await rig.harness.load_store(f"{DOMAIN}.{rig.entry.entry_id}.export_session")
        assert stored["phase"] == "starting"
        # Interrupted positive staging retains an owner and may only reduce.
        rig.after_command = None
        rig.harness.clear_service_calls()
        await _cycle(rig, at)
        assert _calls(rig, entity=DISCHARGE, value=0)
        assert not _calls(rig, entity=MODE, value="Force Discharge")
    finally:
        await _close(rig)
