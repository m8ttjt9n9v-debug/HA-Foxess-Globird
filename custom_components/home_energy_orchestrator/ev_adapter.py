"""Fail-closed EV adapter for explicitly commissioned Home Assistant entities."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from .planner.ev import EvCommand, EvCommandPlan


class EvWriteBlocked(RuntimeError):
    """Raised when an EV command is attempted without explicit write permission."""


@dataclass(frozen=True, slots=True)
class EvEntityMap:
    """Exact entities that an EV profile has permission to write."""

    charge_limit_entity: str | None = None
    current_limit_entity: str | None = None
    charge_switch_entity: str | None = None


class EvServiceAdapter:
    """Execute an adapter-neutral EV plan through Home Assistant services."""

    def __init__(
        self, hass: HomeAssistant, entities: EvEntityMap, *, allow_writes: bool = False
    ) -> None:
        if not any(
            entity and entity.strip()
            for entity in (
                entities.charge_limit_entity,
                entities.current_limit_entity,
                entities.charge_switch_entity,
            )
        ):
            raise ValueError("at least one EV actuator entity must be explicitly mapped")
        self.hass = hass
        self.entities = entities
        self.allow_writes = allow_writes
        self._lock = asyncio.Lock()

    async def async_execute(self, plan: EvCommandPlan) -> tuple[str, ...]:
        """Execute commands in order, or fail before the first write."""
        if not plan.commands:
            return ()
        if not self.allow_writes:
            raise EvWriteBlocked("EV writes are disabled until commissioning")
        async with self._lock:
            executed: list[str] = []
            for command in plan.commands:
                await self._async_execute_command(command)
                executed.append(command.action)
            return tuple(executed)

    async def _async_execute_command(self, command: EvCommand) -> None:
        if command.action == "set_charge_limit":
            entity_id = self.entities.charge_limit_entity
            domain = "number"
            service = "set_value"
            data = {"value": command.value}
        elif command.action == "set_current":
            entity_id = self.entities.current_limit_entity
            domain = "number"
            service = "set_value"
            data = {"value": command.value}
        elif command.action == "turn_on_charge":
            entity_id = self.entities.charge_switch_entity
            domain = "switch"
            service = "turn_on"
            data = {}
        elif command.action == "turn_off_charge":
            entity_id = self.entities.charge_switch_entity
            domain = "switch"
            service = "turn_off"
            data = {}
        else:
            raise ValueError(f"unsupported EV command: {command.action}")
        if not entity_id:
            raise ValueError(f"no mapped entity for EV command: {command.action}")
        await self.hass.services.async_call(
            domain, service, data, target={"entity_id": entity_id}, blocking=True
        )
