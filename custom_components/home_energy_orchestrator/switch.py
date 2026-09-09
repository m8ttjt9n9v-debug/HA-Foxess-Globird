"""Explicit safety interlock for commissioning and automatic control."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnergyConfigEntry
from .const import (
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_EV_BEFORE_EXPORT_ENABLED,
    CONF_EV_CHARGE_TO_FULL,
    CONF_EV_CHARGE_TO_FULL_ENABLED,
    CONF_REHEARSAL_MODE,
    DEFAULT_AUTOMATIC_CHARGE_ENABLED,
    DEFAULT_EV_BEFORE_EXPORT_ENABLED,
    DEFAULT_EV_CHARGE_TO_FULL_ENABLED,
    DOMAIN,
)
from .coordinator import EnergyCoordinator

SAFETY_DESCRIPTION = SwitchEntityDescription(
    key="safety_lock",
    name="Safety Lock",
    icon="mdi:lock",
    entity_category=EntityCategory.CONFIG,
)
EXPORT_DESCRIPTION = SwitchEntityDescription(
    key="automatic_export",
    name="Automatic ZEROHERO Export",
    icon="mdi:transmission-tower-export",
    entity_category=EntityCategory.CONFIG,
)
CHARGE_DESCRIPTION = SwitchEntityDescription(
    key="automatic_charge",
    name="Automatic Battery Free Charge",
    icon="mdi:battery-arrow-up",
    entity_category=EntityCategory.CONFIG,
)
EV_DESCRIPTION = SwitchEntityDescription(
    key="automatic_ev_control",
    name="Automatic EV Control",
    icon="mdi:ev-station",
    entity_category=EntityCategory.CONFIG,
)
EV_BEFORE_EXPORT_DESCRIPTION = SwitchEntityDescription(
    key="ev_before_export",
    name="Prioritise EV Before Export",
    icon="mdi:car-electric-outline",
    entity_category=EntityCategory.CONFIG,
)
CHARGE_TO_FULL_DESCRIPTION = SwitchEntityDescription(
    key="ev_charge_to_full",
    name="EV Charge to Full",
    icon="mdi:battery-arrow-up",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: EnergyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Expose the config-backed safety lock as an unambiguous switch."""
    registry = er.async_get(hass)
    for description in (
        SAFETY_DESCRIPTION,
        CHARGE_DESCRIPTION,
        EXPORT_DESCRIPTION,
        EV_DESCRIPTION,
        EV_BEFORE_EXPORT_DESCRIPTION,
        CHARGE_TO_FULL_DESCRIPTION,
    ):
        unique_id = f"{entry.entry_id}_{description.key}"
        current_entity_id = registry.async_get_entity_id("switch", DOMAIN, unique_id)
        stable_entity_id = f"switch.home_energy_{description.key}"
        if current_entity_id and current_entity_id != stable_entity_id:
            if registry.async_get(stable_entity_id) is None:
                registry.async_update_entity(current_entity_id, new_entity_id=stable_entity_id)
    async_add_entities(
        (
            SafetyLockSwitch(entry.runtime_data, entry, SAFETY_DESCRIPTION),
            AutomaticChargeSwitch(entry.runtime_data, entry, CHARGE_DESCRIPTION),
            AutomaticExportSwitch(entry.runtime_data, entry, EXPORT_DESCRIPTION),
            AutomaticEvControlSwitch(entry.runtime_data, entry, EV_DESCRIPTION),
            EvBeforeExportSwitch(
                entry.runtime_data,
                entry,
                EV_BEFORE_EXPORT_DESCRIPTION,
            ),
            EvChargeToFullSwitch(
                entry.runtime_data,
                entry,
                CHARGE_TO_FULL_DESCRIPTION,
            ),
        )
    )


