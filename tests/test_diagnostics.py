"""Tests for diagnostics."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mmh_monitor.const import CONF_THRESHOLDS_URL
from custom_components.mmh_monitor.diagnostics import async_get_config_entry_diagnostics

from .conftest import INFLUX_WRITE, KUMA_URL, TOKEN


async def test_diagnostics_redacts_secrets(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry_data: dict,
) -> None:
    """Config, thresholds, results and delivery status are present; secrets are not."""
    thresholds_url = "https://config.example.com/t-SECRETKEY.json"
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    aioclient_mock.get(thresholds_url, status=404)
    entry = MockConfigEntry(
        domain="mmh_monitor", data=entry_data, options={CONF_THRESHOLDS_URL: thresholds_url}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diag)  # must be JSON serializable

    assert TOKEN not in text
    assert "SECRETPUSHTOKEN" not in text
    assert "SECRETKEY" not in text
    assert diag["entry"]["data"]["influx_token"] == "**REDACTED**"
    assert diag["entry"]["data"]["kuma_push_url"] == "**REDACTED**"
    assert diag["entry"]["options"]["thresholds_url"] == "**REDACTED**"
    assert diag["entry"]["data"]["site_slug"] == "cliente-exemplo"

    assert diag["thresholds"]["remote_configured"] is True
    assert diag["thresholds"]["source"] == "default"
    assert diag["thresholds"]["values"]["disk_use"] == {"atencao": 75, "critico": 90}
    assert diag["health"]["results"]["integrations"]["level"] == "ok"
    assert diag["publish"]["influx_ok"] is True
    assert diag["publish"]["influx_last_success"] is not None
