"""Explicit submit/stop buttons for the commissioning test tab."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnergyConfigEntry
from .aemo_monitor_controls import AemoClearImportThresholdButton
from .coordinator import EnergyCoordinator
from .entity_catalogue import BUTTON_DESCRIPTIONS as DESCRIPTIONS
from .maintenance_entities import MaintenanceButton


async def async_setup_entry(
    hass: HomeAssistant, entry: EnergyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add explicit buttons; pressing one is the submit action."""
    if (hub := entry.runtime_data.fleet_maintenance) is not None:
        async_add_entities(
            MaintenanceButton(hub, entry, target, action)
            for target in hub.targets
            for action in ("update_and_restart", "restart", "check_releases")
        )
    async_add_entities(
        TestButton(entry.runtime_data, entry, description) for description in DESCRIPTIONS
    )
    async_add_entities((AemoClearImportThresholdButton(entry.runtime_data, entry),))


class TestButton(CoordinatorEntity[EnergyCoordinator], ButtonEntity):
    """A user-triggered commissioning action."""

    entity_description: ButtonEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: ButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = f"button.home_energy_{description.key}"
        self._attr_has_entity_name = True

    async def async_press(self) -> None:
        test = self.coordinator.manual_test
        if self.entity_description.key == "test_force_charge":
            await test.async_start("charge", test.charge_power_kw, test.duration_minutes)
        elif self.entity_description.key == "test_force_discharge":
            await test.async_start("discharge", test.discharge_power_kw, test.duration_minutes)
        else:
            await test.async_stop()
