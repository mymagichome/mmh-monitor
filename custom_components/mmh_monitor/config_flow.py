"""Config, options and reconfigure flows for MMH Monitor."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.loader import async_get_integration
from yarl import URL

from .const import (
    CONF_BACKUP_ENTITY,
    CONF_IGNORED_ENTITIES,
    CONF_INFLUX_BUCKET,
    CONF_INFLUX_ORG,
    CONF_INFLUX_TOKEN,
    CONF_INFLUX_URL,
    CONF_KUMA_DOWN_ON_CRITICAL,
    CONF_KUMA_PUSH_URL,
    CONF_SCAN_INTERVAL,
    CONF_SITE_SLUG,
    CONF_THRESHOLDS_URL,
    CONF_ZIGBEE_ENTITIES,
    DEFAULT_INFLUX_BUCKET,
    DEFAULT_INFLUX_ORG,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SITE_SLUG_PATTERN,
)
from .publisher import (
    InfluxAuthError,
    InfluxBucketError,
    PublishError,
    async_test_influx,
)

_LOGGER = logging.getLogger(__name__)

_URL = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_TEXT = TextSelector()


def _connection_schema(*, token_required: bool) -> vol.Schema:
    """Fields shared by the user and reconfigure steps."""
    token_key = (
        vol.Required(CONF_INFLUX_TOKEN) if token_required else vol.Optional(CONF_INFLUX_TOKEN)
    )
    return vol.Schema(
        {
            vol.Required(CONF_INFLUX_URL): _URL,
            vol.Required(CONF_INFLUX_ORG, default=DEFAULT_INFLUX_ORG): _TEXT,
            vol.Required(CONF_INFLUX_BUCKET, default=DEFAULT_INFLUX_BUCKET): _TEXT,
            token_key: _PASSWORD,
            vol.Optional(CONF_KUMA_PUSH_URL): _URL,
        }
    )


USER_SCHEMA = vol.Schema({vol.Required(CONF_SITE_SLUG): _TEXT}).extend(
    _connection_schema(token_required=True).schema
)
RECONFIGURE_SCHEMA = _connection_schema(token_required=False)


def _is_http_url(value: str) -> bool:
    try:
        url = URL(value)
    except ValueError:
        return False
    return url.scheme in ("http", "https") and bool(url.host)


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """Strip whitespace and drop empty optional values."""
    cleaned = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in user_input.items()
    }
    return {key: value for key, value in cleaned.items() if value not in ("", None)}


def _validate_fields(data: dict[str, Any]) -> dict[str, str]:
    """Validate field formats. Returns errors keyed by field."""
    errors: dict[str, str] = {}
    if CONF_SITE_SLUG in data and not SITE_SLUG_PATTERN.fullmatch(data[CONF_SITE_SLUG]):
        errors[CONF_SITE_SLUG] = "invalid_slug"
    if not _is_http_url(data.get(CONF_INFLUX_URL, "")):
        errors[CONF_INFLUX_URL] = "invalid_url"
    if CONF_KUMA_PUSH_URL in data and not _is_http_url(data[CONF_KUMA_PUSH_URL]):
        errors[CONF_KUMA_PUSH_URL] = "invalid_url"
    return errors


async def _async_test_connection(
    hass: HomeAssistant, data: dict[str, Any], site: str
) -> str | None:
    """Write a test point to InfluxDB. Returns an error key or None."""
    integration = await async_get_integration(hass, DOMAIN)
    try:
        await async_test_influx(
            async_get_clientsession(hass),
            url=data[CONF_INFLUX_URL],
            org=data[CONF_INFLUX_ORG],
            bucket=data[CONF_INFLUX_BUCKET],
            token=data[CONF_INFLUX_TOKEN],
            site=site,
            version=str(integration.version),
        )
    except InfluxAuthError:
        return "invalid_auth"
    except InfluxBucketError:
        return "bucket_not_found"
    except PublishError as err:
        _LOGGER.debug("InfluxDB test write failed: %s", err)
        return "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error testing the InfluxDB connection")
        return "unknown"
    return None


class MMHMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MMH Monitor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _normalize(user_input)
            errors = _validate_fields(data)
            if not errors:
                error = await _async_test_connection(
                    self.hass, data, data[CONF_SITE_SLUG]
                )
                if error:
                    errors["base"] = error
            if not errors:
                await self.async_set_unique_id(data[CONF_SITE_SLUG])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"MMH Monitor ({data[CONF_SITE_SLUG]})", data=data
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, _without_secrets(user_input)
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the InfluxDB and Uptime Kuma settings without reinstalling."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _normalize(user_input)
            # An empty token keeps the current one.
            data.setdefault(CONF_INFLUX_TOKEN, entry.data[CONF_INFLUX_TOKEN])
            errors = _validate_fields(data)
            if not errors:
                error = await _async_test_connection(
                    self.hass, data, entry.data[CONF_SITE_SLUG]
                )
                if error:
                    errors["base"] = error
            if not errors:
                new_data = {CONF_SITE_SLUG: entry.data[CONF_SITE_SLUG], **data}
                return self.async_update_reload_and_abort(entry, data=new_data)

        suggested = _without_secrets(user_input if user_input is not None else dict(entry.data))
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(RECONFIGURE_SCHEMA, suggested),
            errors=errors,
            description_placeholders={"site": entry.data[CONF_SITE_SLUG]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MMHMonitorOptionsFlow:
        """Return the options flow."""
        return MMHMonitorOptionsFlow()


def _without_secrets(values: dict[str, Any] | None) -> dict[str, Any] | None:
    """Never pre-fill the token back into a form."""
    if values is None:
        return None
    return {k: v for k, v in values.items() if k != CONF_INFLUX_TOKEN}


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=MIN_SCAN_INTERVAL,
                max=MAX_SCAN_INTERVAL,
                step=1,
                unit_of_measurement="s",
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(CONF_THRESHOLDS_URL): _URL,
        vol.Optional(CONF_IGNORED_ENTITIES): TextSelector(
            TextSelectorConfig(multiple=True)
        ),
        vol.Optional(CONF_ZIGBEE_ENTITIES): EntitySelector(
            EntitySelectorConfig(multiple=True)
        ),
        vol.Optional(CONF_BACKUP_ENTITY): EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="timestamp")
        ),
        vol.Required(CONF_KUMA_DOWN_ON_CRITICAL, default=False): BooleanSelector(),
    }
)


class MMHMonitorOptionsFlow(OptionsFlowWithReload):
    """Adjust monitoring options. Saving reloads the entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            options = _normalize(user_input)
            options[CONF_SCAN_INTERVAL] = int(options[CONF_SCAN_INTERVAL])
            if CONF_IGNORED_ENTITIES in options:
                patterns = [p.strip() for p in options[CONF_IGNORED_ENTITIES] if p.strip()]
                if patterns:
                    options[CONF_IGNORED_ENTITIES] = patterns
                else:
                    del options[CONF_IGNORED_ENTITIES]
            if not options.get(CONF_ZIGBEE_ENTITIES):
                options.pop(CONF_ZIGBEE_ENTITIES, None)
            if CONF_THRESHOLDS_URL in options and not _is_http_url(
                options[CONF_THRESHOLDS_URL]
            ):
                errors[CONF_THRESHOLDS_URL] = "invalid_url"
            if not errors:
                return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA,
                user_input if user_input is not None else self.config_entry.options,
            ),
            errors=errors,
        )
