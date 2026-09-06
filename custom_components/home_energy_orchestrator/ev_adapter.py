"""Fail-closed Home Assistant adapter for explicitly mapped Tessie controls."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from .planner.ev import EvCommand, EvCommandPlan


class EvWriteBlocked(RuntimeError):
    """Raised when an EV command is attempted without explicit permission."""


@dataclass(frozen=True, slots=True)
class EvEntityMap:
    """Exact writable entities commissioned for one vehicle."""

    charge_current_entity: str
    charge_limit_entity: str
    charge_switch_entity: str


class EvServiceAdapter:
    """Execute a reviewed direct-EVSE plan through Home Assistant services."""

    def __init__(
        self, hass: HomeAssistant, entities: EvEntityMap, *, allow_writes: bool = False
    ) -> None:
        if any(
            not entity.strip()
            for entity in (
                entities.charge_current_entity,
                entities.charge_limit_entity,
                entities.charge_switch_entity,
            )
        ):
            raise ValueError("all EV actuator entities must be explicitly mapped")
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
        if command.action == "set_charge_current":
            entity_id = self.entities.charge_current_entity
            await self.hass.services.async_call(
                "number",
                "set_value",
                {"value": command.value},
                target={"entity_id": entity_id},
                blocking=True,
            )
        elif command.action == "set_charge_limit":
            entity_id = self.entities.charge_limit_entity
            await self.hass.services.async_call(
                "number",
                "set_value",
                {"value": command.value},
                target={"entity_id": entity_id},
                blocking=True,
            )
        elif command.action == "start_charging":
            await self.hass.services.async_call(
                "switch",
                "turn_on",
                target={"entity_id": self.entities.charge_switch_entity},
                blocking=True,
            )
        else:
            raise ValueError(f"unsupported EV command: {command.action}")
