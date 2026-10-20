"""Physical EV-to-export handoff at the existing inverter writer boundary."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.foxess_adapter import FoxessWriteBlocked
from custom_components.home_energy_orchestrator.planner.export_session import ExportSessionState
from tests.test_ev_backfill_timing import _charging, _fresh
from tests.test_ev_before_export_charging import _case, _foxess, _now
from tests.test_zerohero_active import _loaded_controller


@pytest.fixture(autouse=True)
def utc_clock(monkeypatch):
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.active.dt_util.now",
        lambda: datetime.now(UTC),
    )


def _rig(hass, freezer, **changes):
    now = _now(20, 55)
    freezer.move_to(now)
    coordinator, _ev = _case(hass, now, ev_protected_baseline_a=1, **changes)
    coordinator.snapshot = replace(coordinator.snapshot, ev_soc=30)
    hass.states.async_set("sensor.car_soc", "30", {"unit_of_measurement": "%"})
    controller = _loaded_controller(hass, coordinator)
    coordinator.active_controller = controller
    # Deliberately no EV runtime: physical source proof must stand on its own.
    del coordinator.ev_controller
    return now, coordinator, controller


def _services(hass, monkeypatch, *, after_discharge=None):
    calls = []

    async def apply(call):
        entity = call.data["entity_id"]
        if isinstance(entity, list):
            entity = entity[0]
        value = call.data.get("value", call.data.get("option"))
        calls.append((entity, value))
        state = hass.states.get(entity)
        hass.states.async_set(entity, str(value), dict(state.attributes), force_update=True)
        if entity == "number.foxess_discharge" and value > 0 and after_discharge:
            after_discharge()

    async def no_wait(_seconds):
        return None

    hass.services.async_register("number", "set_value", apply)
    hass.services.async_register("select", "select_option", apply)
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.foxess_adapter.asyncio.sleep", no_wait
    )
    return calls


@pytest.mark.parametrize("state", ["baseline", "off", "disconnected"])
async def test_fresh_physical_baseline_or_off_admits_export_without_ev_runtime(
    hass, freezer, monkeypatch, state
):
    _, _, controller = _rig(hass, freezer)
    calls = _services(hass, monkeypatch)
    _charging(hass, 1)
    if state == "off":
        hass.states.async_set("sensor.car_charging", "stopped")
        hass.states.async_set("switch.car_charge", "off")
        hass.states.async_set("sensor.car_actual_current", "0", {"unit_of_measurement": "A"})
        # A retained high request is harmless only with the charge switch off.
        hass.states.async_set("number.car_current", "16", {"unit_of_measurement": "A"})
    elif state == "disconnected":
        hass.states.async_set("binary_sensor.car_cable", "off")
        hass.states.async_set("sensor.car_charging", "disconnected")
        hass.states.async_set("switch.car_charge", "off")
        hass.states.async_set("number.car_current", "16", {"unit_of_measurement": "A"})
        hass.states.async_set("sensor.car_actual_current", "16", {"unit_of_measurement": "A"})

    await controller.async_reconcile()

    assert controller.export_session.phase == "starting"
    assert ("select.foxess_mode", "Force Discharge") in calls


@pytest.mark.parametrize(
    "failure",
    [
        "actual_high",
        "requested_high",
        "switch_off_actual_high",
        "missing_current",
        "missing_cable",
        "invalid_requested_unit",
        "invalid_step",
        "restored",
        "charging_but_switch_off",
        "zero_baseline_charging",
        "requested_below_min",
        "stale_requested",
        "stale_actual",
        "stale_switch",
        "stale_cable",
        "stale_state",
    ],
)
async def test_missing_stale_or_conflicting_handoff_cannot_start_export(
    hass, freezer, monkeypatch, failure
):
    now, coordinator, controller = _rig(hass, freezer)
    calls = _services(hass, monkeypatch)
    _charging(hass, 1)
    if failure.startswith("stale_"):
        field = {
            "stale_requested": "number.car_current",
            "stale_actual": "sensor.car_actual_current",
            "stale_switch": "switch.car_charge",
            "stale_cable": "binary_sensor.car_cable",
            "stale_state": "sensor.car_charging",
        }[failure]
        current_states = {
            entity: hass.states.get(entity)
            for entity in (
                "number.car_current",
                "sensor.car_actual_current",
                "switch.car_charge",
                "binary_sensor.car_cable",
                "sensor.car_charging",
            )
        }
        now += timedelta(seconds=91)
        freezer.move_to(now)
        for entity, previous in current_states.items():
            if entity != field:
                hass.states.async_set(
                    entity, previous.state, dict(previous.attributes), force_update=True
                )
        _fresh(coordinator, now, current_a=1)
    elif failure == "actual_high":
        hass.states.async_set("sensor.car_actual_current", "8", {"unit_of_measurement": "A"})
    elif failure == "requested_high":
        current = hass.states.get("number.car_current")
        hass.states.async_set("number.car_current", "8", dict(current.attributes))
    elif failure == "requested_below_min":
        current = hass.states.get("number.car_current")
        hass.states.async_set("number.car_current", "0", dict(current.attributes))
    elif failure == "switch_off_actual_high":
        hass.states.async_set("switch.car_charge", "off")
        hass.states.async_set("sensor.car_charging", "stopped")
        hass.states.async_set("sensor.car_actual_current", "8", {"unit_of_measurement": "A"})
    elif failure == "missing_current":
        hass.states.async_remove("sensor.car_actual_current")
    elif failure == "missing_cable":
        hass.states.async_remove("binary_sensor.car_cable")
    elif failure in {"invalid_requested_unit", "invalid_step", "restored"}:
        current = hass.states.get("number.car_current")
        attrs = dict(current.attributes)
        attrs.update(
            {
                "invalid_requested_unit": {"unit_of_measurement": "kW"},
                "invalid_step": {"step": 0},
                "restored": {"restored": True},
            }[failure]
        )
        hass.states.async_set("number.car_current", "1", attrs)
    elif failure == "charging_but_switch_off":
        hass.states.async_set("switch.car_charge", "off")
    elif failure == "zero_baseline_charging":
        coordinator.config["ev_protected_baseline_a"] = 0
        coordinator.runtime_config = RuntimeConfiguration.from_mapping(coordinator.config)

    await controller.async_reconcile()

    assert controller.export_session.phase == "idle"
    assert not controller.export_effective_enabled
    assert controller.ev_before_export_decision.reason == "ev_handoff_pending"
    assert calls == []


@pytest.mark.parametrize("changes", [{"ev_before_export_enabled": False}, {"configure_ev": False}])
async def test_unselected_handoff_does_not_change_existing_export(
    hass, freezer, monkeypatch, changes
):
    _, _, controller = _rig(hass, freezer, **changes)
    calls = _services(hass, monkeypatch)
    hass.states.async_remove("sensor.car_actual_current")
    await controller.async_reconcile()
    assert ("select.foxess_mode", "Force Discharge") in calls


async def test_active_export_survives_retained_current_under_proved_disconnection(
    hass, freezer, monkeypatch
):
    _, _, controller = _rig(hass, freezer)
    calls = _services(hass, monkeypatch)
    _foxess(hass, mode="Force Discharge", discharge=15)
    controller.export_session = ExportSessionState("active", 15, 0)
    hass.states.async_set("binary_sensor.car_cable", "off")
    hass.states.async_set("sensor.car_charging", "disconnected")
    hass.states.async_set("switch.car_charge", "off")
    hass.states.async_set("sensor.car_actual_current", "16", {"unit_of_measurement": "A"})
    hass.states.async_set("number.car_current", "16", {"unit_of_measurement": "A"})

    await controller.async_reconcile()

    assert controller.export_session.phase == "active"
    assert calls == []


@pytest.mark.parametrize("step,minimum,configured,physical_baseline", [
    (1, 1, 0.5, 1), (2, 0, 1, 2), (0.5, 0, 1.1, 1.5),
])
async def test_baseline_handoff_uses_the_representable_physical_current(
    hass, freezer, monkeypatch, step, minimum, configured, physical_baseline
):
    _, coordinator, controller = _rig(hass, freezer)
    coordinator.config["ev_protected_baseline_a"] = configured
    coordinator.runtime_config = RuntimeConfiguration.from_mapping(coordinator.config)
    calls = _services(hass, monkeypatch)
    _charging(hass, physical_baseline)
    hass.states.async_set(
        "number.car_current", str(physical_baseline),
        {"min": minimum, "max": 16, "step": step, "unit_of_measurement": "A"},
    )

    await controller.async_reconcile()

    assert ("select.foxess_mode", "Force Discharge") in calls


async def test_physical_loss_does_not_block_owned_export_cleanup(hass, freezer, monkeypatch):
    _, _, controller = _rig(hass, freezer)
    calls = _services(hass, monkeypatch)
    _foxess(hass, mode="Force Discharge", discharge=15)
    controller.export_session = ExportSessionState("active", 15, 0)
    hass.states.async_remove("sensor.car_actual_current")

    await controller.async_reconcile()

    assert controller.export_session.phase == "stopping"
    assert calls == [("select.foxess_mode", "Self Use"), ("number.foxess_discharge", 0)]


async def test_mid_staging_ev_change_blocks_mode_then_preserves_reducing_cleanup(
    hass, freezer, monkeypatch
):
    _, _, controller = _rig(hass, freezer)
    _charging(hass, 1)
    calls = _services(hass, monkeypatch, after_discharge=lambda: _charging(hass, 8))

    with pytest.raises(FoxessWriteBlocked):
        await controller.async_reconcile()

    assert controller.export_session.phase == "starting"
    assert calls == [("number.foxess_discharge", 15)]
    assert hass.states.get("select.foxess_mode").state == "Self Use"
    # The durable session still owns the staged nonzero target. Missing/high EV
    # feedback must not also forbid the next zeroing cleanup command.
    await controller.async_reconcile()

    assert controller.export_session.phase == "stopping"
    assert calls[-1] == ("number.foxess_discharge", 0)
    assert ("select.foxess_mode", "Force Discharge") not in calls
