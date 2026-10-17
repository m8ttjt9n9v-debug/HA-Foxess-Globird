"""Real native HA helpers/automation tests; the HEO switch is the only writer."""

import json
from datetime import UTC, datetime

import pytest
from homeassistant.components.automation.config import async_validate_config_item
from homeassistant.core import Context, ServiceRegistry, State
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed, mock_restore_cache

from scripts.trip_charge_wrapper import (
    ARMED,
    CAPACITY,
    CONTROL,
    EFFICIENCY,
    GENERATION,
    LOCK,
    MARGIN,
    NATIVE_STATUS,
    OVERRIDE,
    OWNED,
    PLAN,
    POWER,
    READY,
    RESUME,
    SOC,
    STARTED_TARGET,
    STATUS,
    TARGET,
    TICKET,
    TIMEOUT,
    build_package,
)

NOW = datetime(2026, 10, 11, 8, tzinfo=UTC)


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_legacy_trip_replans_when_shared_capacity_is_corrected(hass):
    _, calls = await _setup(hass, soc=20, capacity=120, power=3.6)
    await hass.services.async_call(
        "input_select", "select_option", {"entity_id": TARGET, "option": "50%"}, blocking=True
    )
    await hass.async_block_till_done()
    before = Template(
        "{{ states('sensor.heo_trip_charge_plan') | from_json }}", hass
    ).async_render()
    hass.states.async_set(CAPACITY, "80", {"unit_of_measurement": "kWh"})
    await hass.async_block_till_done()
    after = Template("{{ states('sensor.heo_trip_charge_plan') | from_json }}", hass).async_render()
    assert before["hours"] == pytest.approx(36 / 3.24, abs=1e-6)
    assert after["hours"] == pytest.approx(24 / 3.24, abs=1e-6)
    assert after["start"] > before["start"] + 3 * 3600
    assert after["target"] == 50
    assert calls == []


@pytest.fixture(autouse=True)
async def _detach_test_automation(hass):
    yield
    if hass.services.has_service("automation", "turn_off"):
        ids = [state.entity_id for state in hass.states.async_all("automation")]
        if ids:
            await hass.services.async_call(
                "automation",
                "turn_off",
                {
                    "entity_id": ids,
                    "stop_actions": True,
                },
                blocking=True,
            )
            await hass.async_block_till_done()


async def _setup(
    hass,
    *,
    soc=80,
    capacity=60,
    power=3.6,
    restore_states=None,
    override_state="off",
    native_attributes=None,
    location_state="home",
    cable_state="on",
):
    await hass.config.async_set_time_zone("Australia/Sydney")
    package = build_package(
        location_entity="device_tracker.test_ev", cable_entity="binary_sensor.test_cable"
    )
    if restore_states:
        mock_restore_cache(hass, restore_states)
    for domain in ("input_datetime", "input_boolean", "input_number", "input_select", "input_text"):
        assert await async_setup_component(hass, domain, {domain: package[domain]})
    for entity, value, unit in ((SOC, soc, "%"), (CAPACITY, capacity, "kWh"), (POWER, power, "kW")):
        hass.states.async_set(entity, str(value), {"unit_of_measurement": unit})
    for entity, value in (
        (CONTROL, "on"),
        (LOCK, "off"),
        (OVERRIDE, override_state),
        ("device_tracker.test_ev", location_state),
        ("binary_sensor.test_cable", cable_state),
    ):
        hass.states.async_set(entity, value)
    hass.states.async_set(
        "sensor.home_energy_ev_control_status", "feedback_confirmed", {"gate": "ready"}
    )
    hass.states.async_set(
        NATIVE_STATUS, "legacy_conflict", native_attributes or {"full_generation": 0}
    )
    if not restore_states:
        for entity, value in ((EFFICIENCY, 90), (TIMEOUT, 12), (MARGIN, 0)):
            await hass.services.async_call(
                "input_number", "set_value", {"entity_id": entity, "value": value}, blocking=True
            )
        await hass.services.async_call(
            "input_datetime",
            "set_datetime",
            {
                "entity_id": READY,
                "datetime": "2026-10-12 07:00:00",
            },
            blocking=True,
        )
    assert await async_setup_component(hass, "template", {"template": package["template"]})
    await hass.async_block_till_done()
    calls = []

    async def override(call):
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            assert entity == [OVERRIDE]
        else:
            assert entity == OVERRIDE
        if call.service == "turn_on":
            assert hass.states.get(OWNED).state == "on"
            assert hass.states.get(TICKET).state == hass.states.get(READY).state
            assert float(hass.states.get(STARTED_TARGET).state) == float(
                hass.states.get(TARGET).state.removesuffix("%")
            )
        calls.append(call.service)
        native = hass.states.get(NATIVE_STATUS)
        attributes = dict(native.attributes)
        attributes["full_generation"] = attributes.get("full_generation", 0) + 1
        hass.states.async_set(NATIVE_STATUS, "legacy_conflict", attributes)
        hass.states.async_set(
            OVERRIDE, "on" if call.service == "turn_on" else "off", context=call.context
        )

    hass.services.async_register("switch", "turn_on", override)
    hass.services.async_register("switch", "turn_off", override)
    assert await async_setup_component(hass, "automation", {"automation": package["automation"]})
    await hass.async_block_till_done()
    return package, calls


