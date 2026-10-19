"""Read the native Amber price entity; no API client, key or second poller.

The native entity state is a tariff. Only its confirmed five-minute wholesale
attribute can supply this adapter. The operator explicitly binds its NEM region.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from math import isfinite

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_CHANNELS = {"general": "general", "feedIn": "feed_in", "controlledLoad": "controlled_load"}


@dataclass(frozen=True, slots=True)
class AmberPriceSample:
    """Validated native evidence, with no invented AEMO market-quality flags."""

    status: str
    entity_id: str | None
    price_per_kwh: float | None = None
    interval_start: datetime | None = None
    interval_end: datetime | None = None
    updated_at: datetime | None = None


def _aware(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)
    except (OverflowError, ValueError, TypeError):
        return None


def capture_amber_price(
    hass: HomeAssistant,
    entity_id: str | None,
    bound_region: str | None,
    market_region: str | None,
    now: datetime,
) -> AmberPriceSample:
    """Require native provenance, explicit matching region and current confirmation."""

    def rejected(reason: str) -> AmberPriceSample:
        return AmberPriceSample(reason, entity_id)

    if not entity_id:
        return rejected("not_configured")
    if bound_region is None or bound_region != market_region:
        return rejected("region_mismatch")
    current = _aware(now)
    if current is None:
        return rejected("invalid_clock")
    registry = er.async_get(hass).async_get(entity_id)
    if (
        registry is None
        or registry.platform != "amberelectric"
        or registry.disabled_by is not None
        or not registry.config_entry_id
    ):
        return rejected("invalid_native_source")
    provider = hass.config_entries.async_get_entry(registry.config_entry_id)
    if (
        provider is None
        or provider.domain != "amberelectric"
        or provider.state != ConfigEntryState.LOADED
    ):
        return rejected("provider_unloaded")
    state = hass.states.get(entity_id)
    if state is None or state.state in {"unavailable", "unknown"}:
        return rejected("unavailable")
    attributes = state.attributes
    raw_channel = attributes.get("channel_type")
    channel = _CHANNELS.get(raw_channel) if isinstance(raw_channel, str) else None
    site_id = provider.data.get("site_id")
    if (
        not isinstance(site_id, str)
        or not site_id
        or channel is None
        or registry.unique_id != f"{site_id}-current-{channel}"
        or attributes.get("restored", False) is not False
        or attributes.get("unit_of_measurement") != "$/kWh"
    ):
        return rejected("invalid_native_source")
    if type(attributes.get("duration")) is not int or attributes["duration"] != 5:
        return rejected("not_five_minute")
    if attributes.get("estimate") is not False:
        return rejected("unconfirmed")
    start, end = _aware(attributes.get("start_time")), _aware(attributes.get("end_time"))
    updated = _aware(state.last_updated)
    if start is None or end is None or updated is None:
        return rejected("invalid_interval")
    try:
        canonical_start = end - timedelta(minutes=5)
    except OverflowError:
        return rejected("invalid_interval")
    # Amber's native API commonly reports hh:mm:01 through hh:mm+5:00 (299s).
    # Both that convention and an exact 300s interval denote the same NEM block.
    if (
        end.minute % 5
        or end.second
        or end.microsecond
        or start not in (canonical_start, canonical_start + timedelta(seconds=1))
    ):
        return rejected("invalid_interval")
    if current < canonical_start:
        return rejected("future")
    if current >= end:
        return rejected("stale")
    if not canonical_start <= updated <= current:
        return rejected("invalid_source_clock")
    spot = attributes.get("spot_per_kwh")
    if isinstance(spot, bool) or not isinstance(spot, (int, float)):
        return rejected("invalid_wholesale_price")
    try:
        # HA already converted the API's cents into dollars. Remove GST once.
        # Decimal preserves the inclusive $3 boundary: float(3.3 / 1.1) does not.
        price = float(Decimal(str(spot)) / Decimal("1.1"))
    except (InvalidOperation, OverflowError, ValueError):
        return rejected("invalid_wholesale_price")
    if not isfinite(price):
        return rejected("invalid_wholesale_price")
    return AmberPriceSample("confirmed", entity_id, price, canonical_start, end, updated)
