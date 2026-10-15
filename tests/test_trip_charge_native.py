"""Native Trip parity and ownership against the actual EV request controller."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN
from custom_components.home_energy_orchestrator.coordinator import EnergyCoordinator
from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.ev_adapter import EvServiceAdapter
from custom_components.home_energy_orchestrator.trip_charge import TripChargeController

from .test_ev_active import _controller_config, _set_ev_states
from .test_setup import ENTRY_DATA

NOW = datetime(2026, 10, 11, 8, tzinfo=UTC)
DUE = NOW + timedelta(hours=12)
pytestmark = pytest.mark.freeze_time(NOW, real_asyncio=True)


async def test_explicit_capacity_replaces_ratio_for_native_trip_without_stored_energy(trip_site):
    site = await trip_site(
        soc=20, capacity=120, ev_capacity_source="configured", ev_capacity_fallback_kwh=80
    )
    site.hass.states.async_set("sensor.car_energy", "unavailable")
    await _arm(site, target=50)
    inputs = site.trip._current_plan_inputs()
    assert inputs["capacity_kwh"] == 80
    assert site.trip.planned_start is not None
    assert site.trip.planned_start == DUE - timedelta(hours=24 / (3.6 * 0.9))
    assert not site.trip.owns_full
    assert site.calls == []


async def test_selected_capacity_failure_does_not_start_native_trip_using_ratio(trip_site):
    site = await trip_site(
        soc=20,
        capacity=120,
        ev_capacity_source="mapped_entity",
        ev_capacity_entity="sensor.pack_capacity",
    )
    site.hass.states.async_set("sensor.pack_capacity", "unavailable")
    await _arm(site, target=50)
    assert site.trip._current_plan_inputs()["capacity_kwh"] is None
    assert site.trip.planned_start is None
    assert not site.trip.owns_full
    assert site.calls == []


@pytest.fixture
async def trip_site(hass, freezer):
    """Actual HA, persisted entry and EV controller; actuator services are local fakes."""
    freezer.move_to(NOW)
    await hass.config.async_set_time_zone("Australia/Sydney")
    sites = []
    calls = []

    async def actuator(call):
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            assert len(entity) == 1
            entity = entity[0]
        assert entity in {"number.car_current", "number.car_limit", "switch.car_charge"}
        calls.append((call.domain, call.service, dict(call.data)))
        old = hass.states.get(entity)
        value = call.data.get("value", "on" if call.service == "turn_on" else "off")
        hass.states.async_set(entity, str(value), dict(old.attributes), context=call.context)

    hass.services.async_register("number", "set_value", actuator)
    hass.services.async_register("switch", "turn_on", actuator)
    hass.services.async_register("switch", "turn_off", actuator)

    async def create(*, soc=80, capacity=60, phases=1, voltage=225, **changes):
        _set_ev_states(hass)
        hass.states.async_set("sensor.car_soc", str(soc), {"unit_of_measurement": "%"})
        hass.states.async_set(
            "sensor.car_energy", str(capacity * soc / 100), {"unit_of_measurement": "kWh"}
        )
        for entity, value, unit in (
            ("sensor.test_grid_power", 0, "kW"),
            ("sensor.test_house_load", 0.8, "kW"),
            ("sensor.site_current", 0, "A"),
            ("sensor.battery_signed", 0, "kW"),
        ):
            hass.states.async_set(entity, str(value), {"unit_of_measurement": unit})
        config = {
            **ENTRY_DATA,
            **_controller_config(
                configure_ev=True,
                site_grid_current_entity="sensor.site_current",
                battery_power_entity="sensor.battery_signed",
                ev_phase_count=phases,
                site_phase_count=phases,
                ev_voltage=voltage,
                ev_protected_baseline_a=1,
                ev_charge_to_full_enabled=False,
                ev_charge_to_full_max_hours=12,
                **changes,
            ),
        }
        entry = MockConfigEntry(domain=DOMAIN, title="Native trip fixture", data=config, version=6)
        entry.add_to_hass(hass)
        coordinator = EnergyCoordinator(hass, dict(config), entry.entry_id)
        await coordinator.async_refresh()
        ev = ActiveEvController(hass, coordinator)
        coordinator.ev_controller = ev
        # This is the existing HEO usable-capacity projection, not a guessed car
        # profile. Retaining it lets the 1%-target vector exercise SoC exactly 0.
        ev.learned_charge_limit = SimpleNamespace(usable_capacity_kwh=capacity)
        trip = TripChargeController(hass, coordinator, entry)
        coordinator.trip_charge = trip
        await trip.async_start()
        site = SimpleNamespace(
            hass=hass,
            freezer=freezer,
            coordinator=coordinator,
            ev=ev,
            trip=trip,
            entry=entry,
            calls=calls,
            capacity=capacity,
        )
        sites.append(site)
        return site

    yield create
    for site in sites:
        site.coordinator.shutdown()
        await site.trip.async_stop()
        await site.ev.async_stop()
    await hass.async_block_till_done(wait_background_tasks=True)
    for site in sites:
        await site.coordinator.async_shutdown()


async def _reconcile(site, at=None):
    if at is not None:
        site.freezer.move_to(at)
    # Fast electrical sources are fresh; stable SoC retains its value semantics.
    for entity in (
        "sensor.test_grid_power",
        "sensor.test_house_load",
        "sensor.site_current",
        "sensor.battery_signed",
    ):
        old = site.hass.states.get(entity)
        site.hass.states.async_set(entity, old.state, dict(old.attributes), force_update=True)
    await site.coordinator.async_refresh()
    site.ev.learned_charge_limit = SimpleNamespace(usable_capacity_kwh=site.capacity)
    await site.trip.async_reconcile(at)


async def _arm(site, *, target=90, due=DUE):
    await site.trip.async_set_departure(due)
    await site.trip.async_set_target_soc(target)
    await site.trip.async_set_armed(True)
    await _reconcile(site)


async def _start(site, *, target=90):
    await _arm(site, target=target)
    start = site.trip.planned_start
    assert start is not None
    await _reconcile(site, start + timedelta(seconds=1))
    assert site.trip.owns_full
    assert site.ev._charge_to_full_requested()


async def test_default_is_disarmed_without_helper_or_hardware_installation(trip_site):
    site = await trip_site()
    assert not site.trip.armed and not site.trip.owns_full
    assert site.trip.target_soc == 100
    assert site.trip.departure is None
    assert not site.ev._charge_to_full_requested()
    assert site.calls == []
    assert not any(s.entity_id.startswith("input_") for s in site.hass.states.async_all())


@pytest.mark.parametrize("target", [1, 80, 90, 100])
@pytest.mark.parametrize("phases,voltage", [(1, 225), (3, 230)])
async def test_selected_target_math_uses_heo_capacity_and_configured_maximum(
    trip_site, target, phases, voltage
):
    site = await trip_site(soc=target - 1, phases=phases, voltage=voltage)
    await _arm(site, target=target)
    expected_hours = (60 / 100) / (16 * voltage * phases / 1000 * 0.9)
    assert site.trip.planned_hours == pytest.approx(expected_hours, abs=1e-6)
    assert site.trip.planned_start.timestamp() == pytest.approx(
        DUE.timestamp() - expected_hours * 3600, abs=1e-3
    )
    assert not site.ev._charge_to_full_requested()
    assert site.calls == []


async def test_extra_minutes_preserves_the_original_deficit_arithmetic(trip_site):
    site = await trip_site()
    await site.trip.async_set_extra_minutes(15)
    await _arm(site)
    assert site.trip.planned_hours == pytest.approx(6 / (3.6 * 0.9) + 0.25, abs=1e-6)


async def test_start_exactly_once_and_immediate_selected_soc_completion(trip_site):
    site = await trip_site()
    before = dict(site.entry.data)
    await _start(site)
    generation = site.trip.attributes["full_generation"]
    await _reconcile(site)
    assert site.trip.attributes["full_generation"] == generation
    site.hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
    await _reconcile(site)
    assert not site.ev._charge_to_full_requested()
    assert not site.trip.armed and not site.trip.owns_full
    assert site.trip.status == "completed"
    site.hass.states.async_set("sensor.car_soc", "80", {"unit_of_measurement": "%"})
    await _reconcile(site)
    assert not site.ev._charge_to_full_requested()
    for key in ("ev_automatic_control_enabled", "rehearsal_mode", "automatic_control_enabled"):
        assert site.entry.data[key] == before[key]


async def test_already_at_target_stays_armed_until_departure_without_full(trip_site):
    site = await trip_site(soc=90)
    await _arm(site, target=80)
    assert site.trip.armed and not site.trip.owns_full
    assert site.trip.planned_hours == 0
    assert site.trip.status == "already_at_target"
    assert site.calls == []


async def test_exact_unstarted_deadline_expires_without_a_paid_request(trip_site):
    site = await trip_site()
    await site.trip.async_set_departure(DUE)
    await site.trip.async_set_target_soc(90)
    site.freezer.move_to(DUE)
    await site.trip.async_set_armed(True)
    await _reconcile(site, DUE)
    assert not site.trip.armed and not site.ev._charge_to_full_requested()
    assert site.trip.status == "expired"


async def test_owned_late_trip_retains_original_override_not_a_new_start(trip_site):
    site = await trip_site()
    await _start(site)
    generation = site.trip.attributes["full_generation"]
    await _reconcile(site, DUE)
    assert site.trip.owns_full and site.ev._charge_to_full_requested()
    assert site.trip.status == "charging_late"
    assert site.trip.attributes["full_generation"] == generation


@pytest.mark.parametrize("edit", ["cancel", "target", "departure"])
async def test_active_edit_or_cancel_withdraws_only_owned_full_and_consumes_trip(trip_site, edit):
    site = await trip_site()
    await _start(site)
    if edit == "cancel":
        await site.trip.async_set_armed(False)
    elif edit == "target":
        await site.trip.async_set_target_soc(100)
    else:
        await site.trip.async_set_departure(DUE + timedelta(days=1))
    await _reconcile(site)
    assert not site.ev._charge_to_full_requested()
    assert not site.trip.armed and not site.trip.owns_full
    assert site.trip.status == "cancelled"


async def test_waiting_edit_replans_and_old_start_cannot_activate_full(trip_site):
    site = await trip_site()
    await _arm(site)
    old_start = site.trip.planned_start
    await site.trip.async_set_departure(DUE + timedelta(days=1))
    await site.trip.async_set_target_soc(100)
    await _reconcile(site, old_start)
    assert site.trip.planned_start > old_start
    assert site.trip.armed and not site.trip.owns_full
    assert not site.ev._charge_to_full_requested()


@pytest.mark.parametrize("soc", ["unknown", "unavailable", "-1", "101", "NaN", "inf"])
async def test_invalid_soc_never_starts_and_interrupts_only_owned_full(trip_site, soc):
    site = await trip_site()
    await _start(site)
    site.hass.states.async_set("sensor.car_soc", soc, {"unit_of_measurement": "%"})
    await _reconcile(site)
    assert not site.ev._charge_to_full_requested()
    assert not site.trip.armed and not site.trip.owns_full
    assert site.trip.status == "interrupted"


@pytest.mark.parametrize(
    "field,value",
    [
        ("ev_automatic_control_enabled", False),
        ("rehearsal_mode", True),
        ("ev_control_commissioned", False),
        ("sign_conventions_verified", False),
    ],
)
async def test_commissioning_gates_never_enable_or_bypass_policy(trip_site, field, value):
    site = await trip_site(**{field: value})
    await _arm(site)
    await _reconcile(site, DUE - timedelta(minutes=1))
    assert not site.trip.owns_full and not site.ev._charge_to_full_requested()
    assert site.entry.data[field] == value
    assert site.calls == []


@pytest.mark.parametrize(
    "entity,state",
    [
        ("device_tracker.car", "not_home"),
        ("binary_sensor.car_cable", "off"),
        ("device_tracker.car", "unknown"),
        ("binary_sensor.car_cable", "unavailable"),
    ],
)
async def test_home_and_cable_are_explicit_start_gates(trip_site, entity, state):
    site = await trip_site()
    site.hass.states.async_set(entity, state)
    await _arm(site)
    await _reconcile(site, DUE - timedelta(minutes=1))
    assert not site.ev._charge_to_full_requested() and not site.trip.owns_full
    assert site.calls == []


async def test_existing_manual_full_is_not_adopted_or_stopped(trip_site):
    site = await trip_site()
    await site.ev.async_request_charge_to_full(True)
    generation = site.trip.attributes["full_generation"]
    await _arm(site)
    await _reconcile(site, DUE - timedelta(minutes=1))
    assert site.ev._charge_to_full_requested()
    assert site.trip.attributes["full_generation"] == generation
    assert not site.trip.owns_full
    await site.trip.async_set_armed(False)
    assert site.ev._charge_to_full_requested()


async def test_legacy_dispatcher_conflict_is_visible_and_has_no_takeover(trip_site):
    site = await trip_site()
    site.hass.states.async_set(
        "automation.heo_trip_charge_schedule_existing_full_override",
        "on",
        {"id": "heo_trip_charge_dispatch"},
    )
    site.hass.states.async_set("input_boolean.heo_trip_charge_scheduled", "off")
    site.hass.states.async_set("input_boolean.heo_trip_charge_started", "off")
    await site.trip.async_set_departure(DUE)
    with pytest.raises(HomeAssistantError, match="legacy"):
        await site.trip.async_set_armed(True)
    await _reconcile(site, DUE - timedelta(minutes=1))
    assert not site.ev._charge_to_full_requested()
    assert not site.trip.owns_full
    assert "legacy" in site.trip.status
    assert (
        site.hass.states.get("automation.heo_trip_charge_schedule_existing_full_override").state
        == "on"
    )


async def test_retired_legacy_wrapper_does_not_block_a_deliberate_new_trip(trip_site):
    site = await trip_site()
    site.hass.states.async_set(
        "automation.heo_trip_charge_schedule_existing_full_override",
        "off",
        {"id": "heo_trip_charge_dispatch"},
    )
    site.hass.states.async_set("input_boolean.heo_trip_charge_scheduled", "off")
    site.hass.states.async_set("input_boolean.heo_trip_charge_started", "off")
    await _start(site)
    assert site.trip.owns_full


async def test_restored_waiting_schedule_catches_up_without_rearming_completed_trip(trip_site):
    site = await trip_site()
    await _arm(site)
    start = site.trip.planned_start
    await site.trip.async_stop()
    restored = TripChargeController(site.hass, site.coordinator, site.entry)
    site.coordinator.trip_charge = site.trip = restored
    await restored.async_start()
    assert restored.armed and not restored.owns_full
    await _reconcile(site, start + timedelta(seconds=1))
    assert restored.owns_full
    site.hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
    await _reconcile(site)
    await restored.async_stop()
    completed = TripChargeController(site.hass, site.coordinator, site.entry)
    site.coordinator.trip_charge = site.trip = completed
    await completed.async_start()
    await _reconcile(site)
    assert not completed.armed and not site.ev._charge_to_full_requested()


async def test_restored_owned_generation_can_release_only_its_captured_target(trip_site):
    site = await trip_site()
    await _start(site)
    generation = site.trip.attributes["full_generation"]
    await site.trip.async_stop()
    restored = TripChargeController(site.hass, site.coordinator, site.entry)
    site.coordinator.trip_charge = site.trip = restored
    await restored.async_start()
    assert restored.owns_full
    assert site.trip.attributes["full_generation"] == generation
    site.hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
    await _reconcile(site)
    assert not site.ev._charge_to_full_requested() and not restored.armed


async def test_corrupt_trip_journal_does_not_adopt_a_manual_full(trip_site, monkeypatch):
    site = await trip_site()
    await site.ev.async_request_charge_to_full(True)
    await site.trip.async_stop()
    broken = TripChargeController(site.hass, site.coordinator, site.entry)
    site.coordinator.trip_charge = site.trip = broken
    monkeypatch.setattr(broken._store, "async_load", AsyncMock(return_value={"schema": 99}))
    await broken.async_start()
    await _reconcile(site)
    assert not site.trip.armed and not site.trip.owns_full
    assert site.ev._charge_to_full_requested()
    assert site.trip.status == "invalid_storage"


async def test_failed_pre_action_save_never_requests_full(trip_site, monkeypatch):
    site = await trip_site()
    await _arm(site)
    original_save = site.trip._store.async_save
    positive_checkpoint_reached = False

    async def failed_positive_checkpoint(payload):
        nonlocal positive_checkpoint_reached
        if payload.get("full_enabled") and str(payload.get("owner_token", "")).startswith("trip:"):
            positive_checkpoint_reached = True
        if positive_checkpoint_reached:
            raise OSError("disk")
        await original_save(payload)

    monkeypatch.setattr(site.trip._store, "async_save", failed_positive_checkpoint)
    try:
        await _reconcile(site, site.trip.planned_start + timedelta(seconds=1))
    except (OSError, HomeAssistantError):
        pass  # Either explicit failure or a visible fail-closed status is acceptable.
    assert positive_checkpoint_reached
    assert not site.ev._charge_to_full_requested()
    assert not site.trip.armed
    assert site.trip.status == "storage_unavailable"
    assert site.trip.attributes["cleanup_pending"]
    monkeypatch.setattr(site.trip._store, "async_save", original_save)
    await _reconcile(site)
    assert not site.trip.owns_full and not site.ev._charge_to_full_requested()


async def test_manual_off_on_new_generation_survives_old_completion(trip_site):
    site = await trip_site()
    await _start(site)
    old_generation = site.trip.attributes["full_generation"]
    await site.ev.async_request_charge_to_full(False)
    await site.ev.async_request_charge_to_full(True)
    new_generation = site.trip.attributes["full_generation"]
    assert new_generation > old_generation
    site.hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
    await _reconcile(site)
    assert site.ev._charge_to_full_requested()
    assert site.trip.attributes["full_generation"] == new_generation
    assert not site.trip.owns_full and not site.trip.armed


async def test_queued_old_release_rechecks_generation_inside_actual_ev_lock(trip_site):
    site = await trip_site()
    await _start(site)
    token = site.trip.attributes["owner_token"]
    generation = site.trip.attributes["full_generation"]
    await site.ev._lock.acquire()
    manual_off = asyncio.create_task(site.ev.async_request_charge_to_full(False, reconcile=False))
    manual_on = asyncio.create_task(site.ev.async_request_charge_to_full(True, reconcile=False))
    stale_release = asyncio.create_task(
        site.ev.async_request_charge_to_full(
            False, owner_token=token, expected_generation=generation, reconcile=False
        )
    )
    await asyncio.sleep(0)
    # Three awaited callers must validate ownership after obtaining the lock.
    site.ev._lock.release()
    _, _, rejected = await asyncio.gather(manual_off, manual_on, stale_release)
    assert rejected["accepted"] is False
    assert site.ev._charge_to_full_requested()
    assert not site.trip.owns_full


@pytest.mark.parametrize("kind", ["manual_off", "natural_clear"])
async def test_full_off_config_failure_retains_durable_application_until_restart(
    trip_site, monkeypatch, kind
):
    """A crash after the lease checkpoint must not orphan the old Full ON."""
    site = await trip_site()
    await _start(site)
    original = site.coordinator.update_persisted_config_value
    reached_window = False

    def broken_config(entry, key, value, **kwargs):
        nonlocal reached_window
        if key == "ev_charge_to_full_enabled" and value is False:
            reached_window = True
            raise OSError("config checkpoint failed after journal")
        return original(entry, key, value, **kwargs)

    monkeypatch.setattr(site.coordinator, "update_persisted_config_value", broken_config)
    try:
        if kind == "manual_off":
            await site.ev.async_request_charge_to_full(False, reconcile=False)
        else:
            async with site.ev._lock:
                await site.ev._async_clear_charge_to_full()
    except (OSError, HomeAssistantError):
        pass
    assert reached_window, "The test must reach the config-write crash boundary"
    assert site.ev._charge_to_full_requested()
    await site.trip.async_stop()
    monkeypatch.setattr(site.coordinator, "update_persisted_config_value", original)
    restored = TripChargeController(site.hass, site.coordinator, site.entry)
    site.coordinator.trip_charge = site.trip = restored
    await restored.async_start()
    await _reconcile(site)
    assert not site.ev._charge_to_full_requested()
    assert not restored.armed and not restored.owns_full


async def test_failed_manual_on_cannot_revoke_an_existing_trip_lease(trip_site, monkeypatch):
    site = await trip_site()
    await _start(site)
    original_save = site.trip._store.async_save
    original = dict(site.trip.attributes)
    monkeypatch.setattr(site.trip._store, "async_save", AsyncMock(side_effect=OSError("disk")))
    try:
        result = await site.ev.async_request_charge_to_full(True, reconcile=False)
        assert result["accepted"] is False
    except (OSError, HomeAssistantError):
        pass
    assert site.ev._charge_to_full_requested()
    assert site.trip.armed and site.trip.owns_full
    assert site.trip.attributes["owner_token"] == original["owner_token"]
    assert site.trip.attributes["full_generation"] == original["full_generation"]
    monkeypatch.setattr(site.trip._store, "async_save", original_save)
    site.hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
    await _reconcile(site)
    assert not site.ev._charge_to_full_requested()
    assert site.trip.status == "completed"


@pytest.mark.parametrize("soc", ["unknown", "unavailable", "-1", "101", "NaN", "inf"])
async def test_invalid_soc_before_start_remains_waiting_without_a_full_request(trip_site, soc):
    site = await trip_site()
    site.hass.states.async_set("sensor.car_soc", soc, {"unit_of_measurement": "%"})
    await _arm(site)
    await _reconcile(site, DUE - timedelta(minutes=1))
    assert site.trip.status == "waiting_for_data"
    assert not site.trip.owns_full and not site.ev._charge_to_full_requested()
    assert site.calls == []


@pytest.mark.parametrize("target", [0, 101, 80.5, True, "80"])
async def test_noninteger_or_out_of_range_target_is_rejected_without_rounding(trip_site, target):
    site = await trip_site()
    with pytest.raises(HomeAssistantError):
        await site.trip.async_set_target_soc(target)
    assert site.trip.target_soc == 100
    assert not site.trip.armed and site.calls == []


async def test_completion_with_safety_lock_withdraws_intent_without_actuator_bypass(trip_site):
    site = await trip_site()
    await _start(site)
    count = len(site.calls)
    site.coordinator.update_config_value("rehearsal_mode", True)
    site.hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
    await _reconcile(site)
    assert not site.ev._charge_to_full_requested()
    assert site.trip.status == "completed"
    assert len(site.calls) == count


async def test_completed_off_checkpoint_reduces_a_stale_restored_on_without_restart(
    trip_site,
):
    site = await trip_site()
    await _start(site)
    site.hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
    await _reconcile(site)
    assert site.trip.status == "completed"
    assert not site.ev._charge_to_full_requested()
    # Simulate HA restoring the older persisted configuration despite the
    # durable trip OFF checkpoint. This is not a fresh operator generation.
    site.coordinator.update_persisted_config_value(site.entry, "ev_charge_to_full_enabled", True)
    await site.trip.async_stop()
    restored = TripChargeController(site.hass, site.coordinator, site.entry)
    site.coordinator.trip_charge = site.trip = restored
    await restored.async_start()
    await _reconcile(site)
    assert not site.ev._charge_to_full_requested()
    assert not restored.armed and not restored.owns_full


async def test_old_off_checkpoint_cannot_replay_over_a_new_operator_generation(trip_site):
    site = await trip_site()
    await _start(site)
    site.hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
    await _reconcile(site)
    previous = site.trip.attributes["full_generation"]
    await site.ev.async_request_charge_to_full(True, reconcile=False)
    current = site.trip.attributes["full_generation"]
    assert current > previous
    rejected = await site.ev.async_request_charge_to_full(
        False, expected_generation=previous, reconcile=False
    )
    assert rejected["accepted"] is False
    await _reconcile(site)
    assert site.ev._charge_to_full_requested()
    assert site.trip.attributes["full_generation"] == current


@pytest.mark.parametrize("interruption", ["cancel", "target", "soc", "gate", "capacity"])
async def test_last_awaited_start_checkpoint_rechecks_current_intent_before_full_on(
    trip_site, monkeypatch, interruption
):
    site = await trip_site()
    await _arm(site)
    entered, release = asyncio.Event(), asyncio.Event()
    original_save = site.trip._store.async_save
    original_config = site.coordinator.update_persisted_config_value
    full_on_updates = []

    async def pause_checkpoint(payload):
        if payload.get("full_enabled") and str(payload.get("owner_token", "")).startswith("trip:"):
            entered.set()
            await release.wait()
        await original_save(payload)

    def record_config(entry, key, value, **kwargs):
        if key == "ev_charge_to_full_enabled" and value is True:
            full_on_updates.append(value)
        return original_config(entry, key, value, **kwargs)

    monkeypatch.setattr(site.trip._store, "async_save", pause_checkpoint)
    monkeypatch.setattr(site.coordinator, "update_persisted_config_value", record_config)
    start = asyncio.create_task(_reconcile(site, site.trip.planned_start + timedelta(seconds=1)))
    await asyncio.wait_for(entered.wait(), timeout=2)
    edit = None
    if interruption == "cancel":
        edit = asyncio.create_task(site.trip.async_set_armed(False))
    elif interruption == "target":
        edit = asyncio.create_task(site.trip.async_set_target_soc(100))
    elif interruption == "soc":
        site.hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
    elif interruption == "gate":
        site.coordinator.update_config_value("rehearsal_mode", True)
    else:
        site.ev.learned_charge_limit = SimpleNamespace(usable_capacity_kwh=None)
    await asyncio.sleep(0)
    release.set()
    await start
    if edit is not None:
        await edit
    assert full_on_updates == []
    assert not site.ev._charge_to_full_requested()


async def _setup_actual_site(site, monkeypatch):
    """Keep the integration lifecycle real and replace only device transport."""
    site.coordinator.shutdown()
    await site.trip.async_stop()
    await site.ev.async_stop()
    await site.coordinator.async_shutdown()
    actuator_commands = []

    async def local_actuator(adapter, command):
        # Leave the real adapter's commissioning and per-command write guard
        # intact. Only its final device-service transport is an isolated fake.
        actuator_commands.append(command)
        if command.action == "set_charge_current":
            entity, value = adapter.entities.charge_current_entity, command.value
        elif command.action == "set_charge_limit":
            entity, value = adapter.entities.charge_limit_entity, command.value
        else:
            assert command.action in {"start_charging", "stop_charging"}
            entity = adapter.entities.charge_switch_entity
            value = "on" if command.action == "start_charging" else "off"
        old = site.hass.states.get(entity)
        site.hass.states.async_set(entity, str(value), dict(old.attributes))

    monkeypatch.setattr(EvServiceAdapter, "_async_execute_command", local_actuator)
    assert await site.hass.config_entries.async_setup(site.entry.entry_id)
    await site.hass.async_block_till_done()
    site.coordinator = site.entry.runtime_data
    site.ev, site.trip = site.coordinator.ev_controller, site.coordinator.trip_charge
    return actuator_commands


@pytest.fixture
async def actual_trip_site(trip_site, monkeypatch):
    site = await trip_site()
    site.actuator_commands = await _setup_actual_site(site, monkeypatch)
    yield site
    assert await site.hass.config_entries.async_unload(site.entry.entry_id)
    await site.hass.async_block_till_done()


async def test_actual_config_entry_reload_preserves_owned_trip_and_releases_at_target(
    trip_site, monkeypatch
):
    """Exercise setup/unload, not only a replacement Trip on the old EV object."""
    site = await trip_site()
    actuator_commands = await _setup_actual_site(site, monkeypatch)
    try:
        # Too little lead time for the deficit makes this a due start without
        # advancing all the actual integration timers by many hours.
        await site.trip.async_set_departure(NOW + timedelta(minutes=10))
        await site.trip.async_set_target_soc(90)
        await site.trip.async_set_armed(True)
        await site.trip.async_reconcile()
        assert site.trip.owns_full and site.ev._charge_to_full_requested(), (
            site.trip.status,
            site.trip.planned_hours,
            site.ev.learned_charge_limit,
            site.ev.gate_status,
            site.coordinator.data.ev_max_power_kw,
        )
        lease = (site.trip.attributes["owner_token"], site.trip.attributes["full_generation"])
        previous_ev = site.ev
        settings = {
            key: value
            for key, value in site.entry.data.items()
            if key != "ev_charge_to_full_enabled"
        }
        assert await site.hass.config_entries.async_reload(site.entry.entry_id)
        await site.hass.async_block_till_done()
        site.coordinator = site.entry.runtime_data
        site.ev, site.trip = site.coordinator.ev_controller, site.coordinator.trip_charge
        assert site.ev is not previous_ev
        assert site.trip.armed and site.trip.owns_full
        assert site.ev._charge_to_full_requested()
        assert (
            site.trip.attributes["owner_token"],
            site.trip.attributes["full_generation"],
        ) == lease
        assert site.trip.target_soc == 90
        assert site.trip.departure == NOW + timedelta(minutes=10)
        site.hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
        await site.trip.async_reconcile()
        await site.hass.async_block_till_done()
        assert site.trip.status == "completed"
        assert not site.trip.armed and not site.trip.owns_full
        assert not site.ev._charge_to_full_requested()
        assert {
            key: value
            for key, value in site.entry.data.items()
            if key != "ev_charge_to_full_enabled"
        } == settings
        assert actuator_commands
    finally:
        assert await site.hass.config_entries.async_unload(site.entry.entry_id)
        await site.hass.async_block_till_done()


@pytest.mark.parametrize(
    ("entity", "state"),
    [
        ("device_tracker.car", "not_home"),
        ("device_tracker.car", "unavailable"),
        ("binary_sensor.car_cable", "off"),
        ("binary_sensor.car_cable", "unknown"),
    ],
)
async def test_owned_disconnect_consumes_trip_and_withdraws_only_its_full(trip_site, entity, state):
    site = await trip_site()
    await _start(site)
    site.hass.states.async_set(entity, state)
    await _reconcile(site)
    assert not site.ev._charge_to_full_requested()
    assert not site.trip.armed and not site.trip.owns_full
    assert site.trip.status == "interrupted"
    site.hass.states.async_set("device_tracker.car", "home")
    site.hass.states.async_set("binary_sensor.car_cable", "on")
    await _reconcile(site)
    assert not site.ev._charge_to_full_requested()


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("full_owner", "operator"),
        ("owner_token", "trip:999999"),
        ("owner_token", "trip:01"),
        ("owned_generation", 999999),
        ("captured_departure", None),
        ("captured_target", None),
        ("target_soc", 0),
        ("armed", "on"),
        ("extra_minutes", float("nan")),
    ],
)
async def test_corrupt_owned_journal_cannot_adopt_or_release_live_full(
    trip_site, monkeypatch, field, bad_value
):
    site = await trip_site()
    await _start(site)
    payload = site.trip._state.to_payload()
    payload[field] = bad_value
    await site.trip.async_stop()
    calls_before = list(site.calls)
    broken = TripChargeController(site.hass, site.coordinator, site.entry)
    site.coordinator.trip_charge = site.trip = broken
    monkeypatch.setattr(broken._store, "async_load", AsyncMock(return_value=payload))
    await broken.async_start()
    await _reconcile(site)
    assert broken.status == "invalid_storage"
    assert not broken.armed and not broken.owns_full
    assert site.ev._charge_to_full_requested()
    assert site.calls == calls_before


def _trip_entity(site, platform, key):
    entity = er.async_get(site.hass).async_get_entity_id(
        platform, DOMAIN, f"{site.entry.entry_id}_{key}"
    )
    assert entity is not None
    return entity


async def _start_through_native_services(site):
    due = NOW + timedelta(minutes=10)
    for domain, service, key, data in (
        ("datetime", "set_value", "trip_ready_by", {"datetime": due.isoformat()}),
        ("select", "select_option", "trip_target_soc", {"option": "90%"}),
        ("switch", "turn_on", "trip_charge_scheduled", {}),
    ):
        await site.hass.services.async_call(
            domain, service, {"entity_id": _trip_entity(site, domain, key), **data}, blocking=True
        )
    await site.hass.async_block_till_done()
    assert site.trip.armed and site.trip.owns_full and site.ev._charge_to_full_requested()
    assert site.ev.charge_to_full_started_at is not None


@pytest.mark.parametrize("repeat", ["schedule_on", "target", "departure", "departure_other_zone"])
async def test_unchanged_native_service_requests_never_cancel_or_restart_owned_trip(
    actual_trip_site, repeat
):
    site = actual_trip_site
    await _start_through_native_services(site)
    original = site.trip._state
    started_at = site.ev.charge_to_full_started_at
    commands = list(site.actuator_commands)
    if repeat == "schedule_on":
        domain, service, key, data = "switch", "turn_on", "trip_charge_scheduled", {}
    elif repeat == "target":
        domain, service, key, data = "select", "select_option", "trip_target_soc", {"option": "90%"}
    else:
        departure = site.trip.departure
        if repeat == "departure_other_zone":
            departure = departure.astimezone(ZoneInfo("Australia/Sydney"))
        domain, service, key = "datetime", "set_value", "trip_ready_by"
        data = {"datetime": departure.isoformat()}
    for _ in range(2):
        await site.hass.services.async_call(
            domain, service, {"entity_id": _trip_entity(site, domain, key), **data}, blocking=True
        )
    await site.hass.async_block_till_done()
    assert site.trip._state == original
    assert site.trip.armed and site.trip.owns_full and site.ev._charge_to_full_requested()
    assert site.ev.charge_to_full_started_at == started_at
    assert site.actuator_commands == commands


async def test_active_extra_minutes_service_edit_preserves_captured_trip_and_full_timeout(
    actual_trip_site,
):
    site = actual_trip_site
    await _start_through_native_services(site)
    original = site.trip._state
    started_at = site.ev.charge_to_full_started_at
    commands = list(site.actuator_commands)
    for extra in (15, 30):
        await site.hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": _trip_entity(site, "number", "trip_extra_minutes"), "value": extra},
            blocking=True,
        )
        assert site.trip.extra_minutes == extra
        assert site.trip.armed and site.trip.owns_full and site.ev._charge_to_full_requested()
        for field in (
            "full_generation",
            "full_owner",
            "owner_token",
            "owned_generation",
            "captured_departure",
            "captured_target",
            "departure",
            "target_soc",
        ):
            assert getattr(site.trip._state, field) == getattr(original, field)
        assert site.ev.charge_to_full_started_at == started_at
    await site.hass.async_block_till_done()
    assert site.actuator_commands == commands


async def test_repeated_native_schedule_off_retries_pending_owned_cleanup(
    actual_trip_site, monkeypatch
):
    site = actual_trip_site
    await _start_through_native_services(site)
    original_config = site.coordinator.update_persisted_config_value
    off_attempts = []

    def fail_off(entry, key, value, **kwargs):
        if key == "ev_charge_to_full_enabled" and value is False:
            off_attempts.append(False)
            raise OSError("Full OFF configuration checkpoint unavailable")
        return original_config(entry, key, value, **kwargs)

    monkeypatch.setattr(site.coordinator, "update_persisted_config_value", fail_off)
    try:
        await site.hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": _trip_entity(site, "switch", "trip_charge_scheduled")},
            blocking=True,
        )
    except (OSError, HomeAssistantError):
        pass
    assert off_attempts
    assert not site.trip.armed and site.trip.owns_full
    assert site.trip.attributes["cleanup_pending"]
    assert site.ev._charge_to_full_requested()
    monkeypatch.setattr(site.coordinator, "update_persisted_config_value", original_config)
    await site.hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": _trip_entity(site, "switch", "trip_charge_scheduled")},
        blocking=True,
    )
    await site.hass.async_block_till_done()
    assert not site.trip.armed and not site.trip.owns_full
    assert not site.trip.attributes["cleanup_pending"]
    assert not site.ev._charge_to_full_requested()


async def _restore_corrupt_journal_over_unowned_full(site):
    await site.ev.async_request_charge_to_full(True)
    assert site.ev._charge_to_full_requested() and not site.trip.owns_full
    await site.trip.async_stop()
    corrupt = {"schema": 99, "unrecognised_journal": "must not be replaced by an ordinary edit"}
    await site.trip._store.async_save(corrupt)
    restored = TripChargeController(site.hass, site.coordinator, site.entry)
    site.coordinator.trip_charge = site.trip = restored
    await restored.async_start()
    assert restored.status == "invalid_storage"
    assert not restored.armed and not restored.owns_full
    return corrupt


@pytest.mark.parametrize(
    ("domain", "service", "key", "data"),
    [
        ("datetime", "set_value", "trip_ready_by", {"datetime": DUE.isoformat()}),
        ("select", "select_option", "trip_target_soc", {"option": "90%"}),
        ("select", "select_option", "trip_target_soc", {"option": "100%"}),
        ("number", "set_value", "trip_extra_minutes", {"value": 15}),
        ("number", "set_value", "trip_extra_minutes", {"value": 0}),
        ("switch", "turn_on", "trip_charge_scheduled", {}),
    ],
)
async def test_invalid_journal_rejects_ordinary_native_edits_and_survives_restore(
    actual_trip_site, domain, service, key, data
):
    site = actual_trip_site
    corrupt = await _restore_corrupt_journal_over_unowned_full(site)
    commands_before = list(site.actuator_commands)
    with pytest.raises(HomeAssistantError):
        await site.hass.services.async_call(
            domain, service, {"entity_id": _trip_entity(site, domain, key), **data}, blocking=True
        )
    assert site.trip.status == "invalid_storage"
    assert await site.trip._store.async_load() == corrupt
    await site.trip.async_stop()
    restored = TripChargeController(site.hass, site.coordinator, site.entry)
    site.coordinator.trip_charge = site.trip = restored
    await restored.async_start()
    await site.ev.async_reconcile()
    await site.hass.async_block_till_done()
    assert restored.status == "invalid_storage"
    assert not restored.armed and not restored.owns_full
    assert restored.departure is None and restored.target_soc == 100 and restored.extra_minutes == 0
    assert await restored._store.async_load() == corrupt
    assert site.ev._charge_to_full_requested()
    assert site.actuator_commands == commands_before


async def test_only_explicit_native_schedule_off_acknowledges_invalid_journal(actual_trip_site):
    site = actual_trip_site
    await _restore_corrupt_journal_over_unowned_full(site)
    commands_before = list(site.actuator_commands)
    await site.hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": _trip_entity(site, "switch", "trip_charge_scheduled")},
        blocking=True,
    )
    assert site.trip.status != "invalid_storage"
    assert site.trip.attributes["storage_status"] == "ready"
    acknowledged = await site.trip._store.async_load()
    assert acknowledged["schema"] == 1 and acknowledged["armed"] is False
    assert acknowledged["owner_token"] is None
    for domain, service, key, data in (
        ("datetime", "set_value", "trip_ready_by", {"datetime": DUE.isoformat()}),
        ("select", "select_option", "trip_target_soc", {"option": "80%"}),
        ("number", "set_value", "trip_extra_minutes", {"value": 15}),
    ):
        await site.hass.services.async_call(
            domain, service, {"entity_id": _trip_entity(site, domain, key), **data}, blocking=True
        )
    await site.hass.async_block_till_done()
    assert (
        site.trip.departure == DUE and site.trip.target_soc == 80 and site.trip.extra_minutes == 15
    )
    assert not site.trip.armed and not site.trip.owns_full
    assert site.ev._charge_to_full_requested()
    assert site.actuator_commands == commands_before
    await site.trip.async_stop()
    restored = TripChargeController(site.hass, site.coordinator, site.entry)
    site.coordinator.trip_charge = site.trip = restored
    await restored.async_start()
    assert restored.status != "invalid_storage"
    assert restored.departure == DUE and restored.target_soc == 80 and restored.extra_minutes == 15
    assert not restored.armed and not restored.owns_full
    assert site.ev._charge_to_full_requested()
    assert site.actuator_commands == commands_before