async def _arm(hass):
    await hass.services.async_call("input_boolean", "turn_on", {"entity_id": ARMED}, blocking=True)
    await hass.async_block_till_done()


async def _target(hass, target):
    await hass.services.async_call(
        "input_select",
        "select_option",
        {"entity_id": TARGET, "option": f"{target}%"},
        blocking=True,
    )
    await hass.async_block_till_done()


async def _tick(hass, freezer, at):
    freezer.move_to(at)
    async_fire_time_changed(hass, at)
    await hass.async_block_till_done()


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_dynamic_plan_reuses_soc_capacity_and_configured_power(hass):
    package, calls = await _setup(hass)
    assert (
        await async_validate_config_item(hass, "automation", package["automation"][0]) is not None
    )
    state = hass.states.get(PLAN)
    assert len(state.state) < 255
    plan = Template("{{ states('sensor.heo_trip_charge_plan') | from_json }}", hass).async_render()
    assert plan["hours"] == pytest.approx(60 * 0.2 / 0.9 / 3.6, abs=1e-6)
    assert plan["due"] == datetime(2026, 10, 11, 20, tzinfo=UTC).timestamp()
    await _arm(hass)
    assert calls == []
    first_start = plan["start"]
    hass.states.async_set(SOC, "90", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    plan = Template("{{ states('sensor.heo_trip_charge_plan') | from_json }}", hass).async_render()
    assert plan["start"] > first_start
    assert calls == []


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_due_ticket_starts_override_once_and_preserves_existing_control(hass, freezer):
    _, calls = await _setup(hass)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 18, tzinfo=UTC))
    assert calls == ["turn_on"]
    assert hass.states.get(STATUS).state == "Override active"
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 19, tzinfo=UTC))
    assert calls == ["turn_on"]
    assert hass.states.get(CONTROL).state == "on"
    assert hass.states.get(LOCK).state == "off"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_completion_consumes_one_off_and_returns_override_to_normal(hass, freezer):
    _, calls = await _setup(hass)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 18, tzinfo=UTC))
    hass.states.async_set(SOC, "100", {"unit_of_measurement": "%"})
    await _tick(hass, freezer, datetime(2026, 10, 11, 20, tzinfo=UTC))
    assert calls == ["turn_on", "turn_off"]
    assert hass.states.get(ARMED).state == hass.states.get(OWNED).state == "off"
    assert hass.states.get(STATUS).state == "Completed"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
@pytest.mark.parametrize(
    "entity,value",
    [
        (SOC, "unknown"),
        (CAPACITY, "unavailable"),
        (POWER, "0"),
        (EFFICIENCY, "0"),
        (TARGET, "105%"),
        (TARGET, "80.5%"),
        (TARGET, "80"),
        (TIMEOUT, "1"),
    ],
)
async def test_missing_or_unsupported_plan_inputs_do_not_start(hass, freezer, entity, value):
    _, calls = await _setup(hass)
    # Fault injection is state-only; never a physical service.
    state = hass.states.get(entity)
    hass.states.async_set(entity, value, dict(state.attributes))
    await hass.async_block_till_done()
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 19, 0, tzinfo=UTC))
    assert calls == []
    assert hass.states.get(STATUS).state == "Waiting for data"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
