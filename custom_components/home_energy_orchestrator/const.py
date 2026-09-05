"""Constants for Home Energy Orchestrator."""

from __future__ import annotations

DOMAIN = "home_energy_orchestrator"
PLATFORMS = ["sensor", "number", "button", "switch"]

CONF_BATTERY_SOC = "battery_soc_entity"
CONF_BATTERY_CAPACITY_ENTITY = "battery_capacity_entity"
CONF_BATTERY_CAPACITY = "battery_capacity_kwh"
CONF_BATTERY_FLOOR = "battery_floor_percent"
CONF_GRID_POWER = "grid_power_entity"
CONF_DAILY_IMPORT_ENTITY = "daily_import_entity"
CONF_DAILY_FREE_ALLOWANCE_KWH = "daily_free_allowance_kwh"
CONF_PEAK_WINDOW_START = "peak_window_start"
CONF_PEAK_WINDOW_END = "peak_window_end"
CONF_PEAK_RATE = "peak_rate_per_kwh"
CONF_OFFPEAK_RATE = "offpeak_rate_per_kwh"
CONF_OFFPEAK_BALANCE_RATE = "offpeak_balance_rate_per_kwh"
CONF_SHOULDER_RATE = "shoulder_rate_per_kwh"
CONF_EXPORT_RATE = "export_rate_per_kwh"
CONF_SUPER_EXPORT_RATE = "super_export_rate_per_kwh"
CONF_DAILY_CHARGE = "daily_charge"
CONF_GRID_IMPORT_POSITIVE = "grid_import_positive"
CONF_SITE_PHASE_COUNT = "site_phase_count"
CONF_SERVICE_IMPORT_LIMIT_A = "service_import_limit_a"
CONF_EXPORT_LIMIT_KW = "export_limit_kw"
CONF_INVERTER_CHARGE_LIMIT_KW = "inverter_charge_limit_kw"
CONF_INVERTER_DISCHARGE_LIMIT_KW = "inverter_discharge_limit_kw"
CONF_HOUSE_LOAD = "house_load_entity"
CONF_SOLAR_POWER = "solar_power_entity"
CONF_RESERVE = "reserve_kwh"
CONF_EV_SOC = "ev_soc_entity"
CONF_EV_MAX_CURRENT = "ev_max_current"
CONF_EV_MIN_CURRENT = "ev_min_current"
CONF_EV_VOLTAGE = "ev_voltage"
CONF_EV_PHASE_COUNT = "ev_phase_count"
CONF_EV_CHARGER_PROFILE = "ev_charger_profile"
CONF_INVERTER_CAPACITY = "inverter_capacity_kw"
CONF_BONUS_LOAD_FOLLOWING_PERCENT = "bonus_load_following_percent"
CONF_NON_FREE_LOAD_FOLLOWING_PERCENT = "non_free_load_following_percent"
CONF_LOAD_FOLLOWING_OVERRIDE = "load_following_override"
CONF_BONUS_WINDOW_START = "bonus_window_start"
CONF_BONUS_WINDOW_END = "bonus_window_end"
CONF_ZERO_IMPORT_THRESHOLD_KW = "zero_import_threshold_kw"
CONF_ZERO_IMPORT_CONFIRM_MINUTES = "zero_import_confirm_minutes"
CONF_FREE_CHARGE_START = "free_charge_window_start"
CONF_FREE_CHARGE_END = "free_charge_window_end"
CONF_FREE_CHARGE_FULL_BATTERY_IMPORT_THRESHOLD_KWH = (
    "free_charge_full_battery_import_threshold_kwh"
)
CONF_HOUSE_LEARNING_FALLBACK = "house_learning_fallback_kwh"
CONF_AUTOMATIC_CONTROL_ENABLED = "automatic_control_enabled"
CONF_FOXESS_CONTROL_OWNER = "foxess_control_owner"
CONF_EV_AUTOMATIC_CONTROL_ENABLED = "ev_automatic_control_enabled"
CONF_REHEARSAL_MODE = "rehearsal_mode"

# Explicit, short-lived commissioning tests. These are independent of the
# automatic scheduler and remain unavailable until the control gate is opened.
SERVICE_TEST_FORCE_CHARGE = "test_force_charge"
SERVICE_TEST_FORCE_DISCHARGE = "test_force_discharge"
SERVICE_TEST_STOP = "test_stop"

