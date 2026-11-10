"""Tests for each health check."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mmh_monitor.checks import backup as backup_mod
from custom_components.mmh_monitor.checks import system as system_mod
from custom_components.mmh_monitor.checks.backup import BackupCheck, ManagerInfo
from custom_components.mmh_monitor.checks.base import BaseCheck
from custom_components.mmh_monitor.checks.entities import UnavailableEntitiesCheck
from custom_components.mmh_monitor.checks.integrations import IntegrationsCheck
from custom_components.mmh_monitor.checks.recorder import RecorderCheck
from custom_components.mmh_monitor.checks.system import SystemCheck, collect
from custom_components.mmh_monitor.checks.system_log import SystemLogCheck
from custom_components.mmh_monitor.checks.updates import UpdatesCheck
from custom_components.mmh_monitor.checks.zigbee import ZigbeeCheck
from custom_components.mmh_monitor.const import (
    CONF_BACKUP_ENTITY,
    CONF_IGNORED_ENTITIES,
    CONF_ZIGBEE_ENTITIES,
    DOMAIN,
)
from custom_components.mmh_monitor.models import CheckResult, HealthLevel
from custom_components.mmh_monitor.thresholds import DEFAULT_THRESHOLDS, Threshold

OK = HealthLevel.OK
ATENCAO = HealthLevel.ATENCAO
CRITICO = HealthLevel.CRITICO
NAO = HealthLevel.NAO_MONITORADO


def _entry(hass: HomeAssistant, **options: Any) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options)
    entry.add_to_hass(hass)
    return entry


async def _run(
    check_cls: type[BaseCheck],
    hass: HomeAssistant,
    thresholds: dict[str, Threshold] | None = None,
    **options: Any,
) -> dict[str, CheckResult]:
    check = check_cls(hass, _entry(hass, **options))
    results = await check.async_run(thresholds or DEFAULT_THRESHOLDS)
    return {r.key: r for r in results}


# -- thresholds -------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "level"),
    [(None, NAO), (0, OK), (74.9, OK), (75, ATENCAO), (89.9, ATENCAO), (90, CRITICO)],
)
def test_threshold_levels(value: float | None, level: HealthLevel) -> None:
    """Limits are inclusive."""
    assert Threshold(atencao=75, critico=90).level_for(value) is level


def test_threshold_without_limits() -> None:
    """A threshold without limits is always OK."""
    assert Threshold().level_for(1e9) is OK


# -- integrations -----------------------------------------------------------


def _failed_entry(
    hass: HomeAssistant, domain: str, state: ConfigEntryState, **kw
) -> MockConfigEntry:
    entry = MockConfigEntry(domain=domain, title=domain.title(), **kw)
    entry.add_to_hass(hass)
    entry.mock_state(hass, state)
    return entry


@pytest.mark.parametrize(("failed", "level"), [(0, OK), (1, ATENCAO), (2, ATENCAO), (3, CRITICO)])
async def test_integrations(hass: HomeAssistant, failed: int, level: HealthLevel) -> None:
    """Failed entries are counted; disabled and loaded ones are not."""
    states = [
        ConfigEntryState.SETUP_ERROR,
        ConfigEntryState.SETUP_RETRY,
        ConfigEntryState.MIGRATION_ERROR,
    ]
    for i in range(failed):
        _failed_entry(hass, f"broken{i}", states[i])
    _failed_entry(hass, "fine", ConfigEntryState.LOADED)
    _failed_entry(
        hass, "off", ConfigEntryState.SETUP_ERROR, disabled_by=ConfigEntryDisabler.USER
    )
    result = (await _run(IntegrationsCheck, hass))["integrations"]
    assert result.value == failed
    assert result.level is level
    assert len(result.details["entries"]) == failed
    if failed == 1:
        assert result.details["entries"][0] == {
            "domain": "broken0",
            "title": "Broken0",
            "state": "setup_error",
        }


# -- unavailable entities ---------------------------------------------------


@pytest.mark.parametrize(("bad", "level"), [(0, OK), (4, OK), (5, ATENCAO), (15, CRITICO)])
async def test_unavailable_entities(hass: HomeAssistant, bad: int, level: HealthLevel) -> None:
    """The percentage of unavailable entities drives the level."""
    for i in range(100):
        hass.states.async_set(f"sensor.s{i:03}", "unavailable" if i < bad else "1")
    result = (await _run(UnavailableEntitiesCheck, hass))["unavailable_entities"]
    assert result.value == bad
    assert result.unit == "%"
    assert result.level is level
    assert result.details["count"] == bad
    assert result.details["total"] == 100
    assert len(result.details["entities"]) == min(bad, 20)


async def test_unavailable_entities_ignored(hass: HomeAssistant) -> None:
    """Ignored patterns leave the count and the total."""
    for i in range(10):
        hass.states.async_set(f"sensor.tv_{i}", "unavailable")
    for i in range(10):
        hass.states.async_set(f"light.l{i}", "on")
    result = (
        await _run(UnavailableEntitiesCheck, hass, **{CONF_IGNORED_ENTITIES: ["sensor.tv_*"]})
    )["unavailable_entities"]
    assert result.value == 0
    assert result.details["total"] == 10


async def test_unavailable_entities_none(hass: HomeAssistant) -> None:
    """No entities is not an error."""
    result = (await _run(UnavailableEntitiesCheck, hass))["unavailable_entities"]
    assert result.value == 0
    assert result.level is OK


# -- system -----------------------------------------------------------------


def _fake_proc(tmp_path: Path, mem_available_kb: int = 2_000_000) -> Path:
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "meminfo").write_text(
        f"MemTotal:       4000000 kB\nMemFree:  100 kB\nMemAvailable:   {mem_available_kb} kB\n"
    )
    (proc / "uptime").write_text("10000.50 20000.00\n")
    fields = ["S"] + ["0"] * 18 + ["100000"] + ["0"] * 10  # starttime at index 19
    (proc / "self" / "stat").write_text("123 (python3 -m homeassistant) " + " ".join(fields))
    return proc


def test_collect_reads_proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Values are read from /proc and the config dir filesystem."""
    monkeypatch.setattr(system_mod.os, "sysconf", lambda name: 100)
    monkeypatch.setattr(system_mod.os, "getloadavg", lambda: (3.0, 0, 0))
    monkeypatch.setattr(system_mod.os, "cpu_count", lambda: 4)
    values = collect(str(tmp_path), _fake_proc(tmp_path))
    assert values["memory_use"] == 50.0
    assert values["host_uptime"] == 10000.5
    assert values["ha_uptime"] == 9000  # 10000.5 - 100000 / 100
    assert values["load_1m"] == 0.75
    assert 0 < values["disk_use"] <= 100


