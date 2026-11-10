"""Tests for the human-readable reasons."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mmh_monitor.models import CheckResult, HealthLevel
from custom_components.mmh_monitor.reasons import describe, limits_text
from custom_components.mmh_monitor.thresholds import DEFAULT_THRESHOLDS, Threshold

from .conftest import INFLUX_WRITE, KUMA_URL

A, C = HealthLevel.ATENCAO, HealthLevel.CRITICO


def test_describe_with_limits() -> None:
    """Level, measurement and both limits."""
    r = CheckResult("disk_use", 81.0, "%", A, "Disco em 81%")
    assert describe(r, DEFAULT_THRESHOLDS["disk_use"]) == (
        "Atenção — Disco em 81% (atenção a partir de 75%, crítico a partir de 90%)"
    )


def test_limits_are_readable() -> None:
    """Backup in days, database in GB, plain numbers without a unit."""
    assert limits_text("backup", DEFAULT_THRESHOLDS["backup"], "h") == (
        "atenção a partir de 16 dias, crítico a partir de 30 dias"
    )
    assert limits_text("recorder", DEFAULT_THRESHOLDS["recorder"], "MB") == (
        "atenção a partir de 2 GB, crítico a partir de 5 GB"
    )
    assert limits_text("integrations", DEFAULT_THRESHOLDS["integrations"], None) == (
        "atenção a partir de 1, crítico a partir de 3"
    )
    assert limits_text("updates", DEFAULT_THRESHOLDS["updates"], None) == "atenção a partir de 1"
    assert limits_text("zigbee", Threshold(), None) == ""


def test_log_limits_mention_sources() -> None:
    """The log is only critical with several sources, and the reason says so."""
    assert limits_text("system_log", DEFAULT_THRESHOLDS["system_log"], None) == (
        "atenção a partir de 5, crítico a partir de 20 vindos de 3 ou mais origens"
    )


def test_describe_without_value_or_limits() -> None:
    """A check without a number only states the level and the message."""
    r = CheckResult("zigbee", None, None, C, "Coordenador Zigbee offline")
    assert describe(r, DEFAULT_THRESHOLDS["zigbee"]) == "Crítico — Coordenador Zigbee offline"


async def test_health_sensor_explains_why(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """sensor.mmh_health says which checks are not OK and why."""
    for i in range(10):
        hass.states.async_set(f"sensor.dead_{i}", "unavailable")
    hass.states.async_set("update.addon", "on")
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    health = hass.states.get("sensor.mmh_health")
    assert health.state == "critico"
    attrs = health.attributes
    assert attrs["checagens_criticas"] == ["Entidades indisponíveis"]
    assert attrs["checagens_atencao"] == ["Atualizações"]
    # Critical first, each with level and limits.
    assert attrs["motivos"][0].startswith("Crítico — 10 entidades indisponíveis")
    assert "(atenção a partir de 5%, crítico a partir de 15%)" in attrs["motivos"][0]
    assert attrs["motivos"][1] == (
        "Atenção — 1 atualização pendente (atenção a partir de 1)"
    )
    assert attrs["resumo"] == "; ".join(attrs["motivos"])

    disk = hass.states.get("sensor.mmh_disk_use").attributes
    assert (disk["limite_atencao"], disk["limite_critico"]) == (75, 90)
    assert disk["limites"] == "atenção a partir de 75%, crítico a partir de 90%"
