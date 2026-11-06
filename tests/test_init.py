"""Tests for setting up and unloading MMH Monitor."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mmh_monitor.const import CONF_SITE_SLUG, DOMAIN


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    """The entry loads and unloads cleanly."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_SITE_SLUG: "cliente-exemplo"})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