@pytest.mark.parametrize(
    "entity,value",
    [
        (CONTROL, "off"),
        (LOCK, "on"),
        ("device_tracker.test_ev", "not_home"),
        ("binary_sensor.test_cable", "off"),
    ],
)
async def test_disabled_control_away_or_disconnected_never_starts(hass, freezer, entity, value):
    _, calls = await _setup(hass)
    hass.states.async_set(entity, value)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 19, tzinfo=UTC))
    assert calls == []


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_expired_unstarted_schedule_does_not_start_on_restart_tick(hass, freezer):
    _, calls = await _setup(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 20, 1, tzinfo=UTC))
    await _arm(hass)
    assert calls == []
    assert hass.states.get(ARMED).state == "off"
    assert hass.states.get(STATUS).state == "Expired"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_manual_override_is_never_adopted_or_stopped(hass):
    _, calls = await _setup(hass)
    hass.states.async_set(OVERRIDE, "on", context=Context(user_id="test_user"))
    await _arm(hass)
    assert calls == []
    assert hass.states.get(STATUS).state == "External override"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_cancelling_owned_trip_releases_only_its_override(hass, freezer):
    _, calls = await _setup(hass)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 18, tzinfo=UTC))
    await hass.services.async_call("input_boolean", "turn_off", {"entity_id": ARMED}, blocking=True)
    await hass.async_block_till_done()
    assert calls == ["turn_on", "turn_off"]
    assert hass.states.get(STATUS).state == "Cancelled"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_changed_departure_cannot_use_stale_start_sensor(hass, freezer):
    _, calls = await _setup(hass)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 17, tzinfo=UTC))
    await hass.services.async_call(
        "input_datetime",
        "set_datetime",
        {
            "entity_id": READY,
            "datetime": "2026-10-13 07:00:00",
        },
        blocking=True,
    )
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 18, tzinfo=UTC))
    assert calls == []


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_early_override_cancellation_does_not_fight_human_or_timeout(hass, freezer):
    _, calls = await _setup(hass)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 18, tzinfo=UTC))
    hass.states.async_set(OVERRIDE, "off")
    await hass.async_block_till_done()
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 19, tzinfo=UTC))
    assert calls == ["turn_on"]
    assert hass.states.get(ARMED).state == "off"
    assert hass.states.get(STATUS).state == "Interrupted"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_gui_template_helpers_accept_the_same_checked_templates(hass):
    package, _ = await _setup(hass)
    for sensor in package["template"][0]["sensor"]:
        flow = await hass.config_entries.flow.async_init("template", context={"source": "user"})
        flow = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"next_step_id": "sensor"}
        )
        data = {
            key: sensor[key]
            for key in ("name", "state", "device_class", "unit_of_measurement")
            if key in sensor
        }
        data["name"] += " GUI Test"
        if "availability" in sensor:
            data["additional_options"] = {"availability": sensor["availability"]}
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], data)
        assert flow["type"] == "create_entry", flow.get("errors")
    await hass.async_block_till_done()


@pytest.mark.freeze_time(NOW, real_asyncio=True)
@pytest.mark.parametrize("interruption", ["cancel", "source", "target", "external_override"])
async def test_last_awaited_start_boundary_rechecks_current_intent_and_inputs(
    hass, freezer, monkeypatch, interruption
):
    _, calls = await _setup(hass)
    original = ServiceRegistry.async_call

    async def inject(registry, domain, service, service_data=None, *args, **kwargs):
        result = await original(registry, domain, service, service_data, *args, **kwargs)
        data = {**(service_data or {}), **(kwargs.get("target") or {})}
        entities = data.get("entity_id")
        if domain == "input_boolean" and service == "turn_on" and entities in (OWNED, [OWNED]):
            if interruption == "cancel":
                await original(
                    registry, "input_boolean", "turn_off", {"entity_id": ARMED}, blocking=True
                )
            elif interruption == "source":
                hass.states.async_set(CAPACITY, "unavailable")
            elif interruption == "target":
                await original(
                    registry,
                    "input_select",
                    "select_option",
                    {"entity_id": TARGET, "option": "90%"},
                    blocking=True,
                )
            else:
                hass.states.async_set(OVERRIDE, "on")
        return result

    monkeypatch.setattr(ServiceRegistry, "async_call", inject)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 18, tzinfo=UTC))
    assert calls == []
    assert hass.states.get(OWNED).state == "off"
    if interruption == "external_override":
        assert hass.states.get(OVERRIDE).state == "on"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_already_full_before_departure_keeps_schedule_for_possible_later_drop(hass):
    _, calls = await _setup(hass, soc=100)
    await _arm(hass)
    assert calls == []
    assert hass.states.get(ARMED).state == "on"
    assert hass.states.get(STATUS).state == "Already at target"
    hass.states.async_set(SOC, "99", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert hass.states.get(ARMED).state == "on"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
@pytest.mark.parametrize("target", [1, 80, 90, 100])
async def test_selected_target_controls_deficit_and_prompt_owned_completion(hass, freezer, target):
    _, calls = await _setup(hass, soc=target - 1)
    await _target(hass, target)
    plan = Template("{{ states('sensor.heo_trip_charge_plan') | from_json }}", hass).async_render()
    assert plan["v"] == 2
    assert plan["target"] == target
    assert plan["hours"] == pytest.approx(0.6 / 0.9 / 3.6, abs=1e-6)
    assert len(hass.states.get(PLAN).state) < 255
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 19, 49, tzinfo=UTC))
    assert calls == ["turn_on"]
    # No minute tick: an SoC update itself must end the owned Full override.
    hass.states.async_set(SOC, str(target), {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert calls == ["turn_on", "turn_off"]
    assert hass.states.get(STATUS).state == "Completed"
    assert hass.states.get(ARMED).state == hass.states.get(OWNED).state == "off"
    await _tick(hass, freezer, datetime(2026, 10, 11, 19, 50, tzinfo=UTC))
    assert calls == ["turn_on", "turn_off"]
    assert hass.states.get(CONTROL).state == "on"
    assert hass.states.get(LOCK).state == "off"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_above_target_has_zero_deficit_and_never_starts_override(hass):
    _, calls = await _setup(hass, soc=90)
    await _target(hass, 80)
    plan = Template("{{ states('sensor.heo_trip_charge_plan') | from_json }}", hass).async_render()
    assert plan["hours"] == 0
    await _arm(hass)
    assert calls == []
    assert hass.states.get(STATUS).state == "Already at target"
    assert hass.states.get(ARMED).state == "on"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
@pytest.mark.parametrize("soc,capacity,power,target", [(83, 84.5, 3.45, 90), (55, 75, 11.04, 80)])
async def test_target_plan_uses_single_or_three_phase_heo_maximum(
    hass, soc, capacity, power, target
):
    _, calls = await _setup(hass, soc=soc, capacity=capacity, power=power)
    await _target(hass, target)
    plan = Template("{{ states('sensor.heo_trip_charge_plan') | from_json }}", hass).async_render()
    assert plan["kw"] == power
    assert plan["hours"] == pytest.approx((target - soc) * capacity / 100 / 0.9 / power, abs=1e-6)
    assert calls == []


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_waiting_target_edit_replans_without_using_previous_start(hass, freezer):
    _, calls = await _setup(hass)
    await _arm(hass)
    await _target(hass, 90)
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 18, tzinfo=UTC))
    assert calls == []
    await _tick(hass, freezer, datetime(2026, 10, 11, 18, 10, tzinfo=UTC))
    assert calls == ["turn_on"]
    assert float(hass.states.get(STARTED_TARGET).state) == 90


