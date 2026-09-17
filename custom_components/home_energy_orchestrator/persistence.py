"""Typed persistence mechanics around Home Assistant Store instances."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from homeassistant.helpers.storage import Store


class RestorableState(Protocol):
    """State with an existing payload contract owned by its domain model."""

    def restore(self, payload: dict[str, object] | None, now: datetime) -> None:
        """Restore a payload or the safe empty fallback."""

    def to_payload(self) -> dict[str, object]:
        """Return the unchanged Store payload."""


RestoreStatus = Literal["restored", "missing", "invalid"]


@dataclass(slots=True)
class TypedStoreRepository[StateT: RestorableState]:
    """Load and save one typed state without changing its Store envelope."""

    store: Store[dict[str, object]]

    async def async_restore(self, state: StateT, now: datetime) -> RestoreStatus:
        """Restore state, falling back safely for an invalid outer payload."""
        payload = await self.store.async_load()
        if payload is not None and not isinstance(payload, dict):
            state.restore(None, now)
            return "invalid"
        try:
            state.restore(payload, now)
        except (KeyError, OverflowError, TypeError, ValueError):
            state.restore(None, now)
            return "invalid"
        return "missing" if payload is None else "restored"

    async def async_save(self, state: StateT) -> None:
        """Save the domain model's existing payload without an extra wrapper."""
        await self.store.async_save(state.to_payload())


@dataclass(slots=True)
class TypedValueStoreRepository[StateT]:
    """Persist state whose domain decoder returns a replacement value."""

    store: Store[dict[str, object]]
    decode: Callable[[dict[str, object] | None], StateT]
    encode: Callable[[StateT], dict[str, object]]
    last_restore_status: RestoreStatus = field(default="missing", init=False)

    async def async_load(self) -> StateT:
        """Decode stored state or return the decoder's safe fallback."""
        payload = await self.store.async_load()
        if payload is not None and not isinstance(payload, dict):
            self.last_restore_status = "invalid"
            return self.decode(None)
        try:
            state = self.decode(payload)
        except (KeyError, OverflowError, TypeError, ValueError):
            self.last_restore_status = "invalid"
            return self.decode(None)
        self.last_restore_status = "missing" if payload is None else "restored"
        return state

    async def async_save(self, state: StateT) -> None:
        """Save the domain encoder's existing payload without an extra wrapper."""
        await self.store.async_save(self.encode(state))
