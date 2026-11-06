"""Tests for the MMH Monitor config, options and reconfigure flows."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mmh_monitor.const import (
    CONF_BACKUP_ENTITY,
    CONF_IGNORED_ENTITIES,
    CONF_INFLUX_TOKEN,
    CONF_INFLUX_URL,
    CONF_KUMA_DOWN_ON_CRITICAL,
    CONF_KUMA_PUSH_URL,
    CONF_SCAN_INTERVAL,
    CONF_SITE_SLUG,
    CONF_THRESHOLDS_URL,
    DOMAIN,
)

from .conftest import INFLUX_WRITE, KUMA_URL, TOKEN


def _user_input(entry_data: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return {**entry_data, **overrides}


async def _start(hass: HomeAssistant) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_user_flow_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry_data: dict[str, Any]
) -> None:
    """Valid settings write a setup point and create the entry."""
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    aioclient_mock.post(INFLUX_WRITE, status=204)

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(entry_data)
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "MMH Monitor (cliente-exemplo)"
    assert result["data"] == entry_data
    assert result["result"].unique_id == "cliente-exemplo"

    method, url, body, headers = aioclient_mock.mock_calls[0]
    assert method == "POST"
    assert url.query == {"org": "mmh", "bucket": "mmh_health", "precision": "s"}
    assert headers["Authorization"] == f"Token {TOKEN}"
    assert body.decode().startswith(
        "mmh_monitor_setup,site=cliente-exemplo,version=0.1.0 ok=1i "
    )


async def test_user_flow_without_kuma(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry_data: dict[str, Any]
) -> None:
    """The Kuma URL is optional and empty values are not stored."""
    aioclient_mock.post(INFLUX_WRITE, status=204)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(entry_data, **{CONF_KUMA_PUSH_URL: ""})
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_KUMA_PUSH_URL not in result["data"]


@pytest.mark.parametrize("slug", ["Cliente Exemplo", "cliente.exemplo", "ção"])
async def test_user_flow_invalid_slug(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry_data: dict[str, Any],
    slug: str,
) -> None:
    """An invalid slug is rejected before any network call."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(entry_data, **{CONF_SITE_SLUG: slug})
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SITE_SLUG: "invalid_slug"}
    assert aioclient_mock.call_count == 0


async def test_user_flow_invalid_url(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry_data: dict[str, Any]
) -> None:
    """Malformed URLs are rejected."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _user_input(
            entry_data,
            **{CONF_INFLUX_URL: "influx.example.com", CONF_KUMA_PUSH_URL: "ftp://x"},
        ),
    )
    assert result["errors"] == {
        CONF_INFLUX_URL: "invalid_url",
        CONF_KUMA_PUSH_URL: "invalid_url",
    }


@pytest.mark.parametrize(
    ("mock_kwargs", "error"),
    [
        ({"exc": aiohttp.ClientConnectionError()}, "cannot_connect"),
        ({"exc": TimeoutError()}, "cannot_connect"),
        ({"status": 500}, "cannot_connect"),
        ({"status": 401}, "invalid_auth"),
        ({"status": 403}, "invalid_auth"),
        ({"status": 404}, "bucket_not_found"),
    ],
)
async def test_user_flow_connection_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry_data: dict[str, Any],
    mock_kwargs: dict[str, Any],
    error: str,
) -> None:
    """InfluxDB failures map to form errors and the flow can recover."""
    aioclient_mock.post(INFLUX_WRITE, **mock_kwargs)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(entry_data)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    # The token is never echoed back into the form.
    suggested = {
        str(key): key.description.get("suggested_value")
        for key in result["data_schema"].schema
        if key.description
    }
    assert TOKEN not in suggested.values()

    aioclient_mock.clear_requests()
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(entry_data)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_single_instance(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A second instance is not allowed."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_reconfigure_keeps_token_when_empty(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Reconfigure updates the URL and keeps the token when left empty."""
    new_url = "https://influx2.example.com"
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.post(f"{new_url}/api/v2/write", status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    data = dict(config_entry.data)
    data.pop(CONF_SITE_SLUG)
    data[CONF_INFLUX_URL] = new_url
    data[CONF_INFLUX_TOKEN] = ""
    result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_INFLUX_URL] == new_url
    assert config_entry.data[CONF_INFLUX_TOKEN] == TOKEN
    assert config_entry.data[CONF_SITE_SLUG] == "cliente-exemplo"


async def test_reconfigure_invalid_auth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A rejected new token shows an error and changes nothing."""
    config_entry.add_to_hass(hass)
    aioclient_mock.post(INFLUX_WRITE, status=401)
    result = await config_entry.start_reconfigure_flow(hass)
    data = dict(config_entry.data)
    data.pop(CONF_SITE_SLUG)
    data[CONF_INFLUX_TOKEN] = "new-bad-token"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert config_entry.data[CONF_INFLUX_TOKEN] == TOKEN


async def test_options_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Options are cleaned and saved."""
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_THRESHOLDS_URL: "not a url", CONF_SCAN_INTERVAL: 120}
    )
    assert result["errors"] == {CONF_THRESHOLDS_URL: "invalid_url"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 120.0,
            CONF_THRESHOLDS_URL: "",
            CONF_IGNORED_ENTITIES: ["sensor.tv_*", " "],
            CONF_KUMA_DOWN_ON_CRITICAL: True,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_SCAN_INTERVAL: 120,
        CONF_IGNORED_ENTITIES: ["sensor.tv_*"],
        CONF_KUMA_DOWN_ON_CRITICAL: True,
    }
    assert CONF_BACKUP_ENTITY not in config_entry.options
    assert config_entry.runtime_data.update_interval.total_seconds() == 120
