"""Same-frame native Solis measurement timestamps, without additional polling."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.home_energy_orchestrator import solar_provider
from custom_components.home_energy_orchestrator.solar_provider import (
    SolisPublishedFrames,
    capture_solis_solar,
)
from custom_components.home_energy_orchestrator.telemetry import normalize_power_sample

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
ENTITY = "sensor.renamed_ac_power"
SERIAL = "TEST_INVERTER_01"


@pytest.fixture
def rig(monkeypatch):
    state = SimpleNamespace(
        state="4920",
        attributes={
            "Inverter serial": SERIAL,
            "API Name": "SolisCloud",
            "unit_of_measurement": "W",
        },
        last_changed=NOW - timedelta(hours=20),
        last_reported=NOW,
        last_updated=NOW,
    )
    entry = SimpleNamespace(
        entry_id="solis-entry",
        domain="solis",
        state=ConfigEntryState.LOADED,
        data={"name": "Solar"},
    )
    registry = SimpleNamespace(
        platform="solis",
        config_entry_id=entry.entry_id,
        device_id="native-device",
        unique_id=f"{SERIAL}Solar_AC_Output_Total_Power",
    )
    device = SimpleNamespace(
        config_entries={entry.entry_id},
        identifiers={
            ("solis", f"{SERIAL}_SolisCloud"),
        },
    )
    cache = {
        "serial": SERIAL,
        "acPower": 4920,
        "timestampUpdate": NOW.timestamp(),
        "pacUnit": "W",
        "state": 1,
    }
    # No fetch methods or credentials are present: this adapter cannot poll.
    api = SimpleNamespace(_data=cache)
    service = SimpleNamespace(_api=api)
    hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda entity: state if entity == ENTITY else None),
        config_entries=SimpleNamespace(
            async_get_entry=lambda key: entry if key == entry.entry_id else None
        ),
        data={"solis": {entry.entry_id: service}},
    )
    monkeypatch.setattr(
        solar_provider.er,
        "async_get",
        lambda _hass: SimpleNamespace(
            async_get=lambda entity: registry if entity == ENTITY else None
        ),
    )
    monkeypatch.setattr(
        solar_provider.dr,
        "async_get",
        lambda _hass: SimpleNamespace(
            async_get=lambda key: device if key == registry.device_id else None
        ),
    )
    return SimpleNamespace(
        hass=hass,
        state=state,
        entry=entry,
        registry=registry,
        device=device,
        api=api,
        service=service,
        cache=cache,
    )


def qualified(rig, now=NOW):
    return normalize_power_sample(
        capture_solis_solar(rig.hass, ENTITY, cached_frame=rig.api._data),
        now=now,
        max_age_seconds=600,
        multiplier=1,
        positive_direction="generation_positive",
    )


@pytest.mark.parametrize("power", [0, 4920])
def test_constant_night_or_clipped_power_qualifies_only_from_matching_new_measurement(rig, power):
    rig.state.state = str(power)
    rig.cache["acPower"] = power
    assert qualified(rig).value == power / 1000
    # HA publishes no numeric change, but the complete provider frame advances.
    rig.api._data = {**rig.cache, "timestampUpdate": (NOW + timedelta(minutes=5)).timestamp()}
    result = qualified(rig, NOW + timedelta(minutes=5))
    assert result.value == power / 1000 and result.fresh
    assert result.updated_at == NOW + timedelta(minutes=5)
    # A fresh HA report/attribute change alone cannot renew an old provider frame.
    rig.state.last_reported = NOW + timedelta(minutes=16)
    rig.state.last_updated = rig.state.last_reported
    rig.state.attributes["other"] = "refreshed"
    assert qualified(rig, NOW + timedelta(minutes=16)).value is None


@pytest.mark.parametrize("field", ["serial", "acPower", "timestampUpdate", "pacUnit", "state"])
def test_partial_frame_never_promotes_another_field_or_companion_timestamp(rig, field):
    rig.cache.pop(field)
    assert qualified(rig).value is None


@pytest.mark.parametrize(
    "failure",
    [
        "other_inverter",
        "other_value",
        "wrong_unit",
        "future",
        "ms",
        "bool",
        "nan",
        "empty",
        "missing_provider",
        "restored",
        "unloaded",
        "other_entity",
        "other_device",
    ],
)
def test_unbound_or_invalid_provider_evidence_is_unavailable(rig, failure):
    if failure == "other_inverter":
        rig.cache["serial"] = "ANOTHER_INVERTER"
    elif failure == "other_value":
        rig.cache["acPower"] = 5000
    elif failure == "wrong_unit":
        rig.cache["pacUnit"] = "kW"
    elif failure == "future":
        rig.cache["timestampUpdate"] = (NOW + timedelta(seconds=1)).timestamp()
    elif failure == "ms":
        rig.cache["timestampUpdate"] *= 1000
    elif failure == "bool":
        rig.cache["acPower"] = True
    elif failure == "nan":
        rig.cache["timestampUpdate"] = float("nan")
    elif failure == "empty":
        rig.api._data = {}
    elif failure == "missing_provider":
        rig.hass.data = {}
    elif failure == "restored":
        rig.state.attributes["restored"] = True
    elif failure == "unloaded":
        rig.entry.state = ConfigEntryState.NOT_LOADED
    elif failure == "other_entity":
        rig.registry.unique_id = f"{SERIAL}Solar_String_DC_Power"
    elif failure == "other_device":
        rig.device.identifiers = {("solis", "ANOTHER_INVERTER_SolisCloud")}
    assert qualified(rig).value is None


def test_cache_replacement_and_late_older_packet_do_not_extend_age(rig):
    assert qualified(rig).fresh
    rig.api._data = {}
    assert qualified(rig).value is None
    rig.api._data = {**rig.cache, "timestampUpdate": (NOW - timedelta(seconds=601)).timestamp()}
    assert qualified(rig).value is None
    rig.api._data = dict(rig.cache)
    assert qualified(rig).fresh


def test_offline_display_override_is_not_mistaken_for_measured_zero(rig):
    rig.cache["state"] = 2
    rig.state.state = "0"
    assert qualified(rig).value is None  # Retained nonzero power is not measured zero.
    rig.cache["acPower"] = 0
    assert qualified(rig).value == 0  # Complete frame actually measures zero.
    rig.cache.pop("acPower")
    assert qualified(rig).value is None


@pytest.mark.parametrize("field", ["serial", "pacUnit", "acPower", "timestampUpdate", "state"])
def test_diagnostics_identify_rejected_frame_without_changing_capture(rig, field):
    rig.cache.pop(field)
    expected = capture_solis_solar(rig.hass, ENTITY, cached_frame=rig.api._data)
    evidence = {}
    assert (
        capture_solis_solar(rig.hass, ENTITY, cached_frame=rig.api._data, diagnostics=evidence)
        == expected
    )
    assert evidence["capture_accepted"] is False
    assert evidence["frame_fields"][field]["present"] is False
    assert evidence["reason"] in {
        "native_frame_identity_or_unit_mismatch",
        "native_frame_value_types_invalid",
    }


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("binding", "native_entity_identity_mismatch"),
        ("provider", "native_cache_unavailable"),
        ("unit", "native_frame_identity_or_unit_mismatch"),
        ("value", "native_entity_value_or_unit_mismatch"),
        ("timestamp", "native_frame_value_types_invalid"),
        ("state", "native_frame_value_types_invalid"),
    ],
)
def test_diagnostic_reasons_are_bounded_and_pure(rig, fault, reason):
    if fault == "binding":
        rig.registry.unique_id = "different_property"
    elif fault == "provider":
        rig.hass.data = {}
    elif fault == "unit":
        rig.cache["pacUnit"] = "kW"
    elif fault == "value":
        rig.state.state = "100"
    elif fault == "timestamp":
        rig.cache["timestampUpdate"] = float("nan")
    else:
        rig.cache["state"] = None
    evidence = {}
    expected = capture_solis_solar(rig.hass, ENTITY, cached_frame=rig.api._data)
    assert (
        capture_solis_solar(rig.hass, ENTITY, cached_frame=rig.api._data, diagnostics=evidence)
        == expected
    )
    assert evidence["reason"] == reason and evidence["capture_accepted"] is False
    json.dumps(evidence, allow_nan=False)


def test_diagnostics_expose_no_provider_identity_credentials_or_arbitrary_cache(rig):
    rig.cache["password"] = "DO_NOT_EXPORT_SECRET"
    rig.cache["private_extra_key"] = {"url": "PRIVATE_PROVIDER_URL"}
    evidence = {}
    expected = capture_solis_solar(rig.hass, ENTITY, cached_frame=rig.api._data)
    assert (
        capture_solis_solar(rig.hass, ENTITY, cached_frame=rig.api._data, diagnostics=evidence)
        == expected
    )
    assert evidence["capture_accepted"] is True
    assert evidence["reason"] == "accepted_frame"
    assert evidence["frame_power_w"] == 4920
    assert evidence["measurement_at"] == NOW.isoformat()
    serialized = json.dumps(evidence, allow_nan=False)
    for private in [
        SERIAL,
        ENTITY,
        rig.entry.entry_id,
        "DO_NOT_EXPORT_SECRET",
        "PRIVATE_PROVIDER_URL",
        "private_extra_key",
        "password",
    ]:
        assert private not in serialized
    rig.cache["pacUnit"] = "DO_NOT_EXPORT_SECRET"
    evidence = {}
    capture_solis_solar(rig.hass, ENTITY, cached_frame=rig.api._data, diagnostics=evidence)
    assert evidence["frame_unit"] == "unsupported"
    assert "DO_NOT_EXPORT_SECRET" not in json.dumps(evidence)


def test_diagnostics_do_not_renew_or_fabricate_source_freshness(rig):
    rig.cache["timestampUpdate"] = (NOW - timedelta(seconds=601)).timestamp()
    evidence = {}
    source = capture_solis_solar(rig.hass, ENTITY, cached_frame=rig.api._data, diagnostics=evidence)
    assert evidence["capture_accepted"] is True  # Shape acceptance is not age permission.
    assert (
        normalize_power_sample(
            source,
            now=NOW,
            max_age_seconds=600,
            multiplier=1,
            positive_direction="generation_positive",
        ).fresh
        is False
    )
    assert source.updated_at == NOW - timedelta(seconds=601)


class _Publisher:
    """Characterise native 4.0.x synchronous per-inverter dispatch, no I/O."""

    def __init__(self, rig):
        self.rig, self._api, self._subscriptions = rig, rig.api, {}

    def subscribe(self, subscriber, serial, attribute):
        self._subscriptions.setdefault(serial, {}).setdefault(attribute, []).append(subscriber)

    def publish(self, frame):
        self._api._data = dict(frame)
        serial = frame.get("serial")
        for subscriber in tuple(self._subscriptions.get(serial, {}).get("serial", [])):
            subscriber.data_updated(serial, NOW)
        # The actual native serial callback runs before AC power is written.
        if serial == SERIAL and "acPower" in frame:
            self.rig.state.state = str(0 if frame.get("state") == 2 else frame["acPower"])


@pytest.fixture
def published(rig):
    rig.service = _Publisher(rig)
    rig.hass.data["solis"][rig.entry.entry_id] = rig.service
    collector = SolisPublishedFrames(rig.hass)
    collector.ensure_source(ENTITY)
    return rig, collector


def _published_source(rig, collector):
    return capture_solis_solar(rig.hass, ENTITY, cached_frame=collector.current_frame())


def test_two_inverters_keep_only_the_selected_published_frame(published):
    rig, collector = published
    selected = {**rig.cache, "acPower": 4100}
    other = {**rig.cache, "serial": "DIFFERENT_INVERTER", "acPower": 9900}
    rig.service.publish(selected)
    rig.service.publish(other)
    # The old shared-cache reader correctly rejects the other serial, but
    # loses this entity's valid measurement. The new binding retains its frame.
    assert capture_solis_solar(rig.hass, ENTITY, cached_frame=rig.api._data).raw_value is None
    source = _published_source(rig, collector)
    assert source.raw_value == 4100 and source.updated_at == NOW
    evidence = {}
    assert (
        capture_solis_solar(
            rig.hass,
            ENTITY,
            cached_frame=collector.current_frame(),
            diagnostics=evidence,
        )
        == source
    )
    assert evidence["frame_origin"] == "selected_inverter_publication"
    assert evidence["frame_serial_matches"] is True


@pytest.mark.parametrize("field", ["pacUnit", "acPower", "timestampUpdate", "state"])
def test_partial_selected_publication_invalidates_old_frame(published, field):
    rig, collector = published
    frame = {**rig.cache}
    frame.pop(field)
    rig.service.publish(frame)
    assert _published_source(rig, collector).raw_value is None
    rig.service.publish(rig.cache)
    assert _published_source(rig, collector).raw_value == 4920


@pytest.mark.parametrize("power", [0, 4920])
def test_constant_selected_power_renews_only_on_real_measurement(published, power):
    rig, collector = published
    rig.service.publish({**rig.cache, "acPower": power})
    rig.service.publish(
        {
            **rig.cache,
            "serial": "OTHER",
            "timestampUpdate": (NOW + timedelta(minutes=5)).timestamp(),
        }
    )
    source = _published_source(rig, collector)
    assert source.raw_value == power and source.updated_at == NOW
    expired = normalize_power_sample(
        source,
        now=NOW + timedelta(seconds=601),
        max_age_seconds=600,
        multiplier=1,
        positive_direction="generation_positive",
    )
    assert expired.value is None and not expired.fresh
    rig.service.publish(
        {**rig.cache, "acPower": power, "timestampUpdate": (NOW + timedelta(minutes=5)).timestamp()}
    )
    assert _published_source(rig, collector).updated_at == NOW + timedelta(minutes=5)


def test_seed_waits_for_selected_inverter_and_does_not_poll(rig):
    rig.service = _Publisher(rig)
    rig.hass.data["solis"][rig.entry.entry_id] = rig.service
    rig.api._data = {**rig.cache, "serial": "OTHER"}
    collector = SolisPublishedFrames(rig.hass)
    collector.ensure_source(ENTITY)
    assert collector.current_frame() is None
    assert _published_source(rig, collector).raw_value is None
    rig.service.publish(rig.cache)
    assert _published_source(rig, collector).raw_value == 4920


def test_subscription_is_idempotent_and_unload_removes_only_own_listener(published):
    rig, collector = published
    marker = object()
    callbacks = rig.service._subscriptions[SERIAL]["serial"]
    callbacks.append(marker)
    for _ in range(10):
        collector.ensure_source(ENTITY)
    assert len(callbacks) == 2
    stale = callbacks[0]
    collector.close()
    assert callbacks == [marker] and collector.current_frame() is None
    stale.data_updated(SERIAL, NOW)
    assert collector.current_frame() is None


@pytest.mark.parametrize("fault", ["entry", "provider", "api", "registry", "restored"])
def test_replacement_and_invalid_binding_cannot_reuse_old_frame(published, fault):
    rig, collector = published
    stale = collector._listener
    if fault == "entry":
        rig.entry.state = ConfigEntryState.NOT_LOADED
    elif fault == "provider":
        rig.service = _Publisher(rig)
        rig.hass.data["solis"][rig.entry.entry_id] = rig.service
    elif fault == "api":
        rig.service._api = SimpleNamespace(_data={**rig.cache, "serial": "OTHER"})
    elif fault == "registry":
        rig.registry.unique_id = "different"
    else:
        rig.state.attributes["restored"] = True
    assert collector.current_frame() is None
    collector.ensure_source(ENTITY)
    # A new provider may seed only a matching current frame, never an old callback.
    current = collector.current_frame()
    stale.data_updated(SERIAL, NOW)
    assert collector.current_frame() == current


def test_unsupported_native_publisher_has_no_shared_cache_fallback(rig):
    collector = SolisPublishedFrames(rig.hass)
    collector.ensure_source(ENTITY)
    assert collector.current_frame() is None
    assert _published_source(rig, collector).raw_value is None


def test_subscription_failure_removes_partial_registration(published):
    rig, collector = published
    collector.close()
    native_subscribe = rig.service.subscribe

    def broken(*args):
        native_subscribe(*args)
        raise RuntimeError("synthetic publisher failure")

    rig.service.subscribe = broken
    collector.ensure_source(ENTITY)
    assert collector.current_frame() is None
    assert rig.service._subscriptions[SERIAL]["serial"] == []


def test_snapshot_is_immutable_and_invalid_publication_cannot_keep_old_zero(published):
    rig, collector = published
    frame = collector.current_frame()
    with pytest.raises(TypeError):
        frame["acPower"] = 0
    rig.service.publish({**rig.cache, "state": 2})
    assert _published_source(rig, collector).raw_value is None
    rig.service.publish({**rig.cache, "state": 2, "acPower": 0})
    assert _published_source(rig, collector).raw_value == 0


def test_separate_owners_unload_without_disturbing_other_subscribers(published):
    rig, first = published
    second = SolisPublishedFrames(rig.hass)
    second.ensure_source(ENTITY)
    assert len(rig.service._subscriptions[SERIAL]["serial"]) == 2
    first.ensure_source(None)
    assert first.current_frame() is None
    assert len(rig.service._subscriptions[SERIAL]["serial"]) == 1
    rig.service.publish({**rig.cache, "acPower": 4800})
    assert _published_source(rig, second).raw_value == 4800
    assert first.current_frame() is None
    second.close()
    assert rig.service._subscriptions[SERIAL]["serial"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("timestampUpdate", True),
        ("timestampUpdate", float("nan")),
        ("timestampUpdate", NOW.timestamp() * 1000),
        ("acPower", float("inf")),
        ("state", True),
        ("pacUnit", "kW"),
    ],
)
def test_bad_selected_frame_never_reuses_last_good_measurement(published, field, value):
    rig, collector = published
    rig.service.publish({**rig.cache, field: value})
    result = normalize_power_sample(
        _published_source(rig, collector),
        now=NOW,
        max_age_seconds=600,
        multiplier=1,
        positive_direction="generation_positive",
    )
    assert result.value is None and not result.valid
