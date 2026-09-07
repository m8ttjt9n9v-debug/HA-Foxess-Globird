"""UI-only setup and reconfiguration flow for the observer."""

from __future__ import annotations

import math
from datetime import time

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback, valid_entity_id
from homeassistant.helpers import selector

from .const import (
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_CHARGE_EFFICIENCY,
    CONF_BATTERY_FLOOR,
    CONF_BATTERY_FREE_WINDOW_TARGET,
    CONF_BATTERY_SOC,
    CONF_BONUS_WINDOW_END,
    CONF_BONUS_WINDOW_START,
    CONF_DAILY_CHARGE,
    CONF_DAILY_FREE_ALLOWANCE_KWH,
    CONF_DAILY_IMPORT_ENTITY,
    CONF_DISCHARGE_EFFICIENCY_PERCENT,
    CONF_EV_ACTUAL_CURRENT,
    CONF_EV_ALLOWANCE_GUARD_ENABLED,
    CONF_EV_ALLOWANCE_SAFETY_MARGIN,
    CONF_EV_AT_HOME,
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_EV_CABLE_CONNECTED,
    CONF_EV_CHARGE_EFFICIENCY,
    CONF_EV_CHARGE_LIMIT,
    CONF_EV_CHARGE_SWITCH,
    CONF_EV_CHARGE_TO_FULL,
    CONF_EV_CHARGING_STATE,
    CONF_EV_CONTROL_COMMISSIONED,
    CONF_EV_CURRENT_LIMIT,
    CONF_EV_DIRECT_LIMIT_HEADROOM,
    CONF_EV_FREE_WINDOW_CHARGE_LIMIT,
    CONF_EV_FREE_WINDOW_MINIMUM_CURRENT,
    CONF_EV_FREE_WINDOW_PRIORITY,
    CONF_EV_FREE_WINDOW_SETTLE_MINUTES,
    CONF_EV_LOCATION_MODE,
    CONF_EV_MAX_CURRENT,
    CONF_EV_MIN_CURRENT,
    CONF_EV_PHASE_COUNT,
    CONF_EV_PROTECTED_BASELINE_A,
    CONF_EV_SOC,
    CONF_EV_STORED_ENERGY,
    CONF_EV_VOLTAGE,
    CONF_EXPORT_ALLOWANCE_KWH,
    CONF_EXPORT_DISCHARGE_POWER_KW,
    CONF_EXPORT_LIMIT_KW,
    CONF_EXPORT_RATE,
    CONF_FORCE_DISCHARGE_FINISH,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_FREE_CHARGE_END,
    CONF_FREE_CHARGE_START,
    CONF_GRID_IMPORT_POSITIVE,
    CONF_GRID_POWER,
    CONF_HOUSE_LEARNING_FALLBACK,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_OFFPEAK_BALANCE_RATE,
    CONF_OFFPEAK_RATE,
    CONF_PEAK_RATE,
    CONF_PEAK_WINDOW_END,
    CONF_PEAK_WINDOW_START,
    CONF_REHEARSAL_MODE,
    CONF_RESERVE,
    CONF_SERVICE_IMPORT_LIMIT_A,
    CONF_SHOULDER_RATE,
    CONF_SITE_GRID_CURRENT,
    CONF_SITE_GRID_HEADROOM_CURRENT,
    CONF_SITE_PHASE_COUNT,
    CONF_SOLAR_POWER,
    CONF_SUPER_EXPORT_RATE,
    CONF_ZERO_IMPORT_CONFIRM_MINUTES,
    CONF_ZERO_IMPORT_THRESHOLD_KW,
    DEFAULT_AUTOMATIC_CONTROL_ENABLED,
    DEFAULT_AUTOMATIC_EXPORT_ENABLED,
    DEFAULT_BATTERY_CHARGE_EFFICIENCY,
    DEFAULT_BATTERY_FLOOR,
    DEFAULT_BATTERY_FREE_WINDOW_TARGET,
    DEFAULT_BONUS_WINDOW_END,
    DEFAULT_BONUS_WINDOW_START,
    DEFAULT_DAILY_CHARGE,
    DEFAULT_DAILY_FREE_ALLOWANCE_KWH,
    DEFAULT_DISCHARGE_EFFICIENCY_PERCENT,
    DEFAULT_EV_ALLOWANCE_GUARD_ENABLED,
    DEFAULT_EV_ALLOWANCE_SAFETY_MARGIN,
    DEFAULT_EV_AUTOMATIC_CONTROL_ENABLED,
    DEFAULT_EV_CHARGE_EFFICIENCY,
    DEFAULT_EV_CONTROL_COMMISSIONED,
    DEFAULT_EV_DIRECT_LIMIT_HEADROOM,
    DEFAULT_EV_FREE_WINDOW_CHARGE_LIMIT,
    DEFAULT_EV_FREE_WINDOW_MINIMUM_CURRENT,
    DEFAULT_EV_FREE_WINDOW_PRIORITY,
    DEFAULT_EV_FREE_WINDOW_SETTLE_MINUTES,
    DEFAULT_EV_LOCATION_MODE,
    DEFAULT_EV_MAX_CURRENT,
    DEFAULT_EV_MIN_CURRENT,
    DEFAULT_EV_PHASE_COUNT,
    DEFAULT_EV_PROTECTED_BASELINE_A,
    DEFAULT_EV_VOLTAGE,
    DEFAULT_EXPORT_ALLOWANCE_KWH,
    DEFAULT_EXPORT_DISCHARGE_POWER_KW,
    DEFAULT_EXPORT_LIMIT_KW,
    DEFAULT_EXPORT_RATE,
    DEFAULT_FORCE_DISCHARGE_FINISH,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DEFAULT_FREE_CHARGE_END,
    DEFAULT_FREE_CHARGE_START,
    DEFAULT_HOUSE_LEARNING_FALLBACK_KWH,
    DEFAULT_INVERTER_CHARGE_LIMIT_KW,
    DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
    DEFAULT_OFFPEAK_BALANCE_RATE,
    DEFAULT_OFFPEAK_RATE,
    DEFAULT_PEAK_RATE,
    DEFAULT_PEAK_WINDOW_END,
    DEFAULT_PEAK_WINDOW_START,
    DEFAULT_REHEARSAL_MODE,
    DEFAULT_RESERVE_KWH,
    DEFAULT_SERVICE_IMPORT_LIMIT_A,
    DEFAULT_SHOULDER_RATE,
    DEFAULT_SITE_GRID_HEADROOM_CURRENT,
    DEFAULT_SITE_PHASE_COUNT,
    DEFAULT_SUPER_EXPORT_RATE,
    DEFAULT_ZERO_IMPORT_CONFIRM_MINUTES,
    DEFAULT_ZERO_IMPORT_THRESHOLD_KW,
    DOMAIN,
    EV_FREE_WINDOW_PRIORITIES,
    EV_LOCATION_MODES,
    FOXESS_CONTROL_OWNERS,
)

ENTITY = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
SELECT_ENTITY = selector.EntitySelector(selector.EntitySelectorConfig(domain="select"))
NUMBER_ENTITY = selector.EntitySelector(selector.EntitySelectorConfig(domain="number"))
SWITCH_ENTITY = selector.EntitySelector(selector.EntitySelectorConfig(domain="switch"))


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create and maintain one observer per independently configured site."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, object] | None = None):
        """Collect the mappings and site limits required by the observer."""
        if user_input is not None:
            user_input = self._apply_defaults(user_input)
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
            user_input = self._apply_defaults(user_input)
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

    @callback
    def _schema(self, defaults: dict[str, object] | None = None) -> vol.Schema:
        """Keep setup and reconfigure field definitions identical."""
        defaults = defaults or {}
        def optional_entity(key: str):
            """Require entity roles to be mapped explicitly by the user."""
            value = defaults.get(key)
            return vol.Optional(key, default=value) if value else vol.Optional(key)

        return vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default=defaults.get(CONF_NAME, "Home Energy")
                ): selector.TextSelector(),
                vol.Required(CONF_BATTERY_SOC, default=defaults.get(CONF_BATTERY_SOC)): ENTITY,
                optional_entity(CONF_BATTERY_CAPACITY_ENTITY): ENTITY,
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
                optional_entity(CONF_DAILY_IMPORT_ENTITY): ENTITY,
                vol.Required(
                    CONF_DAILY_FREE_ALLOWANCE_KWH,
                    default=defaults.get(
                        CONF_DAILY_FREE_ALLOWANCE_KWH, DEFAULT_DAILY_FREE_ALLOWANCE_KWH
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_DAILY_CHARGE, default=defaults.get(CONF_DAILY_CHARGE, DEFAULT_DAILY_CHARGE)
                ): vol.Coerce(float),
                vol.Required(
                    CONF_PEAK_WINDOW_START,
                    default=defaults.get(CONF_PEAK_WINDOW_START, DEFAULT_PEAK_WINDOW_START),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_PEAK_WINDOW_END,
                    default=defaults.get(CONF_PEAK_WINDOW_END, DEFAULT_PEAK_WINDOW_END),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_PEAK_RATE, default=defaults.get(CONF_PEAK_RATE, DEFAULT_PEAK_RATE)
                ): vol.Coerce(float),
                vol.Required(
                    CONF_OFFPEAK_RATE,
                    default=defaults.get(CONF_OFFPEAK_RATE, DEFAULT_OFFPEAK_RATE),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_OFFPEAK_BALANCE_RATE,
                    default=defaults.get(
                        CONF_OFFPEAK_BALANCE_RATE, DEFAULT_OFFPEAK_BALANCE_RATE
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_SHOULDER_RATE,
                    default=defaults.get(CONF_SHOULDER_RATE, DEFAULT_SHOULDER_RATE),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EXPORT_RATE,
                    default=defaults.get(CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_SUPER_EXPORT_RATE,
                    default=defaults.get(CONF_SUPER_EXPORT_RATE, DEFAULT_SUPER_EXPORT_RATE),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_SITE_PHASE_COUNT,
                    default=defaults.get(CONF_SITE_PHASE_COUNT, DEFAULT_SITE_PHASE_COUNT),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_SERVICE_IMPORT_LIMIT_A,
                    default=defaults.get(
                        CONF_SERVICE_IMPORT_LIMIT_A, DEFAULT_SERVICE_IMPORT_LIMIT_A
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EXPORT_LIMIT_KW,
                    default=defaults.get(CONF_EXPORT_LIMIT_KW, DEFAULT_EXPORT_LIMIT_KW),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_INVERTER_CHARGE_LIMIT_KW,
                    default=defaults.get(
                        CONF_INVERTER_CHARGE_LIMIT_KW, DEFAULT_INVERTER_CHARGE_LIMIT_KW
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_INVERTER_DISCHARGE_LIMIT_KW,
                    default=defaults.get(
                        CONF_INVERTER_DISCHARGE_LIMIT_KW, DEFAULT_INVERTER_DISCHARGE_LIMIT_KW
                    ),
                ): vol.Coerce(float),
                optional_entity(CONF_HOUSE_LOAD): ENTITY,
                optional_entity(CONF_SOLAR_POWER): ENTITY,
                vol.Required(
                    CONF_FREE_CHARGE_START,
                    default=defaults.get(CONF_FREE_CHARGE_START, DEFAULT_FREE_CHARGE_START),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_FREE_CHARGE_END,
                    default=defaults.get(CONF_FREE_CHARGE_END, DEFAULT_FREE_CHARGE_END),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_HOUSE_LEARNING_FALLBACK,
                    default=defaults.get(
                        CONF_HOUSE_LEARNING_FALLBACK, DEFAULT_HOUSE_LEARNING_FALLBACK_KWH
                    ),
                ): vol.Coerce(float),
                optional_entity(CONF_EV_SOC): ENTITY,
                vol.Required(
                    CONF_EV_VOLTAGE, default=defaults.get(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE)
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_PHASE_COUNT,
                    default=defaults.get(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_MIN_CURRENT,
                    default=defaults.get(CONF_EV_MIN_CURRENT, DEFAULT_EV_MIN_CURRENT),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_MAX_CURRENT,
                    default=defaults.get(CONF_EV_MAX_CURRENT, DEFAULT_EV_MAX_CURRENT),
                ): vol.Coerce(float),
                optional_entity(CONF_EV_AT_HOME): selector.EntitySelector(),
                optional_entity(CONF_EV_CABLE_CONNECTED): selector.EntitySelector(),
                optional_entity(CONF_EV_CHARGING_STATE): ENTITY,
                optional_entity(CONF_EV_ACTUAL_CURRENT): ENTITY,
                optional_entity(CONF_EV_STORED_ENERGY): ENTITY,
                optional_entity(CONF_EV_CURRENT_LIMIT): NUMBER_ENTITY,
                optional_entity(CONF_EV_CHARGE_LIMIT): NUMBER_ENTITY,
                optional_entity(CONF_EV_CHARGE_SWITCH): SWITCH_ENTITY,
                optional_entity(CONF_EV_CHARGE_TO_FULL): selector.EntitySelector(),
                vol.Required(
                    CONF_EV_LOCATION_MODE,
                    default=defaults.get(CONF_EV_LOCATION_MODE, DEFAULT_EV_LOCATION_MODE),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(EV_LOCATION_MODES))
                ),
                vol.Required(
                    CONF_EV_FREE_WINDOW_PRIORITY,
                    default=defaults.get(
                        CONF_EV_FREE_WINDOW_PRIORITY, DEFAULT_EV_FREE_WINDOW_PRIORITY
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(EV_FREE_WINDOW_PRIORITIES))
                ),
                vol.Required(
                    CONF_EV_FREE_WINDOW_CHARGE_LIMIT,
                    default=defaults.get(
                        CONF_EV_FREE_WINDOW_CHARGE_LIMIT,
                        DEFAULT_EV_FREE_WINDOW_CHARGE_LIMIT,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_FREE_WINDOW_MINIMUM_CURRENT,
                    default=defaults.get(
                        CONF_EV_FREE_WINDOW_MINIMUM_CURRENT,
                        DEFAULT_EV_FREE_WINDOW_MINIMUM_CURRENT,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_FREE_WINDOW_SETTLE_MINUTES,
                    default=defaults.get(
                        CONF_EV_FREE_WINDOW_SETTLE_MINUTES,
                        DEFAULT_EV_FREE_WINDOW_SETTLE_MINUTES,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_DIRECT_LIMIT_HEADROOM,
                    default=defaults.get(
                        CONF_EV_DIRECT_LIMIT_HEADROOM, DEFAULT_EV_DIRECT_LIMIT_HEADROOM
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_CHARGE_EFFICIENCY,
                    default=defaults.get(
                        CONF_EV_CHARGE_EFFICIENCY, DEFAULT_EV_CHARGE_EFFICIENCY
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_SITE_GRID_HEADROOM_CURRENT,
                    default=defaults.get(
                        CONF_SITE_GRID_HEADROOM_CURRENT,
                        DEFAULT_SITE_GRID_HEADROOM_CURRENT,
                    ),
                ): vol.Coerce(float),
                optional_entity(CONF_SITE_GRID_CURRENT): ENTITY,
                vol.Required(
                    CONF_BATTERY_FREE_WINDOW_TARGET,
                    default=defaults.get(
                        CONF_BATTERY_FREE_WINDOW_TARGET,
                        DEFAULT_BATTERY_FREE_WINDOW_TARGET,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_BATTERY_CHARGE_EFFICIENCY,
                    default=defaults.get(
                        CONF_BATTERY_CHARGE_EFFICIENCY,
                        DEFAULT_BATTERY_CHARGE_EFFICIENCY,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_ALLOWANCE_GUARD_ENABLED,
                    default=defaults.get(
                        CONF_EV_ALLOWANCE_GUARD_ENABLED,
                        DEFAULT_EV_ALLOWANCE_GUARD_ENABLED,
                    ),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_EV_ALLOWANCE_SAFETY_MARGIN,
                    default=defaults.get(
                        CONF_EV_ALLOWANCE_SAFETY_MARGIN,
                        DEFAULT_EV_ALLOWANCE_SAFETY_MARGIN,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_CONTROL_COMMISSIONED,
                    default=defaults.get(
                        CONF_EV_CONTROL_COMMISSIONED, DEFAULT_EV_CONTROL_COMMISSIONED
                    ),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_BONUS_WINDOW_START,
                    default=defaults.get(CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_BONUS_WINDOW_END,
                    default=defaults.get(CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_FORCE_DISCHARGE_FINISH,
                    default=defaults.get(
                        CONF_FORCE_DISCHARGE_FINISH, DEFAULT_FORCE_DISCHARGE_FINISH
                    ),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_EXPORT_ALLOWANCE_KWH,
                    default=defaults.get(
                        CONF_EXPORT_ALLOWANCE_KWH, DEFAULT_EXPORT_ALLOWANCE_KWH
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EXPORT_DISCHARGE_POWER_KW,
                    default=defaults.get(
                        CONF_EXPORT_DISCHARGE_POWER_KW,
                        DEFAULT_EXPORT_DISCHARGE_POWER_KW,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_DISCHARGE_EFFICIENCY_PERCENT,
                    default=defaults.get(
                        CONF_DISCHARGE_EFFICIENCY_PERCENT,
                        DEFAULT_DISCHARGE_EFFICIENCY_PERCENT,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_PROTECTED_BASELINE_A,
                    default=defaults.get(
                        CONF_EV_PROTECTED_BASELINE_A, DEFAULT_EV_PROTECTED_BASELINE_A
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_ZERO_IMPORT_THRESHOLD_KW,
                    default=defaults.get(
                        CONF_ZERO_IMPORT_THRESHOLD_KW, DEFAULT_ZERO_IMPORT_THRESHOLD_KW
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_ZERO_IMPORT_CONFIRM_MINUTES,
                    default=defaults.get(
                        CONF_ZERO_IMPORT_CONFIRM_MINUTES, DEFAULT_ZERO_IMPORT_CONFIRM_MINUTES
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_FOXESS_CONTROL_OWNER,
                    default=defaults.get(
                        CONF_FOXESS_CONTROL_OWNER, DEFAULT_FOXESS_CONTROL_OWNER
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(FOXESS_CONTROL_OWNERS))
                ),
                vol.Required(
                    CONF_AUTOMATIC_CONTROL_ENABLED,
                    default=defaults.get(
                        CONF_AUTOMATIC_CONTROL_ENABLED, DEFAULT_AUTOMATIC_CONTROL_ENABLED
                    ),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_AUTOMATIC_EXPORT_ENABLED,
                    default=defaults.get(
                        CONF_AUTOMATIC_EXPORT_ENABLED, DEFAULT_AUTOMATIC_EXPORT_ENABLED
                    ),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
                    default=defaults.get(
                        CONF_EV_AUTOMATIC_CONTROL_ENABLED,
                        DEFAULT_EV_AUTOMATIC_CONTROL_ENABLED,
                    ),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_REHEARSAL_MODE,
                    default=defaults.get(CONF_REHEARSAL_MODE, DEFAULT_REHEARSAL_MODE),
                ): selector.BooleanSelector(),
                optional_entity(CONF_FOXESS_WORK_MODE): SELECT_ENTITY,
                optional_entity(CONF_FOXESS_FORCE_CHARGE_POWER): NUMBER_ENTITY,
                optional_entity(CONF_FOXESS_FORCE_DISCHARGE_POWER): NUMBER_ENTITY,
            }
        )

    @staticmethod
    def _apply_defaults(data: dict[str, object]) -> dict[str, object]:
        """Backfill options for entries created before learning was exposed."""
        removed = {
            "ev_charger_profile",
            "inverter_capacity_kw",
            "bonus_load_following_percent",
            "non_free_load_following_percent",
            "load_following_override",
            "free_charge_full_battery_import_threshold_kwh",
        }
        cleaned = {key: value for key, value in data.items() if key not in removed}
        return {
            **cleaned,
            CONF_FREE_CHARGE_START: data.get(CONF_FREE_CHARGE_START, DEFAULT_FREE_CHARGE_START),
            CONF_FREE_CHARGE_END: data.get(CONF_FREE_CHARGE_END, DEFAULT_FREE_CHARGE_END),
            CONF_SITE_PHASE_COUNT: data.get(CONF_SITE_PHASE_COUNT, DEFAULT_SITE_PHASE_COUNT),
            CONF_DAILY_FREE_ALLOWANCE_KWH: data.get(
                CONF_DAILY_FREE_ALLOWANCE_KWH, DEFAULT_DAILY_FREE_ALLOWANCE_KWH
            ),
            CONF_DAILY_CHARGE: data.get(CONF_DAILY_CHARGE, DEFAULT_DAILY_CHARGE),
            CONF_PEAK_WINDOW_START: data.get(CONF_PEAK_WINDOW_START, DEFAULT_PEAK_WINDOW_START),
            CONF_PEAK_WINDOW_END: data.get(CONF_PEAK_WINDOW_END, DEFAULT_PEAK_WINDOW_END),
            CONF_PEAK_RATE: data.get(CONF_PEAK_RATE, DEFAULT_PEAK_RATE),
            CONF_OFFPEAK_RATE: data.get(CONF_OFFPEAK_RATE, DEFAULT_OFFPEAK_RATE),
            CONF_OFFPEAK_BALANCE_RATE: data.get(
                CONF_OFFPEAK_BALANCE_RATE, DEFAULT_OFFPEAK_BALANCE_RATE
            ),
            CONF_SHOULDER_RATE: data.get(CONF_SHOULDER_RATE, DEFAULT_SHOULDER_RATE),
            CONF_EXPORT_RATE: data.get(CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE),
            CONF_SUPER_EXPORT_RATE: data.get(
                CONF_SUPER_EXPORT_RATE, DEFAULT_SUPER_EXPORT_RATE
            ),
            CONF_SERVICE_IMPORT_LIMIT_A: data.get(
                CONF_SERVICE_IMPORT_LIMIT_A, DEFAULT_SERVICE_IMPORT_LIMIT_A
            ),
            CONF_EXPORT_LIMIT_KW: data.get(CONF_EXPORT_LIMIT_KW, DEFAULT_EXPORT_LIMIT_KW),
            CONF_INVERTER_CHARGE_LIMIT_KW: data.get(
                CONF_INVERTER_CHARGE_LIMIT_KW, DEFAULT_INVERTER_CHARGE_LIMIT_KW
            ),
            CONF_INVERTER_DISCHARGE_LIMIT_KW: data.get(
                CONF_INVERTER_DISCHARGE_LIMIT_KW, DEFAULT_INVERTER_DISCHARGE_LIMIT_KW
            ),
            CONF_HOUSE_LEARNING_FALLBACK: data.get(
                CONF_HOUSE_LEARNING_FALLBACK, DEFAULT_HOUSE_LEARNING_FALLBACK_KWH
            ),
            CONF_EV_PHASE_COUNT: data.get(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT),
            CONF_EV_MAX_CURRENT: data.get(CONF_EV_MAX_CURRENT, DEFAULT_EV_MAX_CURRENT),
            CONF_EV_LOCATION_MODE: data.get(
                CONF_EV_LOCATION_MODE, DEFAULT_EV_LOCATION_MODE
            ),
            CONF_EV_FREE_WINDOW_PRIORITY: data.get(
                CONF_EV_FREE_WINDOW_PRIORITY, DEFAULT_EV_FREE_WINDOW_PRIORITY
            ),
            CONF_EV_FREE_WINDOW_CHARGE_LIMIT: data.get(
                CONF_EV_FREE_WINDOW_CHARGE_LIMIT,
                DEFAULT_EV_FREE_WINDOW_CHARGE_LIMIT,
            ),
            CONF_EV_FREE_WINDOW_MINIMUM_CURRENT: data.get(
                CONF_EV_FREE_WINDOW_MINIMUM_CURRENT,
                DEFAULT_EV_FREE_WINDOW_MINIMUM_CURRENT,
            ),
            CONF_EV_FREE_WINDOW_SETTLE_MINUTES: data.get(
                CONF_EV_FREE_WINDOW_SETTLE_MINUTES,
                DEFAULT_EV_FREE_WINDOW_SETTLE_MINUTES,
            ),
            CONF_EV_DIRECT_LIMIT_HEADROOM: data.get(
                CONF_EV_DIRECT_LIMIT_HEADROOM, DEFAULT_EV_DIRECT_LIMIT_HEADROOM
            ),
            CONF_EV_CHARGE_EFFICIENCY: data.get(
                CONF_EV_CHARGE_EFFICIENCY, DEFAULT_EV_CHARGE_EFFICIENCY
            ),
            CONF_SITE_GRID_HEADROOM_CURRENT: data.get(
                CONF_SITE_GRID_HEADROOM_CURRENT, DEFAULT_SITE_GRID_HEADROOM_CURRENT
            ),
            CONF_BATTERY_FREE_WINDOW_TARGET: data.get(
                CONF_BATTERY_FREE_WINDOW_TARGET, DEFAULT_BATTERY_FREE_WINDOW_TARGET
            ),
            CONF_BATTERY_CHARGE_EFFICIENCY: data.get(
                CONF_BATTERY_CHARGE_EFFICIENCY, DEFAULT_BATTERY_CHARGE_EFFICIENCY
            ),
            CONF_EV_ALLOWANCE_GUARD_ENABLED: data.get(
                CONF_EV_ALLOWANCE_GUARD_ENABLED, DEFAULT_EV_ALLOWANCE_GUARD_ENABLED
            ),
            CONF_EV_ALLOWANCE_SAFETY_MARGIN: data.get(
                CONF_EV_ALLOWANCE_SAFETY_MARGIN, DEFAULT_EV_ALLOWANCE_SAFETY_MARGIN
            ),
            CONF_EV_CONTROL_COMMISSIONED: data.get(
                CONF_EV_CONTROL_COMMISSIONED, DEFAULT_EV_CONTROL_COMMISSIONED
            ),
            CONF_BONUS_WINDOW_START: data.get(
                CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START
            ),
            CONF_BONUS_WINDOW_END: data.get(CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END),
            CONF_FORCE_DISCHARGE_FINISH: data.get(
                CONF_FORCE_DISCHARGE_FINISH, DEFAULT_FORCE_DISCHARGE_FINISH
            ),
            CONF_EXPORT_ALLOWANCE_KWH: data.get(
                CONF_EXPORT_ALLOWANCE_KWH, DEFAULT_EXPORT_ALLOWANCE_KWH
            ),
            CONF_EXPORT_DISCHARGE_POWER_KW: data.get(
                CONF_EXPORT_DISCHARGE_POWER_KW, DEFAULT_EXPORT_DISCHARGE_POWER_KW
            ),
            CONF_DISCHARGE_EFFICIENCY_PERCENT: data.get(
                CONF_DISCHARGE_EFFICIENCY_PERCENT,
                DEFAULT_DISCHARGE_EFFICIENCY_PERCENT,
            ),
            CONF_EV_PROTECTED_BASELINE_A: data.get(
                CONF_EV_PROTECTED_BASELINE_A, DEFAULT_EV_PROTECTED_BASELINE_A
            ),
            CONF_ZERO_IMPORT_THRESHOLD_KW: data.get(
                CONF_ZERO_IMPORT_THRESHOLD_KW, DEFAULT_ZERO_IMPORT_THRESHOLD_KW
            ),
            CONF_ZERO_IMPORT_CONFIRM_MINUTES: data.get(
                CONF_ZERO_IMPORT_CONFIRM_MINUTES, DEFAULT_ZERO_IMPORT_CONFIRM_MINUTES
            ),
            CONF_AUTOMATIC_CONTROL_ENABLED: data.get(
                CONF_AUTOMATIC_CONTROL_ENABLED, DEFAULT_AUTOMATIC_CONTROL_ENABLED
            ),
            CONF_AUTOMATIC_EXPORT_ENABLED: data.get(
                CONF_AUTOMATIC_EXPORT_ENABLED, DEFAULT_AUTOMATIC_EXPORT_ENABLED
            ),
            CONF_EV_AUTOMATIC_CONTROL_ENABLED: data.get(
                CONF_EV_AUTOMATIC_CONTROL_ENABLED,
                DEFAULT_EV_AUTOMATIC_CONTROL_ENABLED,
            ),
            CONF_FOXESS_CONTROL_OWNER: data.get(
                CONF_FOXESS_CONTROL_OWNER, DEFAULT_FOXESS_CONTROL_OWNER
            ),
            CONF_REHEARSAL_MODE: data.get(CONF_REHEARSAL_MODE, DEFAULT_REHEARSAL_MODE),
        }

    @staticmethod
    def _validate_input(data: dict[str, object]) -> dict[str, str]:
        """Reject malformed IDs and unsafe physical limits before saving them."""
        if not str(data.get(CONF_NAME, "")).strip():
            return {CONF_NAME: "invalid_name"}
        if data.get(CONF_FOXESS_CONTROL_OWNER) not in FOXESS_CONTROL_OWNERS:
            return {CONF_FOXESS_CONTROL_OWNER: "invalid_foxess_control_owner"}
        for key in (
            CONF_BATTERY_SOC,
            CONF_BATTERY_CAPACITY_ENTITY,
            CONF_DAILY_IMPORT_ENTITY,
            CONF_GRID_POWER,
            CONF_HOUSE_LOAD,
            CONF_SOLAR_POWER,
            CONF_EV_SOC,
            CONF_EV_AT_HOME,
            CONF_EV_CABLE_CONNECTED,
            CONF_EV_CHARGING_STATE,
            CONF_EV_ACTUAL_CURRENT,
            CONF_EV_STORED_ENERGY,
            CONF_EV_CURRENT_LIMIT,
            CONF_EV_CHARGE_LIMIT,
            CONF_EV_CHARGE_SWITCH,
            CONF_EV_CHARGE_TO_FULL,
            CONF_SITE_GRID_CURRENT,
            CONF_FOXESS_WORK_MODE,
            CONF_FOXESS_FORCE_CHARGE_POWER,
            CONF_FOXESS_FORCE_DISCHARGE_POWER,
        ):
            entity_id = data.get(key)
            if entity_id is not None and not valid_entity_id(str(entity_id)):
                return {key: "invalid_entity"}
        foxess_mapping = (
            data.get(CONF_FOXESS_WORK_MODE),
            data.get(CONF_FOXESS_FORCE_CHARGE_POWER),
            data.get(CONF_FOXESS_FORCE_DISCHARGE_POWER),
        )
        if any(foxess_mapping) and not all(foxess_mapping):
            return {"base": "incomplete_foxess_mapping"}
        ev_mapping = (
            data.get(CONF_EV_SOC),
            data.get(CONF_EV_AT_HOME),
            data.get(CONF_EV_CABLE_CONNECTED),
            data.get(CONF_EV_CHARGING_STATE),
            data.get(CONF_EV_ACTUAL_CURRENT),
            data.get(CONF_EV_STORED_ENERGY),
            data.get(CONF_EV_CURRENT_LIMIT),
            data.get(CONF_EV_CHARGE_LIMIT),
            data.get(CONF_EV_CHARGE_SWITCH),
        )
        if data.get(CONF_EV_CONTROL_COMMISSIONED) and not all(ev_mapping):
            return {"base": "incomplete_ev_mapping"}
        if data.get(CONF_EV_LOCATION_MODE) not in EV_LOCATION_MODES:
            return {CONF_EV_LOCATION_MODE: "invalid_ev_location_mode"}
        if data.get(CONF_EV_FREE_WINDOW_PRIORITY) not in EV_FREE_WINDOW_PRIORITIES:
            return {CONF_EV_FREE_WINDOW_PRIORITY: "invalid_ev_priority"}
        try:
            capacity = float(data[CONF_BATTERY_CAPACITY])
            floor = float(data[CONF_BATTERY_FLOOR])
            reserve = float(data[CONF_RESERVE])
            site_phase_count = float(data[CONF_SITE_PHASE_COUNT])
            daily_allowance = float(data[CONF_DAILY_FREE_ALLOWANCE_KWH])
            service_import_limit = float(data[CONF_SERVICE_IMPORT_LIMIT_A])
            export_limit = float(data[CONF_EXPORT_LIMIT_KW])
            inverter_charge_limit = float(data[CONF_INVERTER_CHARGE_LIMIT_KW])
            inverter_discharge_limit = float(data[CONF_INVERTER_DISCHARGE_LIMIT_KW])
            min_current = float(data[CONF_EV_MIN_CURRENT])
            max_current = float(data[CONF_EV_MAX_CURRENT])
            phase_count = float(data[CONF_EV_PHASE_COUNT])
            voltage = float(data[CONF_EV_VOLTAGE])
            zero_import_threshold = float(data[CONF_ZERO_IMPORT_THRESHOLD_KW])
            zero_import_minutes = float(data[CONF_ZERO_IMPORT_CONFIRM_MINUTES])
            daily_charge = float(data[CONF_DAILY_CHARGE])
            peak_rate = float(data[CONF_PEAK_RATE])
            offpeak_rate = float(data[CONF_OFFPEAK_RATE])
            offpeak_balance_rate = float(data[CONF_OFFPEAK_BALANCE_RATE])
            shoulder_rate = float(data[CONF_SHOULDER_RATE])
            export_rate = float(data[CONF_EXPORT_RATE])
            super_export_rate = float(data[CONF_SUPER_EXPORT_RATE])
            export_allowance = float(data[CONF_EXPORT_ALLOWANCE_KWH])
            export_discharge_power = float(data[CONF_EXPORT_DISCHARGE_POWER_KW])
            discharge_efficiency = float(data[CONF_DISCHARGE_EFFICIENCY_PERCENT])
            protected_ev_baseline = float(data[CONF_EV_PROTECTED_BASELINE_A])
            ev_free_limit = float(data[CONF_EV_FREE_WINDOW_CHARGE_LIMIT])
            ev_free_minimum = float(data[CONF_EV_FREE_WINDOW_MINIMUM_CURRENT])
            ev_settle_minutes = float(data[CONF_EV_FREE_WINDOW_SETTLE_MINUTES])
            ev_limit_headroom = float(data[CONF_EV_DIRECT_LIMIT_HEADROOM])
            ev_charge_efficiency = float(data[CONF_EV_CHARGE_EFFICIENCY])
            site_headroom = float(data[CONF_SITE_GRID_HEADROOM_CURRENT])
            battery_target = float(data[CONF_BATTERY_FREE_WINDOW_TARGET])
            battery_efficiency = float(data[CONF_BATTERY_CHARGE_EFFICIENCY])
            allowance_margin = float(data[CONF_EV_ALLOWANCE_SAFETY_MARGIN])
            fallback = float(data[CONF_HOUSE_LEARNING_FALLBACK])
        except (KeyError, TypeError, ValueError):
            return {"base": "invalid_site_limits"}
        try:
            start = time.fromisoformat(str(data[CONF_FREE_CHARGE_START]))
            end = time.fromisoformat(str(data[CONF_FREE_CHARGE_END]))
            bonus_start = time.fromisoformat(str(data[CONF_BONUS_WINDOW_START]))
            bonus_end = time.fromisoformat(str(data[CONF_BONUS_WINDOW_END]))
            discharge_finish = time.fromisoformat(str(data[CONF_FORCE_DISCHARGE_FINISH]))
            peak_start = time.fromisoformat(str(data[CONF_PEAK_WINDOW_START]))
            peak_end = time.fromisoformat(str(data[CONF_PEAK_WINDOW_END]))
        except (KeyError, TypeError, ValueError):
            return {"base": "invalid_schedule"}
        if (
            start == end
            or bonus_start == bonus_end
            or discharge_finish == bonus_start
            or peak_start == peak_end
            or not math.isfinite(fallback)
            or fallback < 0
        ):
            return {"base": "invalid_schedule"}
        values = (
            capacity,
            floor,
            reserve,
            service_import_limit,
            export_limit,
            inverter_charge_limit,
            inverter_discharge_limit,
            daily_allowance,
            zero_import_threshold,
            zero_import_minutes,
            min_current,
            max_current,
            voltage,
            daily_charge,
            peak_rate,
            offpeak_rate,
            offpeak_balance_rate,
            shoulder_rate,
            export_rate,
            super_export_rate,
            export_allowance,
            export_discharge_power,
            discharge_efficiency,
            protected_ev_baseline,
            ev_free_limit,
            ev_free_minimum,
            ev_settle_minutes,
            ev_limit_headroom,
            ev_charge_efficiency,
            site_headroom,
            battery_target,
            battery_efficiency,
            allowance_margin,
        )
        if (
            not all(math.isfinite(value) for value in values)
            or capacity <= 0
            or not 0 <= floor <= 100
            or reserve < 0
            or site_phase_count < 1
            or not site_phase_count.is_integer()
            or daily_allowance < 0
            or zero_import_threshold < 0
            or zero_import_minutes < 0
            or service_import_limit < 0
            or export_limit < 0
            or inverter_charge_limit < 0
            or inverter_discharge_limit < 0
            or min_current < 0
            or max_current < min_current
            or voltage <= 0
            or phase_count < 1
            or not phase_count.is_integer()
            or export_rate < 0
            or super_export_rate < 0
            or export_allowance < 0
            or export_discharge_power < 0
            or not 50 <= discharge_efficiency <= 100
            or protected_ev_baseline < 0
            or not 0 <= ev_free_limit <= 100
            or ev_free_minimum < 0
            or ev_free_minimum > max_current
            or ev_settle_minutes < 0
            or ev_limit_headroom < 0
            or not 0 < ev_charge_efficiency <= 100
            or site_headroom < 0
            or (service_import_limit > 0 and site_headroom > service_import_limit)
            or not 0 <= battery_target <= 100
            or not 0 < battery_efficiency <= 100
            or allowance_margin < 0
            or (
                bool(data.get(CONF_EV_CONTROL_COMMISSIONED))
                and service_import_limit <= 0
            )
        ):
            return {"base": "invalid_site_limits"}
        if (
            data.get(CONF_EV_CONTROL_COMMISSIONED)
            and site_phase_count > 1
            and not data.get(CONF_SITE_GRID_CURRENT)
        ):
            return {"base": "multiphase_current_mapping_required"}
        return {}
