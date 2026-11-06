"""Tests for repair issues."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mmh_monitor.const import DOMAIN

from .conftest import INFLUX_WRITE, KUMA_URL


async def test_critical_check_opens_and_closes_issue(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """An issue exists while a check is critical and goes away afterwards."""
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    for i in range(10):
        hass.states.async_set(f"sensor.dead_{i}", "unavailable")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    issue = issue_registry.async_get_issue(DOMAIN, "critical_unavailable_entities")
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.is_fixable is False
    assert issue.translation_key == "check_critical"
    assert issue.translation_placeholders["check"] == "unavailable_entities"
    assert "indisponíveis" in issue.translation_placeholders["message"]

    # Down to warning: 1 of ~11 entities unavailable is still > 5% -> warning.
    for i in range(1, 10):
        hass.states.async_set(f"sensor.dead_{i}", "on")
    await config_entry.runtime_data.async_refresh()
    assert issue_registry.async_get_issue(DOMAIN, "critical_unavailable_entities") is None


async def test_unload_removes_issues(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Unloading the integration removes its issues."""
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    for i in range(10):
        hass.states.async_set(f"sensor.dead_{i}", "unavailable")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, "critical_unavailable_entities")

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert not [i for (d, i) in issue_registry.issues if d == DOMAIN]


async def test_unchanged_issue_not_rewritten(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    monkeypatch: Any,
) -> None:
    """A critical check with the same message does not recreate the issue every cycle."""
    aioclient_mock.post(INFLUX_WRITE, status=204)
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    for i in range(10):
        hass.states.async_set(f"sensor.dead_{i}", "unavailable")
    calls: list[str] = []
    original = ir.async_create_issue
    monkeypatch.setattr(
        "custom_components.mmh_monitor.repairs.ir.async_create_issue",
        lambda *a, **kw: (calls.append(a[2]), original(*a, **kw)),
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await config_entry.runtime_data.async_refresh()
    await config_entry.runtime_data.async_refresh()
    assert calls.count("critical_unavailable_entities") == 1
