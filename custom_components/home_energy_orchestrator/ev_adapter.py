"""Fail-closed Home Assistant adapter for explicitly mapped Tessie controls."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from .const import (
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_EV_CONTROL_COMMISSIONED,
    CONF_REHEARSAL_MODE,
    CONF_SITE_GRID_CURRENT,
    CONF_SITE_PHASE_COUNT,
    DEFAULT_SITE_PHASE_COUNT,
    EV_REQUIRED_ENTITY_KEYS,
)
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
        self,
        hass: HomeAssistant,
        entities: EvEntityMap,
        *,
        allow_writes: bool = False,
        write_guard: Callable[[], bool] | None = None,
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
        self.write_guard = write_guard
        self._lock = asyncio.Lock()
        self.last_executed: tuple[str, ...] = ()

    async def async_execute(self, plan: EvCommandPlan) -> tuple[str, ...]:
        """Execute commands in order, or fail before the first write."""
        if not plan.commands:
            return ()
        async with self._lock:
            self.last_executed = ()
            if not self.allow_writes or (
                self.write_guard is not None and not self.write_guard()
            ):
                raise EvWriteBlocked("EV writes are disabled until commissioning")
            executed: list[str] = []
            for command in plan.commands:
                if self.write_guard is not None and not self.write_guard():
                    raise EvWriteBlocked("EV write gate closed during command plan")
                await self._async_execute_command(command)
                executed.append(command.action)
                self.last_executed = tuple(executed)
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


def ev_control_gate_status(
    config: dict[str, object], *, adapter_connected: bool = False
) -> str:
    """Return an honest, ordered EV authorization status."""
    if not config.get(CONF_EV_AUTOMATIC_CONTROL_ENABLED, False):
        return "disabled"
    if config.get(CONF_REHEARSAL_MODE, True):
        return "safety_locked"
    if not config.get(CONF_EV_CONTROL_COMMISSIONED, False):
        return "not_commissioned"
    if not all(config.get(key) for key in EV_REQUIRED_ENTITY_KEYS):
        return "incomplete_mapping"
    try:
        site_phases = float(config.get(CONF_SITE_PHASE_COUNT, DEFAULT_SITE_PHASE_COUNT))
    except (TypeError, ValueError):
        return "invalid_site_topology"
    if site_phases > 1 and not config.get(CONF_SITE_GRID_CURRENT):
        return "multiphase_current_mapping_required"
    return "ready" if adapter_connected else "adapter_not_connected"
