"""Deterministic Home Assistant lifecycle trace helpers.

The harness deliberately records public states and service calls rather than
controller-private implementation details. Incident fixtures can therefore
remain stable while internal boundaries are improved.
"""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_CALL_SERVICE, STATE_UNAVAILABLE
from homeassistant.core import Event, HomeAssistant


@dataclass(frozen=True, slots=True)
class EntityStateTrace:
    """One stable public entity observation."""

    entity_id: str
    state: str
    attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ServiceCallTrace:
    """One ordered Home Assistant service-call observation."""

    domain: str
    service: str
    service_data: dict[str, Any]


class LifecycleHarness:
    """Drive setup/reload while recording public outcomes."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._service_calls: list[ServiceCallTrace] = []
        self._unsub_service_calls = hass.bus.async_listen(
            EVENT_CALL_SERVICE, self._record_service_call
        )

    def _record_service_call(self, event: Event) -> None:
        self._service_calls.append(
            ServiceCallTrace(
                domain=event.data["domain"],
                service=event.data["service"],
                service_data=deepcopy(event.data.get("service_data", {})),
            )
        )

    @property
    def service_calls(self) -> tuple[ServiceCallTrace, ...]:
        """Return service calls in exact observed order."""
        return tuple(self._service_calls)

    def clear_service_calls(self) -> None:
        """Start a new command-trace segment."""
        self._service_calls.clear()

    async def setup(self, entry: ConfigEntry) -> None:
        """Set up one config entry and drain scheduled work."""
        assert await self.hass.config_entries.async_setup(entry.entry_id)
        await self.hass.async_block_till_done()

    async def unload(self, entry: ConfigEntry) -> None:
        """Unload one config entry and drain scheduled work."""
        assert await self.hass.config_entries.async_unload(entry.entry_id)
        await self.hass.async_block_till_done()

    async def reload(self, entry: ConfigEntry) -> None:
        """Reload one config entry and drain scheduled work."""
        assert await self.hass.config_entries.async_reload(entry.entry_id)
        await self.hass.async_block_till_done()

    async def set_state(
        self,
        entity_id: str,
        state: str | float | int,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Publish one input state and drain state-change listeners."""
        self.hass.states.async_set(entity_id, str(state), attributes or {})
        await self.hass.async_block_till_done()

    async def set_unavailable(self, entity_id: str) -> None:
        """Make one input explicitly unavailable."""
        self.hass.states.async_set(entity_id, STATE_UNAVAILABLE)
        await self.hass.async_block_till_done()

    async def remove_state(self, entity_id: str) -> None:
        """Remove one input state and drain state-change listeners."""
        self.hass.states.async_remove(entity_id)
        await self.hass.async_block_till_done()

    def states(
        self,
        entity_ids: Iterable[str],
        *,
        ignored_attributes: frozenset[str] = frozenset(),
    ) -> tuple[EntityStateTrace, ...]:
        """Snapshot selected public states without volatile attributes."""
        result: list[EntityStateTrace] = []
        for entity_id in sorted(entity_ids):
            state = self.hass.states.get(entity_id)
            assert state is not None, f"Missing expected entity {entity_id}"
            result.append(
                EntityStateTrace(
                    entity_id=entity_id,
                    state=state.state,
                    attributes={
                        key: deepcopy(value)
                        for key, value in state.attributes.items()
                        if key not in ignored_attributes
                    },
                )
            )
        return tuple(result)

    def close(self) -> None:
        """Remove the harness event listener."""
        self._unsub_service_calls()