# Actuator mappings are collected for commissioning and diagnostics. The
# observer release never writes to these entities; an active release must
# still pass every mapping through its explicit safety gate.
CONF_FOXESS_WORK_MODE = "foxess_work_mode_entity"
CONF_FOXESS_FORCE_CHARGE_POWER = "foxess_force_charge_power_entity"
CONF_FOXESS_FORCE_DISCHARGE_POWER = "foxess_force_discharge_power_entity"
CONF_EV_CHARGE_LIMIT = "ev_charge_limit_entity"
CONF_EV_CURRENT_LIMIT = "ev_current_limit_entity"
CONF_EV_CHARGE_SWITCH = "ev_charge_switch_entity"

DEFAULT_BATTERY_FLOOR = 10.0
DEFAULT_RESERVE_KWH = 0.0
DEFAULT_DAILY_FREE_ALLOWANCE_KWH = 50.0
DEFAULT_PEAK_WINDOW_START = "16:00:00"
DEFAULT_PEAK_WINDOW_END = "23:00:00"
DEFAULT_PEAK_RATE = 0.594
DEFAULT_OFFPEAK_RATE = 0.0
DEFAULT_OFFPEAK_BALANCE_RATE = 0.308
DEFAULT_SHOULDER_RATE = 0.528
DEFAULT_EXPORT_RATE = 0.0
DEFAULT_SUPER_EXPORT_RATE = 0.10
DEFAULT_DAILY_CHARGE = 2.035
DEFAULT_ZERO_IMPORT_THRESHOLD_KW = 0.03
DEFAULT_ZERO_IMPORT_CONFIRM_MINUTES = 5.0
DEFAULT_SITE_PHASE_COUNT = 1
DEFAULT_SERVICE_IMPORT_LIMIT_A = 0.0
DEFAULT_EXPORT_LIMIT_KW = 0.0
DEFAULT_INVERTER_CHARGE_LIMIT_KW = 0.0
DEFAULT_INVERTER_DISCHARGE_LIMIT_KW = 0.0
DEFAULT_EV_VOLTAGE = 230.0
DEFAULT_EV_PHASE_COUNT = 1
DEFAULT_EV_CHARGER_PROFILE = "not_configured"
DEFAULT_EV_MIN_CURRENT = 0.0
DEFAULT_EV_MAX_CURRENT = 0.0
DEFAULT_FREE_CHARGE_START = "12:01:00"
DEFAULT_FREE_CHARGE_END = "14:59:00"
DEFAULT_FREE_CHARGE_FULL_BATTERY_IMPORT_THRESHOLD_KWH = 49.0
DEFAULT_HOUSE_LEARNING_FALLBACK_KWH = 17.5
DEFAULT_AUTOMATIC_CONTROL_ENABLED = False
FOXESS_CONTROL_OWNER_OBSERVER = "observer_only"
FOXESS_CONTROL_OWNER_MODBUS = "local_modbus"
FOXESS_CONTROL_OWNER_CLOUD = "foxcloud_scheduler"
FOXESS_CONTROL_OWNERS = (
    FOXESS_CONTROL_OWNER_OBSERVER,
    FOXESS_CONTROL_OWNER_MODBUS,
    FOXESS_CONTROL_OWNER_CLOUD,
)
DEFAULT_FOXESS_CONTROL_OWNER = FOXESS_CONTROL_OWNER_OBSERVER
DEFAULT_EV_AUTOMATIC_CONTROL_ENABLED = False
DEFAULT_REHEARSAL_MODE = True
DEFAULT_INVERTER_CAPACITY_KW = 0.0
DEFAULT_BONUS_LOAD_FOLLOWING_PERCENT = 20.0
DEFAULT_NON_FREE_LOAD_FOLLOWING_PERCENT = 30.0
DEFAULT_LOAD_FOLLOWING_OVERRIDE = False
DEFAULT_BONUS_WINDOW_START = "18:00:00"
DEFAULT_BONUS_WINDOW_END = "21:00:00"

# These are deliberately the only supported charger profiles in the setup
# wizard. Current is per phase; total power is calculated from voltage and the
# physical phase count rather than inferred from a nominal kW label.
EV_CHARGER_PROFILES = {
    "not_configured": (1, 0.0),
    "single_phase_10a": (1, 10.0),
    "single_phase_15a": (1, 15.0),
    "single_phase_32a": (1, 32.0),
    "three_phase_16a": (3, 16.0),
}

REASON_INVALID_CONFIGURATION = "invalid_configuration"
REASON_MISSING_BATTERY_SOC = "missing_battery_soc"
REASON_MISSING_GRID_POWER = "missing_grid_power"
REASON_OBSERVER_ONLY = "observer_only"
