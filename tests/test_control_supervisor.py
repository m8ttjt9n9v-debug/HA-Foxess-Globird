from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant

from custom_components.home_energy_orchestrator.control_supervisor import (
    CONTROL_ISSUE_EVENT,
    ControlConformanceSupervisor,
    SupervisionObservation,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def _supervisor(hass: HomeAssistant) -> ControlConformanceSupervisor:
    coordinator = SimpleNamespace(
        entry_id="test-entry",
        async_update_listeners=lambda: None,
        active_controller=SimpleNamespace(async_supervisory_repair=AsyncMock()),
        ev_controller=SimpleNamespace(async_supervisory_repair=AsyncMock()),
    )
    return ControlConformanceSupervisor(hass, coordinator)


async def test_persistent_free_charge_mismatch_repairs_once_and_emits_event(
    hass: HomeAssistant, monkeypatch
) -> None:
    supervisor = _supervisor(hass)
    events = []
    hass.bus.async_listen(CONTROL_ISSUE_EVENT, events.append)
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.control_supervisor."
        "persistent_notification.async_create",
        lambda *_args, **_kwargs: None,
    )
    battery = SupervisionObservation(
        "battery_free_charge_not_active",
        "Force Charge",
        "Back-up",
        True,
        "FoxESS mode does not match the HEO-owned state",
    )
    healthy_ev = SupervisionObservation(
        None, "15.0 A; charge on", "15.0 A; charge on", False, "matched"
    )
    monkeypatch.setattr(supervisor, "_battery_observation", lambda: battery)
    monkeypatch.setattr(supervisor, "_ev_observation", lambda: healthy_ev)

    await supervisor.async_reconcile(NOW)
    await supervisor.async_reconcile(NOW + timedelta(minutes=5))
    await supervisor.async_reconcile(NOW + timedelta(minutes=6))
    await hass.async_block_till_done()

    repair = supervisor.coordinator.active_controller.async_supervisory_repair
    repair.assert_awaited_once_with("Force Charge")
    assert len(events) == 1
    assert events[0].data["issue"] == "battery_free_charge_not_active"
    assert events[0].data["foxess_cloud_verification"] == "unavailable"
    assert supervisor.status == "issue"


async def test_unverified_external_discharge_alerts_but_is_never_repaired(
    hass: HomeAssistant, monkeypatch
) -> None:
    supervisor = _supervisor(hass)
    events = []
    hass.bus.async_listen(CONTROL_ISSUE_EVENT, events.append)
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.control_supervisor."
        "persistent_notification.async_create",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        supervisor,
        "_battery_observation",
        lambda: SupervisionObservation(
            "battery_unattributed_force_discharge",
            "Self Use",
            "Force Discharge",
            False,
            "External Force Discharge detected; FoxESS Cloud/VPP origin is "
            "not verifiable",
        ),
    )
    monkeypatch.setattr(
        supervisor,
        "_ev_observation",
        lambda: SupervisionObservation(None, "idle", "idle", False, "matched"),
    )

    await supervisor.async_reconcile(NOW)
    await supervisor.async_reconcile(NOW + timedelta(minutes=5))
    await hass.async_block_till_done()

    repair = supervisor.coordinator.active_controller.async_supervisory_repair
    repair.assert_not_awaited()
    assert len(events) == 1
    assert "not verifiable" in events[0].data["message"]


async def test_ev_mismatch_opens_a_fresh_reconciliation_after_grace(
    hass: HomeAssistant, monkeypatch
) -> None:
    supervisor = _supervisor(hass)
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.control_supervisor."
        "persistent_notification.async_create",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        supervisor,
        "_battery_observation",
        lambda: SupervisionObservation(None, "Self Use", "Self Use", False, "matched"),
    )
    monkeypatch.setattr(
        supervisor,
        "_ev_observation",
        lambda: SupervisionObservation(
            "ev_target_not_applied",
            "15.0 A; charge on",
            "1.0 A; charge on",
            True,
            "target mismatch",
        ),
    )

    await supervisor.async_reconcile(NOW)
    await supervisor.async_reconcile(NOW + timedelta(minutes=5))

    repair = supervisor.coordinator.ev_controller.async_supervisory_repair
    repair.assert_awaited_once_with(NOW + timedelta(minutes=5))
