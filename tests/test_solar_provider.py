"""Same-frame native Solis measurement timestamps, without additional polling."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.home_energy_orchestrator import solar_provider
from custom_components.home_energy_orchestrator.solar_provider import capture_solis_solar
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
        capture_solis_solar(rig.hass, ENTITY),
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
    expected = capture_solis_solar(rig.hass, ENTITY)
    evidence = {}
    assert capture_solis_solar(rig.hass, ENTITY, diagnostics=evidence) == expected
    assert evidence["capture_accepted"] is False
    assert evidence["frame_fields"][field]["present"] is False
    assert evidence["reason"] in {
        "native_frame_identity_or_unit_mismatch", "native_frame_value_types_invalid",
    }


@pytest.mark.parametrize("fault,reason", [
    ("binding", "native_entity_identity_mismatch"),
    ("provider", "native_cache_unavailable"),
    ("unit", "native_frame_identity_or_unit_mismatch"),
    ("value", "native_entity_value_or_unit_mismatch"),
    ("timestamp", "native_frame_value_types_invalid"),
    ("state", "native_frame_value_types_invalid"),
])
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
    expected = capture_solis_solar(rig.hass, ENTITY)
    assert capture_solis_solar(rig.hass, ENTITY, diagnostics=evidence) == expected
    assert evidence["reason"] == reason and evidence["capture_accepted"] is False
    json.dumps(evidence, allow_nan=False)


def test_diagnostics_expose_no_provider_identity_credentials_or_arbitrary_cache(rig):
    rig.cache["password"] = "DO_NOT_EXPORT_SECRET"
    rig.cache["private_extra_key"] = {"url": "PRIVATE_PROVIDER_URL"}
    evidence = {}
    expected = capture_solis_solar(rig.hass, ENTITY)
    assert capture_solis_solar(rig.hass, ENTITY, diagnostics=evidence) == expected
    assert evidence["capture_accepted"] is True
    assert evidence["reason"] == "accepted_frame"
    assert evidence["frame_power_w"] == 4920
    assert evidence["measurement_at"] == NOW.isoformat()
    serialized = json.dumps(evidence, allow_nan=False)
    for private in [SERIAL, ENTITY, rig.entry.entry_id, "DO_NOT_EXPORT_SECRET",
                    "PRIVATE_PROVIDER_URL", "private_extra_key", "password"]:
        assert private not in serialized
    rig.cache["pacUnit"] = "DO_NOT_EXPORT_SECRET"
    evidence = {}
    capture_solis_solar(rig.hass, ENTITY, diagnostics=evidence)
    assert evidence["frame_unit"] == "unsupported"
    assert "DO_NOT_EXPORT_SECRET" not in json.dumps(evidence)


def test_diagnostics_do_not_renew_or_fabricate_source_freshness(rig):
    rig.cache["timestampUpdate"] = (NOW - timedelta(seconds=601)).timestamp()
    evidence = {}
    source = capture_solis_solar(rig.hass, ENTITY, diagnostics=evidence)
    assert evidence["capture_accepted"] is True  # Shape acceptance is not age permission.
    assert normalize_power_sample(
        source, now=NOW, max_age_seconds=600, multiplier=1,
        positive_direction="generation_positive",
    ).fresh is False
    assert source.updated_at == NOW - timedelta(seconds=601)
