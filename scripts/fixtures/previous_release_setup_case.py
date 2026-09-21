"""System case executed against the extracted previous known-good release."""

from __future__ import annotations

import json
import os
from pathlib import Path

from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN


async def test_previous_release_reads_current_unchanged_surface(hass) -> None:
    """The previous release must restore current config and retained state."""
    bundle = json.loads(Path(os.environ["HEO_ROLLBACK_BUNDLE"]).read_text())
    entry_id = bundle["entry_id"]
    for suffix, payload in bundle["stores"].items():
        store = Store(
            hass,
            1,
            f"home_energy_orchestrator.{entry_id}.{suffix}",
            private=True,
        )
        await store.async_save(payload)

    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.test_house_load", "0.8", {"unit_of_measurement": "kW"})
    service_calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, service_calls.append)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Rollback rehearsal",
        data=bundle["entry_data"],
        version=bundle["entry_version"],
        entry_id=entry_id,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 6
    assert hass.states.get("sensor.home_energy_status") is not None

    coordinator = entry.runtime_data
    assert coordinator.active_controller._charge_state_payload() == bundle["stores"][
        "charge_session"
    ]
    assert coordinator.active_controller._export_state_payload() == bundle["stores"][
        "export_session"
    ]
    ev = coordinator.ev_controller
    ev_payload = bundle["stores"]["ev_control"]
    assert ev.reconciliation.target_current_a == 5.0
    assert ev.reconciliation.target_limit_percent == 82.0
    assert ev.reconciliation.attempts == 2
    assert ev.reconciliation.phase == "awaiting_feedback"
    assert ev.pre_free_session.active is True
    assert ev.daily_backfill_delivered_kwh == 3.25
    assert ev.daily_backfill_active is True
    assert ev.daily_backfill_stop_pending is True
    assert ev.daily_backfill_stop_attempts == 2
    assert ev.driving_snapshot.lifetime_energy_kwh == 1234.5
    assert ev.daily_driving_energy_kwh == 12.5
    assert ev.charge_to_full_started_at.isoformat() == ev_payload[
        "charge_to_full_started_at"
    ]
    assert ev.outside_control_active is True
    assert ev.smart_recovery.phase == "fault"
    assert service_calls == []
    assert await hass.config_entries.async_unload(entry.entry_id)
