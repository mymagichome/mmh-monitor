"""Tests for the MMH Monitor config flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mmh_monitor.const import CONF_SITE_SLUG, DOMAIN


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """A valid slug creates the entry with the expected title."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SITE_SLUG: "diegopasa"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "MMH Monitor (diegopasa)"
    assert result["data"] == {CONF_SITE_SLUG: "diegopasa"}


async def test_user_flow_invalid_slug(hass: HomeAssistant) -> None:
    """An invalid slug shows an error and keeps the form open."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SITE_SLUG: "Diego Pasa"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SITE_SLUG: "invalid_slug"}


async def test_single_instance(hass: HomeAssistant) -> None:
    """A second instance is not allowed."""
    MockConfigEntry(domain=DOMAIN, data={CONF_SITE_SLUG: "x"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
