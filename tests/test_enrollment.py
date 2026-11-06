"""Tests for enrollment by code through the MMH gateway."""

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
    CONF_ENROLLMENT_CODE,
    CONF_GATEWAY_URL,
    CONF_INFLUX_TOKEN,
    CONF_KUMA_PUSH_URL,
    CONF_SITE_SLUG,
    DEFAULT_GATEWAY_URL,
    DOMAIN,
)

from .conftest import INFLUX_URL, INFLUX_WRITE, KUMA_URL, TOKEN, VERSION

ENROLL = f"{DEFAULT_GATEWAY_URL}/monitor/enroll"
CODE = "MMH-ABCDE-FGH23"
NEW_TOKEN = "NEW-SITE-TOKEN"


def _ok(token: str = NEW_TOKEN) -> dict[str, Any]:
    return {
        "ok": True,
        "site": {"slug": "cliente-exemplo"},
        "influx": {"url": INFLUX_URL, "org": "mmh", "bucket": "mmh_health", "token": token},
        "reconnected": False,
    }


async def _code_form(hass: HomeAssistant) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "code"}
    )


def _input(**overrides: Any) -> dict[str, Any]:
    return {
        CONF_SITE_SLUG: "cliente-exemplo",
        CONF_ENROLLMENT_CODE: f" {CODE} ",
        CONF_GATEWAY_URL: DEFAULT_GATEWAY_URL,
        **overrides,
    }


async def test_code_flow_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A valid code fills in every InfluxDB setting; the code is not stored."""
    aioclient_mock.post(ENROLL, json=_ok())
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})

    result = await _code_form(hass)
    assert result["step_id"] == "code"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _input(**{CONF_KUMA_PUSH_URL: KUMA_URL})
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "MMH Monitor (cliente-exemplo)"
    assert result["data"] == {
        CONF_SITE_SLUG: "cliente-exemplo",
        "influx_url": INFLUX_URL,
        "influx_org": "mmh",
        "influx_bucket": "mmh_health",
        CONF_INFLUX_TOKEN: NEW_TOKEN,
        CONF_GATEWAY_URL: DEFAULT_GATEWAY_URL,
        CONF_KUMA_PUSH_URL: KUMA_URL,
    }
    method, url, body, _ = aioclient_mock.mock_calls[0]
    assert (method, str(url)) == ("POST", ENROLL)
    assert body == {"code": CODE, "slug": "cliente-exemplo", "integration_version": VERSION}

    # The new entry starts sending with the received token.
    entry = result["result"]
    assert entry.runtime_data.publish_status.influx_ok is True


@pytest.mark.parametrize(
    ("mock_kwargs", "error"),
    [
        ({"status": 403, "json": {"ok": False, "error": "inválido"}}, "invalid_code"),
        ({"status": 409, "json": {"ok": False, "error": "este código é do site 'outro'"}}, "wrong_site"),
        ({"status": 429, "json": {"ok": False}}, "too_many_attempts"),
        ({"status": 502, "json": {"ok": False, "error": "InfluxDB não respondeu"}}, "gateway_error"),
        ({"status": 200, "json": {"ok": True, "influx": {"url": INFLUX_URL}}}, "gateway_error"),
        ({"exc": aiohttp.ClientConnectionError()}, "cannot_connect_gateway"),
        ({"exc": TimeoutError()}, "cannot_connect_gateway"),
    ],
)
async def test_code_flow_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_kwargs: dict[str, Any],
    error: str,
) -> None:
    """Gateway answers map to form errors; the code is not echoed back."""
    aioclient_mock.post(ENROLL, **mock_kwargs)
    result = await _code_form(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _input())
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    suggested = [
        key.description.get("suggested_value")
        for key in result["data_schema"].schema
        if key.description
    ]
    assert CODE not in [str(v).strip() for v in suggested]


async def test_code_flow_shows_gateway_detail(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The gateway's explanation is passed to the form."""
    aioclient_mock.post(ENROLL, status=409, json={"ok": False, "error": "este código é do site 'outro'"})
    result = await _code_form(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], _input())
    assert result["description_placeholders"]["detail"] == "este código é do site 'outro'"


async def test_code_flow_validates_before_calling(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A bad slug or gateway URL never reaches the network."""
    result = await _code_form(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _input(**{CONF_SITE_SLUG: "Cliente X"})
    )
    assert result["errors"] == {CONF_SITE_SLUG: "invalid_slug"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _input(**{CONF_GATEWAY_URL: "http://gateway.example.com"})
    )
    assert result["errors"] == {"base": "invalid_url"}
    assert aioclient_mock.call_count == 0


async def test_reconfigure_with_code_rotates_token(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A new code replaces the token and keeps the slug and Kuma URL."""
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    aioclient_mock.post(ENROLL, json=_ok("ROTATED"))
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.data[CONF_INFLUX_TOKEN] == TOKEN

    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["reconfigure_code", "reconfigure_manual"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "reconfigure_code"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENROLLMENT_CODE: CODE, CONF_GATEWAY_URL: DEFAULT_GATEWAY_URL}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_INFLUX_TOKEN] == "ROTATED"
    assert config_entry.data[CONF_SITE_SLUG] == "cliente-exemplo"
    assert config_entry.data[CONF_KUMA_PUSH_URL] == KUMA_URL
    enroll_calls = [c for c in aioclient_mock.mock_calls if str(c[1]) == ENROLL]
    assert enroll_calls[0][2]["slug"] == "cliente-exemplo"


async def test_reconfigure_with_bad_code_changes_nothing(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A rejected code leaves the entry as it was."""
    aioclient_mock.post(ENROLL, status=403, json={"ok": False})
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "reconfigure_code"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENROLLMENT_CODE: CODE, CONF_GATEWAY_URL: DEFAULT_GATEWAY_URL}
    )
    assert result["errors"] == {"base": "invalid_code"}
    assert config_entry.data[CONF_INFLUX_TOKEN] == TOKEN
