"""Local disconnection evidence never borrows a vehicle or other sensor clock."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.ev_local_connection import (
    LocalEvConnectionObserver,
)

ENTITY = "binary_sensor.local_ev_connected"
SERIAL = "SYNTHETIC-CONNECTOR"


class Publisher:
    """The native coordinator contract, without HTTP or a polling timer."""

    def __init__(self, entry):
        self.config_entry = entry
        self.last_update_success = True
        self.data = self.payload()
        self._listeners = {0: lambda: None}  # Existing native entity subscriber.
        self.additions = 0

    @staticmethod
    def payload(connected=False, contactor=False):
        return {"vitals": SimpleNamespace(vehicle_connected=connected, contactor_closed=contactor)}

    def async_add_listener(self, listener):
        self.additions += 1
        key = max(self._listeners, default=0) + 1
        self._listeners[key] = listener
        return lambda: self._listeners.pop(key)

    def publish(self, data=None):
        self.data = self.payload() if data is None else data
        for listener in list(self._listeners.values()):
            listener()


def native(hass):
    entry = MockConfigEntry(domain="tesla_wall_connector")
    entry.add_to_hass(hass)
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("tesla_wall_connector", SERIAL)},
    )
    row = er.async_get(hass).async_get_or_create(
        "binary_sensor", "tesla_wall_connector", f"{SERIAL}-vehicle_connected",
        config_entry=entry, device_id=device.id, suggested_object_id=ENTITY.split(".")[1],
    )
    assert row.entity_id == ENTITY
    provider = Publisher(entry)
    entry.runtime_data = SimpleNamespace(serial_number=SERIAL, update_coordinator=provider)
    hass.states.async_set(ENTITY, "off")
    return SimpleNamespace(entry=entry, device=device, provider=provider)


@pytest.fixture(autouse=True)
async def native_cleanup(hass):
    yield
    for entry in hass.config_entries.async_entries("tesla_wall_connector"):
        entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    await hass.async_block_till_done()


def capture(observer, *, entity=ENTITY, age=90, now=None):
    return observer.capture(entity, now=now or datetime.now(UTC), max_age_seconds=age)


@pytest.mark.parametrize("state,expected", [("on", "connected"), ("off", "disconnected")])
async def test_explicit_generic_binary_uses_only_own_fresh_report(hass, state, expected):
    hass.states.async_set(ENTITY, state)
    observer = LocalEvConnectionObserver(hass)
    result = capture(observer)
    assert result.status == expected
    assert result.available
    assert result.disconnected is (expected == "disconnected")
    assert result.source == "entity_report"


@pytest.mark.parametrize("fault", ["unknown", "unavailable", "missing", "restored", "wrong_domain"])
async def test_invalid_generic_cannot_prove_absence(hass, fault):
    entity = ENTITY if fault != "wrong_domain" else "sensor.local_ev_connected"
    if fault != "missing":
        state = fault if fault in {"unknown", "unavailable"} else "off"
        hass.states.async_set(entity, state, {"restored": fault == "restored"})
    result = capture(LocalEvConnectionObserver(hass), entity=entity)
    assert result.status == "unknown" and not result.disconnected


@pytest.mark.parametrize("age,allowed", [(0, True), (90, True), (90.001, False), (-1, False)])
async def test_generic_own_clock_expiry_and_future(hass, freezer, age, allowed):
    now = datetime(2026, 1, 2, 3, tzinfo=UTC)
    freezer.move_to(now - timedelta(seconds=age))
    hass.states.async_set(ENTITY, "off")
    freezer.move_to(now)
    hass.states.async_set("sensor.unrelated_live", "123")
    assert capture(LocalEvConnectionObserver(hass), now=now).disconnected is allowed


@pytest.mark.parametrize("age", [float("inf"), float("nan"), -1, None, True])
async def test_invalid_age_cannot_grant_disconnection(hass, age):
    hass.states.async_set(ENTITY, "off")
    assert not capture(LocalEvConnectionObserver(hass), age=age).disconnected


async def test_unmapped_is_distinct_from_unknown(hass):
    result = capture(LocalEvConnectionObserver(hass), entity=None)
    assert result.status == "unmapped" and not result.available


async def test_native_waits_for_real_new_publication_without_cache_seed(hass, freezer):
    rig = native(hass)
    observer = LocalEvConnectionObserver(hass)
    assert capture(observer).reason == "awaiting_native_publication"
    original_clock = hass.states.get(ENTITY).last_reported
    rig.provider.publish()
    result = capture(observer)
    assert result.disconnected and result.source == "tesla_wall_connector"
    assert hass.states.get(ENTITY).last_reported == original_clock
    assert rig.provider.additions == 1
    observer.close()
    assert len(rig.provider._listeners) == 1


async def test_native_repeated_cache_callback_and_other_entity_do_not_renew(hass, freezer):
    rig = native(hass)
    observer = LocalEvConnectionObserver(hass)
    capture(observer)
    rig.provider.publish()
    stamp = capture(observer).observed_at
    freezer.tick(timedelta(seconds=91))
    rig.provider.publish(rig.provider.data)
    hass.states.async_set("sensor.other_connector_power", "0", force_update=True)
    hass.states.async_set(ENTITY, "off", force_update=True)
    result = capture(observer)
    assert not result.disconnected
    assert result.reason == "native_publication_expired"
    assert result.observed_at is None
    assert stamp is not None
    rig.provider.publish()
    assert capture(observer).disconnected
    observer.close()


@pytest.mark.parametrize("fault", [
    "failed", "unloaded", "wrong_field", "wrong_device", "wrong_serial", "wrong_entry",
    "disabled", "restored", "unavailable", "bad_payload", "bad_bool", "missing_contactor",
    "connected_cache_entity_off", "open_cache_entity_on", "closed_contactor", "future_entity",
    "future_publication", "removed_registry", "naive_clock", "closed",
])
async def test_native_identity_health_coherence_and_clock_fail_closed(hass, freezer, fault):
    rig = native(hass)
    observer = LocalEvConnectionObserver(hass)
    capture(observer)
    rig.provider.publish()
    assert capture(observer).disconnected
    if fault == "failed":
        rig.provider.last_update_success = False
    elif fault == "unloaded":
        rig.entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
    elif fault in {"wrong_field", "wrong_device", "disabled"}:
        change = {
            "wrong_field": {"new_unique_id": f"{SERIAL}-contactor_closed"},
            "wrong_device": {"device_id": None},
            "disabled": {"disabled_by": er.RegistryEntryDisabler.USER},
        }[fault]
        er.async_get(hass).async_update_entity(ENTITY, **change)
    elif fault == "wrong_serial":
        rig.entry.runtime_data.serial_number = "OTHER-CONNECTOR"
    elif fault == "wrong_entry":
        rig.provider.config_entry = SimpleNamespace(entry_id="other-entry")
    elif fault in {"restored", "unavailable"}:
        hass.states.async_set(ENTITY, "unavailable" if fault == "unavailable" else "off",
                              {"restored": fault == "restored"})
    elif fault == "bad_payload":
        rig.provider.publish({"other": "not-vitals"})
    elif fault == "bad_bool":
        rig.provider.publish(Publisher.payload(0, False))
    elif fault == "missing_contactor":
        rig.provider.publish({"vitals": SimpleNamespace(vehicle_connected=False)})
    elif fault == "connected_cache_entity_off":
        rig.provider.data = Publisher.payload(True, False)
    elif fault == "open_cache_entity_on":
        hass.states.async_set(ENTITY, "on")
    elif fault == "closed_contactor":
        rig.provider.publish(Publisher.payload(False, True))
    elif fault == "future_entity":
        freezer.tick(timedelta(seconds=2))
        hass.states.async_set(ENTITY, "off", force_update=True)
        freezer.tick(timedelta(seconds=-2))
    elif fault == "future_publication":
        freezer.tick(timedelta(seconds=2))
        rig.provider.publish()
        freezer.tick(timedelta(seconds=-2))
    elif fault == "removed_registry":
        er.async_get(hass).async_remove(ENTITY)
    elif fault == "naive_clock":
        result = capture(observer, now=datetime.now(UTC).replace(tzinfo=None))
        assert not result.disconnected
        observer.close()
        return
    elif fault == "closed":
        observer.close()
    result = capture(observer)
    assert not result.disconnected, fault
    assert result.source == "tesla_wall_connector"
    observer.close()


async def test_connected_retracts_immediately_without_callback_and_no_old_proof_returns(hass):
    rig = native(hass)
    observer = LocalEvConnectionObserver(hass)
    capture(observer)
    rig.provider.publish()
    assert capture(observer).disconnected
    rig.provider.data = Publisher.payload(True, False)
    hass.states.async_set(ENTITY, "on")
    assert capture(observer).status == "connected"
    rig.provider.data = Publisher.payload(False, False)
    hass.states.async_set(ENTITY, "off")
    assert not capture(observer).disconnected
    rig.provider.publish()
    assert capture(observer).disconnected
    observer.close()


async def test_failed_provider_recovery_requires_new_publication(hass):
    rig = native(hass)
    observer = LocalEvConnectionObserver(hass)
    capture(observer)
    rig.provider.publish()
    assert capture(observer).disconnected
    rig.provider.last_update_success = False
    assert not capture(observer).disconnected
    rig.provider.last_update_success = True
    assert not capture(observer).disconnected
    rig.provider.publish()
    assert capture(observer).disconnected
    observer.close()


async def test_rebind_discards_old_frame_and_late_callback_cannot_repopulate(hass):
    rig = native(hass)
    observer = LocalEvConnectionObserver(hass)
    capture(observer)
    old_listener = list(rig.provider._listeners.values())[-1]
    rig.provider.publish()
    assert capture(observer).disconnected
    replacement = Publisher(rig.entry)
    rig.entry.runtime_data.update_coordinator = replacement
    assert not capture(observer).disconnected
    old_listener()
    assert not capture(observer).disconnected
    assert len(rig.provider._listeners) == 1
    replacement.publish()
    assert capture(observer).disconnected
    observer.close()


async def test_mapping_change_removes_only_own_subscription_and_history(hass):
    rig = native(hass)
    observer = LocalEvConnectionObserver(hass)
    capture(observer)
    rig.provider.publish()
    assert capture(observer).disconnected
    hass.states.async_set("binary_sensor.explicit_other", "off")
    assert capture(observer, entity="binary_sensor.explicit_other").disconnected
    assert len(rig.provider._listeners) == 1
    assert not capture(observer).disconnected
    observer.close()


async def test_observer_never_starts_an_unsubscribed_native_poller(hass):
    rig = native(hass)
    rig.provider._listeners.clear()
    observer = LocalEvConnectionObserver(hass)
    assert not capture(observer).disconnected
    assert rig.provider.additions == 0
    observer.close()


async def test_provider_teardown_cannot_break_close_or_restore_old_callback(hass):
    rig = native(hass)
    observer = LocalEvConnectionObserver(hass)
    capture(observer)
    old_listener = list(rig.provider._listeners.values())[-1]
    rig.provider.publish()
    assert capture(observer).disconnected
    rig.provider._listeners.clear()
    observer.close()
    old_listener()
    assert not capture(observer).disconnected
    observer.close()
