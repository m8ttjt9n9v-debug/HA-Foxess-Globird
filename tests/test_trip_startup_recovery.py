"""Native Trip restoration while its upstream vehicle integration is still loading."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from itertools import permutations

import pytest

from . import test_trip_charge_native as native

trip_site = native.trip_site
pytestmark = pytest.mark.freeze_time(native.NOW, real_asyncio=True)

_SOURCE_GROUPS = {
    "connection": ("device_tracker.car", "binary_sensor.car_cable", "sensor.car_charging"),
    "soc": ("sensor.car_soc", "sensor.car_energy"),
    "actuators": ("number.car_current", "number.car_limit", "switch.car_charge"),
}


async def _boot_before_sources(trip_site, monkeypatch, *, absence=None, old_journal=False):
    site = await trip_site(soc=20, capacity=60)
    await native._start(site, target=80)
    original = site.trip._state
    original_timer = site.ev.charge_to_full_started_at
    assert original_timer is not None
    if old_journal:
        site.trip._state = replace(original, first_started_at=None, timeout_at=None)
        assert await site.trip._save()
    await site.trip.async_stop()
    await site.ev.async_stop()
    sources = {
        entity: site.hass.states.get(entity)
        for group in _SOURCE_GROUPS.values()
        for entity in group
    }
    for entity in sources:
        site.hass.states.async_remove(entity)
    if absence:
        site.hass.states.async_set(*absence)
    commands = await native._setup_actual_site(site, monkeypatch)
    return site, original, original_timer, sources, commands


async def _arrive(site, sources, group):
    for entity in _SOURCE_GROUPS[group]:
        original = sources[entity]
        site.hass.states.async_set(entity, original.state, dict(original.attributes))
        await site.hass.async_block_till_done()


@pytest.mark.parametrize("order", tuple(permutations(_SOURCE_GROUPS)))
async def test_actual_boot_retains_native_full_until_whole_source_cohort_arrives(
    trip_site, monkeypatch, order
):
    site, original, timer, sources, commands = await _boot_before_sources(trip_site, monkeypatch)
    try:
        assert site.trip.armed and site.trip.owns_full
        assert site.trip.status == "waiting_for_data"
        assert site.trip._state.full_generation == original.full_generation
        assert site.ev._charge_to_full_requested()
        assert site.ev.charge_to_full_started_at == timer
        assert commands == []
        for index, group in enumerate(order):
            await _arrive(site, sources, group)
            if index < len(order) - 1:
                assert site.trip.armed and site.trip.owns_full
                assert site.trip._state.full_generation == original.full_generation
                assert site.ev._charge_to_full_requested()
                assert site.ev.charge_to_full_started_at == timer
                assert commands == []
        await site.ev.async_reconcile()
        await site.trip.async_reconcile()
        assert site.trip.armed and site.trip.owns_full
        assert site.trip._state.full_generation == original.full_generation
        assert site.trip._state.first_started_at == original.first_started_at
        assert site.trip._state.timeout_at == original.timeout_at
        assert site.ev.charge_to_full_started_at == timer
        assert site.ev._charge_to_full_requested()
    finally:
        assert await site.hass.config_entries.async_unload(site.entry.entry_id)
        await site.hass.async_block_till_done()


@pytest.mark.parametrize(
    "absence", [("device_tracker.car", "not_home"), ("binary_sensor.car_cable", "off")]
)
async def test_confirmed_absence_at_boot_pauses_even_when_other_sources_have_not_loaded(
    trip_site, monkeypatch, absence
):
    site, original, _, _, commands = await _boot_before_sources(
        trip_site, monkeypatch, absence=absence
    )
    try:
        assert site.trip.armed and not site.trip.owns_full
        assert site.trip.status == "paused"
        assert site.trip._state.first_started_at == original.first_started_at
        assert site.trip._state.timeout_at == original.timeout_at
        assert site.trip._state.full_stop_reason == "disconnected"
        assert not site.ev._charge_to_full_requested()
        assert commands == []
    finally:
        assert await site.hass.config_entries.async_unload(site.entry.entry_id)
        await site.hass.async_block_till_done()


async def test_missing_startup_sources_cannot_extend_the_original_absolute_timeout(
    trip_site, monkeypatch
):
    site, original, _, _, commands = await _boot_before_sources(trip_site, monkeypatch)
    try:
        assert site.trip.armed and site.trip.owns_full
        site.freezer.move_to(original.timeout_at + timedelta(seconds=1))
        await site.trip.async_reconcile()
        assert not site.trip.armed and not site.trip.owns_full
        assert not site.ev._charge_to_full_requested()
        assert site.trip.status == "expired"
        assert site.trip._state.full_stop_reason == "timeout"
        assert site.trip._state.first_started_at == original.first_started_at
        assert site.trip._state.timeout_at == original.timeout_at
        assert commands == []
    finally:
        assert await site.hass.config_entries.async_unload(site.entry.entry_id)
        await site.hass.async_block_till_done()


async def test_old_native_journal_uses_restored_ev_timer_before_startup_reconciliation(
    trip_site, monkeypatch
):
    site, original, timer, _, commands = await _boot_before_sources(
        trip_site, monkeypatch, old_journal=True
    )
    try:
        assert site.trip.armed and site.trip.owns_full
        assert site.trip.status == "waiting_for_data"
        assert site.trip._state.first_started_at == timer
        assert site.trip._state.timeout_at == original.timeout_at
        assert site.trip._state.full_generation == original.full_generation
        assert site.ev.charge_to_full_started_at == timer
        assert site.ev._charge_to_full_requested()
        assert commands == []
        site.freezer.move_to(original.timeout_at + timedelta(seconds=1))
        await site.trip.async_reconcile()
        assert not site.trip.armed and not site.ev._charge_to_full_requested()
        assert site.trip._state.full_stop_reason == "timeout"
        assert commands == []
    finally:
        assert await site.hass.config_entries.async_unload(site.entry.entry_id)
        await site.hass.async_block_till_done()


async def test_invalid_soc_after_cohort_was_trusted_still_ends_native_trip(trip_site, monkeypatch):
    site, _, _, sources, _ = await _boot_before_sources(trip_site, monkeypatch)
    try:
        for group in _SOURCE_GROUPS:
            await _arrive(site, sources, group)
        await site.ev.async_reconcile()
        assert site.trip.owns_full
        generation = site.trip._state.full_generation
        site.hass.states.async_set("sensor.car_soc", "unavailable")
        await site.trip.async_reconcile()
        assert not site.trip.armed and not site.trip.owns_full
        assert not site.ev._charge_to_full_requested()
        assert site.trip.status == "interrupted"
        assert site.trip._state.full_stop_reason == "invalid_data"
        assert site.trip._state.full_stop_generation == generation
        assert site.trip._state.full_generation == generation + 1
    finally:
        assert await site.hass.config_entries.async_unload(site.entry.entry_id)
        await site.hass.async_block_till_done()
