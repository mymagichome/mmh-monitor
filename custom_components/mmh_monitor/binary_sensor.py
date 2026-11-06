"""Binary sensors for MMH Monitor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MMHMonitorConfigEntry, MMHMonitorCoordinator
from .entity import MMHMonitorEntity
from .models import HealthLevel


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MMHMonitorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities([ProblemSensor(coordinator), CentralDeliverySensor(coordinator)])


class ProblemSensor(MMHMonitorEntity, BinarySensorEntity):
    """On when the overall level is not ok."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: MMHMonitorCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "binary_sensor", "problema")

    @property
    def is_on(self) -> bool:
        """Return True when there is a problem."""
        return self.coordinator.data.level is not HealthLevel.OK

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the overall level."""
        return {"nivel": self.coordinator.data.level.state}


class CentralDeliverySensor(MMHMonitorEntity, BinarySensorEntity):
    """On when the last delivery to InfluxDB succeeded."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: MMHMonitorCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "binary_sensor", "envio_central")

    @property
    def is_on(self) -> bool | None:
        """Return the outcome of the last InfluxDB delivery."""
        return self.coordinator.publish_status.influx_ok

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the last error, if any."""
        return {"ultimo_erro": self.coordinator.publish_status.influx_last_error}
