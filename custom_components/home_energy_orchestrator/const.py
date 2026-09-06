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
CONF_BONUS_WINDOW_START = "bonus_window_start"
CONF_BONUS_WINDOW_END = "bonus_window_end"
CONF_ZERO_IMPORT_THRESHOLD_KW = "zero_import_threshold_kw"
CONF_ZERO_IMPORT_CONFIRM_MINUTES = "zero_import_confirm_minutes"
CONF_FREE_CHARGE_START = "free_charge_window_start"
CONF_FREE_CHARGE_END = "free_charge_window_end"
CONF_HOUSE_LEARNING_FALLBACK = "house_learning_fallback_kwh"
CONF_AUTOMATIC_CONTROL_ENABLED = "automatic_control_enabled"
CONF_AUTOMATIC_EXPORT_ENABLED = "automatic_export_enabled"
CONF_EV_AUTOMATIC_CONTROL_ENABLED = "ev_automatic_control_enabled"
CONF_EXPORT_ALLOWANCE_KWH = "export_allowance_kwh"
CONF_EXPORT_DISCHARGE_POWER_KW = "export_discharge_power_kw"
CONF_DISCHARGE_EFFICIENCY_PERCENT = "discharge_efficiency_percent"
CONF_FORCE_DISCHARGE_FINISH = "force_discharge_finish"
CONF_EV_PROTECTED_BASELINE_A = "ev_protected_baseline_a"
CONF_FOXESS_CONTROL_OWNER = "foxess_control_owner"
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
CONF_EV_AT_HOME = "ev_at_home_entity"
CONF_EV_CABLE_CONNECTED = "ev_cable_connected_entity"
CONF_EV_CHARGING_STATE = "ev_charging_state_entity"
CONF_EV_ACTUAL_CURRENT = "ev_actual_current_entity"
CONF_EV_STORED_ENERGY = "ev_stored_energy_entity"
CONF_EV_CURRENT_LIMIT = "ev_current_limit_entity"
CONF_EV_CHARGE_LIMIT = "ev_charge_limit_entity"
CONF_EV_CHARGE_SWITCH = "ev_charge_switch_entity"
CONF_EV_LOCATION_MODE = "ev_location_mode"
CONF_EV_FREE_WINDOW_PRIORITY = "ev_free_window_priority"
CONF_EV_FREE_WINDOW_CHARGE_LIMIT = "ev_free_window_charge_limit_percent"
CONF_EV_FREE_WINDOW_MINIMUM_CURRENT = "ev_free_window_minimum_current_a"
CONF_EV_FREE_WINDOW_SETTLE_MINUTES = "ev_free_window_settle_minutes"
CONF_EV_DIRECT_LIMIT_HEADROOM = "ev_direct_limit_headroom_percent"
CONF_EV_CHARGE_EFFICIENCY = "ev_charge_efficiency_percent"
CONF_SITE_GRID_HEADROOM_CURRENT = "site_grid_headroom_current_a"
CONF_BATTERY_FREE_WINDOW_TARGET = "battery_free_window_target_percent"
CONF_BATTERY_CHARGE_EFFICIENCY = "battery_charge_efficiency_percent"
CONF_EV_ALLOWANCE_GUARD_ENABLED = "ev_allowance_guard_enabled"
CONF_EV_ALLOWANCE_SAFETY_MARGIN = "ev_allowance_safety_margin_kwh"
CONF_EV_CONTROL_COMMISSIONED = "ev_control_commissioned"
EV_REQUIRED_ENTITY_KEYS = (
    CONF_EV_SOC,
    CONF_EV_AT_HOME,
    CONF_EV_CABLE_CONNECTED,
    CONF_EV_CHARGING_STATE,
    CONF_EV_ACTUAL_CURRENT,
    CONF_EV_STORED_ENERGY,
    CONF_EV_CURRENT_LIMIT,
    CONF_EV_CHARGE_LIMIT,
    CONF_EV_CHARGE_SWITCH,
)

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
DEFAULT_EV_MIN_CURRENT = 0.0
DEFAULT_EV_MAX_CURRENT = 0.0
DEFAULT_FREE_CHARGE_START = "12:01:00"
DEFAULT_FREE_CHARGE_END = "14:59:00"
DEFAULT_HOUSE_LEARNING_FALLBACK_KWH = 17.5
DEFAULT_AUTOMATIC_CONTROL_ENABLED = False
DEFAULT_AUTOMATIC_EXPORT_ENABLED = False
DEFAULT_EV_AUTOMATIC_CONTROL_ENABLED = False
DEFAULT_EXPORT_ALLOWANCE_KWH = 15.0
DEFAULT_EXPORT_DISCHARGE_POWER_KW = 10.0
DEFAULT_DISCHARGE_EFFICIENCY_PERCENT = 95.0
DEFAULT_FORCE_DISCHARGE_FINISH = "21:01:00"
DEFAULT_EV_PROTECTED_BASELINE_A = 0.0
DEFAULT_EV_LOCATION_MODE = "auto"
EV_LOCATION_MODES = ("auto", "home", "away")
DEFAULT_EV_FREE_WINDOW_PRIORITY = "ev"
EV_FREE_WINDOW_PRIORITIES = ("house_battery", "ev")
DEFAULT_EV_FREE_WINDOW_CHARGE_LIMIT = 90.0
DEFAULT_EV_FREE_WINDOW_MINIMUM_CURRENT = 1.0
DEFAULT_EV_FREE_WINDOW_SETTLE_MINUTES = 5.0
DEFAULT_EV_DIRECT_LIMIT_HEADROOM = 2.0
DEFAULT_EV_CHARGE_EFFICIENCY = 90.0
DEFAULT_SITE_GRID_HEADROOM_CURRENT = 1.0
DEFAULT_BATTERY_FREE_WINDOW_TARGET = 100.0
DEFAULT_BATTERY_CHARGE_EFFICIENCY = 95.0
DEFAULT_EV_ALLOWANCE_GUARD_ENABLED = True
DEFAULT_EV_ALLOWANCE_SAFETY_MARGIN = 0.0
DEFAULT_EV_CONTROL_COMMISSIONED = False
FOXESS_CONTROL_OWNER_OBSERVER = "observer_only"
FOXESS_CONTROL_OWNER_MODBUS = "local_modbus"
FOXESS_CONTROL_OWNER_CLOUD = "foxcloud_scheduler"
FOXESS_CONTROL_OWNERS = (
    FOXESS_CONTROL_OWNER_OBSERVER,
    FOXESS_CONTROL_OWNER_MODBUS,
    FOXESS_CONTROL_OWNER_CLOUD,
)
DEFAULT_FOXESS_CONTROL_OWNER = FOXESS_CONTROL_OWNER_OBSERVER
DEFAULT_REHEARSAL_MODE = True
DEFAULT_BONUS_WINDOW_START = "18:00:00"
DEFAULT_BONUS_WINDOW_END = "21:00:00"

REASON_INVALID_CONFIGURATION = "invalid_configuration"
REASON_MISSING_BATTERY_SOC = "missing_battery_soc"
REASON_MISSING_GRID_POWER = "missing_grid_power"
REASON_OBSERVER_ONLY = "observer_only"
