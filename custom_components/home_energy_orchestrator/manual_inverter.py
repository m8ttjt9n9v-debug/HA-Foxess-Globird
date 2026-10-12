"""Persistent operator handoff through the commissioned FoxESS actuator.

The automatic controller owns serialization. It must load this journal before
starting its policies, defer every automatic writer while ``is_active``, and
call ``async_reconcile_locked`` while holding its reconciliation lock. No native
schedule, register mapping, or second inverter implementation is introduced.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from math import isfinite
from typing import Any

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import FOXESS_CONTROL_OWNER_MODBUS
from .foxess_adapter import FoxessEntityMap, FoxessServiceAdapter, FoxessWriteBlocked
from .foxess_observation_adapter import capture_foxess_feedback
from .normalise import power_to_kw
from .persistence import TypedValueStoreRepository
from .planner.foxess import (
    ControlDecision,
    FoxessCommand,
    FoxessCommandPlan,
    apply_force_mode_command_delays,
    foxess_response_matches,
    plan_foxess_commands,
)

_TARGETS = frozenset({"export_max", "self_use", "automatic"})
_PHASES = frozenset({"pending", "confirming", "held", "idle"})


class ManualInverterError(ValueError):
    """A manual request cannot establish a durable, commissioned handoff."""


class ManualInverterController:
    """Retain one operator target until an explicit stop or confirmed resume."""

    def __init__(self, hass: Any, coordinator: Any, active_controller: Any) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.active_controller = active_controller
        self._store = Store(
            hass, 1,
            "home_energy_orchestrator."
            f"{getattr(coordinator, 'entry_id', 'runtime')}.manual_inverter",
            private=True,
        )
        self._repository = TypedValueStoreRepository(
            self._store, decode=decode_manual_inverter_journal, encode=lambda payload: payload,
        )
        self._save_lock = asyncio.Lock()
        self._load_lock = asyncio.Lock()
        self._target = "automatic"
        self._phase = "pending"
        self._hold = True
        self._generation = 0
        self._durable_generation = -1
        self._entities: FoxessEntityMap | None = None
        self._last_request_id: str | None = None
        self._last_issued_at: datetime | None = None
        self._local_control_confirmed = False
        self._loaded = False
        self._trusted = False
        self._storage_fault = False
        self._stopped = False
        self._relinquished_generation = -1
        self._attempts = 0
        self._next_retry_at: datetime | None = None
        self._power_kw: float | None = None
        self._command_confirmed = False
        self._status = "manual_journal_loading"

    @property
    def is_active(self) -> bool:
        """Fence automatic work, including while persistence is in flight."""
        return self._hold

    @property
    def target(self) -> str:
        return self._target

    @property
    def status(self) -> str:
        return self._status

    @property
    def generation(self) -> int:
        return self._generation

    def attributes(self) -> dict[str, object]:
        """Expose ownership and mapped feedback, without claiming grid export."""
        return {
            "manual_inverter_hold": self._hold,
            "manual_inverter_target": self._target,
            "manual_inverter_status": self._status,
            "manual_inverter_generation": self._generation,
            "manual_inverter_power_kw": self._power_kw,
            "manual_inverter_command_confirmed": self._confirmed_now(),
            "manual_inverter_request_id": self._last_request_id,
            "manual_inverter_issued_at": (
                self._last_issued_at.isoformat() if self._last_issued_at else None
            ),
            "manual_inverter_storage_trusted": self._trusted and not self._storage_fault,
        }

    async def async_restore_handoff(self) -> None:
        """Restore the fence before automatic startup, failing closed on damage."""
        async with self._load_lock:
            if self._loaded:
                return
            self._stopped = False
            try:
                payload = await self._repository.async_load()
                if self._repository.last_restore_status == "invalid":
                    raise ValueError("invalid manual journal")
                if payload is None:
                    self._phase, self._hold = "idle", False
                else:
                    self._restore(payload)
                self._trusted = True
                self._durable_generation = self._generation
                self._status = "manual_restored" if self._hold else "automatic"
            except Exception:
                self._hold = True
                self._trusted = False
                self._status = "manual_journal_untrusted"
            self._loaded = True
            self._notify()

    async def async_request(
        self,
        target: str,
        *,
        local_control_confirmed: bool = False,
        request_id: str | None = None,
        issued_at: str | None = None,
    ) -> dict[str, object]:
        """Admit intent synchronously, then persist and serialize hardware work."""
        now = dt_util.utcnow()
        rejection = None
        stamp = now
        if not self._loaded or self._stopped:
            rejection = "manual_controller_unavailable"
        elif target not in _TARGETS:
            rejection = "manual_target_invalid"
        elif request_id is not None and (not request_id or issued_at is None):
            rejection = "manual_request_timestamp_required"
        if issued_at is not None:
            try:
                stamp = _aware_datetime(issued_at)
            except (TypeError, ValueError):
                rejection = "manual_request_timestamp_invalid"
        if rejection is None and request_id is not None and request_id == self._last_request_id:
            if stamp == self._last_issued_at and target == self._target:
                return self._response(True, request_id)
            rejection = "manual_request_id_reused"
        if rejection is None and self._last_issued_at is not None and (
            stamp < self._last_issued_at
            or stamp == self._last_issued_at and target != "self_use"
        ):
            rejection = "manual_request_out_of_order"
        if rejection is None and target == "export_max":
            age = (now - stamp).total_seconds()
            if age > 30 or age < -5:
                rejection = "manual_export_request_expired"
            elif not local_control_confirmed:
                rejection = "manual_local_control_confirmation_required"
            elif not self._trusted:
                rejection = "manual_journal_requires_self_use_recovery"
        if rejection is None and not self._trusted and not local_control_confirmed:
            rejection = "manual_journal_confirmation_required"
        if rejection is not None:
            return self._response(False, request_id, status=rejection)

        # No await precedes the generation change: Stop fences even a queued
        # Force Discharge plan while a preceding service/storage call finishes.
        self._generation += 1
        self._hold = True
        self._target, self._phase = target, "pending"
        self._status = "manual_request_pending"
        self._command_confirmed = False
        self._last_request_id, self._last_issued_at = request_id, stamp
        self._local_control_confirmed = local_control_confirmed
        self._attempts, self._next_retry_at = 0, None
        self._power_kw = None
        if self._entities is None:
            self._entities = self._current_entities()
        self._trusted = True
        self._notify()
        try:
            await self._persist()
            async with self.active_controller._reconcile_lock:
                await self.async_reconcile_locked()
        except ManualInverterError:
            pass  # The durable/visible fence remains; no write bypasses it.
        return self._response(True, request_id)

    async def async_reconcile_locked(self) -> bool:
        """Reconcile under the automatic owner's lock; return the current fence."""
        if not self._hold or not self._loaded or self._stopped:
            return self._hold
        if not self._trusted:
            return True
        generation = self._generation
        if self._durable_generation != generation or self._storage_fault:
            try:
                await self._persist()
            except ManualInverterError:
                return True
        if not self._current(generation):
            return True
        if self._entities is None:
            self._entities = self._current_entities()
            await self._persist()
        if reason := self._gate_reason():
            self._status = reason
            self._command_confirmed = False
            self._notify()
            return True
        assert self._entities is not None
        if self._relinquished_generation != generation:
            await self.active_controller.async_relinquish_for_manual(self._entities)
            if not self._current(generation):
                return True
            self._relinquished_generation = generation
        if reason := self._gate_reason():
            self._status = reason
            self._command_confirmed = False
            self._notify()
            return True
        feedback = capture_foxess_feedback(self.hass, self._entities)
        export = self._target == "export_max"
        if export:
            if reason := self._export_gate_reason():
                self._status = reason
                self._command_confirmed = False
                self._notify()
                return True
            self._power_kw = self._maximum_discharge_kw()
        else:
            self._power_kw = 0.0
        decision = ControlDecision(
            "force_discharge" if export else "restore_self_use",
            self._power_kw,
            "manual_operator_handoff",
        )
        observation = feedback.observation
        if observation is not None and foxess_response_matches(
            decision, observation
        ):
            await self._confirm(generation)
            return self._hold
        if self._next_retry_at is not None and dt_util.utcnow() < self._next_retry_at:
            self._status = "manual_feedback_retry_pending"
            self._command_confirmed = False
            self._notify()
            return True
        if observation is None:
            # Only known reducing cleanup can proceed with missing state
            # values and valid native capability metadata.
            plan = FoxessCommandPlan(
                (
                    FoxessCommand("select_mode", "Self Use", wait_seconds=5.0),
                    FoxessCommand("set_charge_power", 0.0),
                    FoxessCommand("set_discharge_power", 0.0),
                ),
                decision.reason,
            )
        else:
            plan = plan_foxess_commands(
                decision, observation,
                charge_power_max_kw=feedback.charge_power_max_kw,
                discharge_power_max_kw=feedback.discharge_power_max_kw,
            )
        try:
            plan = self._native_plan(apply_force_mode_command_delays(plan))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            self._status = "manual_blocked_power_metadata"
            self._command_confirmed = False
            self._notify()
            return True
        metadata = self._metadata_signature()
        self._phase = "confirming"
        self._command_confirmed = False
        self._attempts += 1
        self._next_retry_at = dt_util.utcnow() + timedelta(
            seconds=min(1800, 30 * 2 ** min(self._attempts - 1, 6))
        )
        await self._persist()
        if not self._current(generation):
            return True
        adapter = FoxessServiceAdapter(
            self.hass, self._entities, allow_writes=True,
            write_guard=lambda: (
                self._write_authorized(generation, export)
                and self._metadata_signature() == metadata
            ),
        )
        try:
            await adapter.async_execute(plan)
        except asyncio.CancelledError:
            self._status = "manual_command_interrupted"
            self._notify()
            raise
        except Exception as err:
            if self._current(generation):
                self._status = (
                    "manual_command_gated" if isinstance(err, FoxessWriteBlocked)
                    else "manual_command_failed"
                )
                self._notify()
            return self._hold
        if not self._current(generation):
            return self._hold
        feedback = capture_foxess_feedback(self.hass, self._entities)
        if feedback.observation is not None and foxess_response_matches(
            decision, feedback.observation
        ):
            await self._confirm(generation)
        else:
            self._status = "manual_feedback_pending"
            self._notify()
        return self._hold

    async def async_unload(self) -> None:
        """Fence delayed commands and checkpoint; an indefinite hold survives."""
        self._stopped = True
        self._hold = True
        if self._loaded and self._trusted:
            try:
                await self._persist()
            except ManualInverterError:
                pass
        async with self.active_controller._reconcile_lock:
            pass

    async def _confirm(self, generation: int) -> None:
        if not self._current(generation):
            return
        if reason := self._gate_reason():
            self._status = reason
            self._command_confirmed = False
            self._notify()
            return
        self._phase = "idle" if self._target == "automatic" else "held"
        self._attempts, self._next_retry_at = 0, None
        await self._persist()
        if not self._current(generation):
            return
        if reason := self._gate_reason():
            # Keep the original mapping obligation if reconfiguration or a
            # no-write gate changed during the final durable checkpoint.
            self._phase = "pending"
            self._status = reason
            self._command_confirmed = False
            await self._persist()
            self._notify()
            return
        self._command_confirmed = True
        if self._target == "automatic":
            self._hold = False
            self._entities = None
            self._status = "automatic"
        else:
            self._status = f"manual_{self._target}_held"
        self._notify()

    def _current(self, generation: int) -> bool:
        return self._hold and not self._stopped and self._generation == generation

    def _current_entities(self) -> FoxessEntityMap | None:
        inverter = self.coordinator.runtime_config.inverter
        if not inverter.actuator_mapping_complete:
            return None
        return FoxessEntityMap(
            inverter.work_mode_entity, inverter.force_charge_power_entity,
            inverter.force_discharge_power_entity,
        )

    def _gate_reason(self) -> str | None:
        runtime = self.coordinator.runtime_config
        if runtime.automation.safety_lock:
            return "manual_blocked_safety_lock"
        if runtime.automation.control_owner != FOXESS_CONTROL_OWNER_MODBUS:
            return "manual_blocked_control_owner"
        if not runtime.automation.master_enabled:
            return "manual_blocked_master_disabled"
        if self._entities is None:
            return "manual_blocked_incomplete_mapping"
        if self._entities != self._current_entities():
            return "manual_blocked_mapping_changed"
        automatic_adapter = getattr(self.active_controller, "_adapter", None)
        if (
            isinstance(automatic_adapter, FoxessServiceAdapter)
            and automatic_adapter.entities != self._entities
        ):
            return "manual_blocked_adapter_mapping_changed"
        if self._storage_fault or self._durable_generation != self._generation:
            return "manual_blocked_storage"
        mode = self.hass.states.get(self._entities.work_mode_entity)
        options = mode.attributes.get("options") if mode is not None else None
        if not isinstance(options, (list, tuple)) or "Self Use" not in options:
            return "manual_blocked_mode_options"
        try:
            for entity in (
                self._entities.force_charge_power_entity,
                self._entities.force_discharge_power_entity,
            ):
                state = self.hass.states.get(entity)
                if state is None:
                    raise ValueError("missing power metadata")
                _number_metadata(state)
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return "manual_blocked_power_metadata"
        return None

    def _export_gate_reason(self) -> str | None:
        if not self._local_control_confirmed:
            return "manual_blocked_local_confirmation"
        runtime = self.coordinator.runtime_config
        if not runtime.electrical.verified:
            return "manual_blocked_sign_verification"
        assert self._entities is not None
        feedback = capture_foxess_feedback(self.hass, self._entities)
        if not feedback.export_source_available or feedback.observation is None:
            return "manual_blocked_export_feedback"
        telemetry = getattr(self.coordinator, "telemetry", None)
        if (
            telemetry is None or not telemetry.battery_power.valid
            or not telemetry.battery_power.fresh
        ):
            return "manual_blocked_battery_power_telemetry"
        soc = self.hass.states.get(runtime.battery.soc_entity)
        try:
            value = float(soc.state) if soc is not None else float("nan")
            floor = runtime.battery.configured_floor_percent
            if (
                floor is None or not isfinite(floor) or not 0 <= floor <= 100
                or not isfinite(value) or not 0 <= value <= 100
                or value <= floor or soc is None
            ):
                return "manual_blocked_battery_floor_or_soc"
            self._maximum_discharge_kw()
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return "manual_blocked_discharge_limit"
        return None

    def _write_authorized(self, generation: int, export: bool) -> bool:
        return (
            self._current(generation) and self._gate_reason() is None
            and (not export or self._export_gate_reason() is None)
        )

    def _maximum_discharge_kw(self) -> float:
        assert self._entities is not None
        state = self.hass.states.get(self._entities.force_discharge_power_entity)
        minimum, maximum, step, factor = _number_metadata(state)
        ceiling = Decimal(str(self.coordinator.runtime_config.inverter.discharge_limit_kw))
        if not ceiling.is_finite() or ceiling <= 0:
            raise ValueError("invalid commissioned discharge ceiling")
        native = min(ceiling / factor, maximum)
        native = minimum + ((native - minimum) / step).to_integral_value(
            rounding=ROUND_FLOOR
        ) * step
        kw = float(native * factor)
        if kw <= 0 or round(kw, 3) != kw:
            raise ValueError("maximum is not representable by the existing FoxESS planner")
        return kw

    def _native_plan(self, plan: FoxessCommandPlan) -> FoxessCommandPlan:
        assert self._entities is not None
        commands = []
        for command in plan.commands:
            if command.action in {"set_charge_power", "set_discharge_power"}:
                entity = (
                    self._entities.force_charge_power_entity
                    if command.action == "set_charge_power"
                    else self._entities.force_discharge_power_entity
                )
                _, _, _, factor = _number_metadata(self.hass.states.get(entity))
                value = float(Decimal(str(command.value)) / factor)
                command = FoxessCommand(command.action, value, command.wait_seconds)
            commands.append(command)
        return FoxessCommandPlan(tuple(commands), plan.reason)

    def _metadata_signature(self) -> tuple[object, ...]:
        assert self._entities is not None
        states = [self.hass.states.get(entity) for entity in asdict(self._entities).values()]
        return tuple(
            tuple((key, repr(state.attributes.get(key))) for key in (
                "options", "min", "max", "step", "unit_of_measurement"
            )) if state is not None else None
            for state in states
        )

    async def _persist(self) -> None:
        async with self._save_lock:
            cancelled = False
            while True:
                generation = self._generation
                try:
                    saving = asyncio.create_task(self._repository.async_save(self._payload()))
                    try:
                        await asyncio.shield(saving)
                    except asyncio.CancelledError:
                        # The ordering fence may already have cancelled an old
                        # plan. Finish its journal write before propagating task
                        # cancellation, so restart cannot revive the old target.
                        cancelled = True
                        await saving
                except Exception as err:
                    self._hold, self._storage_fault = True, True
                    self._command_confirmed = False
                    self._status = "manual_storage_unavailable"
                    self._notify()
                    raise ManualInverterError("manual handoff could not be persisted") from err
                if generation == self._generation:
                    self._durable_generation = generation
                    self._storage_fault = False
                    if cancelled:
                        raise asyncio.CancelledError
                    return

    def _payload(self) -> dict[str, object]:
        return {
            "target": self._target, "phase": self._phase, "generation": self._generation,
            "entities": asdict(self._entities) if self._entities else None,
            "request_id": self._last_request_id,
            "issued_at": self._last_issued_at.isoformat() if self._last_issued_at else None,
            "local_control_confirmed": self._local_control_confirmed,
            "attempts": self._attempts,
            "next_retry_at": self._next_retry_at.isoformat() if self._next_retry_at else None,
        }

    def _restore(self, payload: object) -> None:
        payload = decode_manual_inverter_journal(payload)
        if payload is None:
            raise ValueError("missing journal")
        self._target, self._phase, self._generation = (
            payload["target"], payload["phase"], payload["generation"]
        )
        self._entities = (
            FoxessEntityMap(**payload["entities"])
            if payload["entities"] is not None and self._phase != "idle" else None
        )
        self._last_request_id = payload.get("request_id")
        self._last_issued_at = (
            _aware_datetime(payload["issued_at"]) if payload.get("issued_at") else None
        )
        self._local_control_confirmed = payload["local_control_confirmed"]
        self._attempts = payload.get("attempts", 0)
        self._next_retry_at = (
            _aware_datetime(payload["next_retry_at"]) if payload.get("next_retry_at") else None
        )
        self._hold = self._phase != "idle"

    def _response(
        self, accepted: bool, request_id: str | None, *, status: str | None = None
    ) -> dict[str, object]:
        return {
            "accepted": accepted,
            "command_confirmed": self._confirmed_now(),
            "target": self._target, "status": status or self._status,
            "hold": self._hold, "power_kw": self._power_kw,
            "generation": self._generation, "request_id": request_id,
            "current_request_id": self._last_request_id,
        }

    def _confirmed_now(self) -> bool:
        if not self._command_confirmed or self._stopped:
            return False
        entities = self._entities or self._current_entities()
        if entities is None:
            return False
        observation = capture_foxess_feedback(self.hass, entities).observation
        if observation is None or self._power_kw is None:
            return False
        return foxess_response_matches(
            ControlDecision(
                "force_discharge" if self._target == "export_max" else "restore_self_use",
                self._power_kw, "manual_feedback_confirmation",
            ),
            observation,
        )

    def _notify(self) -> None:
        self.coordinator.async_update_listeners()


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("request timestamp must be ISO 8601")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("request timestamp must include its timezone")
    return stamp


