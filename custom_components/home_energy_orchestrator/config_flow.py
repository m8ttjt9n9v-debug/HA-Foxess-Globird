"""UI-only setup and reconfiguration flow for the observer."""

from __future__ import annotations

import math
from datetime import time

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback, valid_entity_id
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    BATTERY_POSITIVE_DISCHARGE,
    BATTERY_POWER_DIRECTIONS,
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_CHARGE_EFFICIENCY,
    CONF_BATTERY_CHARGE_POSITIVE,
    CONF_BATTERY_CHARGE_POWER,
    CONF_BATTERY_DISCHARGE_POWER,
    CONF_BATTERY_FLOOR,
    CONF_BATTERY_FREE_WINDOW_TARGET,
    CONF_BATTERY_POWER,
    CONF_BATTERY_POWER_DIRECTION,
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
    CONF_EV_ARRIVAL_RESERVE_SOC,
    CONF_EV_AT_HOME,
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_EV_BACKFILL_BUFFER_MINUTES,
    CONF_EV_BEFORE_EXPORT_ENABLED,
    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
    CONF_EV_CABLE_CONNECTED,
    CONF_EV_CHARGE_EFFICIENCY,
    CONF_EV_CHARGE_LIMIT,
    CONF_EV_CHARGE_PATH,
    CONF_EV_CHARGE_SWITCH,
    CONF_EV_CHARGE_TO_FULL,
    CONF_EV_CHARGE_TO_FULL_ENABLED,
    CONF_EV_CHARGE_TO_FULL_MAX_HOURS,
    CONF_EV_CHARGING_STATE,
    CONF_EV_CONTROL_COMMISSIONED,
    CONF_EV_CURRENT_LIMIT,
    CONF_EV_DAILY_BACKFILL_ENERGY,
    CONF_EV_DAILY_READY_TIME,
    CONF_EV_DIRECT_LIMIT_HEADROOM,
    CONF_EV_FREE_WINDOW_CHARGE_LIMIT,
    CONF_EV_FREE_WINDOW_MINIMUM_CURRENT,
    CONF_EV_FREE_WINDOW_PRIORITY,
    CONF_EV_FREE_WINDOW_SETTLE_MINUTES,
    CONF_EV_LEARNING_MINIMUM_SAMPLES,
    CONF_EV_LIFETIME_ENERGY,
    CONF_EV_LOCATION_MODE,
    CONF_EV_MAX_CURRENT,
    CONF_EV_MIN_CURRENT,
    CONF_EV_OUTSIDE_INVERTER_PERCENT,
    CONF_EV_PHASE_COUNT,
    CONF_EV_PRE_FREE_ENABLED,
    CONF_EV_PROTECTED_BASELINE_A,
    CONF_EV_SMART_RECOVERY_CHARGING_CONFIRM_SECONDS,
    CONF_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS,
    CONF_EV_SMART_RECOVERY_IDLE_CURRENT_A,
    CONF_EV_SMART_RECOVERY_NO_POWER_SECONDS,
    CONF_EV_SMART_RECOVERY_POST_POWER_SECONDS,
    CONF_EV_SMART_RECOVERY_POWER_OFF_SECONDS,
    CONF_EV_SMART_RECOVERY_REARM_SECONDS,
    CONF_EV_SMART_RECOVERY_SOCKET_CONFIRM_SECONDS,
    CONF_EV_SMART_SOCKET,
    CONF_EV_SMART_SOCKET_CURRENT_LIMIT,
    CONF_EV_SMART_SOCKET_POWER_SWITCHING,
    CONF_EV_SMART_SOCKET_RETRY_SECONDS,
    CONF_EV_SMART_SOCKET_SETTLE_SECONDS,
    CONF_EV_SOC,
    CONF_EV_SOLAR_SPILL_BATTERY_SOC,
    CONF_EV_SOLAR_SPILL_ENABLED,
    CONF_EV_STORED_ENERGY,
    CONF_EV_TELEMETRY_MAX_AGE_SECONDS,
    CONF_EV_TELEMETRY_MAX_SKEW_SECONDS,
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
    CONF_FREE_CHARGE_SCHEDULE_CONFIRMED,
    CONF_FREE_CHARGE_START,
    CONF_GRID_IMPORT_POSITIVE,
    CONF_GRID_POWER,
    CONF_GRID_POWER_DIRECTION,
    CONF_HEATER_POWER,
    CONF_HOUSE_AWAY_CONFIRMATION_HOURS,
    CONF_HOUSE_AWAY_FALLBACK,
    CONF_HOUSE_LEARNING_FALLBACK,
    CONF_HOUSE_LOAD,
    CONF_HOUSE_OCCUPANCY_MODE,
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
    CONF_SIGN_CONVENTIONS_VERIFIED,
    CONF_SITE_GRID_CURRENT,
    CONF_SITE_GRID_CURRENT_DIRECTION,
    CONF_SITE_GRID_HEADROOM_CURRENT,
    CONF_SITE_PHASE_COUNT,
    CONF_SOLAR_POWER,
    CONF_SOLAR_POWER_DIRECTION,
    CONF_SUPER_EXPORT_RATE,
    CONF_TELEMETRY_MAX_AGE_SECONDS,
    CONF_ZERO_IMPORT_CONFIRM_MINUTES,
    CONF_ZERO_IMPORT_THRESHOLD_KW,
    DEFAULT_AUTOMATIC_CHARGE_ENABLED,
    DEFAULT_AUTOMATIC_CONTROL_ENABLED,
    DEFAULT_AUTOMATIC_EXPORT_ENABLED,
    DEFAULT_BATTERY_CHARGE_EFFICIENCY,
    DEFAULT_BATTERY_CHARGE_POSITIVE,
    DEFAULT_BATTERY_FLOOR,
    DEFAULT_BATTERY_FREE_WINDOW_TARGET,
    DEFAULT_BATTERY_POWER_DIRECTION,
    DEFAULT_BONUS_WINDOW_END,
    DEFAULT_BONUS_WINDOW_START,
    DEFAULT_DAILY_CHARGE,
    DEFAULT_DAILY_FREE_ALLOWANCE_KWH,
    DEFAULT_DISCHARGE_EFFICIENCY_PERCENT,
    DEFAULT_EV_ALLOWANCE_GUARD_ENABLED,
    DEFAULT_EV_ALLOWANCE_SAFETY_MARGIN,
    DEFAULT_EV_ARRIVAL_RESERVE_SOC,
    DEFAULT_EV_AUTOMATIC_CONTROL_ENABLED,
    DEFAULT_EV_BACKFILL_BUFFER_MINUTES,
    DEFAULT_EV_BEFORE_EXPORT_ENABLED,
    DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
    DEFAULT_EV_CHARGE_EFFICIENCY,
    DEFAULT_EV_CHARGE_PATH,
    DEFAULT_EV_CHARGE_TO_FULL_ENABLED,
    DEFAULT_EV_CHARGE_TO_FULL_MAX_HOURS,
    DEFAULT_EV_CONTROL_COMMISSIONED,
    DEFAULT_EV_DAILY_BACKFILL_ENERGY,
    DEFAULT_EV_DAILY_READY_TIME,
    DEFAULT_EV_DIRECT_LIMIT_HEADROOM,
    DEFAULT_EV_FREE_WINDOW_CHARGE_LIMIT,
    DEFAULT_EV_FREE_WINDOW_MINIMUM_CURRENT,
    DEFAULT_EV_FREE_WINDOW_PRIORITY,
    DEFAULT_EV_FREE_WINDOW_SETTLE_MINUTES,
    DEFAULT_EV_LEARNING_MINIMUM_SAMPLES,
    DEFAULT_EV_LOCATION_MODE,
    DEFAULT_EV_MAX_CURRENT,
    DEFAULT_EV_MIN_CURRENT,
    DEFAULT_EV_OUTSIDE_INVERTER_PERCENT,
    DEFAULT_EV_PHASE_COUNT,
    DEFAULT_EV_PRE_FREE_ENABLED,
    DEFAULT_EV_PROTECTED_BASELINE_A,
    DEFAULT_EV_SMART_RECOVERY_CHARGING_CONFIRM_SECONDS,
    DEFAULT_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS,
    DEFAULT_EV_SMART_RECOVERY_IDLE_CURRENT_A,
    DEFAULT_EV_SMART_RECOVERY_NO_POWER_SECONDS,
    DEFAULT_EV_SMART_RECOVERY_POST_POWER_SECONDS,
    DEFAULT_EV_SMART_RECOVERY_POWER_OFF_SECONDS,
    DEFAULT_EV_SMART_RECOVERY_REARM_SECONDS,
    DEFAULT_EV_SMART_RECOVERY_SOCKET_CONFIRM_SECONDS,
    DEFAULT_EV_SMART_SOCKET_CURRENT_LIMIT,
    DEFAULT_EV_SMART_SOCKET_POWER_SWITCHING,
    DEFAULT_EV_SMART_SOCKET_RETRY_SECONDS,
    DEFAULT_EV_SMART_SOCKET_SETTLE_SECONDS,
    DEFAULT_EV_SOLAR_SPILL_BATTERY_SOC,
    DEFAULT_EV_SOLAR_SPILL_ENABLED,
    DEFAULT_EV_TELEMETRY_MAX_AGE_SECONDS,
    DEFAULT_EV_TELEMETRY_MAX_SKEW_SECONDS,
    DEFAULT_EV_VOLTAGE,
    DEFAULT_EXPORT_ALLOWANCE_KWH,
    DEFAULT_EXPORT_DISCHARGE_POWER_KW,
    DEFAULT_EXPORT_LIMIT_KW,
    DEFAULT_EXPORT_RATE,
    DEFAULT_FORCE_DISCHARGE_FINISH,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DEFAULT_FREE_CHARGE_END,
    DEFAULT_FREE_CHARGE_START,
    DEFAULT_GRID_POWER_DIRECTION,
    DEFAULT_HOUSE_AWAY_CONFIRMATION_HOURS,
    DEFAULT_HOUSE_AWAY_FALLBACK_KWH,
    DEFAULT_HOUSE_LEARNING_FALLBACK_KWH,
    DEFAULT_HOUSE_OCCUPANCY_MODE,
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
    DEFAULT_SIGN_CONVENTIONS_VERIFIED,
    DEFAULT_SITE_GRID_CURRENT_DIRECTION,
    DEFAULT_SITE_GRID_HEADROOM_CURRENT,
    DEFAULT_SITE_PHASE_COUNT,
    DEFAULT_SOLAR_POWER_DIRECTION,
    DEFAULT_SUPER_EXPORT_RATE,
    DEFAULT_TELEMETRY_MAX_AGE_SECONDS,
    DEFAULT_ZERO_IMPORT_CONFIRM_MINUTES,
    DEFAULT_ZERO_IMPORT_THRESHOLD_KW,
    DOMAIN,
    EV_CHARGE_PATH_SMART_SOCKET,
    EV_CHARGE_PATHS,
    EV_FREE_WINDOW_PRIORITIES,
    EV_LOCATION_MODES,
    FOXESS_CONTROL_OWNER_MODBUS,
    FOXESS_CONTROL_OWNERS,
    GRID_POSITIVE_EXPORT,
    GRID_POWER_DIRECTIONS,
    HOUSE_OCCUPANCY_MODES,
    SOLAR_POWER_DIRECTIONS,
)
from .discovery import DiscoveryEntity, discover_entity_defaults