def test_collect_without_proc(tmp_path: Path) -> None:
    """Missing /proc only affects the metrics that need it."""
    values = collect(str(tmp_path), tmp_path / "missing")
    assert values["memory_use"] is None
    assert values["host_uptime"] is None
    assert values["ha_uptime"] is None
    assert values["disk_use"] is not None


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            {"disk_use": 50, "memory_use": 50, "load_1m": 0.5, "host_uptime": 99, "ha_uptime": 9},
            {"disk_use": OK, "memory_use": OK, "load_1m": OK, "host_uptime": OK, "ha_uptime": OK},
        ),
        (
            {"disk_use": 80, "memory_use": 90, "load_1m": 2.0, "host_uptime": 1, "ha_uptime": 1},
            {"disk_use": ATENCAO, "memory_use": ATENCAO, "load_1m": ATENCAO},
        ),
        (
            {"disk_use": 95, "memory_use": 96, "load_1m": 3.0, "host_uptime": 1, "ha_uptime": 1},
            {"disk_use": CRITICO, "memory_use": CRITICO, "load_1m": CRITICO},
        ),
        (
            {"disk_use": None, "memory_use": None, "load_1m": None, "host_uptime": None, "ha_uptime": None},
            {"disk_use": NAO, "memory_use": NAO, "load_1m": NAO, "host_uptime": NAO, "ha_uptime": NAO},
        ),
    ],
)
async def test_system_levels(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, float | None],
    expected: dict[str, HealthLevel],
) -> None:
    """Each metric is classified independently."""
    monkeypatch.setattr(system_mod, "collect", lambda config_dir: values)
    results = await _run(SystemCheck, hass)
    assert set(results) == {"disk_use", "memory_use", "load_1m", "host_uptime", "ha_uptime"}
    for key, level in expected.items():
        assert results[key].level is level, key


# -- system log -------------------------------------------------------------


