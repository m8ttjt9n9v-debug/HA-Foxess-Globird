"""Persistent dashboard settings for market observation, never device control."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .aemo_monitor import AemoMarketMonitor
from .configuration import AemoMonitorConfiguration
from .const import (
    AEMO_REGIONS,
    CONF_AEMO_EXPORT_THRESHOLD,
    CONF_AEMO_IMPORT_THRESHOLD,
    CONF_AEMO_MONITOR_ENABLED,
    CONF_AEMO_REGION,
    DOMAIN,
)
from .coordinator import EnergyCoordinator
from .entity_catalogue import (
    AEMO_CLEAR_IMPORT_DESCRIPTION,
    AEMO_REGION_DESCRIPTION,
    AEMO_SWITCH_DESCRIPTION,
)

_SETTING_KEYS = frozenset(
    {
        CONF_AEMO_MONITOR_ENABLED,
        CONF_AEMO_REGION,
        CONF_AEMO_EXPORT_THRESHOLD,
        CONF_AEMO_IMPORT_THRESHOLD,
    }
)
_NOT_CONFIGURED = "Not configured"


async def _update_settings(
    owner: EnergyCoordinator, entry: ConfigEntry, changes: dict[str, object]
) -> None:
    """Persist a validated transaction without waking either hardware policy."""
    monitor: AemoMarketMonitor = owner.market_monitor
    if not changes.keys() <= _SETTING_KEYS:
        raise HomeAssistantError("Only AEMO monitoring settings can be changed here")
    async with monitor.settings_lock:
        candidate = {**entry.data, **entry.options, **changes}
        errors = AemoMonitorConfiguration.validate_mapping(candidate)
        if errors:
            if CONF_AEMO_REGION in errors:
                message = (
                    "Choose a market region first, or switch monitoring off before clearing it"
                )
            else:
                message = (
                    "Use finite price thresholds: supply must be positive and "
                    "consumption must be lower than supply"
                )
            raise HomeAssistantError(message)
        # Options override entry data on reload. Remove only changed market
        # keys from that overlay so a dashboard edit actually survives reload.
        owner.hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, **changes},
            options={key: value for key, value in entry.options.items() if key not in changes},
        )
        if CONF_AEMO_MONITOR_ENABLED in changes:
            owner.update_config_value(CONF_AEMO_MONITOR_ENABLED, changes[CONF_AEMO_MONITOR_ENABLED])
        if CONF_AEMO_REGION in changes:
            owner.update_config_value(CONF_AEMO_REGION, changes[CONF_AEMO_REGION])
        if CONF_AEMO_EXPORT_THRESHOLD in changes:
            owner.update_config_value(
                CONF_AEMO_EXPORT_THRESHOLD, changes[CONF_AEMO_EXPORT_THRESHOLD]
            )
        if CONF_AEMO_IMPORT_THRESHOLD in changes:
            owner.update_config_value(
                CONF_AEMO_IMPORT_THRESHOLD, changes[CONF_AEMO_IMPORT_THRESHOLD]
            )
        await monitor.async_update_configuration(owner.runtime_config.aemo_monitor)


class _AemoSettingEntity(CoordinatorEntity[AemoMarketMonitor]):
    """Market settings remain editable with monitoring off or data unavailable."""

    def __init__(self, owner: EnergyCoordinator, entry: ConfigEntry, description) -> None:
        super().__init__(owner.market_monitor)
        self.entity_description = description
        self._owner = owner
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def available(self) -> bool:
        return True

    async def _set(self, key: str, value: object) -> None:
        await _update_settings(self._owner, self._entry, {key: value})
        self.async_write_ha_state()


class AemoMonitorSwitch(_AemoSettingEntity, SwitchEntity):
    """ON requests market observation only; it cannot enable energy control."""

    def __init__(self, owner: EnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(owner, entry, AEMO_SWITCH_DESCRIPTION)
        self.entity_id = "switch.home_energy_aemo_monitor"

    @property
    def is_on(self) -> bool:
        return self._owner.runtime_config.aemo_monitor.enabled

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._set(CONF_AEMO_MONITOR_ENABLED, True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._set(CONF_AEMO_MONITOR_ENABLED, False)


class AemoRegionSelect(_AemoSettingEntity, SelectEntity):
    """An explicit market-region choice, with no guessed default."""

    _attr_options = [_NOT_CONFIGURED, *AEMO_REGIONS]

    def __init__(self, owner: EnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(owner, entry, AEMO_REGION_DESCRIPTION)
        self.entity_id = "select.home_energy_aemo_region"

    @property
    def current_option(self) -> str:
        return self._owner.runtime_config.aemo_monitor.region or _NOT_CONFIGURED

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise HomeAssistantError("Choose a supported AEMO market region")
        await self._set(CONF_AEMO_REGION, None if option == _NOT_CONFIGURED else option)


class AemoThresholdNumber(_AemoSettingEntity, NumberEntity):
    """Edit a possible-opportunity threshold without assuming event payment."""

    def __init__(
        self, owner: EnergyCoordinator, entry: ConfigEntry, description: NumberEntityDescription
    ) -> None:
        super().__init__(owner, entry, description)
        self.entity_id = f"number.home_energy_{description.key}"
        self._setting_key = (
            CONF_AEMO_EXPORT_THRESHOLD
            if description.key == "aemo_export_threshold"
            else CONF_AEMO_IMPORT_THRESHOLD
        )

    @property
    def native_value(self) -> float | None:
        configuration = self._owner.runtime_config.aemo_monitor
        return (
            configuration.export_threshold_per_kwh
            if self._setting_key == CONF_AEMO_EXPORT_THRESHOLD
            else configuration.import_threshold_per_kwh
        )

    async def async_set_native_value(self, value: float) -> None:
        await self._set(self._setting_key, float(value))


class AemoClearImportThresholdButton(_AemoSettingEntity, ButtonEntity):
    """Disable consumption detection by clearing its optional threshold."""

    def __init__(self, owner: EnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(owner, entry, AEMO_CLEAR_IMPORT_DESCRIPTION)
        self.entity_id = "button.home_energy_aemo_clear_import_threshold"

    async def async_press(self) -> None:
        await self._set(CONF_AEMO_IMPORT_THRESHOLD, None)
