"""Config flow for MMH Monitor.

Phase 1 skeleton: only collects and validates the site slug.
InfluxDB/Kuma fields, options and reconfigure flows arrive in phase 2.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_SITE_SLUG, DOMAIN, SITE_SLUG_PATTERN

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_SITE_SLUG): str})


class MMHMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MMH Monitor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            slug = user_input[CONF_SITE_SLUG].strip()
            if not SITE_SLUG_PATTERN.fullmatch(slug):
                errors[CONF_SITE_SLUG] = "invalid_slug"
            else:
                return self.async_create_entry(
                    title=f"MMH Monitor ({slug})",
                    data={CONF_SITE_SLUG: slug},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )
