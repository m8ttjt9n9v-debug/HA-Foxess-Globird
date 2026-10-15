"""Capacity observation binds to one configured provider without new requests."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.home_energy_orchestrator import ev_capacity
from custom_components.home_energy_orchestrator.ev_capacity import resolve_ev_capacity
from custom_components.home_energy_orchestrator.planner.ev_learning import (
    estimate_usable_ev_capacity_kwh,
)

NOW = datetime(2030, 4, 10, 1, tzinfo=UTC)
VIN = "TESTVEHICLE0000001"
OTHER_VIN = "TESTVEHICLE0000002"
SOC = "sensor.renamed_car_soc"
ENTITY = "sensor.explicit_capacity"


def _settings(source="legacy_ratio", fallback=None):
    return SimpleNamespace(source=source, entity_id=ENTITY, fallback_kwh=fallback)


@pytest.fixture
def rig(monkeypatch):
    coordinator = SimpleNamespace(
        last_update_success=True,
        data={
            "charge_state_nominal_full_pack_energy": 80.0,
            "charge_state_timestamp": NOW.timestamp() * 1000,
        },
    )
    # No api/credential object is exposed: a provider read cannot make requests.
    vehicle = SimpleNamespace(vin=VIN, data_coordinator=coordinator)
    other = SimpleNamespace(
        vin=OTHER_VIN,
        data_coordinator=SimpleNamespace(
            last_update_success=True,
            data={
                "charge_state_nominal_full_pack_energy": 50.0,
                "charge_state_timestamp": NOW.timestamp() * 1000,
            },
        ),
    )
    entry = SimpleNamespace(
        entry_id="provider_entry",
        domain="tessie",
        state=ConfigEntryState.LOADED,
        runtime_data=SimpleNamespace(vehicles=[other, vehicle]),
    )
    registry = SimpleNamespace(
        platform="tessie",
        config_entry_id=entry.entry_id,
        device_id="mapped_device",
        unique_id=f"{VIN}-charge_state_usable_battery_level",
    )
    device = SimpleNamespace(identifiers={("tessie", VIN)}, config_entries={entry.entry_id})
    state = SimpleNamespace(
        state="80000", attributes={"unit_of_measurement": "Wh"}, last_reported=NOW
    )
    hass = SimpleNamespace(
        states=SimpleNamespace(get=Mock(return_value=state)),
        config_entries=SimpleNamespace(async_get_entry=Mock(return_value=entry)),
    )
    entity_registry = SimpleNamespace(async_get=Mock(return_value=registry))
    device_registry = SimpleNamespace(async_get=Mock(return_value=device))
    monkeypatch.setattr(ev_capacity.er, "async_get", lambda _: entity_registry)
    monkeypatch.setattr(ev_capacity.dr, "async_get", lambda _: device_registry)
    return SimpleNamespace(
        hass=hass,
        state=state,
        entry=entry,
        registry=registry,
        device=device,
        vehicle=vehicle,
        coordinator=coordinator,
        other=other,
        entity_registry=entity_registry,
        device_registry=device_registry,
    )


def _resolve(rig, source="tessie", fallback=None, **kwargs):
    return resolve_ev_capacity(
        rig.hass,
        _settings(source, fallback),
        soc_entity=SOC,
        stored_energy_kwh=24,
        soc_percent=20,
        now=kwargs.pop("now", NOW),
        **kwargs,
    )


@pytest.mark.parametrize("stored,soc", [(24, 20), (44, 40), (1000, 1), (1, 100)])
def test_legacy_uses_exact_existing_primitive_without_new_upper_bound(stored, soc):
    result = resolve_ev_capacity(
        None,
        _settings(),
        soc_entity=None,
        stored_energy_kwh=stored,
        soc_percent=soc,
        now=NOW,
    )
    assert result.value_kwh == estimate_usable_ev_capacity_kwh(
        stored_energy_kwh=stored, soc_percent=soc
    )
    assert (result.source, result.basis, result.observed_at, result.reason) == (
        "legacy_ratio",
        "legacy_ratio",
        None,
        "ok",
    )


@pytest.mark.parametrize(
    "stored,soc",
    [(None, 20), (24, None), (0, 20), (24, 0), (24, 101), (float("nan"), 20), (24, float("inf"))],
)
def test_unavailable_legacy_ratio_does_not_raise_or_use_configured_fallback(stored, soc):
    result = resolve_ev_capacity(
        None,
        _settings(fallback=80),
        soc_entity=None,
        stored_energy_kwh=stored,
        soc_percent=soc,
        now=NOW,
    )
    assert result.value_kwh is None
    assert result.reason == "legacy_ratio_unavailable"


def test_tessie_is_bound_to_renamed_explicit_soc_not_first_vehicle(rig):
    result = _resolve(rig)
    assert (result.value_kwh, result.source, result.basis, result.observed_at) == (
        80.0,
        "tessie",
        "nominal_full_pack",
        NOW,
    )
    rig.entity_registry.async_get.assert_called_once_with(SOC)
    rig.hass.states.get.assert_not_called()
    with pytest.raises(FrozenInstanceError):
        result.value_kwh = 100


def test_tessie_supports_runtime_vehicle_mapping_without_using_dictionary_order(rig):
    rig.entry.runtime_data.vehicles = {OTHER_VIN: rig.other, VIN: rig.vehicle}
    assert _resolve(rig).value_kwh == 80.0


@pytest.mark.parametrize("mode", ["tessie", "mapped_entity"])
@pytest.mark.parametrize(
    "age,reason",
    [
        (timedelta(hours=24), "ok"),
        (timedelta(hours=24, microseconds=1), "timestamp_stale"),
        (timedelta(microseconds=-1), "timestamp_future"),
    ],
)
def test_capacity_age_boundary_is_independent_of_fast_control_age(rig, mode, age, reason):
    timestamp = NOW - age
    rig.state.last_reported = timestamp
    rig.coordinator.data["charge_state_timestamp"] = timestamp.timestamp() * 1000
    result = _resolve(rig, mode)
    assert result.reason == "ok" if reason == "ok" else result.reason.endswith(reason)
    assert (result.value_kwh is not None) == (reason == "ok")


@pytest.mark.parametrize(
    "value", [None, True, False, 0, -1, 1000.01, float("nan"), float("inf"), "80.0"]
)
def test_tessie_rejects_invalid_capacity_and_never_uses_raw_ratio(rig, value):
    rig.coordinator.data["charge_state_nominal_full_pack_energy"] = value
    assert _resolve(rig).value_kwh is None
    fallback = _resolve(rig, fallback=80)
    assert (fallback.value_kwh, fallback.source, fallback.observed_at) == (
        80,
        "configured_fallback",
        None,
    )
    assert fallback.reason == "tessie_value_invalid"


@pytest.mark.parametrize("value", [None, True, "123", float("nan"), float("inf"), 1e100])
def test_tessie_rejects_missing_or_malformed_millisecond_timestamp(rig, value):
    rig.coordinator.data["charge_state_timestamp"] = value
    result = _resolve(rig)
    assert result.value_kwh is None
    assert result.reason.endswith(("timestamp_invalid", "timestamp_stale"))


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("platform", "other", "soc_not_tessie"),
        ("config_entry_id", None, "entry_unavailable"),
        ("device_id", None, "device_unavailable"),
        ("unique_id", f"{OTHER_VIN}-charge_state_usable_battery_level", "vehicle_mismatch"),
    ],
)
def test_tessie_rejects_nonmatching_registry_binding(rig, field, value, reason):
    setattr(rig.registry, field, value)
    assert _resolve(rig).reason == f"tessie_{reason}"


@pytest.mark.parametrize(
    "case",
    [
        "no_identifier",
        "multiple_identifiers",
        "wrong_entry",
        "missing_vehicle",
        "duplicate_vehicle",
        "bad_runtime",
        "no_provider",
        "failed_provider",
        "bad_data",
        "wrong_provider_entry",
    ],
)
def test_tessie_ambiguous_or_unsupported_shapes_fail_closed(rig, case):
    if case == "no_identifier":
        rig.device.identifiers = {("other", VIN)}
    elif case == "multiple_identifiers":
        rig.device.identifiers.add(("tessie", OTHER_VIN))
    elif case == "wrong_entry":
        rig.device.config_entries.clear()
    elif case == "missing_vehicle":
        rig.entry.runtime_data.vehicles = [rig.other]
    elif case == "duplicate_vehicle":
        rig.entry.runtime_data.vehicles.append(rig.vehicle)
    elif case == "bad_runtime":
        rig.entry.runtime_data = None
    elif case == "no_provider":
        rig.vehicle.data_coordinator = None
    elif case == "failed_provider":
        rig.coordinator.last_update_success = False
    elif case == "bad_data":
        rig.coordinator.data = []
    else:
        rig.coordinator.config_entry = SimpleNamespace(entry_id="different_entry")
    result = _resolve(rig, fallback=81)
    assert result.value_kwh == 81
    assert result.source == "configured_fallback"
    assert result.reason.startswith("tessie_")


def test_provider_unload_reload_does_not_retain_a_last_good_or_wrong_car_value(rig):
    assert _resolve(rig).value_kwh == 80.0
    rig.entry.state = ConfigEntryState.NOT_LOADED
    assert _resolve(rig).value_kwh is None
    assert _resolve(rig, fallback=80).source == "configured_fallback"
    rig.entry.state = ConfigEntryState.LOADED
    rig.coordinator.data["charge_state_nominal_full_pack_energy"] = 79.9
    assert _resolve(rig).value_kwh == 79.9
    rig.registry.unique_id = f"{OTHER_VIN}-charge_state_usable_battery_level"
    assert _resolve(rig).value_kwh is None


@pytest.mark.parametrize(
    "unit,raw,expected", [("Wh", "80000", 80.0), ("kWh", "80.0", 80.0), ("kWh", "1000", 1000)]
)
def test_mapped_capacity_requires_explicit_energy_units(rig, unit, raw, expected):
    rig.state.state = raw
    rig.state.attributes["unit_of_measurement"] = unit
    result = _resolve(rig, "mapped_entity")
    assert (result.value_kwh, result.basis, result.observed_at) == (
        expected,
        "mapped_capacity",
        NOW,
    )
    rig.hass.states.get.assert_called_once_with(ENTITY)
    rig.hass.config_entries.async_get_entry.assert_not_called()


@pytest.mark.parametrize(
    "unit,raw",
    [
        (None, "82"),
        ("MWh", "0.082"),
        ("%", "82"),
        ("kWh", "unavailable"),
        ("kWh", "NaN"),
        ("kWh", "inf"),
        ("kWh", "0"),
        ("kWh", "-1"),
        ("kWh", "1001"),
        ("kWh", True),
    ],
)
def test_invalid_mapped_source_uses_only_explicit_fallback(rig, unit, raw):
    rig.state.state = raw
    rig.state.attributes["unit_of_measurement"] = unit
    assert _resolve(rig, "mapped_entity").value_kwh is None
    result = _resolve(rig, "mapped_entity", fallback=80)
    assert result.value_kwh == 80 and result.source == "configured_fallback"


@pytest.mark.parametrize("mode", ["mapped_entity", "tessie"])
def test_naive_source_clock_cannot_become_current_observation(rig, mode):
    if mode == "mapped_entity":
        rig.state.last_reported = NOW.replace(tzinfo=None)
    result = _resolve(rig, mode, now=NOW.replace(tzinfo=None))
    assert result.value_kwh is None


@pytest.mark.parametrize(
    "value", [None, True, False, 0, -1, 1001, "80", float("nan"), float("inf")]
)
def test_configured_capacity_has_finite_positive_bounds(rig, value):
    assert _resolve(rig, "configured", fallback=value).value_kwh is None


def test_configured_mode_needs_no_provider_clock_or_legacy_inputs(rig):
    result = resolve_ev_capacity(
        None,
        _settings("configured", 80),
        soc_entity=None,
        stored_energy_kwh=None,
        soc_percent=None,
        now=NOW,
    )
    assert (result.value_kwh, result.source, result.basis, result.observed_at, result.reason) == (
        80,
        "configured",
        "configured",
        None,
        "ok",
    )


def test_unknown_source_cannot_enable_a_fallback(rig):
    result = _resolve(rig, "misspelled", fallback=80)
    assert result.value_kwh is None
    assert result.reason == "capacity_source_unsupported"


@pytest.mark.parametrize("mode", ["configured", "tessie"])
def test_extreme_integer_capacity_is_unavailable_not_an_exception(rig, mode):
    rig.coordinator.data["charge_state_nominal_full_pack_energy"] = 10**1000
    assert _resolve(rig, mode, fallback=10**1000).value_kwh is None


def test_generic_restored_state_does_not_count_as_fresh_provider_observation(rig):
    rig.state.attributes["restored"] = True
    assert _resolve(rig, "mapped_entity").value_kwh is None
    assert _resolve(rig, "mapped_entity", fallback=80).source == "configured_fallback"


def test_generic_stable_value_uses_last_reported_not_last_changed(rig):
    rig.state.last_changed = rig.state.last_updated = NOW - timedelta(days=10)
    assert _resolve(rig, "mapped_entity").value_kwh == 80.0


@pytest.mark.parametrize("part", ["registry", "entry", "device"])
def test_missing_provider_registry_parts_use_only_explicit_fallback(rig, part):
    if part == "registry":
        rig.entity_registry.async_get.return_value = None
    elif part == "entry":
        rig.hass.config_entries.async_get_entry.return_value = None
    else:
        rig.device_registry.async_get.return_value = None
    result = _resolve(rig, fallback=80)
    assert result.value_kwh == 80 and result.source == "configured_fallback"


def test_malformed_device_identifier_shape_fails_closed(rig):
    rig.device.identifiers = None
    assert _resolve(rig).reason == "tessie_device_ambiguous"