@pytest.mark.freeze_time(NOW, real_asyncio=True)
@pytest.mark.parametrize("new_target", [80, 100])
async def test_started_target_edit_cancels_once_and_does_not_extend_session(
    hass, freezer, new_target
):
    _, calls = await _setup(hass)
    await _target(hass, 90)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 18, 10, tzinfo=UTC))
    assert calls == ["turn_on"]
    await _target(hass, new_target)
    assert calls == ["turn_on", "turn_off"]
    assert hass.states.get(STATUS).state == "Cancelled"
    assert hass.states.get(ARMED).state == "off"
    await _tick(hass, freezer, datetime(2026, 10, 11, 19, tzinfo=UTC))
    assert calls == ["turn_on", "turn_off"]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
@pytest.mark.parametrize("bad_soc", ["unknown", "unavailable", "-1", "101"])
async def test_lost_or_invalid_soc_interrupts_owned_charge_without_reassertion(
    hass, freezer, bad_soc
):
    _, calls = await _setup(hass)
    await _target(hass, 90)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 18, 10, tzinfo=UTC))
    hass.states.async_set(SOC, bad_soc, {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert calls == ["turn_on", "turn_off"]
    assert hass.states.get(STATUS).state == "Interrupted"
    hass.states.async_set(SOC, "80", {"unit_of_measurement": "%"})
    await _tick(hass, freezer, datetime(2026, 10, 11, 18, 11, tzinfo=UTC))
    assert calls == ["turn_on", "turn_off"]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_confirmed_full_off_edge_does_not_stop_a_new_manual_full_request(hass, freezer):
    _, calls = await _setup(hass)
    await _target(hass, 90)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 18, 10, tzinfo=UTC))
    # Both arrive before queued scripts execute: current state alone hides OFF.
    hass.states.async_set(OVERRIDE, "off")
    hass.states.async_set(OVERRIDE, "on", context=Context(user_id="test_user"))
    await hass.async_block_till_done()
    assert hass.states.get(OWNED).state == "off"
    assert hass.states.get(STATUS).state == "Interrupted"
    hass.states.async_set(SOC, "90", {"unit_of_measurement": "%"})
    await _tick(hass, freezer, datetime(2026, 10, 11, 18, 11, tzinfo=UTC))
    assert calls == ["turn_on"]
    assert hass.states.get(OVERRIDE).state == "on"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_completion_queued_before_manual_off_on_does_not_stop_manual_full(
    hass, freezer, monkeypatch
):
    _, calls = await _setup(hass)
    await _target(hass, 90)
    original = ServiceRegistry.async_call

    async def inject(registry, domain, service, service_data=None, *args, **kwargs):
        result = await original(registry, domain, service, service_data, *args, **kwargs)
        if domain == "switch" and service == "turn_on":
            # The dispatcher is still awaiting its ON service. Queue completion
            # first, then replace its Full request with a user-owned ON cycle.
            hass.states.async_set(SOC, "90", {"unit_of_measurement": "%"})
            hass.states.async_set(OVERRIDE, "off", context=Context(user_id="test_user"))
            hass.states.async_set(OVERRIDE, "on", context=Context(user_id="test_user"))
        return result

    monkeypatch.setattr(ServiceRegistry, "async_call", inject)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 18, 10, tzinfo=UTC))
    assert calls == ["turn_on"]
    assert hass.states.get(OVERRIDE).state == "on"
    assert hass.states.get(OWNED).state == hass.states.get(ARMED).state == "off"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_old_off_edge_during_awaited_start_cannot_orphan_new_trip(hass, freezer, monkeypatch):
    _, calls = await _setup(hass)
    await _target(hass, 90)
    original = ServiceRegistry.async_call

    async def inject(registry, domain, service, service_data=None, *args, **kwargs):
        result = await original(registry, domain, service, service_data, *args, **kwargs)
        data = {**(service_data or {}), **(kwargs.get("target") or {})}
        if (
            domain == "input_boolean"
            and service == "turn_on"
            and data.get("entity_id") in (OWNED, [OWNED])
        ):
            hass.states.async_set(OVERRIDE, "on", context=Context(user_id="test_user"))
            hass.states.async_set(OVERRIDE, "off", context=Context(user_id="test_user"))
        return result

    monkeypatch.setattr(ServiceRegistry, "async_call", inject)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 18, 10, tzinfo=UTC))
    assert calls == ["turn_on"]
    assert hass.states.get(OWNED).state == "on"
    hass.states.async_set(SOC, "90", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert calls == ["turn_on", "turn_off"]
    assert hass.states.get(STATUS).state == "Completed"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
@pytest.mark.parametrize("order", ["soc_first", "override_first"])
async def test_native_full_completion_off_does_not_restart(hass, freezer, order):
    _, calls = await _setup(hass)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 18, tzinfo=UTC))
    # If native Full ends before read-model SoC catches up, interruption is
    # conservative: never invent completion from an as-yet-unseen reading.
    if order == "override_first":
        hass.states.async_set(OVERRIDE, "off")
        hass.states.async_set(SOC, "100", {"unit_of_measurement": "%"})
    else:
        hass.states.async_set(SOC, "100", {"unit_of_measurement": "%"})
        hass.states.async_set(OVERRIDE, "off")
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == ("Completed" if order == "soc_first" else "Interrupted")
    assert hass.states.get(ARMED).state == hass.states.get(OWNED).state == "off"
    assert calls == (["turn_on", "turn_off"] if order == "soc_first" else ["turn_on"])