async def test_system_log(hass: HomeAssistant) -> None:
    """Errors and warnings are counted per cycle and the handler is removed."""
    check = SystemLogCheck(hass, _entry(hass))
    await check.async_setup()
    log = logging.getLogger("custom.noisy")
    log.setLevel(logging.DEBUG)
    try:
        log.info("ignored")
        for _ in range(5):
            log.error("bad")
        log.warning("hmm")
        logging.getLogger("custom.other").error("other")

        result = (await check.async_run(DEFAULT_THRESHOLDS))[0]
        assert result.value == 6
        assert result.level is ATENCAO
        assert result.details["warnings"] == 1
        assert result.details["top_loggers"][0] == {"logger": "custom.noisy", "count": 6}

        # The counter restarts every cycle.
        result = (await check.async_run(DEFAULT_THRESHOLDS))[0]
        assert result.value == 0
        assert result.level is OK

        # One source repeating the same error is a single problem: attention.
        for _ in range(20):
            log.error("bad")
        result = (await check.async_run(DEFAULT_THRESHOLDS))[0]
        assert result.level is ATENCAO
        assert result.details["error_sources"] == 1
        assert result.message == "20 erros e 0 avisos no log, todos de custom.noisy"

        # Many errors from several sources: critical.
        for _ in range(18):
            log.error("bad")
        logging.getLogger("custom.other").error("other")
        logging.getLogger("custom.third").error("third")
        result = (await check.async_run(DEFAULT_THRESHOLDS))[0]
        assert result.level is CRITICO
        assert result.message == "20 erros e 0 avisos no log, de 3 origens"
        assert result.details["top_error_sources"][0] == {"logger": "custom.noisy", "count": 18}
    finally:
        await check.async_shutdown()
    assert check._handler not in logging.getLogger().handlers


# -- recorder ---------------------------------------------------------------


@pytest.mark.parametrize(("mb", "level"), [(10, OK), (2000, ATENCAO), (5000, CRITICO)])
async def test_recorder_sqlite(
    hass: HomeAssistant,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mb: int,
    level: HealthLevel,
) -> None:
    """The SQLite file size in MB drives the level."""
    db = tmp_path / "home-assistant_v2.db"
    with db.open("wb") as f:
        f.truncate(mb * 1_000_000)
    monkeypatch.setattr(RecorderCheck, "_db_url", lambda self: f"sqlite:///{db}")
    result = (await _run(RecorderCheck, hass))["recorder"]
    assert result.value == mb
    assert result.unit == "MB"
    assert result.level is level


@pytest.mark.parametrize(
    "db_url",
    [None, "mysql://user:pw@host/db", "postgresql://h/db", "sqlite:///missing/file.db"],
)
async def test_recorder_not_monitored(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, db_url: str | None
) -> None:
    """Other engines, a missing recorder or file are not monitored."""
    monkeypatch.setattr(RecorderCheck, "_db_url", lambda self: db_url)
    result = (await _run(RecorderCheck, hass))["recorder"]
    assert result.level is NAO
    assert "pw" not in result.message


async def test_recorder_db_url_without_recorder(hass: HomeAssistant) -> None:
    """Without the recorder component there is no database URL."""
    check = RecorderCheck(hass, _entry(hass))
    assert check._db_url() is None


# -- updates ----------------------------------------------------------------


async def test_updates(hass: HomeAssistant) -> None:
    """Pending updates warn, never go critical, and flag the core update."""
    result = (await _run(UpdatesCheck, hass))["updates"]
    assert (result.value, result.level) == (0, OK)

    hass.states.async_set("update.addon", "on")
    hass.states.async_set("update.other", "off")
    result = (await _run(UpdatesCheck, hass))["updates"]
    assert (result.value, result.level) == (1, ATENCAO)
    assert result.details["core_update"] is False

    for i in range(10):
        hass.states.async_set(f"update.x{i}", "on")
    hass.states.async_set(
        "update.home_assistant_core_update",
        "on",
        {"title": "Home Assistant Core", "latest_version": "2026.11.1"},
    )
    strict = {"updates": Threshold(atencao=1, critico=2)}
    result = (await _run(UpdatesCheck, hass, strict))["updates"]
    assert result.value == 12
    assert result.level is ATENCAO
    assert result.details["core_update"] is True
    assert result.details["core_latest_version"] == "2026.11.1"
    assert "2026.11.1" in result.message


