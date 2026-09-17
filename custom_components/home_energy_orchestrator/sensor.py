"""Observer entities for the public, compact v0.1 surface."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import EnergyConfigEntry
from .const import DOMAIN
from .coordinator import EnergyCoordinator
from .entity_catalogue import SENSOR_DESCRIPTIONS as DESCRIPTIONS
from .read_model import (
    build_site_read_model,
    control_mode,
    effective_export_plan,
    export_status,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: EnergyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add observer entities."""
    async_add_entities(
        EnergySensor(entry.runtime_data, entry, description) for description in DESCRIPTIONS
    )


class EnergySensor(CoordinatorEntity[EnergyCoordinator], SensorEntity):
    """Expose a single calculated ledger term."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = f"sensor.home_energy_{description.key}"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="FoxESS GloBird Tesla Energy Orchestrator",
            model="Energy Orchestrator",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _control_mode(self) -> str:
        """Return the commissioned control surface, not the ledger reason."""
        return control_mode(self.coordinator)

    def _effective_export_plan(self):
        """Expose an export plan only while export is actually permitted."""
        return effective_export_plan(self.coordinator)

    def _export_status(self) -> str:
        """Explain whether export is disabled, withheld, or running."""
        return export_status(self.coordinator)

    def _fleet_summary_attributes(self) -> dict[str, object]:
        """Return one compact, read-only payload for a monitoring hub."""
        return build_site_read_model(self.coordinator).fleet_attributes(dt_util.now())

    @property
    def native_value(self):
        read_model = build_site_read_model(self.coordinator)
        return read_model.sensor_values()[self.entity_description.key]

    @property
    def extra_state_attributes(self):
        if self.entity_description.key == "fleet_summary":
            return self._fleet_summary_attributes()
        read_model = build_site_read_model(self.coordinator)
        if attributes := read_model.telemetry.entity_attributes(
            self.entity_description.key
        ):
            return attributes
        if self.entity_description.key == "zerohero_import_window":
            accumulator = self.coordinator.zerohero_import
            return {
                "hourly_import_kwh": {
                    bucket: round(value, 6)
                    for bucket, value in accumulator.hourly_import_kwh.items()
                },
                "accumulator_date": (
                    None if accumulator.local_date is None else accumulator.local_date.isoformat()
                ),
                "last_sample": (
                    None if accumulator.last_at is None else accumulator.last_at.isoformat()
                ),
                "threshold_kwh_per_hour": (
                    self.coordinator.runtime_config.tariff.zero_import_threshold_kwh_per_hour
                ),
            }
        if self.entity_description.key == "estimated_export_revenue":
            return read_model.cost.export_revenue_attributes()
        if self.entity_description.key == "estimated_net_cost":
            return read_model.cost.sensor_attributes()
        if self.entity_description.key in {
            "forecast_yesterday_cost",
            "globird_yesterday_actual_cost",
            "forecast_error_yesterday",
            "forecast_scorecard_status",
        }:
            return read_model.scorecard.sensor_attributes()
        if self.entity_description.key == "ev_control_status":
            return read_model.ev.control_attributes()
        if self.entity_description.key == "house_occupancy_state":
            return read_model.learning.occupancy_attributes()
        if self.entity_description.key != "status":
            return None
        return read_model.status_attributes()
