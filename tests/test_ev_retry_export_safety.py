"""Retry recovery never substitutes for the physical EV/export handoff.

These synthetic native frames drive the real HA lifecycle and persisted EV
controller. A service acknowledgement can change a number but cannot measure
the charger, grant export authority, or spend the protected house budget.
"""

from datetime import timedelta

import pytest

from tests.test_ev_export_handoff_lifecycle import (
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


def _baseline(rig):
    coordinator = rig.entry.runtime_data
    coordinator.update_persisted_config_value(rig.entry, "ev_protected_baseline_a", 1)


def _native_charging(rig, at, *, actual, requested):
    _vehicle(rig, at, soc=43, current=actual, request=requested)
    _electrical(rig, at, current=actual, battery_soc=80)
    _set(rig.hass, LOCAL, "on", at=at)


def _assert_export_withheld(rig):
    controller = rig.entry.runtime_data.active_controller
    assert controller.export_session.phase == "idle"
    assert not _calls(rig, entity=MODE, value="Force Discharge")
    fleet = rig.hass.states.get("sensor.home_energy_fleet_summary")
    assert fleet.attributes["export_status"] == "withheld_ev_handoff_pending"


@pytest.mark.parametrize("phases", [1, 3])
@pytest.mark.parametrize("actual", [2, 3])
@pytest.mark.parametrize("reload", [False, True])
@pytest.mark.parametrize("ev_first", [False, True])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_failed_baseline_current_preserves_house_export_fallback(
    hass, monkeypatch, freezer, phases, actual, reload, ev_first,
):
    rig = await _site(hass, monkeypatch, phases=phases)
    try:
        _baseline(rig)
        at = _at(20, 55)
        freezer.move_to(at)
        _native_charging(rig, at, actual=actual, requested=actual)
        rig.harness.clear_service_calls()
        await _cycle(rig, at, ev_first=ev_first)
        _assert_export_withheld(rig)
        assert rig.entry.runtime_data.ev_controller.target_current_a == 1

        # Tessie may echo a successful command into its cache. Actual current
        # remains at 2--3 A and the original measurement time does not advance.
        echoed_at = at + timedelta(seconds=1)
        freezer.move_to(echoed_at)
        _set(hass, "number.test_ev_current", 1,
             {"min": 1, "max": 16, "step": 1, "unit_of_measurement": "A"},
             at=echoed_at)
        rig.provider.data["charge_state_charge_current_request"] = 1
        _electrical(rig, echoed_at, current=actual, battery_soc=80)
        _set(hass, LOCAL, "on", at=echoed_at)
        rig.harness.clear_service_calls()
        if reload:
            await rig.harness.reload(rig.entry)
        await _cycle(rig, echoed_at, ev_first=ev_first)
        _assert_export_withheld(rig)
        assert rig.provider.data["charge_state_charger_actual_current"] == actual
        assert rig.provider.data["charge_state_timestamp"] == at.timestamp() * 1000

        # Only a genuinely newer native measurement at the configured physical
        # baseline can release the unchanged strict handoff. Retry state alone
        # can never supply this permission, before or after a real reload.
        settled_at = at + timedelta(seconds=31)
        freezer.move_to(settled_at)
        _native_charging(rig, settled_at, actual=1, requested=1)
        rig.harness.clear_service_calls()
        await _cycle(rig, settled_at, ev_first=ev_first)
        active = rig.entry.runtime_data.active_controller
        assert _calls(rig, entity=MODE, value="Force Discharge"), {
            "handoff": active.ev_export_handoff_reason,
            "phase": active.export_session.phase,
            "status": hass.states.get("sensor.home_energy_fleet_summary").attributes.get(
                "export_status"
            ),
        }
        assert rig.entry.runtime_data.active_controller.export_session.phase in {
            "starting", "active",
        }
    finally:
        await _close(rig)


@pytest.mark.parametrize("reload", [False, True])
@pytest.mark.parametrize("fault", ["stale", "offline", "restored", "wrong_actual"])
@pytest.mark.freeze_time("2026-09-17 19:00:00+00:00")
async def test_cached_or_invalid_baseline_never_releases_export(
    hass, monkeypatch, freezer, reload, fault,
):
    rig = await _site(hass, monkeypatch)
    try:
        _baseline(rig)
        at = _at(20, 55)
        freezer.move_to(at)
        _native_charging(rig, at, actual=1, requested=1)
        if fault == "stale":
            rig.provider.data["charge_state_timestamp"] = (
                at - timedelta(seconds=91)
            ).timestamp() * 1000
        elif fault == "offline":
            rig.provider.data["state"] = "offline"
        elif fault == "restored":
            current = hass.states.get("sensor.test_ev_actual_current")
            _set(hass, current.entity_id, 1,
                 {**current.attributes, "restored": True}, at=at)
        else:
            rig.provider.data["charge_state_charger_actual_current"] = 3
        rig.harness.clear_service_calls()
        if reload:
            await rig.harness.reload(rig.entry)
        await _cycle(rig, at)
        _assert_export_withheld(rig)
    finally:
        await _close(rig)