def _restored_trip(*, owned=False, target=90):
    return [
        State(READY, "2026-10-12 07:00:00", {"has_date": True, "has_time": True}),
        State(TICKET, "2026-10-12 07:00:00", {"has_date": True, "has_time": True}),
        State(ARMED, "on"),
        State(OWNED, "on" if owned else "off"),
        State(TARGET, f"{target}%"),
        State(STARTED_TARGET, str(target if owned else 0)),
        State(EFFICIENCY, "90"),
        State(TIMEOUT, "12"),
        State(MARGIN, "0"),
        State(GENERATION, "on:previous-process-timestamp" if owned else ""),
    ]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_actual_ha_startup_catches_up_restored_unstarted_selected_target(hass, freezer):
    _, calls = await _setup(hass, restore_states=_restored_trip())
    assert hass.states.get(TARGET).state == "90%"
    assert hass.states.get(ARMED).state == "on"
    assert calls == []
    freezer.move_to(datetime(2026, 10, 11, 18, 10, tzinfo=UTC))
    await hass.async_start()
    await hass.async_block_till_done()
    assert calls == ["turn_on"]
    assert float(hass.states.get(STARTED_TARGET).state) == 90


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_restored_owned_target_survives_unavailable_full_and_completes_on_recovery(hass):
    _, calls = await _setup(
        hass, soc=90, restore_states=_restored_trip(owned=True), override_state="unavailable"
    )
    await hass.async_start()
    await hass.async_block_till_done()
    assert calls == []
    assert hass.states.get(OWNED).state == "on"
    assert hass.states.get(ARMED).state == "on"
    assert hass.states.get(STATUS).state == "Waiting for data"
    hass.states.async_set(OVERRIDE, "on")
    await hass.async_block_till_done()
    assert calls == ["turn_off"]
    assert hass.states.get(STATUS).state == "Completed"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_startup_recovery_never_adopts_a_fresh_manual_full_request(hass):
    _, calls = await _setup(
        hass, soc=90, restore_states=_restored_trip(owned=True), override_state="unavailable"
    )
    await hass.async_start()
    await hass.async_block_till_done()
    hass.states.async_set(OVERRIDE, "on", context=Context(user_id="test_user"))
    await hass.async_block_till_done()
    assert calls == []
    assert hass.states.get(OWNED).state == "off"
    assert hass.states.get(OVERRIDE).state == "on"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_runtime_full_unavailability_preserves_target_stop_on_restoration(hass, freezer):
    _, calls = await _setup(hass)
    await _target(hass, 90)
    await _arm(hass)
    await _tick(hass, freezer, datetime(2026, 10, 11, 18, 10, tzinfo=UTC))
    hass.states.async_set(OVERRIDE, "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(OWNED).state == "on"
    assert hass.states.get(STATUS).state == "Waiting for data"
    hass.states.async_set(OVERRIDE, "on")
    await hass.async_block_till_done()
    assert hass.states.get(OWNED).state == "on"
    hass.states.async_set(SOC, "90", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert calls == ["turn_on", "turn_off"]
    assert hass.states.get(STATUS).state == "Completed"


def _resume_record(hass):
    return Template("{{ states('" + RESUME + "') | from_json({}) }}", hass).async_render()


async def _start_day_trip(hass, freezer):
    """Synthetic long trip spanning a mid-day free window, not a site fixture."""
    package, calls = await _setup(hass, soc=20, capacity=75, power=3.6)
    await hass.services.async_call(
        "input_number", "set_value", {"entity_id": TIMEOUT, "value": 16}, blocking=True
    )
    await hass.services.async_call(
        "input_datetime",
        "set_datetime",
        {"entity_id": READY, "datetime": "2026-10-12 17:00:00"},
        blocking=True,
    )
    await _target(hass, 80)
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 10, tzinfo=UTC))
    await _arm(hass)
    assert calls == ["turn_on"]
    return package, calls


