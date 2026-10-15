"""Planning-capacity provenance is a pure, identity-compatible observation."""

from datetime import UTC, datetime

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import DOMAIN
from custom_components.home_energy_orchestrator.entity_catalogue import SENSOR_DESCRIPTIONS
from custom_components.home_energy_orchestrator.ev_capacity import CapacityObservation
from custom_components.home_energy_orchestrator.read_model import build_site_read_model
from custom_components.home_energy_orchestrator.sensor import EnergySensor

from .test_read_model import _coordinator
from .test_setup import ENTRY_DATA

OBSERVED = datetime(2026, 10, 1, 8, tzinfo=UTC)


def _capacity_coordinator(source="mapped_entity", observation=None):
    coordinator = _coordinator()
    coordinator.runtime_config = RuntimeConfiguration.from_mapping({"ev_capacity_source": source})
    coordinator.ev_controller.capacity_observation = observation
    return coordinator


@pytest.mark.parametrize(
    ("selected_source", "actual_source", "basis", "observed_at", "reason"),
    [
        ("mapped_entity", "mapped_entity", "mapped_capacity", OBSERVED, "ok"),
        ("tessie", "tessie", "nominal_full_pack", OBSERVED, "ok"),
        ("configured", "configured", "configured", None, "ok"),
        ("mapped_entity", "configured_fallback", "configured", None, "mapped_entity_unavailable"),
    ],
)
def test_nonlegacy_capacity_survives_missing_charge_limit_learning(
    selected_source, actual_source, basis, observed_at, reason
):
    observation = CapacityObservation(64.5, actual_source, basis, observed_at, reason)
    coordinator = _capacity_coordinator(selected_source, observation)
    coordinator.ev_controller.learned_charge_limit = None
    model = build_site_read_model(coordinator)
    assert model.ev.usable_capacity_kwh == 64.5
    assert model.sensor_values()["ev_usable_capacity"] == 64.5
    assert model.ev.capacity_attributes() == {
        "source": actual_source,
        "basis": basis,
        "observed_at": None if observed_at is None else observed_at.isoformat(),
        "fallback_reason": reason,
    }
    assert model.ev.learned_charge_limit_percent is None
    assert model.ev.free_window_soc_gain_percent is None
    assert model.ev.learning_status == "unavailable"


@pytest.mark.parametrize("source", ["mapped_entity", "tessie", "configured"])
def test_new_mode_never_falls_back_to_old_learned_capacity(source):
    coordinator = _capacity_coordinator(source)
    assert coordinator.ev_controller.learned_charge_limit.usable_capacity_kwh == 72
    model = build_site_read_model(coordinator)
    assert model.ev.usable_capacity_kwh is None
    assert model.ev.capacity_attributes() == {
        "source": None,
        "basis": None,
        "observed_at": None,
        "fallback_reason": None,
    }


def test_invalid_selected_capacity_preserves_failure_provenance_not_last_learned_value():
    coordinator = _capacity_coordinator(
        "mapped_entity",
        CapacityObservation(
            None, "mapped_entity", "mapped_capacity", None, "mapped_entity_unit_unsupported"
        ),
    )
    model = build_site_read_model(coordinator)
    assert model.ev.usable_capacity_kwh is None
    assert model.ev.capacity_attributes() == {
        "source": "mapped_entity",
        "basis": "mapped_capacity",
        "observed_at": None,
        "fallback_reason": "mapped_entity_unit_unsupported",
    }


@pytest.mark.parametrize("learned_available", [True, False])
def test_legacy_capacity_retains_exact_existing_learned_projection(learned_available):
    coordinator = _capacity_coordinator(
        "legacy_ratio", CapacityObservation(99, "legacy_ratio", "legacy_ratio", None, "ok")
    )
    if not learned_available:
        coordinator.ev_controller.learned_charge_limit = None
    model = build_site_read_model(coordinator)
    assert model.ev.usable_capacity_kwh == (72 if learned_available else None)


def test_capacity_projection_uses_observed_timestamp_not_render_time_or_live_state():
    coordinator = _capacity_coordinator(
        "tessie", CapacityObservation(64, "tessie", "nominal_full_pack", OBSERVED, "ok")
    )

    class NoLiveState:
        def __getattr__(self, name):
            raise AssertionError(f"Presentation must not read live Home Assistant {name}")

    coordinator.hass = NoLiveState()
    model = build_site_read_model(coordinator, datetime(2026, 10, 2, tzinfo=UTC))
    coordinator.ev_controller.capacity_observation = None
    assert model.ev.usable_capacity_kwh == 64
    assert model.ev.capacity_attributes()["observed_at"] == OBSERVED.isoformat()


def test_capacity_sensor_projects_only_its_capacity_attributes_and_retains_identity():
    coordinator = _capacity_coordinator(
        "configured", CapacityObservation(64, "configured", "configured", None, "ok")
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Capacity observation")
    description = next(item for item in SENSOR_DESCRIPTIONS if item.key == "ev_usable_capacity")
    sensor = EnergySensor(coordinator, entry, description)
    assert sensor.entity_id == "sensor.home_energy_ev_usable_capacity"
    assert sensor.unique_id == f"{entry.entry_id}_ev_usable_capacity"
    assert sensor.entity_description.name == "EV Planning Capacity"
    assert sensor.native_unit_of_measurement == "kWh"
    assert sensor.native_value == 64
    assert sensor.extra_state_attributes == {
        "source": "configured",
        "basis": "configured",
        "observed_at": None,
        "fallback_reason": "ok",
    }
    assert "source" not in build_site_read_model(coordinator).ev.control_attributes()


def test_missing_ev_controller_has_no_manufactured_capacity_or_source():
    coordinator = _capacity_coordinator("configured")
    coordinator.ev_controller = None
    model = build_site_read_model(coordinator)
    assert model.ev.usable_capacity_kwh is None
    assert model.ev.capacity_attributes() == {
        "source": None,
        "basis": None,
        "observed_at": None,
        "fallback_reason": None,
    }


@pytest.mark.parametrize("disabled", [False, True])
async def test_capacity_entity_preserves_registered_user_identity_on_setup_and_reload(
    hass, disabled
):
    entry = MockConfigEntry(domain=DOMAIN, title="Capacity identity", data=ENTRY_DATA, version=6)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    record = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_ev_usable_capacity",
        suggested_object_id="home_energy_ev_usable_capacity",
        config_entry=entry,
    )
    registry.async_update_entity(
        record.entity_id,
        new_entity_id="sensor.my_ev_capacity",
        name="My EV capacity",
        area_id="energy_area",
        labels={"energy_label"},
        hidden_by=er.RegistryEntryHider.USER,
        disabled_by=er.RegistryEntryDisabler.USER if disabled else None,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for _ in range(2):
        record = registry.async_get("sensor.my_ev_capacity")
        assert record.unique_id == f"{entry.entry_id}_ev_usable_capacity"
        assert record.name == "My EV capacity"
        assert record.area_id == "energy_area" and record.labels == {"energy_label"}
        assert record.hidden_by is er.RegistryEntryHider.USER
        assert record.disabled_by is (er.RegistryEntryDisabler.USER if disabled else None)
        assert registry.async_get("sensor.home_energy_ev_usable_capacity") is None
        if disabled:
            assert hass.states.get("sensor.my_ev_capacity") is None
        assert entry.runtime_data.ev_controller.writes_performed == 0
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
