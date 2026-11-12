"""Setup and native controls for unavailable EV reservation data."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform

from custom_components.home_energy_orchestrator.config_flow import ConfigFlow
from custom_components.home_energy_orchestrator.configuration import (
    RuntimeConfiguration,
    valid_ev_reservation_unplugged_soc_max_age_minutes,
)
from custom_components.home_energy_orchestrator.const import (
    CONF_EV_RESERVATION_SOC_MAX_AGE_HOURS as SLEEPING_KEY,
)
from custom_components.home_energy_orchestrator.const import (
    CONF_EV_RESERVATION_UNAVAILABLE_BEHAVIOR as BEHAVIOR,
)
from custom_components.home_energy_orchestrator.const import (
    CONF_EV_RESERVATION_UNPLUGGED_SOC_MAX_AGE_MINUTES as KEY,
)
from custom_components.home_energy_orchestrator.const import (
    CONF_EV_TELEMETRY_MAX_AGE_SECONDS as FAST_KEY,
)
from custom_components.home_energy_orchestrator.const import (
    DEFAULT_EV_RESERVATION_UNPLUGGED_SOC_MAX_AGE_MINUTES as DEFAULT,
)
from custom_components.home_energy_orchestrator.const import DOMAIN

from .test_config_flow import _open_reconfigure_page, _schema_values
from .test_ev_backfill_controls import _setup
from .test_reconfigure_concurrency import _apply
from .test_setup import ENTRY_DATA

ENTITY = "number.home_energy_ev_reservation_unplugged_soc_max_age_minutes"
BEHAVIOR_ENTITY = "select.home_energy_ev_reservation_unavailable_behavior"
INVALID = (None, True, False, -1, 0.5, 90.1, 1441, "bad", float("nan"), float("inf"))
OTHER_AGES = {SLEEPING_KEY: 24.0, FAST_KEY: 90.0}


def test_missing_value_defaults_to_90_minutes_without_writing_to_entry():
    data = {**ENTRY_DATA, **OTHER_AGES}
    config = RuntimeConfiguration.from_mapping(data)
    numbers = config.ev_numbers
    assert config.ev_preferences.reservation_unavailable_behavior == "timeout"
    assert numbers.value(KEY, -1) == DEFAULT == 90.0
    assert KEY not in data
    for key, age in OTHER_AGES.items():
        assert numbers.value(key, -1) == age


@pytest.mark.parametrize("value", (0.0, 1.0, 90.0, 1439.0, 1440.0))
def test_whole_minutes_share_setup_and_runtime_values(value):
    flow = ConfigFlow()
    data = flow._apply_defaults({"name": "EV data timeout", **ENTRY_DATA, KEY: value})
    assert valid_ev_reservation_unplugged_soc_max_age_minutes(value)
    assert flow._validate_input(data) == {}
    assert RuntimeConfiguration.from_mapping(data).ev_numbers.value(KEY, -1) == value


@pytest.mark.parametrize("value", INVALID)
def test_invalid_input_is_rejected_and_saved_value_disables_extension(value):
    flow = ConfigFlow()
    data = flow._apply_defaults({**ENTRY_DATA, **OTHER_AGES, KEY: value})
    assert not valid_ev_reservation_unplugged_soc_max_age_minutes(value)
    assert flow._validate_input(data) == {KEY: "invalid_site_limits"}
    numbers = RuntimeConfiguration.from_mapping(data).ev_numbers
    assert numbers.value(KEY, -1) == 0.0
    for key, age in OTHER_AGES.items():
        assert numbers.value(key, -1) == age


async def test_setup_can_save_zero_without_enabling_dynamic_or_automatic_control(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER},
        data={"name": "EV data timeout", **ENTRY_DATA, KEY: 0.0},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][KEY] == 0.0
    assert result["data"]["ev_reservation_mode"] == "fixed"
    assert result["data"]["ev_automatic_control_enabled"] is False


async def test_reconfigure_displays_default_and_saves_only_after_review(hass):
    entry = await _setup(hass, data={"configure_ev": True})
    before = dict(entry.data)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    flow = await _open_reconfigure_page(hass, flow, "ev_policies")
    values = _schema_values(flow["data_schema"])
    assert values[KEY] == DEFAULT
    assert values[BEHAVIOR] == "timeout"
    for invalid in (True, 90.5):
        with pytest.raises(InvalidData):
            await hass.config_entries.flow.async_configure(
                flow["flow_id"], user_input={**values, KEY: invalid},
            )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], user_input={**values, KEY: 1440.0, BEHAVIOR: "last_known"},
    )
    assert dict(entry.data) == before
    assert (await _apply(hass, flow))["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[KEY] == 1440.0
    assert float(hass.states.get(ENTITY).state) == 1440.0
    assert entry.data[BEHAVIOR] == "last_known"
    assert hass.states.get(BEHAVIOR_ENTITY).state == "last_known"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_native_control_validates_and_persists_zero_through_reload(hass, monkeypatch):
    entry = await _setup(
        hass, data={**OTHER_AGES, "ev_reservation_mode": "dynamic"},
        options={KEY: 45.0, "reserve_kwh": 4.0},
    )
    owner = entry.runtime_data
    before = dict(entry.data), dict(entry.options)
    number = hass.states.get(ENTITY)
    assert float(number.state) == 45.0
    assert number.attributes["unit_of_measurement"] == "min"
    assert number.attributes["min"] == 0.0 and number.attributes["max"] == 1440.0
    assert number.attributes["step"] == 1.0 and number.attributes["mode"] == "box"
    native = next(
        platform.entities[ENTITY]
        for platform in entity_platform.async_get_platforms(hass, DOMAIN)
        if ENTITY in platform.entities
    )
    for invalid in INVALID:
        with pytest.raises(HomeAssistantError):
            await native.async_set_native_value(invalid)
    assert (dict(entry.data), dict(entry.options)) == before

    refresh = AsyncMock()
    ev_reconcile = AsyncMock()
    export_reconcile = AsyncMock()
    monkeypatch.setattr(owner, "async_request_refresh", refresh)
    monkeypatch.setattr(owner.ev_controller, "async_reconcile", ev_reconcile)
    monkeypatch.setattr(owner.active_controller, "async_reconcile", export_reconcile)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": ENTITY, "value": 0.0}, blocking=True,
    )
    refresh.assert_awaited_once()
    ev_reconcile.assert_awaited_once()
    export_reconcile.assert_awaited_once()
    assert entry.data == {**before[0], KEY: 0.0}
    assert entry.options == {"reserve_kwh": 4.0}
    for key, age in OTHER_AGES.items():
        assert owner.runtime_config.ev_numbers.value(key, -1) == age
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert float(hass.states.get(ENTITY).state) == 0.0
    assert await hass.config_entries.async_unload(entry.entry_id)



@pytest.mark.parametrize("value", [None, "", True, "always_export", "Last Known"])
def test_invalid_behavior_is_rejected_in_setup_and_runtime_keeps_timeout(value):
    flow = ConfigFlow()
    data = flow._apply_defaults({**ENTRY_DATA, BEHAVIOR: value, KEY: 30.0})
    assert flow._validate_input(data) == {BEHAVIOR: "invalid_ev_reservation_behavior"}
    config = RuntimeConfiguration.from_mapping(data)
    assert config.ev_preferences.reservation_unavailable_behavior == "timeout"
    assert config.ev_numbers.value(KEY, -1) == 30.0


async def test_native_behavior_select_reconciles_and_persists_only_its_setting(hass, monkeypatch):
    entry = await _setup(
        hass,
        data={**OTHER_AGES, KEY: 45.0, "ev_reservation_mode": "dynamic"},
        options={BEHAVIOR: "timeout", "reserve_kwh": 4.0},
    )
    owner = entry.runtime_data
    before = dict(entry.data), dict(entry.options)
    native = next(
        platform.entities[BEHAVIOR_ENTITY]
        for platform in entity_platform.async_get_platforms(hass, DOMAIN)
        if BEHAVIOR_ENTITY in platform.entities
    )
    assert hass.states.get(BEHAVIOR_ENTITY).attributes["options"] == ["last_known", "timeout"]
    assert hass.states.get(BEHAVIOR_ENTITY).state == "timeout"
    with pytest.raises(HomeAssistantError):
        await native.async_select_option("always_export")
    assert (dict(entry.data), dict(entry.options)) == before

    refresh = AsyncMock()
    ev_reconcile = AsyncMock()
    export_reconcile = AsyncMock()
    monkeypatch.setattr(owner, "async_request_refresh", refresh)
    monkeypatch.setattr(owner.ev_controller, "async_reconcile", ev_reconcile)
    monkeypatch.setattr(owner.active_controller, "async_reconcile", export_reconcile)
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": BEHAVIOR_ENTITY, "option": "last_known"},
        blocking=True,
    )
    refresh.assert_awaited_once()
    ev_reconcile.assert_awaited_once()
    export_reconcile.assert_awaited_once()
    assert entry.data == {**before[0], BEHAVIOR: "last_known"}
    assert entry.options == {"reserve_kwh": 4.0}
    assert owner.runtime_config.ev_numbers.value(KEY, -1) == 45.0
    assert owner.runtime_config.ev_preferences.reservation_mode == "dynamic"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(BEHAVIOR_ENTITY).state == "last_known"
    assert await hass.config_entries.async_unload(entry.entry_id)
