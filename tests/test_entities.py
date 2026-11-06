"""Tests for the sensors and binary sensors."""

from __future__ import annotations

import aiohttp
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mmh_monitor.checks import ALL_KEYS
from custom_components.mmh_monitor.const import DOMAIN

from .conftest import INFLUX_WRITE, KUMA_URL, VERSION


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entities_created(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Every entity exists with a fixed entity ID on a single device."""
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    await _setup(hass, config_entry)

    expected = (
        ["sensor.mmh_health", "binary_sensor.mmh_problema", "binary_sensor.mmh_envio_central"]
        + [f"sensor.mmh_{key}" for key in ALL_KEYS]
    )
    for entity_id in expected:
        assert hass.states.get(entity_id) is not None, entity_id
        assert entity_registry.async_get(entity_id).translation_key is not None

    devices = dr.async_entries_for_config_entry(device_registry, config_entry.entry_id)
    assert len(devices) == 1
    assert devices[0].name == "MMH Monitor"
    assert devices[0].identifiers == {(DOMAIN, config_entry.entry_id)}

    health = hass.states.get("sensor.mmh_health")
    assert health.attributes["options"] == ["ok", "atencao", "critico"]
    assert health.attributes["site"] == "cliente-exemplo"
    assert health.attributes["versao"] == VERSION
    assert "ultima_coleta" in health.attributes
    assert health.attributes["ultimo_envio_ok"] is not None

    integrations = hass.states.get("sensor.mmh_integrations")
    assert integrations.state == "0"
    assert integrations.attributes["nivel"] == "ok"
    assert "mensagem" in integrations.attributes

    assert hass.states.get("binary_sensor.mmh_envio_central").state == STATE_ON
    assert hass.states.get("binary_sensor.mmh_problema").attributes["nivel"] == health.state


async def test_problem_and_delivery_failure(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A failing check turns on the problem sensor; a failed delivery turns off connectivity."""
    for i in range(10):
        hass.states.async_set(f"sensor.dead_{i}", "unavailable")
    aioclient_mock.post(INFLUX_WRITE, exc=aiohttp.ClientConnectionError())
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    await _setup(hass, config_entry)

    assert hass.states.get("sensor.mmh_health").state == "critico"
    assert hass.states.get("binary_sensor.mmh_problema").state == STATE_ON
    delivery = hass.states.get("binary_sensor.mmh_envio_central")
    assert delivery.state == STATE_OFF
    assert "influx.example.com" in delivery.attributes["ultimo_erro"]
    motivos = hass.states.get("sensor.mmh_health").attributes["motivos"]
    assert any("indisponíveis" in m for m in motivos)
