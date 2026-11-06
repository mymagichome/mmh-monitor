"""Tests for threshold validation, merging and remote fetching."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mmh_monitor.const import CONF_THRESHOLDS_URL
from custom_components.mmh_monitor.models import HealthLevel
from custom_components.mmh_monitor.thresholds import (
    DEFAULT_THRESHOLDS,
    InvalidThresholds,
    Threshold,
    merge_thresholds,
    validate_payload,
)

from .conftest import INFLUX_WRITE, KUMA_URL

THRESHOLDS_URL = "https://config.example.com/mmh/thresholds-SECRETKEY.json"
STORE_KEY = "mmh_monitor.thresholds"

PAYLOAD = {
    "version": 1,
    "checks": {
        "disk_use": {"atencao": 70, "critico": 85},
        "memory_use": {"atencao": 80},
    },
    "sites": {
        "cliente-exemplo": {"disk_use": {"atencao": 80, "critico": 92}},
        "outro-site": {"disk_use": {"atencao": 10, "critico": 20}},
    },
}


# -- validation and merge ---------------------------------------------------


def test_merge_precedence() -> None:
    """sites.<slug> beats checks, which beats the defaults, field by field."""
    merged = merge_thresholds(DEFAULT_THRESHOLDS, validate_payload(PAYLOAD), "cliente-exemplo")
    assert merged["disk_use"] == Threshold(80, 92)  # site
    assert merged["memory_use"] == Threshold(80, 95)  # global atencao, default critico
    assert merged["load_1m"] == DEFAULT_THRESHOLDS["load_1m"]  # default

    other = merge_thresholds(DEFAULT_THRESHOLDS, validate_payload(PAYLOAD), "sem-override")
    assert other["disk_use"] == Threshold(70, 85)  # global only


def test_null_disables_a_limit() -> None:
    """A null field removes that limit."""
    payload = validate_payload({"version": 1, "checks": {"updates": {"atencao": None}}})
    merged = merge_thresholds(DEFAULT_THRESHOLDS, payload, "x")
    assert merged["updates"].level_for(10) is HealthLevel.OK


def test_new_check_keys_are_accepted() -> None:
    """Keys for checks this version does not know yet are kept."""
    payload = validate_payload({"version": 1, "checks": {"future_check": {"critico": 1}}})
    assert merge_thresholds(DEFAULT_THRESHOLDS, payload, "x")["future_check"] == Threshold(None, 1)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        "text",
        {"checks": {}},
        {"version": 2},
        {"version": 1, "checks": []},
        {"version": 1, "checks": {"disk_use": 80}},
        {"version": 1, "checks": {"disk_use": {"atencao": "80"}}},
        {"version": 1, "checks": {"disk_use": {"atencao": True}}},
        {"version": 1, "checks": {"disk_use": {"warning": 80}}},
        {"version": 1, "sites": []},
        {"version": 1, "sites": {"x": {"disk_use": {"critico": "alto"}}}},
    ],
)
def test_invalid_payloads(payload: Any) -> None:
    """Malformed documents are rejected."""
    with pytest.raises(InvalidThresholds):
        validate_payload(payload)


def test_no_payload_returns_defaults() -> None:
    """Without remote data the defaults apply."""
    assert merge_thresholds(DEFAULT_THRESHOLDS, None, "x") == DEFAULT_THRESHOLDS


# -- remote fetch -----------------------------------------------------------


def _entry(entry_data: dict[str, Any], url: str | None = THRESHOLDS_URL) -> MockConfigEntry:
    options = {CONF_THRESHOLDS_URL: url} if url else {}
    return MockConfigEntry(domain="mmh_monitor", data=entry_data, options=options)


async def _setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry
) -> None:
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_remote_thresholds_applied_and_cached(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
    entry_data: dict[str, Any],
) -> None:
    """A valid remote file is applied for the site and saved to the cache."""
    aioclient_mock.get(THRESHOLDS_URL, json=PAYLOAD)
    entry = _entry(entry_data)
    await _setup(hass, aioclient_mock, entry)

    manager = entry.runtime_data.threshold_manager
    assert manager.source == "remote"
    assert manager.current["disk_use"] == Threshold(80, 92)
    assert manager.last_error is None
    assert hass_storage[STORE_KEY]["data"]["url"] == THRESHOLDS_URL
    assert hass_storage[STORE_KEY]["data"]["payload"]["checks"]["disk_use"]["atencao"] == 70


async def test_cache_used_when_fetch_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
    entry_data: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """On network failure the last valid cached values stay in use."""
    hass_storage[STORE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": {"url": THRESHOLDS_URL, "fetched_at": "2026-11-01T00:00:00+00:00", "payload": PAYLOAD},
    }
    aioclient_mock.get(THRESHOLDS_URL, exc=aiohttp.ClientConnectionError())
    entry = _entry(entry_data)
    caplog.set_level(logging.WARNING)
    await _setup(hass, aioclient_mock, entry)

    manager = entry.runtime_data.threshold_manager
    assert manager.source == "cache"
    assert manager.current["disk_use"] == Threshold(80, 92)
    assert "cannot fetch thresholds" in manager.last_error
    assert "Remote thresholds not updated" in caplog.text
    assert "SECRETKEY" not in caplog.text


async def test_defaults_without_cache(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry_data: dict[str, Any],
) -> None:
    """No cache and no network means built-in defaults."""
    aioclient_mock.get(THRESHOLDS_URL, status=500)
    entry = _entry(entry_data)
    await _setup(hass, aioclient_mock, entry)
    manager = entry.runtime_data.threshold_manager
    assert manager.source == "default"
    assert manager.current == DEFAULT_THRESHOLDS


async def test_invalid_remote_file_is_ignored(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
    entry_data: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An invalid document logs a warning and changes nothing."""
    aioclient_mock.get(THRESHOLDS_URL, json={"version": 1, "checks": {"disk_use": "x"}})
    entry = _entry(entry_data)
    caplog.set_level(logging.WARNING)
    await _setup(hass, aioclient_mock, entry)
    manager = entry.runtime_data.threshold_manager
    assert manager.source == "default"
    assert "invalid thresholds file" in caplog.text
    assert STORE_KEY not in hass_storage


