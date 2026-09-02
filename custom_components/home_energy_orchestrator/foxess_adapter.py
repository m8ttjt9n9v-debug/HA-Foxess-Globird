"""Fail-closed Home Assistant adapter for an explicit FoxESS profile."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from .planner.foxess import FoxessCommand, FoxessCommandPlan


class FoxessWriteBlocked(RuntimeError):
    """Raised when a command is attempted without explicit write permission."""


@dataclass(frozen=True, slots=True)
class FoxessEntityMap:
    """Exact Home Assistant entities commissioned for one FoxESS inverter."""

    work_mode_entity: str
    force_charge_power_entity: str
    force_discharge_power_entity: str


class FoxessServiceAdapter:
    """Execute an already-reviewed command plan through HA services.

    The adapter is not wired into the observer setup. A future active release
    must construct it with ``allow_writes=True`` only after commissioning.
    """

    def __init__(
        self, hass: HomeAssistant, entities: FoxessEntityMap, *, allow_writes: bool = False
    ) -> None:
        if any(
            not entity.strip()
            for entity in (
                entities.work_mode_entity,
                entities.force_charge_power_entity,
                entities.force_discharge_power_entity,
            )
        ):
            raise ValueError("all FoxESS actuator entities must be explicitly mapped")
        self.hass = hass
        self.entities = entities
        self.allow_writes = allow_writes
        self._lock = asyncio.Lock()

    async def async_execute(self, plan: FoxessCommandPlan) -> tuple[str, ...]:
        """Execute commands in order, or fail before the first write."""
        if not plan.commands:
            return ()
        if not self.allow_writes:
            raise FoxessWriteBlocked("FoxESS writes are disabled until commissioning")
        async with self._lock:
            executed: list[str] = []
            for command in plan.commands:
                await self._async_execute_command(command)
                executed.append(command.action)
            return tuple(executed)

    async def _async_execute_command(self, command: FoxessCommand) -> None:
        if command.action == "select_mode":
            await self.hass.services.async_call(
                "select",
                "select_option",
                {"option": command.value},
                target={"entity_id": self.entities.work_mode_entity},
                blocking=True,
            )
        elif command.action == "set_charge_power":
            await self.hass.services.async_call(
                "number",
                "set_value",
                {"value": command.value},
                target={"entity_id": self.entities.force_charge_power_entity},
                blocking=True,
            )
        elif command.action == "set_discharge_power":
            await self.hass.services.async_call(
                "number",
                "set_value",
                {"value": command.value},
                target={"entity_id": self.entities.force_discharge_power_entity},
                blocking=True,
            )
        else:
            raise ValueError(f"unsupported FoxESS command: {command.action}")
        if command.wait_seconds > 0:
            await asyncio.sleep(command.wait_seconds)
