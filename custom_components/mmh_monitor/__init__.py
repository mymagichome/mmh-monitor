"""The MMH Monitor integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .coordinator import MMHMonitorConfigEntry, MMHMonitorCoordinator
from .thresholds import ThresholdManager

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: MMHMonitorConfigEntry) -> bool:
    """Set up MMH Monitor from a config entry."""
    integration = await async_get_integration(hass, DOMAIN)
    thresholds = ThresholdManager(hass, entry)
    await thresholds.async_setup()
    entry.async_on_unload(thresholds.async_shutdown)
    coordinator = MMHMonitorCoordinator(
        hass, entry, str(integration.version), thresholds
    )
    await coordinator.async_setup_checks()
    await coordinator.async_config_entry_first_refresh()

    # Keep the coordinator polling even when no entity is listening.
    entry.async_on_unload(coordinator.async_add_listener(lambda: None))

    entry.runtime_data = coordinator
    if thresholds.url:
        # Fetch remote thresholds without delaying startup; the cached or
        # default values are used until the download finishes.
        entry.async_create_background_task(
            hass, thresholds.async_refresh(), f"{DOMAIN} thresholds refresh"
        )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MMHMonitorConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded
