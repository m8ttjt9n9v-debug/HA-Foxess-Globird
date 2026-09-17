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
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store


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

    def record_service_call(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any],
    ) -> None:
        """Record one service invocation at its awaited call boundary."""
        self._service_calls.append(
            ServiceCallTrace(
                domain=domain,
                service=service,
                service_data=deepcopy(service_data),
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

    async def save_store(
        self,
        key: str,
        payload: dict[str, Any],
        *,
        version: int = 1,
    ) -> None:
        """Seed one private Home Assistant store for restart reconstruction."""
        store: Store[dict[str, Any]] = Store(
            self.hass, version, key, private=True
        )
        await store.async_save(deepcopy(payload))

    async def load_store(
        self,
        key: str,
        *,
        version: int = 1,
    ) -> dict[str, Any] | None:
        """Read one private store without exposing controller internals."""
        store: Store[dict[str, Any]] = Store(
            self.hass, version, key, private=True
        )
        return await store.async_load()

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
        """Close the harness (reserved for future owned resources)."""
