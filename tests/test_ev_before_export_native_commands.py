"""Exercise native Tessie command-cache semantics without an API or vehicle.

The installed native Tessie implementation is the provenance for these tests:
``TessieNumberEntity.async_set_native_value`` calls ``TessieEntity.set`` after
the awaited command, mutating coordinator.data and publishing only that number.
``TessieSwitchEntity.async_turn_on/off`` does the same, but replaces the shared
charging-state field with an optimistic bool. The small command double below
faithfully reproduces those three methods and ``TessieEntity.set`` from native
``homeassistant/components/tessie/{number,switch,entity}.py``. Native Tessie's
optional API dependencies are deliberately not required for these offline tests.
Only the command acknowledgement and that entity's HA publication are modeled;
an optimistic bool never becomes a vehicle measurement in this test fixture.
"""

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.home_energy_orchestrator.ev_observation_adapter import (
    capture_ev_feedback,
    ev_observation_entity_map,
)
from custom_components.home_energy_orchestrator.ev_source_feedback import (
    before_export_vehicle_feedback_valid,
)
from tests.test_ev_backfill_timing import _charging, _fresh, _services
from tests.test_ev_before_export_source_clocks import _native


@pytest.fixture(autouse=True)
def utc_clock(monkeypatch):
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.ev_active.dt_util.now",
        lambda: datetime.now(UTC),
    )


@pytest.fixture(autouse=True)
async def native_provider_cleanup(hass):
    yield
    for entry in hass.config_entries.async_entries():
        if entry.domain in {"tessie", "foxess_modbus"}:
            entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    await hass.async_block_till_done()


class _NativeCommandCache:
    """Native Tessie command acknowledgements, without a network command.

    Native source correspondence:
    entity.py:TessieEntity.set writes coordinator.data[key] then this entity;
    number.py:async_set_native_value awaits run then set((self.key, value));
    switch.py:async_turn_on/off await run then set((description.key, bool)).
    A switch's data key is charging_state, although its registry unique-id
    suffix is charge_enable_request. No charge-state measurement timestamp is
    advanced by any of those methods.
    """

    def __init__(self, hass, rig, entity_id):
        self.hass = hass
        self.provider = rig.provider
        self.entity_id = entity_id
        self.key = {
            "number.car_current": "charge_state_charge_current_request",
            "number.car_limit": "charge_state_charge_limit_soc",
            "switch.car_charge": "charge_state_charging_state",
        }[entity_id]

    def _set(self, value):
        self.provider.data[self.key] = value
        old = self.hass.states.get(self.entity_id)
        state = ("on" if value else "off") if isinstance(value, bool) else str(value)
        self.hass.states.async_set(self.entity_id, state, dict(old.attributes))

    async def async_set_native_value(self, value):
        self._set(value)

    async def async_turn_on(self):
        self._set(True)

    async def async_turn_off(self):
        self._set(False)


def _valid(hass, rig, *, now=None):
    now = now or rig.now
    return before_export_vehicle_feedback_valid(
        hass,
        capture_ev_feedback(hass, ev_observation_entity_map(rig.coordinator.runtime_config)),
        now=now,
        max_age_seconds=90,
    )


@pytest.mark.parametrize(
    "entity_id,value,field",
    [
        ("number.car_current", 8, "charge_state_charge_current_request"),
        ("number.car_limit", 90, "charge_state_charge_limit_soc"),
    ],
)
async def test_native_number_command_mutates_cache_without_measurement_time(
    hass, freezer, entity_id, value, field,
):
    rig = _native(hass, freezer)
    actuator = _NativeCommandCache(hass, rig, entity_id)
    original_data = rig.provider.data
    original_stamp = original_data["charge_state_timestamp"]
    await actuator.async_set_native_value(value)
    assert rig.provider.data is original_data
    assert original_data[field] == value
    assert original_data["charge_state_timestamp"] == original_stamp
    assert hass.states.get(entity_id).state == str(value)
    # Acknowledgement does not advance the native measurement's expiry.
    later = rig.now + timedelta(seconds=91)
    freezer.move_to(later)
    assert not _valid(hass, rig, now=later)


@pytest.mark.parametrize("turn_on", [True, False])
async def test_native_switch_boolean_waits_for_genuine_vehicle_publication(
    hass, freezer, turn_on,
):
    rig = _native(hass, freezer)
    actuator = _NativeCommandCache(hass, rig, "switch.car_charge")
    original_stamp = rig.provider.data["charge_state_timestamp"]
    if turn_on:
        await actuator.async_turn_on()
    else:
        await actuator.async_turn_off()
    assert rig.provider.data["charge_state_charging_state"] is turn_on
    assert rig.provider.data["charge_state_timestamp"] == original_stamp
    assert not _valid(hass, rig)
    # The existing measurement publisher, rather than the command response,
    # replaces the frame and publishes all corresponding native entity states.
    now = rig.now + timedelta(seconds=10)
    freezer.move_to(now)
    rig.provider.data = dict(
        rig.provider.data,
        charge_state_timestamp=now.timestamp() * 1000,
        charge_state_charging_state="Charging" if turn_on else "Stopped",
    )
    hass.states.async_set("sensor.car_charging", "charging" if turn_on else "stopped")
    assert _valid(hass, rig, now=now)
    rig.provider.data["charge_state_charging_state"] = None
    assert not _valid(hass, rig, now=now)


