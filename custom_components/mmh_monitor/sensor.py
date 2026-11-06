"""Sensors for MMH Monitor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfInformation,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .checks import ALL_KEYS
from .coordinator import MMHMonitorConfigEntry, MMHMonitorCoordinator
from .entity import MMHMonitorEntity
from .models import HealthLevel

HEALTH_OPTIONS = [HealthLevel.OK.state, HealthLevel.ATENCAO.state, HealthLevel.CRITICO.state]

# Presentation of each check sensor: (device_class, unit).
CHECK_PRESENTATION: dict[str, tuple[SensorDeviceClass | None, str | None]] = {
    "integrations": (None, None),
    "unavailable_entities": (None, PERCENTAGE),
    "disk_use": (None, PERCENTAGE),
    "memory_use": (None, PERCENTAGE),
    "load_1m": (None, None),
    "host_uptime": (SensorDeviceClass.DURATION, UnitOfTime.SECONDS),
    "ha_uptime": (SensorDeviceClass.DURATION, UnitOfTime.SECONDS),
    "system_log": (None, None),
    "recorder": (SensorDeviceClass.DATA_SIZE, UnitOfInformation.MEGABYTES),
    "updates": (None, None),
    "backup": (SensorDeviceClass.DURATION, UnitOfTime.HOURS),
    "zigbee": (None, None),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MMHMonitorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [HealthSensor(coordinator)]
    entities.extend(CheckSensor(coordinator, key) for key in ALL_KEYS)
    async_add_entities(entities)


class HealthSensor(MMHMonitorEntity, SensorEntity):
    """Overall health of the site: ok, atencao or critico."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = HEALTH_OPTIONS
    _unrecorded_attributes = frozenset({"motivos", "ultima_coleta", "ultimo_envio_ok"})

    def __init__(self, coordinator: MMHMonitorCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "sensor", "health")

    @property
    def native_value(self) -> str:
        """Return the overall level."""
        return self.coordinator.data.level.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return reasons and delivery information."""
        data = self.coordinator.data
        status = self.coordinator.publish_status
        return {
            "motivos": [
                r.message
                for r in data.results.values()
                if r.level in (HealthLevel.ATENCAO, HealthLevel.CRITICO)
            ],
            "site": self.coordinator.site,
            "versao": self.coordinator.version,
            "ultima_coleta": data.collected_at.isoformat(),
            "ultimo_envio_ok": (
                status.influx_last_success.isoformat()
                if status.influx_last_success
                else None
            ),
        }


class CheckSensor(MMHMonitorEntity, SensorEntity):
    """Measured value of one check."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset({"mensagem", "details"})

    def __init__(self, coordinator: MMHMonitorCoordinator, key: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "sensor", key)
        self._key = key
        device_class, unit = CHECK_PRESENTATION.get(key, (None, None))
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit

    @property
    def available(self) -> bool:
        """Unavailable when the check produced no result."""
        return super().available and self._key in self.coordinator.data.results

    @property
    def native_value(self) -> float | int | None:
        """Return the measured value."""
        return self.coordinator.data.results[self._key].value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return level, message and details."""
        result = self.coordinator.data.results[self._key]
        return {
            "nivel": result.level.state,
            "mensagem": result.message,
            "details": result.details,
        }
