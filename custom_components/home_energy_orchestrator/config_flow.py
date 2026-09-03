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
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_FLOOR,
    CONF_BATTERY_SOC,
    CONF_BONUS_LOAD_FOLLOWING_PERCENT,
    CONF_BONUS_WINDOW_END,
    CONF_BONUS_WINDOW_START,
    CONF_DAILY_CHARGE,
    CONF_DAILY_FREE_ALLOWANCE_KWH,
    CONF_DAILY_IMPORT_ENTITY,
    CONF_EV_CHARGE_LIMIT,
    CONF_EV_CHARGE_SWITCH,
    CONF_EV_CHARGER_PROFILE,
    CONF_EV_CURRENT_LIMIT,
    CONF_EV_MAX_CURRENT,
    CONF_EV_MIN_CURRENT,
    CONF_EV_PHASE_COUNT,
    CONF_EV_SOC,
    CONF_EV_VOLTAGE,
    CONF_EXPORT_LIMIT_KW,
    CONF_FOXESS_FORCE_CHARGE_POWER,
    CONF_FOXESS_FORCE_DISCHARGE_POWER,
    CONF_FOXESS_WORK_MODE,
    CONF_FREE_CHARGE_END,
    CONF_FREE_CHARGE_START,
    CONF_GRID_IMPORT_POSITIVE,
    CONF_GRID_POWER,
    CONF_HOUSE_LEARNING_FALLBACK,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_CAPACITY,
    CONF_INVERTER_CHARGE_LIMIT_KW,
    CONF_INVERTER_DISCHARGE_LIMIT_KW,
    CONF_LOAD_FOLLOWING_OVERRIDE,
    CONF_NON_FREE_LOAD_FOLLOWING_PERCENT,
    CONF_OFFPEAK_BALANCE_RATE,
    CONF_OFFPEAK_RATE,
    CONF_PEAK_RATE,
    CONF_PEAK_WINDOW_END,
    CONF_PEAK_WINDOW_START,
    CONF_RESERVE,
    CONF_SERVICE_IMPORT_LIMIT_A,
    CONF_SHOULDER_RATE,
    CONF_SITE_PHASE_COUNT,
    CONF_ZERO_IMPORT_CONFIRM_MINUTES,
    CONF_ZERO_IMPORT_THRESHOLD_KW,
    DEFAULT_BATTERY_FLOOR,
    DEFAULT_BONUS_LOAD_FOLLOWING_PERCENT,
    DEFAULT_BONUS_WINDOW_END,
    DEFAULT_BONUS_WINDOW_START,
    DEFAULT_DAILY_CHARGE,
    DEFAULT_DAILY_FREE_ALLOWANCE_KWH,
    DEFAULT_EV_CHARGER_PROFILE,
    DEFAULT_EV_MAX_CURRENT,
    DEFAULT_EV_MIN_CURRENT,
    DEFAULT_EV_PHASE_COUNT,
    DEFAULT_EV_VOLTAGE,
    DEFAULT_EXPORT_LIMIT_KW,
    DEFAULT_FREE_CHARGE_END,
    DEFAULT_FREE_CHARGE_START,
    DEFAULT_HOUSE_LEARNING_FALLBACK_KWH,
    DEFAULT_INVERTER_CAPACITY_KW,
    DEFAULT_INVERTER_CHARGE_LIMIT_KW,
    DEFAULT_INVERTER_DISCHARGE_LIMIT_KW,
    DEFAULT_LOAD_FOLLOWING_OVERRIDE,
    DEFAULT_NON_FREE_LOAD_FOLLOWING_PERCENT,
    DEFAULT_OFFPEAK_BALANCE_RATE,
    DEFAULT_OFFPEAK_RATE,
    DEFAULT_PEAK_RATE,
    DEFAULT_PEAK_WINDOW_END,
    DEFAULT_PEAK_WINDOW_START,
    DEFAULT_RESERVE_KWH,
    DEFAULT_SERVICE_IMPORT_LIMIT_A,
    DEFAULT_SHOULDER_RATE,
    DEFAULT_SITE_PHASE_COUNT,
    DEFAULT_ZERO_IMPORT_CONFIRM_MINUTES,
    DEFAULT_ZERO_IMPORT_THRESHOLD_KW,
    DOMAIN,
    EV_CHARGER_PROFILES,
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

    @staticmethod
    @callback
    def _schema(defaults: dict[str, object] | None = None) -> vol.Schema:
        """Keep setup and reconfigure field definitions identical."""
        defaults = defaults or {}
        profile_default = ConfigFlow._profile_from_data(defaults) or DEFAULT_EV_CHARGER_PROFILE

        def optional_entity(key: str):
            """Avoid passing None to Home Assistant's entity selector."""
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
                    CONF_SITE_PHASE_COUNT,
                    default=defaults.get(CONF_SITE_PHASE_COUNT, DEFAULT_SITE_PHASE_COUNT),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=["1", "3"])
                ),
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
                    CONF_EV_CHARGER_PROFILE, default=profile_default
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(EV_CHARGER_PROFILES), mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(
                    CONF_EV_VOLTAGE, default=defaults.get(CONF_EV_VOLTAGE, DEFAULT_EV_VOLTAGE)
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_MIN_CURRENT,
                    default=defaults.get(CONF_EV_MIN_CURRENT, DEFAULT_EV_MIN_CURRENT),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_INVERTER_CAPACITY,
                    default=defaults.get(CONF_INVERTER_CAPACITY, DEFAULT_INVERTER_CAPACITY_KW),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_BONUS_LOAD_FOLLOWING_PERCENT,
                    default=defaults.get(
                        CONF_BONUS_LOAD_FOLLOWING_PERCENT, DEFAULT_BONUS_LOAD_FOLLOWING_PERCENT
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_NON_FREE_LOAD_FOLLOWING_PERCENT,
                    default=defaults.get(
                        CONF_NON_FREE_LOAD_FOLLOWING_PERCENT,
                        DEFAULT_NON_FREE_LOAD_FOLLOWING_PERCENT,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_LOAD_FOLLOWING_OVERRIDE,
                    default=defaults.get(
                        CONF_LOAD_FOLLOWING_OVERRIDE, DEFAULT_LOAD_FOLLOWING_OVERRIDE
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
                optional_entity(CONF_FOXESS_WORK_MODE): SELECT_ENTITY,
                optional_entity(CONF_FOXESS_FORCE_CHARGE_POWER): NUMBER_ENTITY,
                optional_entity(CONF_FOXESS_FORCE_DISCHARGE_POWER): NUMBER_ENTITY,
                optional_entity(CONF_EV_CHARGE_LIMIT): NUMBER_ENTITY,
                optional_entity(CONF_EV_CURRENT_LIMIT): NUMBER_ENTITY,
                optional_entity(CONF_EV_CHARGE_SWITCH): SWITCH_ENTITY,
            }
        )

    @staticmethod
    def _profile_from_data(data: dict[str, object]) -> str | None:
        """Infer a supported profile only when legacy values match exactly."""
        profile = data.get(CONF_EV_CHARGER_PROFILE)
        if profile in EV_CHARGER_PROFILES:
            return str(profile)
        try:
            phase_count = int(float(data.get(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT)))
            max_current = float(data.get(CONF_EV_MAX_CURRENT, DEFAULT_EV_MAX_CURRENT))
        except (TypeError, ValueError):
            return None
        for name, (phases, current) in EV_CHARGER_PROFILES.items():
            if phase_count == phases and max_current == current:
                return name
        return None

    @staticmethod
    def _apply_defaults(data: dict[str, object]) -> dict[str, object]:
        """Backfill options for entries created before learning was exposed."""
        profile = ConfigFlow._profile_from_data(data) or DEFAULT_EV_CHARGER_PROFILE
        profile_phases, profile_current = EV_CHARGER_PROFILES[profile]
        return {
            **data,
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
            CONF_EV_CHARGER_PROFILE: profile,
            CONF_EV_PHASE_COUNT: profile_phases,
            CONF_EV_MAX_CURRENT: profile_current,
            CONF_INVERTER_CAPACITY: data.get(
                CONF_INVERTER_CAPACITY, DEFAULT_INVERTER_CAPACITY_KW
            ),
            CONF_BONUS_LOAD_FOLLOWING_PERCENT: data.get(
                CONF_BONUS_LOAD_FOLLOWING_PERCENT, DEFAULT_BONUS_LOAD_FOLLOWING_PERCENT
            ),
            CONF_NON_FREE_LOAD_FOLLOWING_PERCENT: data.get(
                CONF_NON_FREE_LOAD_FOLLOWING_PERCENT, DEFAULT_NON_FREE_LOAD_FOLLOWING_PERCENT
            ),
            CONF_LOAD_FOLLOWING_OVERRIDE: data.get(
                CONF_LOAD_FOLLOWING_OVERRIDE, DEFAULT_LOAD_FOLLOWING_OVERRIDE
            ),
            CONF_BONUS_WINDOW_START: data.get(
                CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START
            ),
            CONF_BONUS_WINDOW_END: data.get(CONF_BONUS_WINDOW_END, DEFAULT_BONUS_WINDOW_END),
            CONF_ZERO_IMPORT_THRESHOLD_KW: data.get(
                CONF_ZERO_IMPORT_THRESHOLD_KW, DEFAULT_ZERO_IMPORT_THRESHOLD_KW
            ),
            CONF_ZERO_IMPORT_CONFIRM_MINUTES: data.get(
                CONF_ZERO_IMPORT_CONFIRM_MINUTES, DEFAULT_ZERO_IMPORT_CONFIRM_MINUTES
            ),
        }

    @staticmethod
    def _validate_input(data: dict[str, object]) -> dict[str, str]:
        """Reject malformed IDs and unsafe physical limits before saving them."""
        if not str(data.get(CONF_NAME, "")).strip():
            return {CONF_NAME: "invalid_name"}
        for key in (
            CONF_BATTERY_SOC,
            CONF_BATTERY_CAPACITY_ENTITY,
            CONF_DAILY_IMPORT_ENTITY,
            CONF_GRID_POWER,
            CONF_HOUSE_LOAD,
            CONF_EV_SOC,
            CONF_FOXESS_WORK_MODE,
            CONF_FOXESS_FORCE_CHARGE_POWER,
            CONF_FOXESS_FORCE_DISCHARGE_POWER,
            CONF_EV_CHARGE_LIMIT,
            CONF_EV_CURRENT_LIMIT,
            CONF_EV_CHARGE_SWITCH,
        ):
            entity_id = data.get(key)
            if entity_id is not None and not valid_entity_id(str(entity_id)):
                return {key: "invalid_entity"}
        try:
            capacity = float(data[CONF_BATTERY_CAPACITY])
            floor = float(data[CONF_BATTERY_FLOOR])
            reserve = float(data[CONF_RESERVE])
            site_phase_count = int(float(data[CONF_SITE_PHASE_COUNT]))
            daily_allowance = float(data[CONF_DAILY_FREE_ALLOWANCE_KWH])
            service_import_limit = float(data[CONF_SERVICE_IMPORT_LIMIT_A])
            export_limit = float(data[CONF_EXPORT_LIMIT_KW])
            inverter_charge_limit = float(data[CONF_INVERTER_CHARGE_LIMIT_KW])
            inverter_discharge_limit = float(data[CONF_INVERTER_DISCHARGE_LIMIT_KW])
            min_current = float(data[CONF_EV_MIN_CURRENT])
            max_current = float(data[CONF_EV_MAX_CURRENT])
            phase_count = int(float(data[CONF_EV_PHASE_COUNT]))
            voltage = float(data[CONF_EV_VOLTAGE])
            inverter_capacity = float(data[CONF_INVERTER_CAPACITY])
            bonus_percent = float(data[CONF_BONUS_LOAD_FOLLOWING_PERCENT])
            non_free_percent = float(data[CONF_NON_FREE_LOAD_FOLLOWING_PERCENT])
            zero_import_threshold = float(data[CONF_ZERO_IMPORT_THRESHOLD_KW])
            zero_import_minutes = float(data[CONF_ZERO_IMPORT_CONFIRM_MINUTES])
            daily_charge = float(data[CONF_DAILY_CHARGE])
            peak_rate = float(data[CONF_PEAK_RATE])
            offpeak_rate = float(data[CONF_OFFPEAK_RATE])
            offpeak_balance_rate = float(data[CONF_OFFPEAK_BALANCE_RATE])
            shoulder_rate = float(data[CONF_SHOULDER_RATE])
            fallback = float(data[CONF_HOUSE_LEARNING_FALLBACK])
        except (KeyError, TypeError, ValueError):
            return {"base": "invalid_site_limits"}
        try:
            start = time.fromisoformat(str(data[CONF_FREE_CHARGE_START]))
            end = time.fromisoformat(str(data[CONF_FREE_CHARGE_END]))
            bonus_start = time.fromisoformat(str(data[CONF_BONUS_WINDOW_START]))
            bonus_end = time.fromisoformat(str(data[CONF_BONUS_WINDOW_END]))
            peak_start = time.fromisoformat(str(data[CONF_PEAK_WINDOW_START]))
            peak_end = time.fromisoformat(str(data[CONF_PEAK_WINDOW_END]))
        except (KeyError, TypeError, ValueError):
            return {"base": "invalid_schedule"}
        if (
            start == end
            or bonus_start == bonus_end
            or peak_start == peak_end
            or not math.isfinite(fallback)
            or fallback < 0
        ):
            return {"base": "invalid_schedule"}
        profile = data.get(CONF_EV_CHARGER_PROFILE)
        profile_values = EV_CHARGER_PROFILES.get(profile)
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
            inverter_capacity,
            bonus_percent,
            non_free_percent,
            daily_charge,
            peak_rate,
            offpeak_rate,
            offpeak_balance_rate,
            shoulder_rate,
        )
        if (
            profile_values is None
            or not all(math.isfinite(value) for value in values)
            or capacity <= 0
            or not 0 <= floor <= 100
            or reserve < 0
            or site_phase_count not in (1, 3)
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
            or phase_count != profile_values[0]
            or max_current != profile_values[1]
            or not 0 <= bonus_percent <= 100
            or not 0 <= non_free_percent <= 100
            or inverter_capacity < 0
        ):
            return {"base": "invalid_site_limits"}
        return {}