def decode_manual_inverter_journal(payload: object) -> dict[str, object] | None:
    """Validate the versioned manual ownership journal without releasing a fence."""
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("manual journal must be an object")
    target, phase, generation = payload["target"], payload["phase"], payload["generation"]
    if (
        target not in _TARGETS or phase not in _PHASES or type(generation) is not int
        or generation < 0 or (phase == "idle" and target != "automatic")
        or type(payload["local_control_confirmed"]) is not bool
        or (target == "export_max" and not payload["local_control_confirmed"])
    ):
        raise ValueError("invalid manual journal")
    raw_entities = payload["entities"]
    if raw_entities is not None and not isinstance(raw_entities, dict):
        raise ValueError("invalid original actuator mapping")
    entities = FoxessEntityMap(**raw_entities) if isinstance(raw_entities, dict) else None
    if entities is None and phase in {"held", "confirming"}:
        raise ValueError("missing original actuator mapping")
    if entities is not None and any(
        not isinstance(value, str) or not value.strip() for value in asdict(entities).values()
    ):
        raise ValueError("invalid original actuator mapping")
    attempts = payload.get("attempts", 0)
    if type(attempts) is not int or attempts < 0:
        raise ValueError("invalid retry state")
    request_id = payload.get("request_id")
    if request_id is not None and (not isinstance(request_id, str) or not request_id):
        raise ValueError("invalid request identity")
    issued = _aware_datetime(payload["issued_at"]) if payload.get("issued_at") else None
    if payload.get("next_retry_at"):
        _aware_datetime(payload["next_retry_at"])
    if generation > 0 and issued is None:
        raise ValueError("missing request ordering evidence")
    return dict(payload)


def _number_metadata(state: Any) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Validate native bounds, including representable zero for cleanup."""
    if state is None:
        raise ValueError("missing native power entity")
    attributes = state.attributes
    factor = Decimal(str(power_to_kw(1.0, attributes.get("unit_of_measurement"))))
    minimum = Decimal(str(attributes["min"]))
    maximum = Decimal(str(attributes["max"]))
    step = Decimal(str(attributes["step"]))
    if (
        not all(value.is_finite() for value in (minimum, maximum, step, factor))
        or minimum > 0 or maximum < 0 or step <= 0
        or (-minimum / step) != (-minimum / step).to_integral_value()
    ):
        raise ValueError("native power bounds must represent zero and a positive target")
    return minimum, maximum, step, factor
