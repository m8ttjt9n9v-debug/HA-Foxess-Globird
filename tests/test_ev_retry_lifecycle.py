"""Independent direct-EVSE retries through the real controller and Store.

All services below are inert local fakes. A completed HA service is a dispatch
receipt, never evidence that a vehicle accepted its requested current.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from tests.test_ev_active import (
    _controller_config,
    _coordinator,
    _set_ev_states,
)
from tests.test_ev_export_handoff_lifecycle import (
    FIELDS,
    _at,
    _close,
    _electrical,
    _site,
    _vehicle,
)
from tests.test_ev_retry_export_safety import _baseline, _native_charging

NOW = datetime(2026, 9, 17, 12, 1, tzinfo=UTC)
pytestmark = pytest.mark.freeze_time(NOW)


def _controller(hass, *, charging=False):
    _set_ev_states(hass)
    hass.states.async_set("sensor.car_charging", "charging" if charging else "stopped")
    hass.states.async_set("switch.car_charge", "on" if charging else "off")
    hass.states.async_set("sensor.car_actual_current", 5 if charging else 0,
                          {"unit_of_measurement": "A"})
    hass.states.async_set("number.car_current", 5,
                          {"min": 1, "max": 16, "step": 1,
                           "unit_of_measurement": "A"})
    hass.states.async_set("number.car_limit", 80, {"min": 50, "max": 100, "step": 1})
    coordinator = _coordinator(_controller_config())
    return ActiveEvController(hass, coordinator)


def _services(hass):
    calls = []

    async def record(call):
        calls.append((call.domain, call.service, dict(call.data)))

    hass.services.async_register("number", "set_value", record)
    hass.services.async_register("switch", "turn_on", record)
    hass.services.async_register("switch", "turn_off", record)
    return calls


def _actions(calls):
    return [
        "current" if data.get("entity_id") == "number.car_current"
        else "limit" if data.get("entity_id") == "number.car_limit"
        else service
        for _, service, data in calls
    ]


def _current_clock(controller):
    retry = controller.reconciliation.current_retry
    assert retry is not None
    return retry


@pytest.mark.parametrize("charging", [False, True])
@pytest.mark.parametrize("restore", [False, True])
async def test_percentage_only_edits_preserve_current_and_start_backoff(
    hass, freezer, charging, restore,
):
    controller = _controller(hass, charging=charging)
    calls = _services(hass)
    for seconds in (0, 30):
        at = NOW + timedelta(seconds=seconds)
        freezer.move_to(at)
        await controller.async_reconcile(at)
    current = _current_clock(controller)
    start = controller.reconciliation.start_retry
    assert current.attempts == 2
    if not charging:
        assert start.attempts == 2
    await controller._async_save(NOW + timedelta(seconds=30))
    if restore:
        controller = ActiveEvController(hass, controller.coordinator)
        await controller._async_restore()
        assert _current_clock(controller) == current
        assert controller.reconciliation.start_retry == start

    # The target amps and current/start authority have not changed. A different
    # percentage must receive its own immediate write, not another amp/start.
    at = NOW + timedelta(seconds=45)
    freezer.move_to(at)
    controller.coordinator.update_config_value("ev_free_window_charge_limit_percent", 95)
    calls.clear()
    await controller.async_reconcile(at, force_decision=True)
    assert _actions(calls) == ["limit"]
    assert _current_clock(controller) == current
    assert controller.reconciliation.start_retry == start

    # Independently due actions still proceed at their original deadline.
    at = NOW + timedelta(seconds=90)
    freezer.move_to(at)
    calls.clear()
    await controller.async_reconcile(at)
    assert "current" in _actions(calls)
    assert ("turn_on" in _actions(calls)) is (not charging)
    assert _current_clock(controller).attempts == 3


@pytest.mark.parametrize("restore", [False, True])
async def test_uncertain_disconnect_does_not_renew_failed_current_episode(hass, freezer, restore):
    controller = _controller(hass, charging=True)
    calls = _services(hass)
    for seconds in (0, 30):
        at = NOW + timedelta(seconds=seconds)
        freezer.move_to(at)
        await controller.async_reconcile(at)
    current = _current_clock(controller)
    await controller._async_save(NOW + timedelta(seconds=30))
    # Cable loss while the switch/current still report charging is not the
    # complete physical-idle proof required to retire a command obligation.
    at = NOW + timedelta(seconds=40)
    freezer.move_to(at)
    hass.states.async_set("binary_sensor.car_cable", "off")
    calls.clear()
    await controller.async_reconcile(at)
    assert calls == []
    assert _current_clock(controller) == current
    if restore:
        controller = ActiveEvController(hass, controller.coordinator)
        await controller._async_restore()
    at = NOW + timedelta(seconds=45)
    freezer.move_to(at)
    hass.states.async_set("binary_sensor.car_cable", "on")
    await controller.async_reconcile(at)
    assert "current" not in _actions(calls)
    assert _current_clock(controller) == current


async def test_supervisory_reevaluation_waits_for_inflight_dispatch_and_keeps_retry_history(
    hass, freezer,
):
    controller = _controller(hass, charging=True)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def service(call):
        calls.append(call.data["entity_id"])
        if call.data["entity_id"] == "number.car_current":
            entered.set()
            await release.wait()

    hass.services.async_register("number", "set_value", service)
    first = asyncio.create_task(controller.async_reconcile(NOW))
    await entered.wait()
    expected = controller.reconciliation
    repair = asyncio.create_task(controller.async_supervisory_repair(NOW))
    await asyncio.sleep(0)
    assert controller.reconciliation == expected
    assert not repair.done()
    release.set()
    await asyncio.gather(first, repair)
    assert calls.count("number.car_current") == 1
    assert _current_clock(controller).attempts == 1
    assert any(receipt.action == "set_charge_current"
               for receipt in controller._adapter.last_receipts)
    # Generic entity clocks cannot establish the original native vehicle
    # provenance needed for the faster physical-override path.
    assert controller.reconciliation.current_proof.completed_at is None
    assert not controller.reconciliation.current_proof.armed


@pytest.mark.parametrize("failure", ["current_error", "limit_error"])
async def test_partial_or_uncertain_dispatch_never_creates_current_acceptance_proof(
    hass, failure,
):
    controller = _controller(hass, charging=True)

    async def service(call):
        failed_entity = (
            "number.car_current" if failure == "current_error" else "number.car_limit"
        )
        if call.data["entity_id"] == failed_entity:
            raise RuntimeError("synthetic transport outcome unavailable")

    hass.services.async_register("number", "set_value", service)
    await controller.async_reconcile(NOW)
    assert controller.reconciliation.current_proof.completed_at is None
    assert not controller.reconciliation.current_proof.armed
    assert _current_clock(controller).attempts == (0 if failure == "limit_error" else 1)
    # Reload cannot upgrade planned/uncertain dispatch to completed evidence.
    restored = ActiveEvController(hass, controller.coordinator)
    await restored._async_restore()
    assert restored.reconciliation.current_proof.completed_at is None
    assert not restored.reconciliation.current_proof.armed


@pytest.mark.parametrize("failure", ["limit", "current", "start"])
async def test_known_dispatch_prefix_retains_only_invoked_action_clocks_across_restore(
    hass, failure,
):
    """A prior failed action cannot charge cooldown to commands never called."""
    controller = _controller(hass, charging=False)
    invoked = []
    entities = {
        "number.car_limit": "limit",
        "number.car_current": "current",
        "switch.car_charge": "start",
    }

    async def service(call):
        action = entities[call.data["entity_id"]]
        invoked.append(action)
        if action == failure:
            raise RuntimeError("synthetic transport outcome unavailable")

    hass.services.async_register("number", "set_value", service)
    hass.services.async_register("switch", "turn_on", service)
    await controller.async_reconcile(NOW)
    order = ("limit", "current", "start")
    assert invoked == list(order[:order.index(failure) + 1])
    expected = {}
    for action in order:
        retry = getattr(controller.reconciliation, f"{action}_retry")
        attempts = retry.attempts if retry is not None else 0
        assert attempts == int(action in invoked)
        if retry is not None:
            assert retry.last_command_at == (NOW if action in invoked else None)
        expected[action] = retry
    # The service that raised may have reached the transport; that action keeps
    # its bounded attempt. Later actions provably never invoked do not inherit
    # it, and reload must not manufacture delivery or renew the retry budget.
    restored = ActiveEvController(hass, controller.coordinator)
    await restored._async_restore()
    for action in order:
        assert getattr(restored.reconciliation, f"{action}_retry") == expected[action]
    assert not restored.reconciliation.current_proof.armed


@pytest.mark.parametrize("fault", [
    "missing_earned_span", "short_earned_span", "backwards_seen", "future_receipt",
    "receipt_before_dispatch", "invalid_channel", "unknown_extension_version",
])
async def test_malformed_retry_extension_cannot_erase_backoff_or_manufacture_acknowledgement(
    hass, freezer, fault,
):
    controller = _controller(hass, charging=True)
    _services(hass)
    for seconds in (0, 30):
        at = NOW + timedelta(seconds=seconds)
        freezer.move_to(at)
        await controller.async_reconcile(at)
    expected = _current_clock(controller)
    await controller._async_save(NOW + timedelta(seconds=30))
    payload = await controller._repository.store.async_load()
    extension = payload["reconciliation"]["retry_channels"]
    extension["current_proof"] = {
        "binding": "synthetic-native-source",
        "completed_at": (NOW + timedelta(seconds=30)).isoformat(),
        "stable_since": None,
        "stable_last": None,
        "acknowledged_since": (NOW + timedelta(seconds=31)).isoformat(),
        "acknowledged_at": (NOW + timedelta(seconds=61)).isoformat(),
        "seen_at": (NOW + timedelta(seconds=62)).isoformat(),
        "armed": True,
    }
    proof = extension["current_proof"]
    if fault == "missing_earned_span":
        proof.pop("acknowledged_since")
    elif fault == "short_earned_span":
        proof["acknowledged_since"] = (NOW + timedelta(seconds=60)).isoformat()
    elif fault == "backwards_seen":
        proof["seen_at"] = (NOW + timedelta(seconds=60)).isoformat()
    elif fault == "future_receipt":
        proof["completed_at"] = (NOW + timedelta(seconds=76)).isoformat()
    elif fault == "receipt_before_dispatch":
        proof["completed_at"] = (NOW + timedelta(seconds=29)).isoformat()
    elif fault == "invalid_channel":
        extension["current"]["attempts"] = -1
    else:
        extension["version"] = 2
    await controller._repository.store.async_save(payload)
    at = NOW + timedelta(seconds=75)
    freezer.move_to(at)
    restored = ActiveEvController(hass, controller.coordinator)
    await restored._async_restore()
    assert not restored.reconciliation.current_proof.armed
    assert restored.reconciliation.current_proof.completed_at is None
    calls = _services(hass)
    await restored.async_reconcile(at)
    assert calls == []
    assert _current_clock(restored) == expected


@pytest.mark.parametrize("restore", [False, True])
@pytest.mark.parametrize("genuine", [False, True])
async def test_only_new_native_physical_convergence_earns_prompt_override_correction(
    hass, monkeypatch, freezer, restore, genuine,
):
    freezer.move_to(_at())
    rig = await _site(hass, monkeypatch)
    try:
        _baseline(rig)
        coordinator = rig.entry.runtime_data
        coordinator.update_persisted_config_value(rig.entry, "automatic_export_enabled", False)
        start = _at(19, 10)

        async def run(at):
            _electrical(rig, at, battery_soc=80,
                        current=rig.provider.data["charge_state_charger_actual_current"])
            await rig.entry.runtime_data.async_refresh()
            await rig.entry.runtime_data.ev_controller.async_reconcile(at)
            await hass.async_block_till_done(wait_background_tasks=True)

        # Each failed request gets the existing growing retry interval. Publish
        # the override early enough that the existing feedback-settle rule has
        # elapsed at the next attempt, rather than gaming that independent gate.
        trace = []
        for seconds in (0, 60, 120, 240, 480, 960, 1920):
            at = start + timedelta(seconds=seconds)
            freezer.move_to(at)
            if seconds == 0:
                _native_charging(rig, at, actual=2, requested=3)
            else:
                # An unchanged native report advances its real measurement
                # clock, not the number's value-change clock. The general
                # handoff fixture force-updates every value for other tests.
                rig.provider.data["charge_state_timestamp"] = at.timestamp() * 1000
                for entity in FIELDS:
                    previous = hass.states.get(entity)
                    hass.states.async_set(entity, previous.state, dict(previous.attributes))
            await run(at)
            ev = rig.entry.runtime_data.ev_controller
            trace.append((seconds, ev.last_reason, ev.gate_status,
                          ev.reconciliation.current_retry, ev.last_actions))
            later = at + timedelta(seconds=1)
            freezer.move_to(later)
            _native_charging(rig, later, actual=2, requested=3)
        controller = rig.entry.runtime_data.ev_controller
        current = _current_clock(controller)
        assert current.attempts == 7, trace
        assert controller.reconciliation.current_proof.completed_at is not None
        assert not controller.reconciliation.current_proof.armed
        await controller._async_save(start + timedelta(seconds=1921))
        if restore:
            await rig.harness.reload(rig.entry)
            controller = rig.entry.runtime_data.ev_controller
            assert _current_clock(controller) == current
            assert not controller.reconciliation.current_proof.armed

        for seconds in (1951, 1981):
            at = start + timedelta(seconds=seconds)
            freezer.move_to(at)
            if genuine:
                _native_charging(rig, at, actual=1, requested=1)
            else:
                # A command-only number echo and duplicate cached source clock
                # cannot stand in for a newer physical current measurement.
                previous = hass.states.get("number.test_ev_current")
                hass.states.async_set(previous.entity_id, 1, dict(previous.attributes))
                rig.provider.data["charge_state_charge_current_request"] = 1
            await run(at)
        assert controller.reconciliation.current_proof.armed is genuine

        at = start + timedelta(seconds=1982)
        freezer.move_to(at)
        _vehicle(rig, at, soc=43, current=3, request=3)
        rig.harness.clear_service_calls()
        await run(at)
        currents = [
            call for call in rig.harness.service_calls
            if call.service_data.get("entity_id") == "number.test_ev_current"
        ]
        assert len(currents) == (1 if genuine else 0)
        assert not controller.reconciliation.current_proof.armed
        if genuine:
            assert _current_clock(controller).attempts == 1
        else:
            assert _current_clock(controller) == current
    finally:
        await _close(rig)


async def test_current_completion_uses_actual_service_return_clock_and_restores(hass, monkeypatch,
                                                                             freezer):
    freezer.move_to(_at())
    rig = await _site(hass, monkeypatch)
    try:
        _baseline(rig)
        at = _at(19, 10)
        freezer.move_to(at)
        _native_charging(rig, at, actual=2, requested=3)

        def delayed_completion(entity, _value):
            if entity == "number.test_ev_current":
                freezer.tick(timedelta(seconds=2))

        rig.after_command = delayed_completion
        await rig.entry.runtime_data.async_refresh()
        controller = rig.entry.runtime_data.ev_controller
        await controller.async_reconcile(at)
        completed = at + timedelta(seconds=2)
        assert controller.reconciliation.current_proof.completed_at == completed
        assert _current_clock(controller).last_command_at == at
        payload = await controller._repository.store.async_load()
        assert payload["reconciliation"]["retry_channels"]["current_proof"][
            "completed_at"
        ] == completed.isoformat()
        restored = ActiveEvController(hass, rig.entry.runtime_data)
        await restored._async_restore()
        assert restored.reconciliation.current_proof.completed_at == completed
        assert _current_clock(restored) == _current_clock(controller)
        assert not restored.reconciliation.current_proof.armed
    finally:
        await _close(rig)


@pytest.mark.parametrize("disconnect", ["genuine", "unknown", "optimistic"])
async def test_disconnected_proof_disarms_without_erasing_disabled_owned_retry_duties(
    hass, monkeypatch, freezer, disconnect,
):
    freezer.move_to(_at())
    rig = await _site(hass, monkeypatch)
    try:
        _baseline(rig)
        at = _at(19, 10)
        freezer.move_to(at)
        _native_charging(rig, at, actual=2, requested=3)
        coordinator = rig.entry.runtime_data
        coordinator.update_persisted_config_value(rig.entry, "automatic_export_enabled", False)
        await coordinator.async_refresh()
        controller = coordinator.ev_controller
        await controller.async_reconcile(at)
        for seconds in (1, 31):
            measured = at + timedelta(seconds=seconds)
            freezer.move_to(measured)
            _native_charging(rig, measured, actual=1, requested=1)
            await coordinator.async_refresh()
            await controller.async_reconcile(measured)
        assert controller.reconciliation.current_proof.armed
        current = _current_clock(controller)
        # An outstanding owner and disabled control prevent full episode
        # retirement. Definite physical unplug still withdraws only the faster
        # override acknowledgement; uncertain/command-only absence cannot.
        controller.outside_control_active = True
        coordinator.update_persisted_config_value(rig.entry, "ev_automatic_control_enabled", False)
        now = at + timedelta(seconds=40)
        freezer.move_to(now)
        if disconnect == "genuine":
            _vehicle(rig, now, soc=43, current=0, request=1, connected=False, home=False)
        elif disconnect == "unknown":
            hass.states.async_set("binary_sensor.test_ev_cable", "unknown")
        else:
            hass.states.async_set("binary_sensor.test_ev_cable", "off")
            hass.states.async_set("switch.test_ev_charge", "off")
            rig.provider.data["charge_state_charging_state"] = False
        _electrical(rig, now, battery_soc=80)
        rig.harness.clear_service_calls()
        await coordinator.async_refresh()
        await controller.async_reconcile(now)
        assert not rig.harness.service_calls
        assert controller.outside_control_active
        assert _current_clock(controller) == current
        assert controller.reconciliation.phase != "idle"
        assert controller.reconciliation.current_proof.armed is (disconnect != "genuine")
        if disconnect == "genuine":
            await controller._async_save(now)
            restored = ActiveEvController(hass, coordinator)
            await restored._async_restore()
            assert not restored.reconciliation.current_proof.armed
            assert restored.reconciliation.current_proof.completed_at is None
            assert _current_clock(restored) == current
            assert restored.outside_control_active
    finally:
        await _close(rig)