async def test_cache_from_other_url_is_ignored(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
    entry_data: dict[str, Any],
) -> None:
    """Changing the URL does not reuse values cached for the previous one."""
    hass_storage[STORE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": {"url": "https://old.example.com/t.json", "payload": PAYLOAD},
    }
    aioclient_mock.get(THRESHOLDS_URL, exc=TimeoutError())
    entry = _entry(entry_data)
    await _setup(hass, aioclient_mock, entry)
    assert entry.runtime_data.threshold_manager.source == "default"


async def test_refresh_every_six_hours(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry_data: dict[str, Any],
) -> None:
    """The file is fetched again on the refresh interval."""
    aioclient_mock.get(THRESHOLDS_URL, json=PAYLOAD)
    entry = _entry(entry_data)
    await _setup(hass, aioclient_mock, entry)
    fetches = lambda: sum(1 for _, url, _, _ in aioclient_mock.mock_calls if "thresholds" in str(url))  # noqa: E731
    assert fetches() == 1

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=6, seconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert fetches() == 2


async def test_remote_thresholds_change_levels(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry_data: dict[str, Any],
) -> None:
    """Checks use the effective thresholds on the next cycle."""
    for i in range(100):
        hass.states.async_set(f"sensor.s{i}", "unavailable" if i < 3 else "1")
    aioclient_mock.get(
        THRESHOLDS_URL,
        json={"version": 1, "checks": {"unavailable_entities": {"atencao": 1, "critico": 2}}},
    )
    entry = _entry(entry_data)
    await _setup(hass, aioclient_mock, entry)
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    assert coordinator.data.results["unavailable_entities"].level is HealthLevel.CRITICO


async def test_no_url_no_fetch(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry_data: dict[str, Any],
) -> None:
    """Without a URL nothing is fetched."""
    entry = _entry(entry_data, url=None)
    await _setup(hass, aioclient_mock, entry)
    assert entry.runtime_data.threshold_manager.source == "default"
    assert all("thresholds" not in str(url) for _, url, _, _ in aioclient_mock.mock_calls)