class SafetyLockSwitch(CoordinatorEntity[EnergyCoordinator], SwitchEntity):
    """ON means locked and prevents all FoxESS/Tessie hardware writes."""

    entity_description: SwitchEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: SwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = f"switch.home_energy_{description.key}"
        self._attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        """Return true when the no-write interlock is engaged."""
        return bool(self.coordinator.config.get(CONF_REHEARSAL_MODE, True))

    async def async_turn_on(self, **kwargs: object) -> None:
        """Engage the interlock immediately and persist it."""
        await self._set_locked(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Disengage only the interlock; automatic control remains separate."""
        await self._set_locked(False)

    async def _set_locked(self, locked: bool) -> None:
        config = {**self._entry.data, CONF_REHEARSAL_MODE: locked}
        self.hass.config_entries.async_update_entry(self._entry, data=config)
        self.coordinator.config[CONF_REHEARSAL_MODE] = locked
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()


class AutomaticExportSwitch(CoordinatorEntity[EnergyCoordinator], SwitchEntity):
    """Independent behavior toggle; ownership and Safety Lock remain mandatory."""

    entity_description: SwitchEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: SwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = f"switch.home_energy_{description.key}"
        self._attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.config.get(CONF_AUTOMATIC_EXPORT_ENABLED, False))

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._set_enabled(False)

    async def _set_enabled(self, enabled: bool) -> None:
        config = {**self._entry.data, CONF_AUTOMATIC_EXPORT_ENABLED: enabled}
        self.hass.config_entries.async_update_entry(self._entry, data=config)
        self.coordinator.config[CONF_AUTOMATIC_EXPORT_ENABLED] = enabled
        self.async_write_ha_state()
        controller = self.coordinator.active_controller
        if controller is not None:
            await controller.async_reconcile()
        self.coordinator.async_update_listeners()


class AutomaticChargeSwitch(CoordinatorEntity[EnergyCoordinator], SwitchEntity):
    """Independent fixed-window battery-charge request."""

    entity_description: SwitchEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: SwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = "switch.home_energy_automatic_charge"
        self._attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        return bool(
            self.coordinator.config.get(
                CONF_AUTOMATIC_CHARGE_ENABLED,
                DEFAULT_AUTOMATIC_CHARGE_ENABLED,
            )
        )

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._set_enabled(False)

    async def _set_enabled(self, enabled: bool) -> None:
        config = {**self._entry.data, CONF_AUTOMATIC_CHARGE_ENABLED: enabled}
        self.hass.config_entries.async_update_entry(self._entry, data=config)
        self.coordinator.config[CONF_AUTOMATIC_CHARGE_ENABLED] = enabled
        self.async_write_ha_state()
        controller = self.coordinator.active_controller
        if controller is not None:
            await controller.async_reconcile()
        self.coordinator.async_update_listeners()


class AutomaticEvControlSwitch(CoordinatorEntity[EnergyCoordinator], SwitchEntity):
    """Independent default-off EV intent; Safety Lock remains authoritative."""

    entity_description: SwitchEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: SwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = f"switch.home_energy_{description.key}"
        self._attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        return bool(
            self.coordinator.config.get(CONF_EV_AUTOMATIC_CONTROL_ENABLED, False)
        )

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._set_enabled(False)

    async def _set_enabled(self, enabled: bool) -> None:
        config = {
            **self._entry.data,
            CONF_EV_AUTOMATIC_CONTROL_ENABLED: enabled,
        }
        self.hass.config_entries.async_update_entry(self._entry, data=config)
        self.coordinator.config[CONF_EV_AUTOMATIC_CONTROL_ENABLED] = enabled
        self.async_write_ha_state()
        controller = self.coordinator.ev_controller
        if controller is not None:
            await controller.async_reconcile()
        self.coordinator.async_update_listeners()


class EvBeforeExportSwitch(CoordinatorEntity[EnergyCoordinator], SwitchEntity):
    """Temporarily withhold automatic export while EV SoC is below target."""

    entity_description: SwitchEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: SwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = "switch.home_energy_ev_before_export"
        self._attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        return bool(
            self.coordinator.config.get(
                CONF_EV_BEFORE_EXPORT_ENABLED,
                DEFAULT_EV_BEFORE_EXPORT_ENABLED,
            )
        )

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._set_enabled(False)

    async def _set_enabled(self, enabled: bool) -> None:
        config = {**self._entry.data, CONF_EV_BEFORE_EXPORT_ENABLED: enabled}
        self.hass.config_entries.async_update_entry(self._entry, data=config)
        self.coordinator.config[CONF_EV_BEFORE_EXPORT_ENABLED] = enabled
        self.async_write_ha_state()
        controller = self.coordinator.active_controller
        if controller is not None:
            await controller.async_reconcile()
        self.coordinator.async_update_listeners()


class EvChargeToFullSwitch(CoordinatorEntity[EnergyCoordinator], SwitchEntity):
    """Persistent user intent that temporarily overrides EV charge targets."""

    entity_description: SwitchEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: SwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = "switch.home_energy_ev_charge_to_full"
        self._attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        """Return the explicit HEO-owned override state."""
        if CONF_EV_CHARGE_TO_FULL_ENABLED not in self.coordinator.config:
            legacy_entity = self.coordinator.config.get(CONF_EV_CHARGE_TO_FULL)
            return isinstance(legacy_entity, str) and self.hass.states.is_state(
                legacy_entity, "on"
            )
        return bool(
            self.coordinator.config.get(
                CONF_EV_CHARGE_TO_FULL_ENABLED,
                DEFAULT_EV_CHARGE_TO_FULL_ENABLED,
            )
        )

    async def async_turn_on(self, **kwargs: object) -> None:
        """Request charge-to-full policy without bypassing any safety gate."""
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Resume normal learned/free-window charge targets."""
        await self._set_enabled(False)

    async def _set_enabled(self, enabled: bool) -> None:
        config = {
            key: value
            for key, value in self._entry.data.items()
            if key != CONF_EV_CHARGE_TO_FULL
        }
        config[CONF_EV_CHARGE_TO_FULL_ENABLED] = enabled
        self.hass.config_entries.async_update_entry(self._entry, data=config)
        self.coordinator.config.pop(CONF_EV_CHARGE_TO_FULL, None)
        self.coordinator.config[CONF_EV_CHARGE_TO_FULL_ENABLED] = enabled
        self.async_write_ha_state()
        controller = self.coordinator.ev_controller
        if controller is not None:
            await controller.async_reconcile()
        self.coordinator.async_update_listeners()
