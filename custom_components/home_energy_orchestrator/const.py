"""Constants for Home Energy Orchestrator."""

from __future__ import annotations

DOMAIN = "home_energy_orchestrator"
PLATFORMS = ["sensor"]

CONF_BATTERY_SOC = "battery_soc_entity"
CONF_BATTERY_CAPACITY_ENTITY = "battery_capacity_entity"
CONF_BATTERY_CAPACITY = "battery_capacity_kwh"
CONF_BATTERY_FLOOR = "battery_floor_percent"
CONF_GRID_POWER = "grid_power_entity"
CONF_GRID_IMPORT_POSITIVE = "grid_import_positive"
CONF_HOUSE_LOAD = "house_load_entity"
CONF_RESERVE = "reserve_kwh"
CONF_EV_SOC = "ev_soc_entity"
CONF_EV_MAX_CURRENT = "ev_max_current"
CONF_EV_MIN_CURRENT = "ev_min_current"
CONF_EV_VOLTAGE = "ev_voltage"
CONF_FREE_CHARGE_START = "free_charge_window_start"
CONF_FREE_CHARGE_END = "free_charge_window_end"
CONF_HOUSE_LEARNING_FALLBACK = "house_learning_fallback_kwh"

DEFAULT_BATTERY_FLOOR = 10.0
DEFAULT_RESERVE_KWH = 0.0
DEFAULT_EV_VOLTAGE = 230.0
DEFAULT_EV_MIN_CURRENT = 0.0
DEFAULT_EV_MAX_CURRENT = 0.0
DEFAULT_FREE_CHARGE_START = "12:01:00"
DEFAULT_FREE_CHARGE_END = "14:59:00"
DEFAULT_HOUSE_LEARNING_FALLBACK_KWH = 17.5

REASON_INVALID_CONFIGURATION = "invalid_configuration"
REASON_MISSING_BATTERY_SOC = "missing_battery_soc"
REASON_MISSING_GRID_POWER = "missing_grid_power"
REASON_OBSERVER_ONLY = "observer_only"