ENTITY = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
SELECT_ENTITY = selector.EntitySelector(selector.EntitySelectorConfig(domain="select"))
NUMBER_ENTITY = selector.EntitySelector(selector.EntitySelectorConfig(domain="number"))
SWITCH_ENTITY = selector.EntitySelector(selector.EntitySelectorConfig(domain="switch"))
CONF_CONFIRM_SCHEDULE = "confirm_schedule"
CONF_CONFIRM_OVERNIGHT = "confirm_overnight"


def _time_windows_overlap(
    first_start: time,
    first_end: time,
    second_start: time,
    second_end: time,
) -> bool:
    """Return whether two non-empty daily windows overlap on a 24-hour clock."""

    def segments(start: time, end: time) -> tuple[tuple[int, int], ...]:
        start_s = start.hour * 3600 + start.minute * 60 + start.second
        end_s = end.hour * 3600 + end.minute * 60 + end.second
        if start_s < end_s:
            return ((start_s, end_s),)
        return ((start_s, 86400), (0, end_s))

    return any(
        max(first_left, second_left) < min(first_right, second_right)
        for first_left, first_right in segments(first_start, first_end)
        for second_left, second_right in segments(second_start, second_end)
    )


def _window_duration_minutes(start: time, end: time) -> int:
    """Return the positive duration of a non-empty daily window."""
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    return (end_minutes - start_minutes) % (24 * 60)


