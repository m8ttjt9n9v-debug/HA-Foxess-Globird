"""Reducing direct-current cleanup persists its retry intent before dispatch."""

import asyncio
from datetime import UTC, datetime

import pytest

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from tests.test_ev_active import _controller_config, _coordinator, _set_ev_states

NOW = datetime(2026, 9, 17, 19, tzinfo=UTC)
pytestmark = pytest.mark.freeze_time(NOW)


def _reducing_controller(hass):
    _set_ev_states(hass)
    hass.states.async_set("sensor.car_charging", "charging")
    hass.states.async_set("switch.car_charge", "on")
    hass.states.async_set("sensor.car_actual_current", 6, {"unit_of_measurement": "A"})
    controller = ActiveEvController(hass, _coordinator(_controller_config(
        ev_protected_baseline_a=1,
    )))
    assert controller.gate_status == "ready"
    return controller


@pytest.mark.parametrize("interrupted", [False, True])
async def test_reducing_current_intent_is_durable_when_service_starts(hass, interrupted):
    controller = _reducing_controller(hass)
    dispatched = []

    async def inspect_checkpoint(call):
        payload = await controller._repository.store.async_load()
        pending = payload["reconciliation"]["retry_channels"]["current"]
        assert pending == {
            "target": 1,
            "attempts": 1,
            "last_command_at": NOW.isoformat(),
        }
        assert not payload["reconciliation"]["retry_channels"]["current_proof"]["armed"]
        dispatched.append(dict(call.data))
        if interrupted:
            raise asyncio.CancelledError

    hass.services.async_register("number", "set_value", inspect_checkpoint)
    if interrupted:
        with pytest.raises(asyncio.CancelledError):
            await controller._async_restore_ready_by_baseline(
                NOW, controller._observation(), gate="ready",
            )
    else:
        await controller._async_restore_ready_by_baseline(
            NOW, controller._observation(), gate="ready",
        )

    assert dispatched == [{"entity_id": "number.car_current", "value": 1}]
    restored = ActiveEvController(hass, controller.coordinator)
    await restored._async_restore()
    assert restored.reconciliation.current_retry == controller.reconciliation.current_retry
    assert restored.reconciliation.current_retry.attempts == 1
    assert not restored.reconciliation.current_proof.armed
    assert restored.reconciliation.current_proof.completed_at is None


async def test_reducing_current_checkpoint_failure_prevents_service(hass, monkeypatch):
    controller = _reducing_controller(hass)
    dispatched = []

    async def record(call):
        dispatched.append(dict(call.data))

    async def fail_checkpoint(_now=None):
        raise OSError("synthetic checkpoint failure")

    hass.services.async_register("number", "set_value", record)
    monkeypatch.setattr(controller, "_async_save", fail_checkpoint)
    with pytest.raises(OSError, match="checkpoint failure"):
        await controller._async_restore_ready_by_baseline(
            NOW, controller._observation(), gate="ready",
        )

    assert dispatched == []
    assert await controller._repository.store.async_load() is None