async def _native_full_stop(hass, *, reason="disconnected", disconnect=True, generation=None):
    """Publish the HEO stop receipt before its observable Full OFF edge."""
    if disconnect:
        hass.states.async_set("binary_sensor.test_cable", "off")
        hass.states.async_set("device_tracker.test_ev", "not_home")
    attributes = dict(hass.states.get(NATIVE_STATUS).attributes)
    previous = attributes["full_generation"]
    attributes.update(
        {
            "full_generation": previous + 1,
            "full_stop_reason": reason,
            "full_stop_generation": previous if generation is None else generation,
            "full_stop_at": datetime.now(UTC).isoformat(),
        }
    )
    hass.states.async_set(NATIVE_STATUS, "legacy_conflict", attributes)
    hass.states.async_set(OVERRIDE, "off")
    await hass.async_block_till_done()


async def _reconnect(hass):
    hass.states.async_set("device_tracker.test_ev", "home")
    hass.states.async_set("binary_sensor.test_cable", "on")
    await hass.async_block_till_done()


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_owned_trip_pauses_then_resumes_through_free_end_with_original_timeout(hass, freezer):
    _, calls = await _start_day_trip(hass, freezer)
    original = _resume_record(hass)
    assert original["generation"] == 1
    await _tick(hass, freezer, datetime(2026, 10, 11, 23, 20, tzinfo=UTC))
    await _native_full_stop(hass)
    assert hass.states.get(ARMED).state == "on"
    assert hass.states.get(OWNED).state == "off"
    assert hass.states.get(STATUS).state == "Paused — car disconnected"
    assert calls == ["turn_on"]  # No Full/current/stop request while the car is away.
    hass.states.async_set(SOC, "70", {"unit_of_measurement": "%"})
    await _tick(hass, freezer, datetime(2026, 10, 12, 1, 30, tzinfo=UTC))
    await _reconnect(hass)
    assert calls == ["turn_on", "turn_on"]
    resumed = _resume_record(hass)
    assert resumed["first"] == original["first"]
    assert resumed["expires"] == original["expires"]
    assert resumed["generation"] == 3
    assert resumed["paused"] is False
    # The normal latest start is now later than reconnect; outstanding intent resumes anyway.
    plan = Template("{{ states('" + PLAN + "') | from_json }}", hass).async_render()
    assert plan["start"] > datetime(2026, 10, 12, 1, 30, tzinfo=UTC).timestamp()
    await _tick(hass, freezer, datetime(2026, 10, 12, 3, 0, tzinfo=UTC))
    assert hass.states.get(OVERRIDE).state == "on"
    assert hass.states.get(OWNED).state == "on"
    assert calls == ["turn_on", "turn_on"]
    # Repeated disconnection cannot buy a new sixteen-hour timeout.
    await _native_full_stop(hass)
    await _reconnect(hass)
    assert _resume_record(hass)["expires"] == original["expires"]
    assert calls == ["turn_on", "turn_on", "turn_on"]
    await _tick(hass, freezer, datetime.fromtimestamp(original["expires"], UTC))
    assert calls[-1] == "turn_off"
    assert hass.states.get(ARMED).state == "off"
    assert hass.states.get(STATUS).state == "Expired"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
