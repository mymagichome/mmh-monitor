"""Base entity for MMH Monitor."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MMHMonitorCoordinator


class MMHMonitorEntity(CoordinatorEntity[MMHMonitorCoordinator]):
    """Entity attached to the single MMH Monitor device.

    Entity IDs are fixed (``<platform>.mmh_<key>``) so dashboards, alerts and
    reports work the same on every site, whatever the system language.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: MMHMonitorCoordinator, platform: str, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self.entity_id = f"{platform}.mmh_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="MMH Monitor",
            manufacturer="My Magic Home",
            model=f"Site {coordinator.site}",
            sw_version=coordinator.version,
            entry_type=DeviceEntryType.SERVICE,
        )
