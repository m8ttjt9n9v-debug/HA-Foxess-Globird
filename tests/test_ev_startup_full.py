"""Restored Full intent must not turn a source startup outage into an unplug."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.core import CoreState, HassJob
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController

from .test_ev_active import _controller_config, _coordinator, _set_ev_states

NOW = datetime(2026, 10, 11, 8, tzinfo=UTC)
pytestmark = pytest.mark.freeze_time(NOW, real_asyncio=True)

CAR_ENTITIES = (
    "device_tracker.car", "binary_sensor.car_cable", "sensor.car_charging", "sensor.car_soc",
    "sensor.car_actual_current", "sensor.car_energy", "number.car_current", "number.car_limit",
    "switch.car_charge",
)


@pytest.fixture
async def restored_full(hass):
    controllers = []
    calls = []

    async def actuator(call):
        calls.append((call.domain, call.service, dict(call.data)))

    hass.services.async_register("number", "set_value", actuator)
    hass.services.async_register("switch", "turn_on", actuator)
    hass.services.async_register("switch", "turn_off", actuator)

    async def create(*, missing="all", hours=16, phases=1):
        _set_ev_states(hass)
        config = _controller_config(
            ev_charge_to_full_enabled=True, ev_charge_to_full_max_hours=hours,
            site_phase_count=phases, ev_phase_count=phases,
            site_grid_current_entity="sensor.phase_current" if phases > 1 else None,
        )
        entry = MockConfigEntry(domain="home_energy_orchestrator", data=config)
        entry.add_to_hass(hass)
        coordinator = _coordinator(config)
        coordinator.entry_id = entry.entry_id
        first = ActiveEvController(hass, coordinator)
        first.charge_to_full_started_at = NOW - timedelta(hours=1)
        await first._async_save(NOW - timedelta(minutes=1))
        if missing == "all":
            for entity in CAR_ENTITIES:
                hass.states.async_remove(entity)
        elif missing is not None:
            entity, value = missing
            hass.states.async_set(entity, value)
        restored = ActiveEvController(hass, coordinator)
        controllers.append(restored)
        await restored.async_start()
        return restored, coordinator, entry, calls

    yield create
    for controller in controllers:
        await controller.async_stop()


@pytest.mark.parametrize("missing", [
    "all", ("device_tracker.car", "unknown"), ("binary_sensor.car_cable", "unavailable"),
    ("sensor.car_charging", "unknown"),
])
async def test_restored_full_waits_for_unknown_sources_without_cancelling_or_writing(
    hass, restored_full, missing,
):
    restored, _, entry, calls = await restored_full(missing=missing)
    assert entry.data["ev_charge_to_full_enabled"] is True
    assert restored.charge_to_full_started_at == NOW - timedelta(hours=1)
    assert restored.full_startup_evidence_pending
    assert calls == []
    _set_ev_states(hass)
    await restored.async_reconcile(NOW + timedelta(minutes=1))
    assert entry.data["ev_charge_to_full_enabled"] is True
    assert restored.charge_to_full_started_at == NOW - timedelta(hours=1)
    assert not restored.full_startup_evidence_pending
    assert restored.decision_phase == "charge_to_full_paid_grid_override"
    assert calls


@pytest.mark.parametrize("arrival_order", [
    ("presence", "soc", "actuators"), ("presence", "actuators", "soc"),
    ("soc", "presence", "actuators"), ("actuators", "soc", "presence"),
])
async def test_restored_full_partial_source_arrivals_never_establish_a_false_cohort(
    hass, restored_full, arrival_order,
):
    restored, _, entry, calls = await restored_full()
    groups = {
        "presence": (
            ("device_tracker.car", "home", {}), ("binary_sensor.car_cable", "on", {}),
            ("sensor.car_charging", "stopped", {}),
        ),
        "soc": (("sensor.car_soc", "40", {"unit_of_measurement": "%"}),),
        "actuators": (
            ("number.car_current", "6", {"min": 1, "max": 16, "step": 1}),
            ("number.car_limit", "80", {"min": 50, "max": 100, "step": 1}),
            ("switch.car_charge", "off", {}),
        ),
    }
    for index, group in enumerate(arrival_order):
        for entity, value, attrs in groups[group]:
            hass.states.async_set(entity, value, attrs)
        await restored.async_reconcile(NOW + timedelta(seconds=index + 1))
        assert entry.data["ev_charge_to_full_enabled"] is True
        assert restored.charge_to_full_started_at == NOW - timedelta(hours=1)
        if index < 2:
            assert restored.full_startup_evidence_pending
            assert calls == []
    assert not restored.full_startup_evidence_pending
    assert calls
    # Once established, a later outage cannot turn the startup latch back on.
    hass.states.async_set("sensor.car_soc", "unavailable")
    assert not restored.full_startup_evidence_pending


@pytest.mark.parametrize("hours", [12, 16])
async def test_unknown_startup_preserves_original_full_timeout_exact_boundary(
    restored_full, hours,
):
    restored, _, entry, calls = await restored_full(hours=hours)
    original = NOW - timedelta(hours=1)
    deadline = original + timedelta(hours=hours)
    await restored.async_reconcile(deadline - timedelta(microseconds=1))
    assert entry.data["ev_charge_to_full_enabled"] is True
    assert restored.charge_to_full_started_at == original
    await restored.async_reconcile(deadline)
    assert entry.data["ev_charge_to_full_enabled"] is False
    assert restored.charge_to_full_started_at is None
    assert calls == []


@pytest.mark.parametrize("evidence", [
    ("device_tracker.car", "not_home"), ("binary_sensor.car_cable", "off"),
])
async def test_restored_full_known_absence_still_clears_without_device_writes(
    hass, restored_full, evidence,
):
    restored, _, entry, calls = await restored_full()
    hass.states.async_set(*evidence)
    await restored.async_reconcile(NOW + timedelta(seconds=1))
    assert entry.data["ev_charge_to_full_enabled"] is False
    assert restored.charge_to_full_started_at is None
    assert not restored.full_startup_evidence_pending
    assert calls == []


@pytest.mark.parametrize("evidence", [
    ("device_tracker.car", "unknown"), ("binary_sensor.car_cable", "unavailable"),
    ("sensor.car_charging", "unknown"),
])
async def test_later_unknown_connection_holds_established_full_without_renewing_timer(
    hass, restored_full, evidence,
):
    restored, _, entry, calls = await restored_full()
    _set_ev_states(hass)
    await restored.async_reconcile(NOW + timedelta(seconds=1))
    assert not restored.full_startup_evidence_pending
    original_start = restored.charge_to_full_started_at
    before = list(calls)
    hass.states.async_set(*evidence)
    await restored.async_reconcile(NOW + timedelta(minutes=1))
    assert entry.data["ev_charge_to_full_enabled"] is True
    assert restored.charge_to_full_started_at == original_start
    assert not restored.full_startup_evidence_pending
    assert calls == before


@pytest.mark.parametrize("invalid_soc", ["-1", "101", "not-a-number"])
async def test_available_invalid_soc_is_not_hidden_by_startup_latch(
    hass, restored_full, invalid_soc,
):
    restored, _, _, _ = await restored_full()
    _set_ev_states(hass)
    hass.states.async_set("sensor.car_soc", invalid_soc, {"unit_of_measurement": "%"})
    assert not restored.full_startup_evidence_pending


@pytest.mark.parametrize("hours", [12, 16])
async def test_missing_three_phase_current_cannot_extend_unobserved_full_timeout(
    restored_full, hours,
):
    restored, _, entry, calls = await restored_full(hours=hours, phases=3)
    original = NOW - timedelta(hours=1)
    deadline = original + timedelta(hours=hours)
    await restored.async_reconcile(deadline - timedelta(microseconds=1))
    assert entry.data["ev_charge_to_full_enabled"] is True
    assert restored.charge_to_full_started_at == original
    await restored.async_reconcile(deadline)
    assert entry.data["ev_charge_to_full_enabled"] is False
    assert restored.charge_to_full_started_at is None
    assert calls == []


@pytest.mark.parametrize("evidence", [
    ("device_tracker.car", "not_home"), ("binary_sensor.car_cable", "off"),
])
async def test_missing_three_phase_current_does_not_mask_confirmed_full_disconnect(
    hass, restored_full, evidence,
):
    restored, _, entry, calls = await restored_full(phases=3)
    hass.states.async_set(*evidence)
    await restored.async_reconcile(NOW + timedelta(seconds=1))
    assert entry.data["ev_charge_to_full_enabled"] is False
    assert restored.charge_to_full_started_at is None
    assert calls == []


async def test_complete_restored_full_cohort_waits_until_home_assistant_started(
    hass, restored_full,
):
    hass.set_state(CoreState.not_running)
    restored, coordinator, entry, calls = await restored_full(missing=None)
    assert restored.full_startup_evidence_pending
    assert calls == []
    observations = []
    coordinator.async_update_listeners = lambda: observations.append(
        (hass.state, restored.full_startup_evidence_pending)
    )

    async def other_startup_publication():
        assert hass.state is CoreState.starting
        assert restored.full_startup_evidence_pending
        await restored.async_reconcile(NOW)
        assert entry.data["ev_charge_to_full_enabled"] is True
        assert calls == []

    hass.async_add_startup_job(HassJob(other_startup_publication))
    await hass.async_start()
    await hass.async_block_till_done()
    assert not restored.full_startup_evidence_pending
    assert entry.data["ev_charge_to_full_enabled"] is True
    assert restored.charge_to_full_started_at == NOW - timedelta(hours=1)
    assert observations[-1] == (CoreState.running, False)
    assert calls


@pytest.mark.parametrize("evidence", [
    ("device_tracker.car", "not_home"), ("binary_sensor.car_cable", "off"),
])
async def test_pre_started_barrier_does_not_hide_confirmed_absence(
    hass, restored_full, evidence,
):
    hass.set_state(CoreState.not_running)
    restored, _, entry, calls = await restored_full()
    hass.states.async_set(*evidence)
    await restored.async_reconcile(NOW)
    assert entry.data["ev_charge_to_full_enabled"] is False
    assert restored.charge_to_full_started_at is None
    assert calls == []


@pytest.mark.parametrize("hours", [12, 16])
async def test_pre_started_barrier_cannot_extend_original_full_expiry(hass, restored_full, hours):
    hass.set_state(CoreState.not_running)
    restored, _, entry, calls = await restored_full(missing=None, hours=hours)
    assert restored.full_startup_evidence_pending
    deadline = NOW - timedelta(hours=1) + timedelta(hours=hours)
    await restored.async_reconcile(deadline)
    assert entry.data["ev_charge_to_full_enabled"] is False
    assert restored.charge_to_full_started_at is None
    assert calls == []


async def test_unloaded_controller_does_not_reconcile_at_later_home_assistant_start(
    hass, restored_full,
):
    hass.set_state(CoreState.not_running)
    restored, _, _, calls = await restored_full()
    await restored.async_stop()
    _set_ev_states(hass)
    await hass.async_start()
    await hass.async_block_till_done()
    assert calls == []


async def test_running_home_assistant_reload_does_not_add_a_startup_wait(restored_full):
    restored, _, entry, calls = await restored_full(missing=None)
    assert not restored.full_startup_evidence_pending
    assert entry.data["ev_charge_to_full_enabled"] is True
    assert restored.charge_to_full_started_at == NOW - timedelta(hours=1)
    assert calls


async def test_unload_cancels_started_refresh_already_waiting_for_ev_lock(
    hass, restored_full, monkeypatch,
):
    hass.set_state(CoreState.not_running)
    restored, _, _, calls = await restored_full(missing=None)
    began = asyncio.Event()
    original_tick = restored._async_tick

    async def observed_tick(now):
        began.set()
        await original_tick(now)

    monkeypatch.setattr(restored, "_async_tick", observed_tick)
    async with restored._lock:
        await hass.async_start()
        await began.wait()
        await restored.async_stop()
        assert calls == []
    await hass.async_block_till_done()
    assert calls == []
