"""Shared fixtures for MMH Monitor tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mmh_monitor.const import (
    CONF_INFLUX_BUCKET,
    CONF_INFLUX_ORG,
    CONF_INFLUX_TOKEN,
    CONF_INFLUX_URL,
    CONF_KUMA_PUSH_URL,
    CONF_SITE_SLUG,
    DOMAIN,
)

INFLUX_URL = "https://influx.example.com"
INFLUX_WRITE = f"{INFLUX_URL}/api/v2/write"
KUMA_URL = "https://kuma.example.com/api/push/SECRETPUSHTOKEN"
TOKEN = "SECRET-INFLUX-TOKEN"
VERSION = json.loads(
    (Path(__file__).parents[1] / "custom_components/mmh_monitor/manifest.json").read_text()
)["version"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    return


@pytest.fixture
def entry_data() -> dict[str, Any]:
    """Config entry data for a site."""
    return {
        CONF_SITE_SLUG: "cliente-exemplo",
        CONF_INFLUX_URL: INFLUX_URL,
        CONF_INFLUX_ORG: "mmh",
        CONF_INFLUX_BUCKET: "mmh_health",
        CONF_INFLUX_TOKEN: TOKEN,
        CONF_KUMA_PUSH_URL: KUMA_URL,
    }


@pytest.fixture
def config_entry(entry_data: dict[str, Any]) -> MockConfigEntry:
    """A config entry for MMH Monitor."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="MMH Monitor (cliente-exemplo)",
        unique_id="cliente-exemplo",
        data=entry_data,
    )
