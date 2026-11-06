"""Tests for the coordinator and entry lifecycle."""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mmh_monitor.checks.base import BaseCheck
from custom_components.mmh_monitor.const import (
    CONF_KUMA_DOWN_ON_CRITICAL,
    CONF_KUMA_PUSH_URL,
)
from custom_components.mmh_monitor.models import CheckResult, HealthLevel

from .conftest import INFLUX_WRITE, KUMA_URL, TOKEN


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_publishes_and_unloads(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The first cycle sends lines to InfluxDB and a heartbeat to Kuma."""
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    coordinator = config_entry.runtime_data
    assert coordinator.data.level is HealthLevel.OK
    assert coordinator.data.results["integrations"].value == 0
    assert coordinator.publish_status.influx_ok is True
    assert coordinator.publish_status.kuma_ok is True

    calls = {method: (url, body) for method, url, body, _ in aioclient_mock.mock_calls}
    body = calls["POST"][1].decode()
    assert "mmh_check,check=integrations,site=cliente-exemplo value=0.0,level=0i" in body
    assert "mmh_health,ha_version=" in body
    assert calls["GET"][0].query["status"] == "up"
    assert calls["GET"][0].query["msg"] == "ok"

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_polls_on_interval(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The coordinator keeps sending every cycle without entities."""
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    await _setup(hass, config_entry)
    assert aioclient_mock.call_count == 2

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=301))
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 4


async def test_network_failure_does_not_break_setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """InfluxDB and Kuma being down never fails the entry or leaks secrets."""
    aioclient_mock.post(INFLUX_WRITE, exc=aiohttp.ClientConnectionError())
    aioclient_mock.get(KUMA_URL, exc=TimeoutError())
    caplog.set_level(logging.DEBUG)
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    status = config_entry.runtime_data.publish_status
    assert status.influx_ok is False
    assert status.kuma_ok is False
    assert "influx.example.com" in status.influx_last_error
    assert "Sending to InfluxDB failed" in caplog.text
    assert TOKEN not in caplog.text
    assert "SECRETPUSHTOKEN" not in caplog.text


async def test_influx_failure_does_not_block_kuma(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Each destination is independent."""
    aioclient_mock.post(INFLUX_WRITE, status=500)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    await _setup(hass, config_entry)
    status = config_entry.runtime_data.publish_status
    assert status.influx_ok is False
    assert status.kuma_ok is True


async def test_no_kuma_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry_data: dict,
) -> None:
    """Without a push URL only InfluxDB is called."""
    entry_data.pop(CONF_KUMA_PUSH_URL)
    entry = MockConfigEntry(domain="mmh_monitor", data=entry_data)
    aioclient_mock.post(INFLUX_WRITE, status=204)
    await _setup(hass, entry)
    assert aioclient_mock.call_count == 1
    assert entry.runtime_data.publish_status.kuma_ok is None


class _CriticalCheck(BaseCheck):
    keys = ("fake",)

    async def async_run(self, thresholds):
        return [CheckResult("fake", 9, None, HealthLevel.CRITICO, "Algo crítico")]


class _BrokenCheck(BaseCheck):
    keys = ("broken_a", "broken_b")

    async def async_run(self, thresholds):
        raise RuntimeError("boom")


@pytest.mark.parametrize(("down_on_critical", "status"), [(False, "up"), (True, "down")])
async def test_critical_level_and_kuma_down(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry_data: dict,
    monkeypatch: pytest.MonkeyPatch,
    down_on_critical: bool,
    status: str,
) -> None:
    """A critical check sets the overall level; Kuma gets down only if enabled."""
    monkeypatch.setattr(
        "custom_components.mmh_monitor.coordinator.CHECKS",
        (_CriticalCheck, _BrokenCheck),
    )
    config_entry = MockConfigEntry(
        domain="mmh_monitor",
        data=entry_data,
        options={CONF_KUMA_DOWN_ON_CRITICAL: down_on_critical},
    )
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    await _setup(hass, config_entry)

    data = config_entry.runtime_data.data
    assert data.level is HealthLevel.CRITICO
    assert data.message == "Algo crítico"
    # A failing check is isolated and reported as not monitored.
    assert data.results["broken_a"].level is HealthLevel.NAO_MONITORADO
    assert data.results["broken_b"].level is HealthLevel.NAO_MONITORADO

    kuma = next(url for method, url, _, _ in aioclient_mock.mock_calls if method == "GET")
    assert kuma.query["status"] == status
