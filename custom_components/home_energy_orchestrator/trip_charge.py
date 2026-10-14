"""HACS-owned trip scheduler; the existing EV controller remains the only writer."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import isfinite

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EV_CHARGE_EFFICIENCY,
    CONF_EV_CHARGE_TO_FULL_MAX_HOURS,
    DEFAULT_EV_CHARGE_EFFICIENCY,
    DEFAULT_EV_CHARGE_TO_FULL_MAX_HOURS,
    EV_CHARGE_PATH_DIRECT,
)
from .ev_observation_adapter import capture_ev_entity_feedback
from .persistence import create_typed_value_repository
from .planner.trip_charge import TripChargeState, calculate_trip_charge_plan


class TripChargeController:
    """One persisted schedule and CAS lease on HEO's existing Full intent."""

    def __init__(self, hass, coordinator, entry) -> None:
        self.hass, self.coordinator, self.entry = hass, coordinator, entry
        self._state = TripChargeState()
        self._loaded = False
        self._stopped = True
        self._invalid_storage = False
        self._storage_error = False
        self._dirty = False
        self._load_lock = asyncio.Lock()
        self._save_lock = asyncio.Lock()
        self._unsubs = []
        self._deadline_unsub = None
        self._plan = None
        self._repository = create_typed_value_repository(
            hass,
            storage_version=1,
            storage_key=f"home_energy_orchestrator.{coordinator.entry_id}.trip_charge",
            decode=TripChargeState.from_payload,
            encode=TripChargeState.to_payload,
        )
        self._store = self._repository.store

    @property
    def departure(self):
        return self._state.departure

    @property
    def target_soc(self):
        return self._state.target_soc

    @property
    def extra_minutes(self):
        return self._state.extra_minutes

    @property
    def armed(self):
        return self._state.armed

    @property
    def owns_full(self):
        return self._state.owns_full

    @property
    def status(self):
        if self._invalid_storage:
            return "invalid_storage"
        if self._storage_error:
            return "storage_unavailable"
        if not self.armed and not self.owns_full and self._legacy_conflict():
            return "legacy_conflict"
        return self._state.status

    @property
    def planned_start(self):
        return None if self._plan is None else self._plan.planned_start

    @property
    def planned_hours(self):
        return None if self._plan is None else self._plan.planned_hours

    @property
    def attributes(self):
        return {
            "departure": self.departure.isoformat() if self.departure else None,
            "target_soc": self.target_soc,
            "extra_minutes": self.extra_minutes,
            "armed": self.armed,
            "owns_full": self.owns_full,
            "generation": self._state.generation,
            "full_generation": self._state.full_generation,
            "owner_token": self._state.owner_token,
            "cleanup_pending": self._state.cleanup_pending,
            "legacy_conflict": self._legacy_conflict(),
            "storage_status": "invalid"
            if self._invalid_storage
            else (
                "unavailable" if self._storage_error else "ready" if self._loaded else "not_loaded"
            ),
        }

    @property
    def _ev(self):
        return self.coordinator.ev_controller

    async def async_restore_handoff(self) -> None:
        async with self._load_lock:
            if self._loaded:
                return
            try:
                self._state = await self._repository.async_load()
                self._invalid_storage = self._repository.last_restore_status == "invalid"
            except (OSError, ValueError):
                self._invalid_storage = True
            self._loaded = True
            if not self._invalid_storage:
                async with self._ev._lock:
                    await self._apply_tombstone_locked()

    async def async_load(self) -> None:
        """Compatibility alias; setup calls the explicit restore lifecycle name."""
        await self.async_restore_handoff()

    async def async_start(self) -> None:
        await self.async_restore_handoff()
        self._stopped = False
        if not self._unsubs:
            runtime = self.coordinator.runtime_config
            entities = {
                runtime.ev_telemetry.soc_entity,
                runtime.ev_connection.at_home_entity,
                runtime.ev_connection.cable_connected_entity,
                runtime.ev_preferences.legacy_charge_to_full_entity,
            } - {None}
            if entities:
                self._unsubs.append(
                    async_track_state_change_event(self.hass, entities, self._changed)
                )
            self._unsubs.append(
                async_track_time_interval(self.hass, self._tick, timedelta(minutes=1))
            )
        await self.async_reconcile()

    async def async_stop(self) -> None:
        self._stopped = True
        self._cancel_deadline()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        async with self._ev._lock:
            if self._dirty:
                await self._save()

    async def _changed(self, _event) -> None:
        await self.async_reconcile()

    async def _tick(self, _now) -> None:
        await self.async_reconcile()

    def _cancel_deadline(self) -> None:
        if self._deadline_unsub is not None:
            self._deadline_unsub()
            self._deadline_unsub = None

    def _schedule(self, now: datetime) -> None:
        self._cancel_deadline()
        if self._stopped or not self.armed:
            return
        when = self.departure
        if not self.owns_full and self.planned_start is not None and self.planned_start > now:
            when = min(when, self.planned_start)
        if when is None or when <= now:
            return
        generation = self._state.generation

        async def due(_now):
            if not self._stopped and generation == self._state.generation:
                await self.async_reconcile()

        self._deadline_unsub = async_track_point_in_utc_time(self.hass, due, when)

    async def _save(self) -> bool:
        state = self._state
        async with self._save_lock:
            task = self.hass.async_create_task(self._repository.async_save(state))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await asyncio.shield(task)
                raise
            except (OSError, ValueError):
                self._storage_error = True
                self._dirty = True
                return False
        self._storage_error = False
        self._dirty = self._state != state
        return True

    def _publish(self) -> None:
        self.coordinator.async_update_listeners()

    async def _edit(self, **changes) -> None:
        await self.async_restore_handoff()
        # Fence an awaited start checkpoint before waiting for its shared lock.
        active = self.owns_full
        arm_requested = "armed" in changes
        requested_arm = changes.pop("armed", self.armed)
        if self._invalid_storage and not (arm_requested and requested_arm is False):
            # Do not replace an unreadable ownership journal with defaults
            # merely because an operator edits a planning field. Quarantine
            # must also survive restart until an explicit Cancel acknowledges it.
            raise HomeAssistantError("Cancel once to acknowledge an unreadable trip journal")
        changes = {
            key: value for key, value in changes.items() if value != getattr(self._state, key)
        }
        retry_cleanup = (
            arm_requested
            and not requested_arm
            and (
                active
                or self._state.cleanup_pending
                or self._invalid_storage
                or self._storage_error
                or self._dirty
            )
        )
        if not changes and requested_arm == self.armed and not retry_cleanup:
            return
        cancel_active = active and (
            "departure" in changes
            or "target_soc" in changes
            or (arm_requested and not requested_arm)
        )
        self._state = replace(
            self._state,
            **changes,
            generation=self._state.generation + 1,
            armed=False if cancel_active else requested_arm,
            status="cancelled"
            if cancel_active
            else self._state.status
            if active
            else "waiting_for_start"
            if requested_arm
            else "not_scheduled",
            # Extra minutes changes only later planning. The running Full
            # lease, its captured target/departure and timeout stay frozen.
            cleanup_pending=self._state.cleanup_pending or cancel_active,
        )
        self._dirty = True
        self._cancel_deadline()
        async with self._ev._lock:
            if self._invalid_storage and arm_requested and requested_arm is False:
                self._invalid_storage = False
            if not await self._save() and self.armed:
                self._state = replace(self._state, armed=False, cleanup_pending=self.owns_full)
                raise HomeAssistantError("Trip journal unavailable; schedule was not armed")
        await self.async_reconcile()

    async def async_set_departure(self, value: datetime) -> None:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise HomeAssistantError("Choose an aware departure date and time")
        await self._edit(departure=value.astimezone(UTC))

    async def async_set_target_soc(self, value: int) -> None:
        if type(value) is not int or not 1 <= value <= 100:
            raise HomeAssistantError("Trip target must be a whole percentage from 1 to 100")
        await self._edit(target_soc=value)

    async def async_set_extra_minutes(self, value: float) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
            or not 0 <= value <= 120
        ):
            raise HomeAssistantError("Extra minutes must be between 0 and 120")
        await self._edit(extra_minutes=float(value))

    async def async_set_armed(self, value: bool) -> None:
        if type(value) is not bool:
            raise HomeAssistantError("Trip schedule request must be boolean")
        await self.async_restore_handoff()
        if value and self.armed:
            return
        if value and self._legacy_conflict():
            raise HomeAssistantError(
                "Retire the legacy trip dispatcher before arming native trip charging"
            )
        if value and self.departure is None:
            raise HomeAssistantError("Choose a departure before arming trip charging")
        if value and self._invalid_storage:
            raise HomeAssistantError("Cancel once to acknowledge an unreadable trip journal")
        await self._edit(armed=value)

    def _legacy_conflict(self) -> bool:
        roles = {
            "automation": (
                "automation.heo_trip_charge_dispatch",
                "heo_trip_charge_dispatch",
                "heo trip charge — schedule existing full override",
            ),
            "armed": (
                "input_boolean.heo_trip_charge_scheduled",
                "heo_trip_charge_scheduled",
                "heo trip charge scheduled",
            ),
            "owned": (
                "input_boolean.heo_trip_charge_started",
                "heo_trip_charge_started",
                "heo trip charge started",
            ),
        }
        registry = er.async_get(self.hass)
        for domain_role, (default_id, unique_id, name) in roles.items():
            candidates = {default_id} if self.hass.states.get(default_id) is not None else set()
            domain = "automation" if domain_role == "automation" else "input_boolean"
            for entity in registry.entities.values():
                if entity.domain == domain and (
                    entity.unique_id == unique_id or (entity.original_name or "").casefold() == name
                ):
                    candidates.add(entity.entity_id)
            if domain_role == "automation":
                candidates.update(
                    state.entity_id
                    for state in self.hass.states.async_all("automation")
                    if state.attributes.get("id") == unique_id
                )
            if any(
                (state := self.hass.states.get(entity)) is None or state.state != "off"
                for entity in candidates
            ):
                return True
        return False

    def _full_state(self) -> bool | None:
        preference = self.coordinator.runtime_config.ev_preferences
        if preference.charge_to_full_configured:
            return preference.charge_to_full_enabled
        if not preference.legacy_charge_to_full_entity:
            return False
        state = capture_ev_entity_feedback(self.hass, preference.legacy_charge_to_full_entity)
        return {"on": True, "off": False}.get(state.reported_state)

    async def async_record_full_intent_locked(
        self,
        enabled: bool,
        *,
        owner_token: str | None = None,
        expected_generation: int | None = None,
        natural: bool = False,
    ) -> dict[str, object]:
        """Checkpoint a logical Full change while EV's transaction lock is held."""
        state = self._state
        if expected_generation is not None and (
            state.full_generation != expected_generation or state.full_owner != owner_token
        ):
            return {
                "accepted": False,
                "generation": state.full_generation,
                "owner_token": state.full_owner,
            }
        trip_request = owner_token is not None
        if trip_request and enabled and (not self.armed or self._stopped or self._invalid_storage):
            return {
                "accepted": False,
                "generation": state.full_generation,
                "owner_token": state.full_owner,
            }
        generation = state.full_generation + 1
        if not trip_request:
            self._state = replace(
                state,
                full_generation=generation,
                full_owner="operator" if enabled else None,
                full_enabled=enabled,
                owner_token=None,
                owned_generation=None,
                captured_departure=None,
                captured_target=None,
                cleanup_pending=False,
                armed=False if state.owns_full else state.armed,
                status=(
                    "completed"
                    if natural
                    and state.captured_target is not None
                    and self._soc() is not None
                    and self._soc() >= state.captured_target
                    else "interrupted"
                )
                if state.owns_full
                else state.status,
            )
        else:
            self._state = replace(
                state,
                full_generation=generation,
                full_owner=owner_token,
                full_enabled=enabled,
                owned_generation=generation,
                cleanup_pending=not enabled,
                owner_token=owner_token,
                captured_departure=state.departure if enabled else state.captured_departure,
                captured_target=state.target_soc if enabled else state.captured_target,
            )
        self._dirty = True
        request_generation = self._state.generation
        saved = await self._save()
        if enabled and not saved:
            # A rejected increase cannot relinquish an already-running trip.
            # Preserve any newer synchronous cancel/edit fence while rolling
            # back only the uncommitted Full ownership fields.
            self._state = replace(
                self._state,
                full_generation=state.full_generation,
                full_owner=state.full_owner,
                full_enabled=state.full_enabled,
                owner_token=state.owner_token,
                owned_generation=state.owned_generation,
                captured_departure=state.captured_departure,
                captured_target=state.captured_target,
                cleanup_pending=state.cleanup_pending,
                armed=self._state.armed
                if self._state.generation != state.generation
                else state.armed,
                status=state.status,
            )
            self._dirty = True
            if trip_request and not state.owns_full:
                # A failed save can be ambiguous about whether it reached
                # disk. Retain only reducing cleanup, never automatic retry.
                self._state = replace(
                    self._state,
                    armed=False,
                    full_generation=generation,
                    full_owner=owner_token,
                    owner_token=owner_token,
                    owned_generation=generation,
                    full_enabled=False,
                    captured_departure=state.departure,
                    captured_target=state.target_soc,
                    cleanup_pending=True,
                    status="interrupted",
                )
        accepted = (saved or not enabled) and (
            not enabled
            or owner_token is None
            or (
                request_generation == self._state.generation
                and self.armed
                and not self._stopped
                and self._start_inputs_still_current()
            )
        )
        self._publish()
        return {
            "accepted": accepted,
            "generation": generation,
            "owner_token": self._state.full_owner,
        }

    def _soc(self) -> float | None:
        feedback = capture_ev_entity_feedback(
            self.hass, self.coordinator.runtime_config.ev_telemetry.soc_entity
        )
        return (
            feedback.number if feedback.number is not None and 0 <= feedback.number <= 100 else None
        )

    async def _finish_locked(self, status: str) -> bool:
        self._state = replace(
            self._state, armed=False, status=status, cleanup_pending=self.owns_full
        )
        self._dirty = True
        if self.owns_full:
            result = await self._ev._async_set_charge_to_full_locked(
                False,
                owner_token=self._state.owner_token,
                expected_generation=self._state.owned_generation,
            )
            if not result["accepted"]:
                return False
            pending = self._state
            self._state = replace(
                self._state,
                owner_token=None,
                owned_generation=None,
                full_owner=None,
                captured_departure=None,
                captured_target=None,
                cleanup_pending=False,
            )
            if not await self._save():
                self._state = pending
                self._dirty = True
                return True
            return True
        await self._save()
        return True

    async def async_reconcile_before_ev_locked(self, now: datetime) -> bool:
        """Restore owned cleanup before EV writes, never replay a startup start."""
        if self._invalid_storage:
            # Unknown journal ownership cannot adopt or clear an existing
            # paid override. Otherwise ordinary HEO policy remains available.
            return self._full_state() is False
        if not self._loaded:
            return False
        await self._apply_tombstone_locked()
        if self.owns_full or not self._stopped:
            await self._reconcile_locked(now)
        return True

    async def _apply_tombstone_locked(self) -> None:
        if (
            self._state.full_generation > 0
            and not self._state.full_enabled
            and self._full_state() is not False
        ):
            # ConfigEntry saves are delayed. The last durable OFF intent is a
            # reducing tombstone until a newer Full generation supersedes it.
            await self._ev._async_set_charge_to_full_locked(
                False,
                owner_token=self._state.full_owner,
                expected_generation=self._state.full_generation,
            )

    async def async_reconcile(self, now: datetime | None = None) -> None:
        await self.async_restore_handoff()
        if self._stopped or self._invalid_storage:
            return
        now = now or dt_util.utcnow()
        changed_full = False
        generation = self._state.generation
        try:
            async with self._ev._lock:
                changed_full = await self._reconcile_locked(now)
            self._schedule(now)
            self._publish()
            if changed_full and not self._stopped:
                await self._ev.async_reconcile()
        except asyncio.CancelledError:
            async with self._ev._lock:
                if generation == self._state.generation and self.owns_full:
                    await asyncio.shield(self._finish_locked("interrupted"))
            raise

    def _current_plan_inputs(self):
        runtime = self.coordinator.runtime_config
        learned = self._ev.learned_charge_limit
        return {
            "departure": self.departure,
            "target_soc": self.target_soc,
            "soc": self._soc(),
            "capacity_kwh": None if learned is None else learned.usable_capacity_kwh,
            "maximum_power_kw": getattr(self.coordinator.data, "ev_max_power_kw", None),
            "efficiency_percent": runtime.ev_numbers.value(
                CONF_EV_CHARGE_EFFICIENCY, DEFAULT_EV_CHARGE_EFFICIENCY
            ),
            "extra_minutes": self.extra_minutes,
            "maximum_hours": runtime.ev_numbers.value(
                CONF_EV_CHARGE_TO_FULL_MAX_HOURS, DEFAULT_EV_CHARGE_TO_FULL_MAX_HOURS
            ),
        }

    def _start_inputs_still_current(self) -> bool:
        inputs = self._current_plan_inputs()
        plan = calculate_trip_charge_plan(**inputs)
        now = dt_util.utcnow()
        return (
            inputs == getattr(self, "_starting_inputs", None)
            and plan is not None
            and plan.planned_start <= now < self.departure
            and inputs["soc"] < self.target_soc
            and self._ev.gate_status == "ready"
            and self._ev._connected_at_home()[0]
            and not self._legacy_conflict()
            and self.coordinator.runtime_config.ev_policy.charge_path == EV_CHARGE_PATH_DIRECT
        )

    async def _reconcile_locked(self, now: datetime) -> bool:
        if self._stopped and not self.owns_full:
            return False
        if self._dirty and not await self._save():
            if not self.owns_full:
                return False
        await self._apply_tombstone_locked()
        state = self._state
        full = self._full_state()
        soc = self._soc()
        runtime = self.coordinator.runtime_config
        self._plan = calculate_trip_charge_plan(**self._current_plan_inputs())
        if self.owns_full:
            if full is None:
                self._state = replace(state, status="waiting_for_data")
                return False
            if full is False:
                return await self._finish_locked(
                    "completed"
                    if soc is not None and soc >= state.captured_target
                    else "interrupted"
                )
            if (
                state.cleanup_pending
                or not state.armed
                or (
                    state.departure != state.captured_departure
                    or state.target_soc != state.captured_target
                )
            ):
                return await self._finish_locked("cancelled")
            if soc is None:
                return await self._finish_locked("interrupted")
            if soc >= state.captured_target:
                return await self._finish_locked("completed")
            if not self._ev._connected_at_home()[0]:
                return await self._finish_locked("interrupted")
            self._state = replace(
                state,
                status="charging_late" if now >= state.captured_departure else "override_active",
            )
            return False
        if not self.armed:
            return False
        if self.departure is not None and now >= self.departure:
            return await self._finish_locked(
                "completed" if soc is not None and soc >= self.target_soc else "expired"
            )
        if soc is not None and soc >= self.target_soc:
            self._state = replace(state, status="already_at_target")
        elif full:
            return await self._finish_locked("external_override")
        elif self._legacy_conflict():
            self._state = replace(state, status="legacy_conflict")
        elif full is None or self._plan is None:
            self._state = replace(state, status="waiting_for_data")
        elif runtime.ev_policy.charge_path != EV_CHARGE_PATH_DIRECT:
            self._state = replace(state, status="control_unavailable")
        elif not self._ev._connected_at_home()[0]:
            self._state = replace(state, status="waiting_for_car")
        elif self._ev.gate_status != "ready":
            self._state = replace(state, status="control_unavailable")
        elif now < self.planned_start:
            self._state = replace(state, status="waiting_for_start")
        else:
            token = f"trip:{state.generation}"
            generation = state.generation
            self._starting_inputs = self._current_plan_inputs()
            self._state = replace(state, status="override_active")
            result = await self._ev._async_set_charge_to_full_locked(True, owner_token=token)
            if not result["accepted"] or generation != self._state.generation:
                if self.owns_full:
                    await self._finish_locked("cancelled")
                return False
            return True
        return False