@pytest.mark.parametrize("fault", ["failed_provider", "stale_frame", "missing_clock"])
async def test_native_command_acknowledgement_does_not_repair_invalid_measurement(
    hass, freezer, fault,
):
    rig = _native(hass, freezer)
    if fault == "failed_provider":
        rig.provider.last_update_success = False
    elif fault == "stale_frame":
        rig.provider.data["charge_state_timestamp"] -= 91_000
    else:
        rig.provider.data.pop("charge_state_timestamp")
    await _NativeCommandCache(hass, rig, "number.car_current").async_set_native_value(8)
    await _NativeCommandCache(hass, rig, "number.car_limit").async_set_native_value(90)
    assert not _valid(hass, rig)


async def test_fresh_native_publication_during_checkpoint_does_not_stop_owned_topup(
    hass, freezer, monkeypatch,
):
    """A coherent real refresh after cycle capture is not lost EV authority."""
    rig = _native(hass, freezer)
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.decision_phase == "ev_before_export_charging"
    # Apply actual native number-command cache/publication behavior before the
    # next genuine charging frame, including the previous requested limit.
    for entity_id, value in (("number.car_current", 8), ("number.car_limit", 90)):
        await _NativeCommandCache(hass, rig, entity_id).async_set_native_value(value)
    now = rig.now + timedelta(seconds=60)
    freezer.move_to(now)
    _charging(hass, 8)
    hass.states.async_set("device_tracker.car", "home", force_update=True)
    _fresh(rig.coordinator, now, current_a=8, grid_kw=-0.1)
    rig.provider.data = dict(
        rig.provider.data,
        charge_state_timestamp=now.timestamp() * 1000,
        charge_state_charging_state="Charging",
        charge_state_charger_actual_current=8,
    )
    original_save = rig.controller._async_save
    refreshed = False

    async def publish_during_checkpoint(*args, **kwargs):
        nonlocal refreshed
        if not refreshed:
            refreshed = True
            # Native coordinator refresh replaces the frame and its ordinary
            # synchronous listeners publish the matching HA value together.
            rig.provider.data = dict(
                rig.provider.data, charge_state_charger_actual_current=7,
            )
            hass.states.async_set("sensor.car_actual_current", "7", {"unit_of_measurement": "A"})
        await original_save(*args, **kwargs)

    monkeypatch.setattr(rig.controller, "_async_save", publish_during_checkpoint)
    calls.clear()
    await rig.controller.async_reconcile(now)
    assert refreshed
    assert rig.controller.decision_phase == "ev_before_export_charging"
    assert rig.controller.target_current_a == 8
    assert not any(call[:2] == ("switch", "turn_off") for call in calls)


@pytest.mark.parametrize("boundary", ["vehicle_target", "battery_reserve"])
async def test_checkpoint_boundary_crossing_stops_existing_matching_topup(
    hass, freezer, monkeypatch, boundary,
):
    """Already-matching feedback needs a stop, not just a positive-write veto."""
    rig = _native(hass, freezer)
    calls = _services(hass)
    await rig.controller.async_reconcile(rig.now)
    assert rig.controller.decision_phase == "ev_before_export_charging"
    now = rig.now + timedelta(seconds=60)
    freezer.move_to(now)
    _charging(hass, 8)
    # Every actuator already matches the retained top-up. This deliberately
    # avoids a redundant positive service invoking the adapter's live guard.
    hass.states.async_set("number.car_limit", "50", {"min": 50, "max": 100, "step": 1})
    hass.states.async_set("device_tracker.car", "home", force_update=True)
    _fresh(rig.coordinator, now, current_a=8, grid_kw=-0.1)
    rig.provider.data = dict(
        rig.provider.data,
        charge_state_timestamp=now.timestamp() * 1000,
        charge_state_charging_state="Charging",
        charge_state_charger_actual_current=8,
        charge_state_charge_current_request=8,
        charge_state_charge_limit_soc=50,
    )
    original_save = rig.controller._async_save
    crossed = False

    async def cross_during_checkpoint(*args, **kwargs):
        nonlocal crossed
        if not crossed:
            crossed = True
            if boundary == "vehicle_target":
                rig.provider.data = dict(
                    rig.provider.data, charge_state_usable_battery_level=30,
                )
                hass.states.async_set("sensor.car_soc", "30", {"unit_of_measurement": "%"})
            else:
                hass.states.async_set(
                    "sensor.site_battery_soc", "20", {"unit_of_measurement": "%"},
                )
        await original_save(*args, **kwargs)

    monkeypatch.setattr(rig.controller, "_async_save", cross_during_checkpoint)
    calls.clear()
    await rig.controller.async_reconcile(now)
    assert crossed
    assert rig.controller.target_current_a == 0
    assert rig.controller.decision_phase != "ev_before_export_charging"
    assert any(call[:2] == ("switch", "turn_off") for call in calls)