def _schedule_confirmation(start: time, end: time) -> dict[str, str]:
    """Build an unambiguous 24-hour summary and compact visual timeline."""
    duration = _window_duration_minutes(start, end)
    hours, minutes = divmod(duration, 60)
    crosses_midnight = end <= start
    duration_text = f"{hours} h {minutes:02d} min"
    day_text = "crosses midnight" if crosses_midnight else "same day"
    summary = (
        f"{start.strftime('%H:%M')} → {end.strftime('%H:%M')} "
        f"({duration_text}, {day_text})"
    )
    start_minute = start.hour * 60 + start.minute
    cells = []
    for index in range(48):
        midpoint = index * 30 + 15
        active = (
            start_minute <= midpoint < start_minute + duration
            or start_minute <= midpoint + 24 * 60 < start_minute + duration
        )
        cells.append("█" if active else "·")
    warning = (
        "⚠️ This schedule crosses midnight. It starts on one day and ends the next day."
        if crosses_midnight
        else "This schedule starts and ends on the same day."
    )
    return {
        "schedule_summary": summary,
        "schedule_timeline": f"`00:00 |{''.join(cells)}| 24:00`",
        "schedule_warning": warning,
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create and maintain one observer per independently configured site."""

    VERSION = 3

    _pending_input: dict[str, object] | None = None
    _pending_reconfigure = False

    _NORMALIZATION_KEYS = frozenset(
        {
            CONF_GRID_POWER,
            CONF_GRID_POWER_DIRECTION,
            CONF_BATTERY_POWER,
            CONF_BATTERY_POWER_DIRECTION,
            CONF_BATTERY_CHARGE_POWER,
            CONF_BATTERY_DISCHARGE_POWER,
            CONF_SOLAR_POWER,
            CONF_SOLAR_POWER_DIRECTION,
            CONF_HOUSE_LOAD,
            CONF_SITE_GRID_CURRENT,
            CONF_SITE_GRID_CURRENT_DIRECTION,
        }
    )

    async def async_step_user(self, user_input: dict[str, object] | None = None):
        """Collect the mappings and site limits required by the observer."""
        if user_input is not None:
            user_input = self._apply_defaults(user_input)
            errors = self._validate_input(user_input)
            if errors:
                return self.async_show_form(
                    step_id="user", data_schema=self._schema(), errors=errors
                )
            if user_input.get(CONF_AUTOMATIC_CHARGE_ENABLED):
                return self._show_schedule_confirmation(user_input, reconfigure=False)
            title = str(user_input.pop(CONF_NAME))
            await self.async_set_unique_id(title.strip().casefold())
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=title, data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=self._schema(self._discovery_defaults())
        )

    async def async_step_reconfigure(self, user_input: dict[str, object] | None = None):
        """Update mappings and commissioned limits without reinstalling."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            if CONF_EV_CHARGE_TO_FULL_ENABLED in entry.data:
                user_input[CONF_EV_CHARGE_TO_FULL_ENABLED] = entry.data[
                    CONF_EV_CHARGE_TO_FULL_ENABLED
                ]
            elif CONF_EV_CHARGE_TO_FULL in entry.data:
                user_input[CONF_EV_CHARGE_TO_FULL] = entry.data[CONF_EV_CHARGE_TO_FULL]
            user_input = self._apply_defaults(user_input)
            old_normalized = self._apply_defaults(dict(entry.data))
            if any(
                user_input.get(key) != old_normalized.get(key)
                for key in self._NORMALIZATION_KEYS
            ):
                user_input[CONF_SIGN_CONVENTIONS_VERIFIED] = False
            errors = self._validate_input(user_input)
            if not errors:
                if user_input.get(CONF_AUTOMATIC_CHARGE_ENABLED):
                    return self._show_schedule_confirmation(user_input, reconfigure=True)
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
            step_id="reconfigure",
            data_schema=self._schema(self._reconfigure_defaults(entry)),
        )

    async def async_step_confirm_schedule(
        self, user_input: dict[str, object] | None = None
    ):
        """Require explicit review of the exact 24-hour free-power window."""
        if self._pending_input is None:
            return self.async_abort(reason="schedule_confirmation_expired")
        start = time.fromisoformat(str(self._pending_input[CONF_FREE_CHARGE_START]))
        end = time.fromisoformat(str(self._pending_input[CONF_FREE_CHARGE_END]))
        crosses_midnight = end <= start
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_CONFIRM_SCHEDULE):
                errors[CONF_CONFIRM_SCHEDULE] = "schedule_confirmation_required"
            if crosses_midnight and not user_input.get(CONF_CONFIRM_OVERNIGHT):
                errors[CONF_CONFIRM_OVERNIGHT] = "overnight_confirmation_required"
            if not errors:
                pending = dict(self._pending_input)
                pending[CONF_FREE_CHARGE_SCHEDULE_CONFIRMED] = True
                title = str(pending.pop(CONF_NAME))
                self._pending_input = None
                if self._pending_reconfigure:
                    entry = self._get_reconfigure_entry()
                    return self.async_update_reload_and_abort(
                        entry,
                        title=title,
                        data_updates=pending,
                        reason="reconfigure_successful",
                    )
                await self.async_set_unique_id(title.strip().casefold())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=title, data=pending)
        schema: dict[vol.Marker, object] = {
            vol.Required(CONF_CONFIRM_SCHEDULE, default=False): selector.BooleanSelector()
        }
        if crosses_midnight:
            schema[vol.Required(CONF_CONFIRM_OVERNIGHT, default=False)] = (
                selector.BooleanSelector()
            )
        return self.async_show_form(
            step_id="confirm_schedule",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders=_schedule_confirmation(start, end),
        )

    @callback
    def _show_schedule_confirmation(
        self, user_input: dict[str, object], *, reconfigure: bool
    ):
        self._pending_input = dict(user_input)
        self._pending_reconfigure = reconfigure
        start = time.fromisoformat(str(user_input[CONF_FREE_CHARGE_START]))
        end = time.fromisoformat(str(user_input[CONF_FREE_CHARGE_END]))
        schema: dict[vol.Marker, object] = {
            vol.Required(CONF_CONFIRM_SCHEDULE, default=False): selector.BooleanSelector()
        }
        if end <= start:
            schema[vol.Required(CONF_CONFIRM_OVERNIGHT, default=False)] = (
                selector.BooleanSelector()
            )
        return self.async_show_form(
            step_id="confirm_schedule",
            data_schema=vol.Schema(schema),
            description_placeholders=_schedule_confirmation(start, end),
        )

    @callback
    def _discovery_defaults(self) -> dict[str, object]:
        """Suggest unambiguous entities without changing any control setting."""
        registry = er.async_get(self.hass)
        return discover_entity_defaults(
            [
                DiscoveryEntity(
                    entity_id=entry.entity_id,
                    platform=entry.platform,
                    config_entry_id=entry.config_entry_id,
                    original_name=entry.original_name,
                    disabled=entry.disabled_by is not None,
                )
                for entry in registry.entities.values()
                if entry.platform in {"foxess_modbus", "tessie"}
            ]
        )

    @callback
    def _reconfigure_defaults(
        self, entry: config_entries.ConfigEntry
    ) -> dict[str, object]:
        """Preserve valid mappings and propose replacements for stale ones."""
        defaults: dict[str, object] = {CONF_NAME: entry.title, **entry.data}
        registry = er.async_get(self.hass)
        for key, suggestion in self._discovery_defaults().items():
            current = defaults.get(key)
            if not current or (
                isinstance(current, str)
                and valid_entity_id(current)
                and registry.async_get(current) is None
                and self.hass.states.get(current) is None
            ):
                defaults[key] = suggestion
        return defaults

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
                optional_entity(CONF_BATTERY_POWER): ENTITY,
                optional_entity(CONF_BATTERY_CHARGE_POWER): ENTITY,
                optional_entity(CONF_BATTERY_DISCHARGE_POWER): ENTITY,
                vol.Required(
                    CONF_BATTERY_POWER_DIRECTION,
                    default=defaults.get(
                        CONF_BATTERY_POWER_DIRECTION,
                        DEFAULT_BATTERY_POWER_DIRECTION,
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(BATTERY_POWER_DIRECTIONS))
                ),
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
                    CONF_GRID_POWER_DIRECTION,
                    default=defaults.get(
                        CONF_GRID_POWER_DIRECTION, DEFAULT_GRID_POWER_DIRECTION
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(GRID_POWER_DIRECTIONS))
                ),
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
                    default=defaults.get(CONF_OFFPEAK_BALANCE_RATE, DEFAULT_OFFPEAK_BALANCE_RATE),
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
                optional_entity(CONF_HEATER_POWER): ENTITY,
                optional_entity(CONF_SOLAR_POWER): ENTITY,
                vol.Required(
                    CONF_SOLAR_POWER_DIRECTION,
                    default=defaults.get(
                        CONF_SOLAR_POWER_DIRECTION, DEFAULT_SOLAR_POWER_DIRECTION
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(SOLAR_POWER_DIRECTIONS))
                ),
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
                vol.Required(
                    CONF_HOUSE_AWAY_FALLBACK,
                    default=defaults.get(
                        CONF_HOUSE_AWAY_FALLBACK,
                        DEFAULT_HOUSE_AWAY_FALLBACK_KWH,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_HOUSE_AWAY_CONFIRMATION_HOURS,
                    default=defaults.get(
                        CONF_HOUSE_AWAY_CONFIRMATION_HOURS,
                        DEFAULT_HOUSE_AWAY_CONFIRMATION_HOURS,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_HOUSE_OCCUPANCY_MODE,
                    default=defaults.get(
                        CONF_HOUSE_OCCUPANCY_MODE,
                        DEFAULT_HOUSE_OCCUPANCY_MODE,
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(HOUSE_OCCUPANCY_MODES))
                ),
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
                optional_entity(CONF_EV_LIFETIME_ENERGY): ENTITY,
                optional_entity(CONF_EV_CURRENT_LIMIT): NUMBER_ENTITY,
                optional_entity(CONF_EV_CHARGE_LIMIT): NUMBER_ENTITY,
                optional_entity(CONF_EV_CHARGE_SWITCH): SWITCH_ENTITY,
                vol.Required(
                    CONF_EV_CHARGE_PATH,
                    default=defaults.get(CONF_EV_CHARGE_PATH, DEFAULT_EV_CHARGE_PATH),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(EV_CHARGE_PATHS))
                ),
                optional_entity(CONF_EV_SMART_SOCKET): SWITCH_ENTITY,
                vol.Required(
                    CONF_EV_SMART_SOCKET_CURRENT_LIMIT,
                    default=defaults.get(
                        CONF_EV_SMART_SOCKET_CURRENT_LIMIT,
                        DEFAULT_EV_SMART_SOCKET_CURRENT_LIMIT,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_SMART_SOCKET_SETTLE_SECONDS,
                    default=defaults.get(
                        CONF_EV_SMART_SOCKET_SETTLE_SECONDS,
                        DEFAULT_EV_SMART_SOCKET_SETTLE_SECONDS,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_SMART_SOCKET_RETRY_SECONDS,
                    default=defaults.get(
                        CONF_EV_SMART_SOCKET_RETRY_SECONDS,
                        DEFAULT_EV_SMART_SOCKET_RETRY_SECONDS,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_SMART_SOCKET_POWER_SWITCHING,
                    default=defaults.get(
                        CONF_EV_SMART_SOCKET_POWER_SWITCHING,
                        DEFAULT_EV_SMART_SOCKET_POWER_SWITCHING,
                    ),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_EV_SMART_RECOVERY_NO_POWER_SECONDS,
                    default=defaults.get(
                        CONF_EV_SMART_RECOVERY_NO_POWER_SECONDS,
                        DEFAULT_EV_SMART_RECOVERY_NO_POWER_SECONDS,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS,
                    default=defaults.get(
                        CONF_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS,
                        DEFAULT_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_SMART_RECOVERY_SOCKET_CONFIRM_SECONDS,
                    default=defaults.get(
                        CONF_EV_SMART_RECOVERY_SOCKET_CONFIRM_SECONDS,
                        DEFAULT_EV_SMART_RECOVERY_SOCKET_CONFIRM_SECONDS,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_SMART_RECOVERY_POWER_OFF_SECONDS,
                    default=defaults.get(
                        CONF_EV_SMART_RECOVERY_POWER_OFF_SECONDS,
                        DEFAULT_EV_SMART_RECOVERY_POWER_OFF_SECONDS,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_SMART_RECOVERY_POST_POWER_SECONDS,
                    default=defaults.get(
                        CONF_EV_SMART_RECOVERY_POST_POWER_SECONDS,
                        DEFAULT_EV_SMART_RECOVERY_POST_POWER_SECONDS,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_SMART_RECOVERY_CHARGING_CONFIRM_SECONDS,
                    default=defaults.get(
                        CONF_EV_SMART_RECOVERY_CHARGING_CONFIRM_SECONDS,
                        DEFAULT_EV_SMART_RECOVERY_CHARGING_CONFIRM_SECONDS,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_SMART_RECOVERY_REARM_SECONDS,
                    default=defaults.get(
                        CONF_EV_SMART_RECOVERY_REARM_SECONDS,
                        DEFAULT_EV_SMART_RECOVERY_REARM_SECONDS,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_SMART_RECOVERY_IDLE_CURRENT_A,
                    default=defaults.get(
                        CONF_EV_SMART_RECOVERY_IDLE_CURRENT_A,
                        DEFAULT_EV_SMART_RECOVERY_IDLE_CURRENT_A,
                    ),
                ): vol.Coerce(float),
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
                    CONF_EV_CHARGE_TO_FULL_MAX_HOURS,
                    default=defaults.get(
                        CONF_EV_CHARGE_TO_FULL_MAX_HOURS,
                        DEFAULT_EV_CHARGE_TO_FULL_MAX_HOURS,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_CHARGE_EFFICIENCY,
                    default=defaults.get(CONF_EV_CHARGE_EFFICIENCY, DEFAULT_EV_CHARGE_EFFICIENCY),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_ARRIVAL_RESERVE_SOC,
                    default=defaults.get(
                        CONF_EV_ARRIVAL_RESERVE_SOC,
                        DEFAULT_EV_ARRIVAL_RESERVE_SOC,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_LEARNING_MINIMUM_SAMPLES,
                    default=defaults.get(
                        CONF_EV_LEARNING_MINIMUM_SAMPLES,
                        DEFAULT_EV_LEARNING_MINIMUM_SAMPLES,
                    ),
                ): vol.Coerce(int),
                vol.Required(
                    CONF_SITE_GRID_HEADROOM_CURRENT,
                    default=defaults.get(
                        CONF_SITE_GRID_HEADROOM_CURRENT,
                        DEFAULT_SITE_GRID_HEADROOM_CURRENT,
                    ),
                ): vol.Coerce(float),
                optional_entity(CONF_SITE_GRID_CURRENT): ENTITY,
                vol.Required(
                    CONF_SITE_GRID_CURRENT_DIRECTION,
                    default=defaults.get(
                        CONF_SITE_GRID_CURRENT_DIRECTION,
                        DEFAULT_SITE_GRID_CURRENT_DIRECTION,
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(GRID_POWER_DIRECTIONS))
                ),
                vol.Required(
                    CONF_TELEMETRY_MAX_AGE_SECONDS,
                    default=defaults.get(
                        CONF_TELEMETRY_MAX_AGE_SECONDS,
                        DEFAULT_TELEMETRY_MAX_AGE_SECONDS,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_SIGN_CONVENTIONS_VERIFIED,
                    default=defaults.get(
                        CONF_SIGN_CONVENTIONS_VERIFIED,
                        DEFAULT_SIGN_CONVENTIONS_VERIFIED,
                    ),
                ): selector.BooleanSelector(),
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
                    CONF_EV_SOLAR_SPILL_ENABLED,
                    default=defaults.get(
                        CONF_EV_SOLAR_SPILL_ENABLED, DEFAULT_EV_SOLAR_SPILL_ENABLED
                    ),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_EV_SOLAR_SPILL_BATTERY_SOC,
                    default=defaults.get(
                        CONF_EV_SOLAR_SPILL_BATTERY_SOC,
                        DEFAULT_EV_SOLAR_SPILL_BATTERY_SOC,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_PRE_FREE_ENABLED,
                    default=defaults.get(CONF_EV_PRE_FREE_ENABLED, DEFAULT_EV_PRE_FREE_ENABLED),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_EV_DAILY_BACKFILL_ENERGY,
                    default=defaults.get(
                        CONF_EV_DAILY_BACKFILL_ENERGY,
                        DEFAULT_EV_DAILY_BACKFILL_ENERGY,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_DAILY_READY_TIME,
                    default=defaults.get(
                        CONF_EV_DAILY_READY_TIME,
                        DEFAULT_EV_DAILY_READY_TIME,
                    ),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_EV_OUTSIDE_INVERTER_PERCENT,
                    default=defaults.get(
                        CONF_EV_OUTSIDE_INVERTER_PERCENT,
                        DEFAULT_EV_OUTSIDE_INVERTER_PERCENT,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_BACKFILL_BUFFER_MINUTES,
                    default=defaults.get(
                        CONF_EV_BACKFILL_BUFFER_MINUTES,
                        DEFAULT_EV_BACKFILL_BUFFER_MINUTES,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_TELEMETRY_MAX_AGE_SECONDS,
                    default=defaults.get(
                        CONF_EV_TELEMETRY_MAX_AGE_SECONDS,
                        DEFAULT_EV_TELEMETRY_MAX_AGE_SECONDS,
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_EV_TELEMETRY_MAX_SKEW_SECONDS,
                    default=defaults.get(
                        CONF_EV_TELEMETRY_MAX_SKEW_SECONDS,
                        DEFAULT_EV_TELEMETRY_MAX_SKEW_SECONDS,
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
                    default=defaults.get(CONF_EXPORT_ALLOWANCE_KWH, DEFAULT_EXPORT_ALLOWANCE_KWH),
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
                    default=defaults.get(CONF_FOXESS_CONTROL_OWNER, DEFAULT_FOXESS_CONTROL_OWNER),
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
                    CONF_AUTOMATIC_CHARGE_ENABLED,
                    default=defaults.get(
                        CONF_AUTOMATIC_CHARGE_ENABLED,
                        DEFAULT_AUTOMATIC_CHARGE_ENABLED,
                    ),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_AUTOMATIC_EXPORT_ENABLED,
                    default=defaults.get(
                        CONF_AUTOMATIC_EXPORT_ENABLED, DEFAULT_AUTOMATIC_EXPORT_ENABLED
                    ),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_EV_BEFORE_EXPORT_ENABLED,
                    default=defaults.get(
                        CONF_EV_BEFORE_EXPORT_ENABLED,
                        DEFAULT_EV_BEFORE_EXPORT_ENABLED,
                    ),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
                    default=defaults.get(
                        CONF_EV_BEFORE_EXPORT_SOC_TARGET,
                        DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
                    ),
                ): vol.Coerce(float),
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
            CONF_BATTERY_CHARGE_POSITIVE,
            CONF_GRID_IMPORT_POSITIVE,
            "ev_charger_profile",
            "inverter_capacity_kw",
            "bonus_load_following_percent",
            "non_free_load_following_percent",
            "load_following_override",
            "free_charge_full_battery_import_threshold_kwh",
        }
        cleaned = {key: value for key, value in data.items() if key not in removed}
        result = {
            **cleaned,
            CONF_FREE_CHARGE_START: data.get(CONF_FREE_CHARGE_START, DEFAULT_FREE_CHARGE_START),
            CONF_BATTERY_POWER_DIRECTION: data.get(
                CONF_BATTERY_POWER_DIRECTION,
                (
                    DEFAULT_BATTERY_POWER_DIRECTION
                    if data.get(
                        CONF_BATTERY_CHARGE_POSITIVE,
                        DEFAULT_BATTERY_CHARGE_POSITIVE,
                    )
                    else BATTERY_POSITIVE_DISCHARGE
                ),
            ),
            CONF_GRID_POWER_DIRECTION: data.get(
                CONF_GRID_POWER_DIRECTION,
                (
                    DEFAULT_GRID_POWER_DIRECTION
                    if data.get(CONF_GRID_IMPORT_POSITIVE, True)
                    else GRID_POSITIVE_EXPORT
                ),
            ),
            CONF_SOLAR_POWER_DIRECTION: data.get(
                CONF_SOLAR_POWER_DIRECTION, DEFAULT_SOLAR_POWER_DIRECTION
            ),
            CONF_SITE_GRID_CURRENT_DIRECTION: data.get(
                CONF_SITE_GRID_CURRENT_DIRECTION,
                DEFAULT_SITE_GRID_CURRENT_DIRECTION,
            ),
            CONF_SIGN_CONVENTIONS_VERIFIED: data.get(
                CONF_SIGN_CONVENTIONS_VERIFIED,
                DEFAULT_SIGN_CONVENTIONS_VERIFIED,
            ),
            CONF_TELEMETRY_MAX_AGE_SECONDS: data.get(
                CONF_TELEMETRY_MAX_AGE_SECONDS,
                DEFAULT_TELEMETRY_MAX_AGE_SECONDS,
            ),
            CONF_FREE_CHARGE_END: data.get(CONF_FREE_CHARGE_END, DEFAULT_FREE_CHARGE_END),
            CONF_FREE_CHARGE_SCHEDULE_CONFIRMED: data.get(
                CONF_FREE_CHARGE_SCHEDULE_CONFIRMED, False
            ),
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
            CONF_SUPER_EXPORT_RATE: data.get(CONF_SUPER_EXPORT_RATE, DEFAULT_SUPER_EXPORT_RATE),
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
            CONF_HOUSE_AWAY_FALLBACK: data.get(
                CONF_HOUSE_AWAY_FALLBACK, DEFAULT_HOUSE_AWAY_FALLBACK_KWH
            ),
            CONF_HOUSE_AWAY_CONFIRMATION_HOURS: data.get(
                CONF_HOUSE_AWAY_CONFIRMATION_HOURS,
                DEFAULT_HOUSE_AWAY_CONFIRMATION_HOURS,
            ),
            CONF_HOUSE_OCCUPANCY_MODE: data.get(
                CONF_HOUSE_OCCUPANCY_MODE, DEFAULT_HOUSE_OCCUPANCY_MODE
            ),
            CONF_EV_PHASE_COUNT: data.get(CONF_EV_PHASE_COUNT, DEFAULT_EV_PHASE_COUNT),
            CONF_EV_MAX_CURRENT: data.get(CONF_EV_MAX_CURRENT, DEFAULT_EV_MAX_CURRENT),
            CONF_EV_CHARGE_PATH: data.get(CONF_EV_CHARGE_PATH, DEFAULT_EV_CHARGE_PATH),
            CONF_EV_SMART_SOCKET_CURRENT_LIMIT: data.get(
                CONF_EV_SMART_SOCKET_CURRENT_LIMIT,
                DEFAULT_EV_SMART_SOCKET_CURRENT_LIMIT,
            ),
            CONF_EV_SMART_SOCKET_SETTLE_SECONDS: data.get(
                CONF_EV_SMART_SOCKET_SETTLE_SECONDS,
                DEFAULT_EV_SMART_SOCKET_SETTLE_SECONDS,
            ),
            CONF_EV_SMART_SOCKET_RETRY_SECONDS: data.get(
                CONF_EV_SMART_SOCKET_RETRY_SECONDS,
                DEFAULT_EV_SMART_SOCKET_RETRY_SECONDS,
            ),
            CONF_EV_SMART_SOCKET_POWER_SWITCHING: data.get(
                CONF_EV_SMART_SOCKET_POWER_SWITCHING,
                DEFAULT_EV_SMART_SOCKET_POWER_SWITCHING,
            ),
            CONF_EV_SMART_RECOVERY_NO_POWER_SECONDS: data.get(
                CONF_EV_SMART_RECOVERY_NO_POWER_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_NO_POWER_SECONDS,
            ),
            CONF_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS: data.get(
                CONF_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS,
            ),
            CONF_EV_SMART_RECOVERY_SOCKET_CONFIRM_SECONDS: data.get(
                CONF_EV_SMART_RECOVERY_SOCKET_CONFIRM_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_SOCKET_CONFIRM_SECONDS,
            ),
            CONF_EV_SMART_RECOVERY_POWER_OFF_SECONDS: data.get(
                CONF_EV_SMART_RECOVERY_POWER_OFF_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_POWER_OFF_SECONDS,
            ),
            CONF_EV_SMART_RECOVERY_POST_POWER_SECONDS: data.get(
                CONF_EV_SMART_RECOVERY_POST_POWER_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_POST_POWER_SECONDS,
            ),
            CONF_EV_SMART_RECOVERY_CHARGING_CONFIRM_SECONDS: data.get(
                CONF_EV_SMART_RECOVERY_CHARGING_CONFIRM_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_CHARGING_CONFIRM_SECONDS,
            ),
            CONF_EV_SMART_RECOVERY_REARM_SECONDS: data.get(
                CONF_EV_SMART_RECOVERY_REARM_SECONDS,
                DEFAULT_EV_SMART_RECOVERY_REARM_SECONDS,
            ),
            CONF_EV_SMART_RECOVERY_IDLE_CURRENT_A: data.get(
                CONF_EV_SMART_RECOVERY_IDLE_CURRENT_A,
                DEFAULT_EV_SMART_RECOVERY_IDLE_CURRENT_A,
            ),
            CONF_EV_LOCATION_MODE: data.get(CONF_EV_LOCATION_MODE, DEFAULT_EV_LOCATION_MODE),
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
            CONF_EV_CHARGE_TO_FULL_MAX_HOURS: data.get(
                CONF_EV_CHARGE_TO_FULL_MAX_HOURS,
                DEFAULT_EV_CHARGE_TO_FULL_MAX_HOURS,
            ),
            CONF_EV_ARRIVAL_RESERVE_SOC: data.get(
                CONF_EV_ARRIVAL_RESERVE_SOC, DEFAULT_EV_ARRIVAL_RESERVE_SOC
            ),
            CONF_EV_LEARNING_MINIMUM_SAMPLES: data.get(
                CONF_EV_LEARNING_MINIMUM_SAMPLES,
                DEFAULT_EV_LEARNING_MINIMUM_SAMPLES,
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
            CONF_EV_SOLAR_SPILL_ENABLED: data.get(
                CONF_EV_SOLAR_SPILL_ENABLED, DEFAULT_EV_SOLAR_SPILL_ENABLED
            ),
            CONF_EV_SOLAR_SPILL_BATTERY_SOC: data.get(
                CONF_EV_SOLAR_SPILL_BATTERY_SOC,
                DEFAULT_EV_SOLAR_SPILL_BATTERY_SOC,
            ),
            CONF_EV_PRE_FREE_ENABLED: data.get(
                CONF_EV_PRE_FREE_ENABLED, DEFAULT_EV_PRE_FREE_ENABLED
            ),
            CONF_EV_DAILY_BACKFILL_ENERGY: data.get(
                CONF_EV_DAILY_BACKFILL_ENERGY,
                DEFAULT_EV_DAILY_BACKFILL_ENERGY,
            ),
            CONF_EV_DAILY_READY_TIME: data.get(
                CONF_EV_DAILY_READY_TIME,
                DEFAULT_EV_DAILY_READY_TIME,
            ),
            CONF_EV_OUTSIDE_INVERTER_PERCENT: data.get(
                CONF_EV_OUTSIDE_INVERTER_PERCENT,
                DEFAULT_EV_OUTSIDE_INVERTER_PERCENT,
            ),
            CONF_EV_BACKFILL_BUFFER_MINUTES: data.get(
                CONF_EV_BACKFILL_BUFFER_MINUTES,
                DEFAULT_EV_BACKFILL_BUFFER_MINUTES,
            ),
            CONF_EV_TELEMETRY_MAX_AGE_SECONDS: data.get(
                CONF_EV_TELEMETRY_MAX_AGE_SECONDS,
                DEFAULT_EV_TELEMETRY_MAX_AGE_SECONDS,
            ),
            CONF_EV_TELEMETRY_MAX_SKEW_SECONDS: data.get(
                CONF_EV_TELEMETRY_MAX_SKEW_SECONDS,
                DEFAULT_EV_TELEMETRY_MAX_SKEW_SECONDS,
            ),
            CONF_EV_CONTROL_COMMISSIONED: data.get(
                CONF_EV_CONTROL_COMMISSIONED, DEFAULT_EV_CONTROL_COMMISSIONED
            ),
            **(
                {CONF_EV_CHARGE_TO_FULL_ENABLED: data[CONF_EV_CHARGE_TO_FULL_ENABLED]}
                if CONF_EV_CHARGE_TO_FULL_ENABLED in data
                else {CONF_EV_CHARGE_TO_FULL: data[CONF_EV_CHARGE_TO_FULL]}
                if CONF_EV_CHARGE_TO_FULL in data
                else {
                    CONF_EV_CHARGE_TO_FULL_ENABLED: DEFAULT_EV_CHARGE_TO_FULL_ENABLED
                }
            ),
            CONF_BONUS_WINDOW_START: data.get(CONF_BONUS_WINDOW_START, DEFAULT_BONUS_WINDOW_START),
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
            CONF_AUTOMATIC_CHARGE_ENABLED: data.get(
                CONF_AUTOMATIC_CHARGE_ENABLED,
                DEFAULT_AUTOMATIC_CHARGE_ENABLED,
            ),
            CONF_AUTOMATIC_EXPORT_ENABLED: data.get(
                CONF_AUTOMATIC_EXPORT_ENABLED, DEFAULT_AUTOMATIC_EXPORT_ENABLED
            ),
            CONF_EV_BEFORE_EXPORT_ENABLED: data.get(
                CONF_EV_BEFORE_EXPORT_ENABLED,
                DEFAULT_EV_BEFORE_EXPORT_ENABLED,
            ),
            CONF_EV_BEFORE_EXPORT_SOC_TARGET: data.get(
                CONF_EV_BEFORE_EXPORT_SOC_TARGET,
                DEFAULT_EV_BEFORE_EXPORT_SOC_TARGET,
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
        if CONF_EV_LIFETIME_ENERGY in data:
            result[CONF_EV_LIFETIME_ENERGY] = data[CONF_EV_LIFETIME_ENERGY]
        return result

    @staticmethod
    def _validate_input(data: dict[str, object]) -> dict[str, str]:
        """Reject malformed IDs and unsafe physical limits before saving them."""
        if not str(data.get(CONF_NAME, "")).strip():
            return {CONF_NAME: "invalid_name"}
        if data.get(CONF_FOXESS_CONTROL_OWNER) not in FOXESS_CONTROL_OWNERS:
            return {CONF_FOXESS_CONTROL_OWNER: "invalid_foxess_control_owner"}
        if data.get(CONF_GRID_POWER_DIRECTION) not in GRID_POWER_DIRECTIONS:
            return {CONF_GRID_POWER_DIRECTION: "invalid_power_direction"}
        if data.get(CONF_BATTERY_POWER_DIRECTION) not in BATTERY_POWER_DIRECTIONS:
            return {CONF_BATTERY_POWER_DIRECTION: "invalid_power_direction"}
        if data.get(CONF_SOLAR_POWER_DIRECTION) not in SOLAR_POWER_DIRECTIONS:
            return {CONF_SOLAR_POWER_DIRECTION: "invalid_power_direction"}
        if data.get(CONF_SITE_GRID_CURRENT_DIRECTION) not in GRID_POWER_DIRECTIONS:
            return {CONF_SITE_GRID_CURRENT_DIRECTION: "invalid_power_direction"}
        for key in (
            CONF_BATTERY_SOC,
            CONF_BATTERY_CAPACITY_ENTITY,
            CONF_BATTERY_POWER,
            CONF_BATTERY_CHARGE_POWER,
            CONF_BATTERY_DISCHARGE_POWER,
            CONF_DAILY_IMPORT_ENTITY,
            CONF_GRID_POWER,
            CONF_HEATER_POWER,
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
            CONF_EV_SMART_SOCKET,
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
        split_battery_mapping = (
            data.get(CONF_BATTERY_CHARGE_POWER),
            data.get(CONF_BATTERY_DISCHARGE_POWER),
        )
        if any(split_battery_mapping) and not all(split_battery_mapping):
            return {"base": "incomplete_split_battery_mapping"}
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
        if data.get(CONF_EV_SOLAR_SPILL_ENABLED) and not (
            data.get(CONF_BATTERY_POWER) or all(split_battery_mapping)
        ):
            return {"base": "solar_spill_battery_power_mapping_required"}
        if (
            data.get(CONF_EV_SOLAR_SPILL_ENABLED)
            or data.get(CONF_EV_PRE_FREE_ENABLED)
        ) and data.get(CONF_FOXESS_CONTROL_OWNER) != FOXESS_CONTROL_OWNER_MODBUS:
            return {"base": "outside_ev_policy_requires_local_modbus"}
        if data.get(CONF_EV_LOCATION_MODE) not in EV_LOCATION_MODES:
            return {CONF_EV_LOCATION_MODE: "invalid_ev_location_mode"}
        if data.get(CONF_HOUSE_OCCUPANCY_MODE) not in HOUSE_OCCUPANCY_MODES:
            return {CONF_HOUSE_OCCUPANCY_MODE: "invalid_house_occupancy_mode"}
        if data.get(CONF_EV_FREE_WINDOW_PRIORITY) not in EV_FREE_WINDOW_PRIORITIES:
            return {CONF_EV_FREE_WINDOW_PRIORITY: "invalid_ev_priority"}
        if data.get(CONF_EV_CHARGE_PATH) not in EV_CHARGE_PATHS:
            return {CONF_EV_CHARGE_PATH: "invalid_ev_charge_path"}
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
            smart_socket_limit = float(data[CONF_EV_SMART_SOCKET_CURRENT_LIMIT])
            smart_socket_settle = float(data[CONF_EV_SMART_SOCKET_SETTLE_SECONDS])
            smart_socket_retry = float(data[CONF_EV_SMART_SOCKET_RETRY_SECONDS])
            smart_recovery_timings = (
                float(data[CONF_EV_SMART_RECOVERY_NO_POWER_SECONDS]),
                float(data[CONF_EV_SMART_RECOVERY_CURRENT_CONFIRM_SECONDS]),
                float(data[CONF_EV_SMART_RECOVERY_SOCKET_CONFIRM_SECONDS]),
                float(data[CONF_EV_SMART_RECOVERY_POWER_OFF_SECONDS]),
                float(data[CONF_EV_SMART_RECOVERY_POST_POWER_SECONDS]),
                float(data[CONF_EV_SMART_RECOVERY_CHARGING_CONFIRM_SECONDS]),
                float(data[CONF_EV_SMART_RECOVERY_REARM_SECONDS]),
            )
            smart_recovery_idle_current = float(
                data[CONF_EV_SMART_RECOVERY_IDLE_CURRENT_A]
            )
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
            daily_backfill_energy = float(data[CONF_EV_DAILY_BACKFILL_ENERGY])
            outside_inverter_percent = float(data[CONF_EV_OUTSIDE_INVERTER_PERCENT])
            backfill_buffer_minutes = float(data[CONF_EV_BACKFILL_BUFFER_MINUTES])
            ev_free_limit = float(data[CONF_EV_FREE_WINDOW_CHARGE_LIMIT])
            ev_free_minimum = float(data[CONF_EV_FREE_WINDOW_MINIMUM_CURRENT])
            ev_settle_minutes = float(data[CONF_EV_FREE_WINDOW_SETTLE_MINUTES])
            ev_limit_headroom = float(data[CONF_EV_DIRECT_LIMIT_HEADROOM])
            charge_to_full_max_hours = float(data[CONF_EV_CHARGE_TO_FULL_MAX_HOURS])
            ev_charge_efficiency = float(data[CONF_EV_CHARGE_EFFICIENCY])
            ev_arrival_reserve = float(data[CONF_EV_ARRIVAL_RESERVE_SOC])
            ev_before_export_target = float(data[CONF_EV_BEFORE_EXPORT_SOC_TARGET])
            ev_learning_minimum = float(data[CONF_EV_LEARNING_MINIMUM_SAMPLES])
            site_headroom = float(data[CONF_SITE_GRID_HEADROOM_CURRENT])
            battery_target = float(data[CONF_BATTERY_FREE_WINDOW_TARGET])
            battery_efficiency = float(data[CONF_BATTERY_CHARGE_EFFICIENCY])
            allowance_margin = float(data[CONF_EV_ALLOWANCE_SAFETY_MARGIN])
            solar_spill_soc = float(data[CONF_EV_SOLAR_SPILL_BATTERY_SOC])
            telemetry_max_age = float(data[CONF_EV_TELEMETRY_MAX_AGE_SECONDS])
            normalized_telemetry_max_age = float(data[CONF_TELEMETRY_MAX_AGE_SECONDS])
            telemetry_max_skew = float(data[CONF_EV_TELEMETRY_MAX_SKEW_SECONDS])
            fallback = float(data[CONF_HOUSE_LEARNING_FALLBACK])
            away_fallback = float(data[CONF_HOUSE_AWAY_FALLBACK])
            away_confirmation = float(data[CONF_HOUSE_AWAY_CONFIRMATION_HOURS])
        except (KeyError, TypeError, ValueError):
            return {"base": "invalid_site_limits"}
        try:
            start = time.fromisoformat(str(data[CONF_FREE_CHARGE_START]))
            end = time.fromisoformat(str(data[CONF_FREE_CHARGE_END]))
            bonus_start = time.fromisoformat(str(data[CONF_BONUS_WINDOW_START]))
            bonus_end = time.fromisoformat(str(data[CONF_BONUS_WINDOW_END]))
            discharge_finish = time.fromisoformat(str(data[CONF_FORCE_DISCHARGE_FINISH]))
            daily_ready = time.fromisoformat(str(data[CONF_EV_DAILY_READY_TIME]))
            peak_start = time.fromisoformat(str(data[CONF_PEAK_WINDOW_START]))
            peak_end = time.fromisoformat(str(data[CONF_PEAK_WINDOW_END]))
        except (KeyError, TypeError, ValueError):
            return {"base": "invalid_schedule"}
        if (
            start == end
            or bonus_start == bonus_end
            or discharge_finish == bonus_start
            or peak_start == peak_end
            or (
                bool(data.get(CONF_AUTOMATIC_CHARGE_ENABLED))
                and bool(data.get(CONF_AUTOMATIC_EXPORT_ENABLED))
                and _time_windows_overlap(start, end, bonus_start, discharge_finish)
            )
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
            smart_socket_limit,
            smart_socket_settle,
            smart_socket_retry,
            *smart_recovery_timings,
            smart_recovery_idle_current,
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
            daily_backfill_energy,
            outside_inverter_percent,
            backfill_buffer_minutes,
            ev_free_limit,
            ev_free_minimum,
            ev_settle_minutes,
            ev_limit_headroom,
            charge_to_full_max_hours,
            ev_charge_efficiency,
            ev_arrival_reserve,
            ev_before_export_target,
            ev_learning_minimum,
            site_headroom,
            battery_target,
            battery_efficiency,
            allowance_margin,
            solar_spill_soc,
            telemetry_max_age,
            telemetry_max_skew,
            fallback,
            away_fallback,
            away_confirmation,
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
            or smart_socket_limit < 0
            or smart_socket_settle < 0
            or smart_socket_retry <= 0
            or any(value <= 0 for value in smart_recovery_timings)
            or smart_recovery_idle_current < 0
            or voltage <= 0
            or phase_count < 1
            or not phase_count.is_integer()
            or export_rate < 0
            or super_export_rate < 0
            or export_allowance < 0
            or export_discharge_power < 0
            or not 50 <= discharge_efficiency <= 100
            or protected_ev_baseline < 0
            or daily_backfill_energy < 0
            or not 0 <= outside_inverter_percent <= 100
            or backfill_buffer_minutes < 0
            or not 0 <= ev_free_limit <= 100
            or ev_free_minimum < 0
            or ev_free_minimum > max_current
            or ev_settle_minutes < 0
            or ev_limit_headroom < 0
            or charge_to_full_max_hours <= 0
            or not 0 < ev_charge_efficiency <= 100
            or not 0 <= ev_arrival_reserve <= 100
            or not 0 <= ev_before_export_target <= 100
            or not 1 <= ev_learning_minimum <= 28
            or not ev_learning_minimum.is_integer()
            or site_headroom < 0
            or (service_import_limit > 0 and site_headroom > service_import_limit)
            or not 0 <= battery_target <= 100
            or not 0 < battery_efficiency <= 100
            or allowance_margin < 0
            or not 0 <= solar_spill_soc <= 100
            or telemetry_max_age <= 0
            or normalized_telemetry_max_age <= 0
            or telemetry_max_skew < 0
            or fallback < 0
            or away_fallback < 0
            or away_confirmation < 0
            or (bool(data.get(CONF_EV_CONTROL_COMMISSIONED)) and service_import_limit <= 0)
        ):
            return {"base": "invalid_site_limits"}
        if daily_backfill_energy > 0 and (
            outside_inverter_percent <= 0
            or inverter_discharge_limit <= 0
            or daily_ready >= start
        ):
            return {"base": "invalid_daily_ev_backfill"}
        if (
            data.get(CONF_EV_CONTROL_COMMISSIONED)
            and site_phase_count > 1
            and not data.get(CONF_SITE_GRID_CURRENT)
        ):
            return {"base": "multiphase_current_mapping_required"}
        if (
            data.get(CONF_EV_CONTROL_COMMISSIONED)
            and data.get(CONF_EV_CHARGE_PATH) == EV_CHARGE_PATH_SMART_SOCKET
            and (
                not data.get(CONF_EV_SMART_SOCKET)
                or smart_socket_limit < min_current
                or smart_socket_limit <= 0
            )
        ):
            return {"base": "incomplete_smart_socket_mapping"}
        return {}
