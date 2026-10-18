"""Native Fleet maintenance controls; no browser credentials or remote APIs."""

from homeassistant.components.button import ButtonEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .fleet_maintenance import async_require_admin


class MaintenanceEntity(CoordinatorEntity):
    """Stable entry-scoped identity; names and entity IDs remain user owned."""

    def __init__(self, coordinator, entry, platform, key, name):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self.entity_id = f"{platform}.home_energy_{key}"
        self._attr_name = name
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def available(self):
        return True


class MaintenanceStatus(MaintenanceEntity, SensorEntity):
    """Host or remote-site audit; availability is not inferred from a version."""

    def __init__(self, coordinator, entry, target=None):
        self.target = target
        key = f"fleet_{target['key']}_maintenance" if target else "maintenance"
        name = f"{target['name']} maintenance" if target else "Maintenance"
        super().__init__(coordinator, entry, "sensor", key, name)

    def _status(self):
        data = self.coordinator.data or {}
        return data.get(self.target["key"], {}) if self.target else data

    @property
    def native_value(self):
        return self._status().get("phase", "unknown")

    @property
    def extra_state_attributes(self):
        return self._status()


class MaintenanceVersion(MaintenanceEntity, SelectEntity):
    """Choose a cached published release, never a branch or arbitrary URL."""

    def __init__(self, hub, entry, target):
        self.target = target
        super().__init__(
            hub, entry, "select", f"fleet_{target['key']}_release", f"{target['name']} HEO release"
        )

    @property
    def options(self):
        return (
            (self.coordinator.data or {})
            .get(self.target["key"], {})
            .get(
                "available_versions",
                [],
            )
        )

    @property
    def current_option(self):
        return self.coordinator.selected_versions.get(self.target["key"])

    async def async_select_option(self, option):
        await async_require_admin(self.hass, self._context)
        await self.coordinator.async_select_version(self.target["key"], option)
        self.async_write_ha_state()


class MaintenanceButton(MaintenanceEntity, ButtonEntity):
    """Submit one deliberate per-site request, carrying the actual UI user."""

    def __init__(self, hub, entry, target, action):
        self.target = target
        self.action = action
        label = {
            "update_and_restart": "Update & restart when safe",
            "restart": "Restart",
            "check_releases": "Check releases",
        }[action]
        super().__init__(
            hub, entry, "button", f"fleet_{target['key']}_{action}", f"{target['name']} · {label}"
        )

    async def async_press(self):
        if self.action == "check_releases":
            from homeassistant.exceptions import HomeAssistantError

            result = await self.coordinator.async_check_releases(self.target["key"], self._context)
            if result.get("release_refresh_state") == "failed":
                message = (
                    "Update this site's HEO before using Check releases. "
                    "Its existing release list is unchanged."
                    if result.get("release_refresh_error") == "release_refresh_unsupported"
                    else "Could not check releases. Check the site's HACS connection and try again."
                )
                raise HomeAssistantError(message)
            return
        await self.coordinator.async_request(self.target["key"], self.action, self._context)