@pytest.mark.parametrize("reason", ["timeout", "operator", "completed", "invalid_data", None])
async def test_only_generation_bound_disconnect_receipt_can_pause(hass, freezer, reason):
    _, calls = await _start_day_trip(hass, freezer)
    await _native_full_stop(hass, reason=reason)
    assert hass.states.get(ARMED).state == "off"
    assert hass.states.get(STATUS).state == "Interrupted"
    await _reconnect(hass)
    assert calls == ["turn_on"]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_wrong_generation_disconnect_does_not_authorize_resume(hass, freezer):
    _, calls = await _start_day_trip(hass, freezer)
    await _native_full_stop(hass, generation=999)
    await _reconnect(hass)
    assert hass.states.get(ARMED).state == "off"
    assert calls == ["turn_on"]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_cancel_while_paused_is_terminal(hass, freezer):
    _, calls = await _start_day_trip(hass, freezer)
    await _native_full_stop(hass)
    await hass.services.async_call("input_boolean", "turn_off", {"entity_id": ARMED}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "Cancelled"
    assert hass.states.get(RESUME).state == ""
    await _reconnect(hass)
    assert calls == ["turn_on"]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_manual_full_on_and_off_while_away_supersedes_paused_ticket(hass, freezer):
    _, calls = await _start_day_trip(hass, freezer)
    await _native_full_stop(hass)
    attributes = dict(hass.states.get(NATIVE_STATUS).attributes)
    attributes["full_generation"] += 2
    attributes["full_stop_reason"] = "operator"
    hass.states.async_set(NATIVE_STATUS, "legacy_conflict", attributes)
    hass.states.async_set(OVERRIDE, "on", context=Context(user_id="human"))
    hass.states.async_set(OVERRIDE, "off", context=Context(user_id="human"))
    await hass.async_block_till_done()
    await _reconnect(hass)
    assert calls == ["turn_on"]
    assert hass.states.get(STATUS).state == "External override"
    assert hass.states.get(ARMED).state == "off"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_paused_trip_expires_at_departure_without_away_commands(hass, freezer):
    _, calls = await _start_day_trip(hass, freezer)
    await _native_full_stop(hass)
    await _tick(hass, freezer, datetime(2026, 10, 12, 6, 0, tzinfo=UTC))
    assert hass.states.get(STATUS).state == "Expired"
    await _reconnect(hass)
    assert calls == ["turn_on"]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
@pytest.mark.parametrize("edit", [TARGET, READY])
async def test_paused_target_or_departure_edit_cancels_original_ticket(hass, freezer, edit):
    _, calls = await _start_day_trip(hass, freezer)
    await _native_full_stop(hass)
    if edit == TARGET:
        await _target(hass, 90)
    else:
        await hass.services.async_call(
            "input_datetime",
            "set_datetime",
            {"entity_id": READY, "datetime": "2026-10-12 18:00:00"},
            blocking=True,
        )
        await hass.async_block_till_done()
    await _reconnect(hass)
    assert hass.states.get(STATUS).state == "Cancelled"
    assert calls == ["turn_on"]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_completed_trip_is_not_restarted_after_subsequent_driving(hass, freezer):
    _, calls = await _start_day_trip(hass, freezer)
    hass.states.async_set(SOC, "80", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "Completed"
    hass.states.async_set(SOC, "60", {"unit_of_measurement": "%"})
    await _reconnect(hass)
    await _tick(hass, freezer, datetime(2026, 10, 12, 3, 0, tzinfo=UTC))
    assert calls == ["turn_on", "turn_off"]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_actual_dispatcher_reload_preserves_paused_ticket(hass, freezer, monkeypatch):
    package, calls = await _start_day_trip(hass, freezer)
    await _native_full_stop(hass)
    original = _resume_record(hass)

    async def configuration(_hass):
        return {"automation": package["automation"]}

    monkeypatch.setattr("homeassistant.config.async_hass_config_yaml", configuration)
    await hass.services.async_call("automation", "reload", blocking=True)
    await hass.async_block_till_done()
    assert _resume_record(hass) == original
    await _reconnect(hass)
    assert calls == ["turn_on", "turn_on"]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_restored_paused_trip_waits_away_then_resumes_with_original_expiry(hass, freezer):
    first = datetime(2026, 10, 11, 16, 10, tzinfo=UTC).timestamp()
    record = {"v": 1, "first": first, "expires": first + 16 * 3600, "generation": 1, "paused": True}
    restored = [
        state
        for state in _restored_trip(target=80)
        if state.entity_id not in {READY, TICKET, STARTED_TARGET}
    ] + [
        State(READY, "2026-10-12 17:00:00", {"has_date": True, "has_time": True}),
        State(TICKET, "2026-10-12 17:00:00", {"has_date": True, "has_time": True}),
        State(STARTED_TARGET, "80"),
        State(STATUS, "Paused — car disconnected"),
        State(RESUME, json.dumps(record)),
    ]
    freezer.move_to(datetime(2026, 10, 11, 23, 20, tzinfo=UTC))
    _, calls = await _setup(
        hass,
        soc=70,
        restore_states=restored,
        location_state="not_home",
        cable_state="off",
        native_attributes={
            "full_generation": 2,
            "full_stop_generation": 1,
            "full_stop_reason": "disconnected",
        },
    )
    await hass.async_start()
    await hass.async_block_till_done()
    assert calls == []
    assert _resume_record(hass) == record
    await _tick(hass, freezer, datetime(2026, 10, 12, 1, 30, tzinfo=UTC))
    await _reconnect(hass)
    assert calls == ["turn_on"]
    assert _resume_record(hass)["expires"] == record["expires"]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
@pytest.mark.parametrize("bad_value", ["[]", "{}", "not json"])
async def test_corrupt_pause_record_never_creates_a_fresh_timeout(hass, freezer, bad_value):
    _, calls = await _start_day_trip(hass, freezer)
    await _native_full_stop(hass)
    await hass.services.async_call(
        "input_text", "set_value", {"entity_id": RESUME, "value": bad_value}, blocking=True
    )
    await _reconnect(hass)
    assert calls == ["turn_on"]
    assert hass.states.get(ARMED).state == "off"
    assert hass.states.get(STATUS).state == "Interrupted"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_unavailable_pause_record_cannot_turn_reconnect_into_a_new_trip(hass, freezer):
    _, calls = await _start_day_trip(hass, freezer)
    await _native_full_stop(hass)
    record = hass.states.get(RESUME).state
    hass.states.async_set(RESUME, "unavailable")
    await _reconnect(hass)
    assert calls == ["turn_on"]
    assert hass.states.get(STATUS).state == "Waiting for data"
    hass.states.async_set(RESUME, record)
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 11, tzinfo=UTC))
    assert calls == ["turn_on", "turn_on"]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_paused_trip_waits_for_restored_soc_before_reacquiring_full(
    hass,
    freezer,
):
    _, calls = await _start_day_trip(hass, freezer)
    await _native_full_stop(hass)
    assert hass.states.get(ARMED).state == "on"
    hass.states.async_set(SOC, "unavailable", {"unit_of_measurement": "%"})
    await _reconnect(hass)
    assert calls == ["turn_on"]
    assert hass.states.get(STATUS).state == "Waiting for data"
    hass.states.async_set(SOC, "60", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert calls == ["turn_on", "turn_on"]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_valid_existing_active_lease_keeps_longer_original_timeout(hass, freezer):
    _, calls = await _start_day_trip(hass, freezer)
    record = _resume_record(hass)
    # Restored active permission may predate the helper planner's 48-hour input cap.
    record["expires"] = record["first"] + 72 * 3600
    await hass.services.async_call(
        "input_text",
        "set_value",
        {"entity_id": RESUME, "value": json.dumps(record)},
        blocking=True,
    )
    await _tick(hass, freezer, datetime(2026, 10, 11, 16, 11, tzinfo=UTC))
    assert hass.states.get(OWNED).state == "on"
    assert hass.states.get(OVERRIDE).state == "on"
    await _native_full_stop(hass)
    await _reconnect(hass)
    assert _resume_record(hass)["expires"] == record["expires"]
    assert calls == ["turn_on", "turn_on"]


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_non_user_full_reassertion_cannot_be_adopted_or_stopped_at_old_target(hass, freezer):
    _, calls = await _start_day_trip(hass, freezer)
    original_changed = hass.states.get(OVERRIDE).last_changed
    # A different automation's ON does not change last_changed when Full is already ON.
    await hass.services.async_call("switch", "turn_on", {"entity_id": OVERRIDE}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(OVERRIDE).last_changed == original_changed
    assert hass.states.get(OVERRIDE).context.user_id is None
    assert hass.states.get(ARMED).state == hass.states.get(OWNED).state == "off"
    assert hass.states.get(STATUS).state == "Interrupted"
    hass.states.async_set(SOC, "80", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert calls == ["turn_on", "turn_on"]
    assert hass.states.get(OVERRIDE).state == "on"


@pytest.mark.freeze_time(NOW, real_asyncio=True)
async def test_active_checkpoint_waits_for_temporarily_unavailable_generation(hass, freezer):
    _, calls = await _start_day_trip(hass, freezer)
    attributes = dict(hass.states.get(NATIVE_STATUS).attributes)
    hass.states.async_set(NATIVE_STATUS, "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(OWNED).state == "on"
    assert hass.states.get(STATUS).state == "Waiting for data"
    hass.states.async_set(SOC, "80", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert calls == ["turn_on"]
    hass.states.async_set(NATIVE_STATUS, "legacy_conflict", attributes)
    await hass.async_block_till_done()
    assert calls == ["turn_on", "turn_off"]
    assert hass.states.get(STATUS).state == "Completed"