# -- backup -----------------------------------------------------------------


@pytest.mark.parametrize(("hours", "level"), [(1, OK), (383, OK), (384, ATENCAO), (720, CRITICO)])
async def test_backup_option_entity(
    hass: HomeAssistant, hours: int, level: HealthLevel
) -> None:
    """The configured entity is used first."""
    last = dt_util.utcnow() - timedelta(hours=hours)
    hass.states.async_set("sensor.my_backup", last.isoformat())
    result = (
        await _run(BackupCheck, hass, **{CONF_BACKUP_ENTITY: "sensor.my_backup"})
    )["backup"]
    assert result.value == pytest.approx(hours, abs=0.1)
    assert result.level is level
    assert result.details["source"] == "option"


async def test_backup_native(hass: HomeAssistant, entity_registry: er.EntityRegistry) -> None:
    """The native backup sensor is found through the entity registry."""
    reg = entity_registry.async_get_or_create(
        "sensor", "backup", "last_successful_automatic_backup"
    )
    hass.states.async_set(reg.entity_id, (dt_util.utcnow() - timedelta(hours=2)).isoformat())
    result = (await _run(BackupCheck, hass))["backup"]
    assert result.level is OK
    assert result.details["source"] == "native"

    hass.states.async_set(reg.entity_id, "unknown")
    result = (await _run(BackupCheck, hass))["backup"]
    assert result.level is CRITICO
    assert result.value is None

    hass.states.async_set(reg.entity_id, "unavailable")
    result = (await _run(BackupCheck, hass))["backup"]
    assert result.level is NAO


def _patch_manager(monkeypatch: pytest.MonkeyPatch, info: ManagerInfo | None) -> list[int]:
    calls: list[int] = []

    async def fake(hass):
        calls.append(1)
        return info

    monkeypatch.setattr(backup_mod, "async_get_manager_info", fake)
    return calls


@pytest.mark.parametrize(("days", "level"), [(2, OK), (15, OK), (16, ATENCAO), (30, CRITICO)])
async def test_backup_manager_any_backup(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, days: int, level: HealthLevel
) -> None:
    """Backups created by automations (not the native schedule) are counted."""
    latest = dt_util.utcnow() - timedelta(days=days)
    _patch_manager(
        monkeypatch,
        ManagerInfo(latest, "MMH_Backup Full - 01/11/2026", 3, None, None),
    )
    result = (await _run(BackupCheck, hass))["backup"]
    assert result.level is level
    assert result.value == pytest.approx(days * 24, abs=0.1)
    assert result.details["source"] == "manager"
    assert result.details["last_backup_name"] == "MMH_Backup Full - 01/11/2026"
    assert result.details["last_automatic_failed"] is False


