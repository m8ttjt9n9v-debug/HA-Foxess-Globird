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
from .const import CONF_REHEARSAL_MODE, DOMAIN
from .coordinator import EnergyCoordinator

DESCRIPTION = SwitchEntityDescription(
    key="safety_lock",
    name="Safety Lock",
    icon="mdi:lock",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: EnergyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Expose the config-backed safety lock as an unambiguous switch."""
    registry = er.async_get(hass)
    unique_id = f"{entry.entry_id}_{DESCRIPTION.key}"
    current_entity_id = registry.async_get_entity_id("switch", DOMAIN, unique_id)
    stable_entity_id = f"switch.home_energy_{DESCRIPTION.key}"
    if current_entity_id and current_entity_id != stable_entity_id:
        if registry.async_get(stable_entity_id) is None:
            registry.async_update_entity(current_entity_id, new_entity_id=stable_entity_id)
    async_add_entities((SafetyLockSwitch(entry.runtime_data, entry, DESCRIPTION),))


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
