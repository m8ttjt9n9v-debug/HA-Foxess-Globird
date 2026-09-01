"""UI-only setup and reconfiguration flow for the observer."""

from __future__ import annotations

import math

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback, valid_entity_id
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_FLOOR,
    CONF_BATTERY_SOC,
    CONF_EV_MAX_CURRENT,
    CONF_EV_MIN_CURRENT,
    CONF_EV_SOC,
    CONF_EV_VOLTAGE,
    CONF_GRID_IMPORT_POSITIVE,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_RESERVE,
    DEFAULT_BATTERY_FLOOR,
    DEFAULT_EV_MAX_CURRENT,
    DEFAULT_EV_MIN_CURRENT,
    DEFAULT_EV_VOLTAGE,
    DEFAULT_RESERVE_KWH,
    DOMAIN,
)

ENTITY = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create and maintain one observer per independently configured site."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, object] | None = None):
        """Collect the mappings and site limits required by the observer."""
        if user_input is not None:
            errors = self._validate_input(user_input)
            if errors:
                return self.async_show_form(
                    step_id="user", data_schema=self._schema(), errors=errors
                )
            title = str(user_input.pop(CONF_NAME))
            await self.async_set_unique_id(title.strip().casefold())
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=title, data=user_input)
        return self.async_show_form(step_id="user", data_schema=self._schema())

    async def async_step_reconfigure(self, user_input: dict[str, object] | None = None):
        """Update mappings and commissioned limits without reinstalling."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            errors = self._validate_input(user_input)
            if not errors:
                title = str(user_input.pop(CONF_NAME))
                return self.async_update_reload_and_abort(
                    entry,
                    title=title,
                    data_updates=user_input,
                    reason="reconfigure_successful",
                )
            return self.async_show_form(
                step_id="reconfigure", data_schema=self._schema(entry.data), errors=errors
            )
        return self.async_show_form(
            step_id="reconfigure", data_schema=self._schema({CONF_NAME: entry.title, **entry.data})
        )

    @staticmethod
    @callback
    def _schema(defaults: dict[str, object] | None = None) -> vol.Schema:
        """Keep setup and reconfigure field definitions identical."""
        defaults = defaults or {}
        return vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default=defaults.get(CONF_NAME, "Home Energy")
                ): selector.TextSelector(),
                vol.Required(CONF_BATTERY_SOC, default=defaults.get(CONF_BATTERY_SOC)): ENTITY,
                vol.Required(
                    CONF_BATTERY_CAPACITY, default=defaults.get(CONF_BATTERY_CAPACITY, 10.0)
                ): vol.Coerce(float),
                vol.Required(
                    CONF_BATTERY_FLOOR,
                    default=defaults.get(CONF_BATTERY_FLOOR, DEFAULT_BATTERY_FLOOR),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_RESERVE, default=defaults.get(CONF_RESERVE, DEFAULT_RESERVE_KWH)
                ): vol.Coerce(float),
                vol.Required(CONF_GRID_POWER, default=defaults.get(CONF_GRID_POWER)): ENTITY,
                vol.Required(
                    CONF_GRID_IMPORT_POSITIVE,
                    default=defaults.get(CONF_GRID_IMPORT_POSITIVE, True),
                ): selector.BooleanSelector(),
                vol.Optional(CONF_HOUSE_LOAD, default=defaults.get(CONF_HOUSE_LOAD)): ENTITY,
                vol.Optional(CONF_EV_SOC, default=defaults.get(CONF_EV_SOC)): ENTITY,
                vol.Required(
                    CONF_EV_MIN_CURRENT,
                    default=defaults.get(CONF_EV_MIN_CURRENT, DEFAULT_EV_MIN_CURRENT),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_MAX_CURRENT,
                    default=defaults.get(CONF_EV_MAX_CURRENT, DEFAULT_EV_MAX_CURRENT),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_VOLTAGE, default=defaults.get(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE)
                ): vol.Coerce(float),
            }
        )

    @staticmethod
    def _validate_input(data: dict[str, object]) -> dict[str, str]:
        """Reject malformed IDs and unsafe physical limits before saving them."""
        if not str(data.get(CONF_NAME, "")).strip():
            return {CONF_NAME: "invalid_name"}
        for key in (CONF_BATTERY_SOC, CONF_GRID_POWER, CONF_HOUSE_LOAD, CONF_EV_SOC):
            entity_id = data.get(key)
            if entity_id is not None and not valid_entity_id(str(entity_id)):
                return {key: "invalid_entity"}
        try:
            capacity = float(data[CONF_BATTERY_CAPACITY])
            floor = float(data[CONF_BATTERY_FLOOR])
            reserve = float(data[CONF_RESERVE])
            min_current = float(data[CONF_EV_MIN_CURRENT])
            max_current = float(data[CONF_EV_MAX_CURRENT])
            voltage = float(data[CONF_EV_VOLTAGE])
        except (KeyError, TypeError, ValueError):
            return {"base": "invalid_site_limits"}
        values = (capacity, floor, reserve, min_current, max_current, voltage)
        if (
            not all(math.isfinite(value) for value in values)
            or capacity <= 0
            or not 0 <= floor <= 100
            or reserve < 0
            or min_current < 0
            or max_current < min_current
            or voltage <= 0
        ):
            return {"base": "invalid_site_limits"}
        return {}