async def test_backup_manager_failed_attempt(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed last automatic attempt is critical even with a recent backup."""
    now = dt_util.utcnow()
    _patch_manager(
        monkeypatch,
        ManagerInfo(now - timedelta(days=1), "x", 1, now - timedelta(hours=1), now - timedelta(days=1)),
    )
    result = (await _run(BackupCheck, hass))["backup"]
    assert result.level is CRITICO
    assert result.details["last_automatic_failed"] is True
    assert "falhou" in result.message


async def test_backup_manager_no_backups(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No backup at all is critical."""
    _patch_manager(monkeypatch, ManagerInfo(None, None, 0, None, None))
    result = (await _run(BackupCheck, hass))["backup"]
    assert (result.value, result.level) == (None, CRITICO)


async def test_backup_option_beats_manager(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The configured entity wins over the backup manager."""
    calls = _patch_manager(monkeypatch, ManagerInfo(None, None, 0, None, None))
    hass.states.async_set("sensor.my_backup", dt_util.utcnow().isoformat())
    result = (
        await _run(BackupCheck, hass, **{CONF_BACKUP_ENTITY: "sensor.my_backup"})
    )["backup"]
    assert result.details["source"] == "option"
    assert calls == []


async def test_backup_manager_cached(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The backup list is read at most every 30 minutes."""
    calls = _patch_manager(
        monkeypatch, ManagerInfo(dt_util.utcnow(), "x", 1, None, None)
    )
    check = BackupCheck(hass, _entry(hass))
    await check.async_run(DEFAULT_THRESHOLDS)
    await check.async_run(DEFAULT_THRESHOLDS)
    assert len(calls) == 1
    check._manager_read_at -= timedelta(minutes=31)
    await check.async_run(DEFAULT_THRESHOLDS)
    assert len(calls) == 2


async def test_backup_manager_error_falls_back(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, entity_registry: er.EntityRegistry
) -> None:
    """If listing fails, the native sensor is used."""

    async def boom(hass):
        raise RuntimeError("agent down")

    monkeypatch.setattr(backup_mod, "async_get_manager_info", boom)
    reg = entity_registry.async_get_or_create(
        "sensor", "backup", "last_successful_automatic_backup"
    )
    hass.states.async_set(reg.entity_id, dt_util.utcnow().isoformat())
    result = (await _run(BackupCheck, hass))["backup"]
    assert result.details["source"] == "native"


async def test_backup_not_monitored(hass: HomeAssistant) -> None:
    """Without any source the check is not monitored."""
    result = (await _run(BackupCheck, hass))["backup"]
    assert result.level is NAO


# -- zigbee -----------------------------------------------------------------


async def test_zigbee_entities(hass: HomeAssistant) -> None:
    """Any configured entity in a problem state is critical."""
    hass.states.async_set("binary_sensor.z2m_connection", "on")
    hass.states.async_set("sensor.z2m_state", "online")
    opts = {CONF_ZIGBEE_ENTITIES: ["binary_sensor.z2m_connection", "sensor.z2m_state"]}
    result = (await _run(ZigbeeCheck, hass, **opts))["zigbee"]
    assert (result.value, result.level) == (0, OK)

    hass.states.async_set("sensor.z2m_state", "offline")
    result = (await _run(ZigbeeCheck, hass, **opts))["zigbee"]
    assert (result.value, result.level) == (1, CRITICO)
    assert result.details["problems"] == {"sensor.z2m_state": "offline"}

    opts[CONF_ZIGBEE_ENTITIES].append("sensor.gone")
    result = (await _run(ZigbeeCheck, hass, **opts))["zigbee"]
    assert result.value == 2


@pytest.mark.parametrize(
    ("state", "level"),
    [
        (ConfigEntryState.LOADED, OK),
        (ConfigEntryState.SETUP_IN_PROGRESS, OK),
        (ConfigEntryState.SETUP_RETRY, CRITICO),
        (ConfigEntryState.SETUP_ERROR, CRITICO),
    ],
)
async def test_zigbee_zha(hass: HomeAssistant, state: ConfigEntryState, level: HealthLevel) -> None:
    """Without entities the ZHA config entry state is used."""
    zha = _failed_entry(hass, "zha", state)
    result = (await _run(ZigbeeCheck, hass))["zigbee"]
    assert result.level is level
    assert result.details["source"] == "zha"
    # Avoid unloading the real ZHA integration (not installed) at teardown.
    zha.mock_state(hass, ConfigEntryState.NOT_LOADED)


async def test_zigbee_ignores_dismissed_discoveries(hass: HomeAssistant) -> None:
    """ZHA discoveries the user ignored are not a coordinator in use."""
    from homeassistant.config_entries import SOURCE_IGNORE

    _failed_entry(hass, "zha", ConfigEntryState.NOT_LOADED, source=SOURCE_IGNORE)
    result = (await _run(ZigbeeCheck, hass))["zigbee"]
    assert result.level is NAO


async def test_zigbee_prefers_loaded_entry(hass: HomeAssistant) -> None:
    """With several ZHA entries, a loaded one means the coordinator works."""
    _failed_entry(hass, "zha", ConfigEntryState.SETUP_RETRY)
    loaded = _failed_entry(hass, "zha", ConfigEntryState.LOADED)
    result = (await _run(ZigbeeCheck, hass))["zigbee"]
    assert result.level is OK
    loaded.mock_state(hass, ConfigEntryState.NOT_LOADED)


async def test_zigbee_not_monitored(hass: HomeAssistant) -> None:
    """No entities and no ZHA means not monitored."""
    result = (await _run(ZigbeeCheck, hass))["zigbee"]
    assert result.level is NAO


async def test_backup_manager_info_real_integration(hass: HomeAssistant) -> None:
    """Smoke test against the real backup integration (no backups yet)."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "backup", {})
    await hass.async_block_till_done()
    info = await backup_mod.async_get_manager_info(hass)
    assert info is not None
    assert info.count == 0
    assert info.latest is None
