"""Readiness and its SoC must share a cohort, not the canonical sensor clock."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import CoreState

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.read_model import _build_ev_read_model

from . import test_trip_charge_native as native
from .test_ev_active import _controller_config, _coordinator, _set_ev_states

trip_site = native.trip_site
pytestmark = pytest.mark.freeze_time(native.NOW, real_asyncio=True)


def _projection(hass):
    _set_ev_states(hass)
    coordinator = _coordinator(_controller_config(ev_charge_to_full_enabled=True))
    coordinator.snapshot = replace(coordinator.snapshot, ev_soc=None)
    coordinator.data = SimpleNamespace(ev_max_power_kw=3.68)
    coordinator.ev_controller = ActiveEvController(hass, coordinator)
    return coordinator


def test_ev_status_pairs_ready_raw_soc_without_changing_canonical_soc(hass):
    coordinator = _projection(hass)
    model = _build_ev_read_model(coordinator, native.NOW)
    assert model.sensor_values()["ev_soc"] is None
    attrs = model.control_attributes()
    assert attrs["startup_feedback_pending"] is False
    assert attrs["observed_soc_percent"] == 40


@pytest.mark.parametrize("value", ["unknown", "unavailable", "-1", "101", "nan", "inf", "bad"])
def test_ev_status_explicit_null_never_relabels_invalid_raw_soc_as_zero(hass, value):
    coordinator = _projection(hass)
    # Establish first, so missing feedback remains terminal rather than another boot.
    _build_ev_read_model(coordinator, native.NOW)
    hass.states.async_set("sensor.car_soc", value)
    attrs = _build_ev_read_model(coordinator, native.NOW).control_attributes()
    assert attrs["startup_feedback_pending"] is False
    assert "observed_soc_percent" in attrs and attrs["observed_soc_percent"] is None


def test_ev_status_unknown_startup_soc_pairs_null_with_pending(hass):
    coordinator = _projection(hass)
    hass.states.async_set("sensor.car_soc", "unknown")
    attrs = _build_ev_read_model(coordinator, native.NOW).control_attributes()
    assert attrs["startup_feedback_pending"] is True
    assert "observed_soc_percent" in attrs and attrs["observed_soc_percent"] is None


def test_ev_status_absent_controller_still_publishes_explicit_pair(hass):
    coordinator = _projection(hass)
    coordinator.ev_controller = None
    attrs = _build_ev_read_model(coordinator, native.NOW).control_attributes()
    assert attrs["gate"] == "unavailable"
    assert attrs["startup_feedback_pending"] is True
    assert "observed_soc_percent" in attrs and attrs["observed_soc_percent"] is None


def test_ev_status_qualifies_and_observes_exactly_one_captured_cohort(hass, monkeypatch):
    from custom_components.home_energy_orchestrator import ev_active

    coordinator = _projection(hass)
    original_capture = ev_active.capture_ev_feedback
    captures = []

    def capture_then_change_live_source(hass, mapping):
        captured = original_capture(hass, mapping)
        captures.append(captured)
        hass.states.async_set("sensor.car_soc", "unknown")
        return captured

    monkeypatch.setattr(ev_active, "capture_ev_feedback", capture_then_change_live_source)
    attrs = _build_ev_read_model(coordinator, native.NOW).control_attributes()
    assert len(captures) == 1
    assert attrs["startup_feedback_pending"] is False
    assert attrs["observed_soc_percent"] == 40
    assert hass.states.get("sensor.car_soc").state == "unknown"


@pytest.mark.parametrize("value", ["-1", "101", "bad"])
def test_ev_status_available_invalid_initial_soc_is_not_masked_by_startup(hass, value):
    coordinator = _projection(hass)
    hass.states.async_set("sensor.car_soc", value)
    attrs = _build_ev_read_model(coordinator, native.NOW).control_attributes()
    assert attrs["startup_feedback_pending"] is False
    assert attrs["observed_soc_percent"] is None


async def test_actual_setup_started_tick_pairs_raw_soc_before_late_canonical_projection(
    trip_site, monkeypatch,
):
    site = await trip_site(soc=40)
    await site.ev.async_request_charge_to_full(True, reconcile=False)
    original_generation = site.trip._state.full_generation
    original_timer = native.NOW - timedelta(hours=1)
    site.ev.charge_to_full_started_at = original_timer
    await site.trip.async_stop()
    await site.ev.async_stop()
    site.hass.states.async_remove("sensor.car_soc")
    site.hass.set_state(CoreState.not_running)
    await native._setup_actual_site(site, monkeypatch)
    try:
        assert site.coordinator.snapshot.ev_soc is None
        assert site.hass.states.get("sensor.home_energy_ev_soc").state == "unknown"
        assert site.hass.states.get("sensor.home_energy_ev_control_status").attributes[
            "startup_feedback_pending"
        ] is True
        # Keep the coordinator's independently refreshed canonical projection behind
        # the mapped source, exactly as can occur during upstream integration boot.
        monkeypatch.setattr(site.coordinator, "async_request_refresh", AsyncMock())
        site.hass.states.async_set("sensor.car_soc", "65", {"unit_of_measurement": "%"})
        await site.hass.async_start()
        await site.hass.async_block_till_done()
        attrs = site.hass.states.get("sensor.home_energy_ev_control_status").attributes
        assert attrs["startup_feedback_pending"] is False
        assert attrs["observed_soc_percent"] == 65
        assert site.hass.states.get("sensor.home_energy_ev_soc").state == "unknown"
        assert site.ev._charge_to_full_requested()
        assert site.trip._state.full_generation == original_generation
        assert site.ev.charge_to_full_started_at == original_timer
        await site.coordinator.async_refresh()
        await site.hass.async_block_till_done()
        assert site.hass.states.get("sensor.home_energy_ev_soc").state == "65.0"
    finally:
        assert await site.hass.config_entries.async_unload(site.entry.entry_id)
        await site.hass.async_block_till_done()


async def test_actual_heo_and_restored_wrapper_survive_split_projection_and_complete(
    trip_site, monkeypatch,
):
    """Restore both real owners; fake only the final physical-device transport."""
    import json
    from datetime import UTC, datetime

    from homeassistant.const import EVENT_CALL_SERVICE
    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import mock_restore_cache

    from scripts.trip_charge_wrapper import (
        ARMED,
        EV_STATUS,
        NATIVE_STATUS,
        OVERRIDE,
        OWNED,
        RESUME,
        SOC,
        STATUS,
        build_package,
    )

    from .test_trip_charge_wrapper import _restored_owned_checkpoint

    site = await trip_site(soc=40)
    hass = site.hass
    site.coordinator.update_persisted_config_value(
        site.entry, "ev_charge_to_full_max_hours", 16,
    )
    await site.ev.async_request_charge_to_full(True, reconcile=False)
    original_generation = site.trip._state.full_generation
    restored_helpers, checkpoint = _restored_owned_checkpoint()
    assert checkpoint["generation"] == original_generation
    original_timer = datetime.fromtimestamp(checkpoint["first"], UTC)
    site.ev.charge_to_full_started_at = original_timer
    await site.trip.async_stop()
    await site.ev.async_stop()
    hass.states.async_remove("sensor.car_soc")
    hass.set_state(CoreState.not_running)
    mock_restore_cache(hass, restored_helpers)
    package = build_package(
        location_entity="device_tracker.car", cable_entity="binary_sensor.car_cable",
    )
    for domain in ("input_datetime", "input_boolean", "input_number", "input_select", "input_text"):
        assert await async_setup_component(hass, domain, {domain: package[domain]})
    assert await async_setup_component(hass, "template", {"template": package["template"]})
    assert await async_setup_component(hass, "automation", {"automation": package["automation"]})
    full_calls = []

    def record_full_service(event):
        if event.data.get("domain") != "switch":
            return
        entity = event.data.get("service_data", {}).get("entity_id")
        if entity == OVERRIDE or entity == [OVERRIDE]:
            full_calls.append(event.data["service"])

    remove_listener = hass.bus.async_listen(EVENT_CALL_SERVICE, record_full_service)
    await native._setup_actual_site(site, monkeypatch)
    try:
        assert site.trip.status == "legacy_conflict" and not site.trip.armed
        assert hass.states.get(SOC).state == "unknown"
        monkeypatch.setattr(site.coordinator, "async_request_refresh", AsyncMock())
        hass.states.async_set("sensor.car_soc", "65", {"unit_of_measurement": "%"})
        await hass.async_start()
        await hass.async_block_till_done()
        attrs = hass.states.get(EV_STATUS).attributes
        assert attrs["startup_feedback_pending"] is False
        assert attrs["observed_soc_percent"] == 65
        assert hass.states.get(SOC).state == "unknown"
        assert hass.states.get(ARMED).state == hass.states.get(OWNED).state == "on"
        assert hass.states.get(OVERRIDE).state == "on"
        assert hass.states.get(STATUS).state == "Override active"
        assert hass.states.get(NATIVE_STATUS).state == "legacy_conflict"
        assert site.trip._state.full_generation == original_generation
        assert site.ev.charge_to_full_started_at == original_timer
        assert json.loads(hass.states.get(RESUME).state) == checkpoint
        assert full_calls == [], "Boot must continue its lease, not send a new Full ON"

        await site.coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(SOC).state == "65.0"
        assert hass.states.get(ARMED).state == hass.states.get(OWNED).state == "on"
        assert site.trip._state.full_generation == original_generation
        assert site.ev.charge_to_full_started_at == original_timer
        assert json.loads(hass.states.get(RESUME).state) == checkpoint
        assert full_calls == []

        # Completion uses the paired raw SoC even while canonical remains lower.
        hass.states.async_set("sensor.car_soc", "90", {"unit_of_measurement": "%"})
        await site.ev._async_tick(None)
        await hass.async_block_till_done()
        assert hass.states.get(SOC).state == "65.0"
        assert hass.states.get(STATUS).state == "Completed"
        assert hass.states.get(ARMED).state == hass.states.get(OWNED).state == "off"
        assert hass.states.get(OVERRIDE).state == "off"
        assert not site.ev._charge_to_full_requested()
        assert site.trip._state.full_generation == original_generation + 1
        assert full_calls == ["turn_off"]
        assert site.ev.target_limit_percent <= 90
        assert site.ev.policy_route.route == "outside_window"
    finally:
        remove_listener()
        dispatcher = next(
            state.entity_id for state in hass.states.async_all("automation")
            if state.attributes.get("id") == "heo_trip_charge_dispatch"
        )
        await hass.services.async_call(
            "automation", "turn_off", {"entity_id": dispatcher, "stop_actions": True},
            blocking=True,
        )
        assert await hass.config_entries.async_unload(site.entry.entry_id)
        await hass.async_block_till_done()
