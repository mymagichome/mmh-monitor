"""Time since the last backup, and whether the last automatic attempt failed.

Source priority:

1. the ``backup_entity`` option (sites with their own backup tool);
2. the backup manager: every backup the HA knows about, whatever created it
   (the native schedule, an automation calling ``hassio.backup_full``,
   manual backups);
3. the native "last successful automatic backup" sensor;
4. otherwise not monitored.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from ..const import CONF_BACKUP_ENTITY
from ..models import CheckResult, HealthLevel
from ..thresholds import Threshold, get_threshold
from .base import BaseCheck

_LOGGER = logging.getLogger(__name__)

NATIVE_UNIQUE_ID = "last_successful_automatic_backup"
# Listing backups may query remote agents (cloud storage), so the list is
# refreshed at most this often. Backup age does not need finer resolution.
MANAGER_REFRESH = timedelta(minutes=30)


@dataclass(slots=True)
class ManagerInfo:
    """What the backup manager knows."""

    latest: datetime | None
    latest_name: str | None
    count: int
    last_attempted_automatic: datetime | None
    last_completed_automatic: datetime | None
    agent_errors: list[str] = field(default_factory=list)


async def async_get_manager_info(hass: HomeAssistant) -> ManagerInfo | None:
    """Read backups from the backup manager, or None when it is not available."""
    if "backup" not in hass.config.components:
        return None
    from homeassistant.components.backup import async_get_manager  # noqa: PLC0415

    try:
        manager = async_get_manager(hass)
    except Exception:  # noqa: BLE001 - integration not ready or not available
        return None

    backups, agent_errors = await manager.async_get_backups()
    latest: datetime | None = None
    latest_name: str | None = None
    for backup in backups.values():
        if not backup.homeassistant_included:
            continue
        date = dt_util.parse_datetime(backup.date)
        if date is None:
            continue
        if date.tzinfo is None:
            date = dt_util.as_utc(date.replace(tzinfo=dt_util.get_default_time_zone()))
        if latest is None or date > latest:
            latest, latest_name = date, backup.name

    config = manager.config.data
    return ManagerInfo(
        latest=latest,
        latest_name=latest_name,
        count=len(backups),
        last_attempted_automatic=config.last_attempted_automatic_backup,
        last_completed_automatic=config.last_completed_automatic_backup,
        agent_errors=sorted(agent_errors),
    )


def _age_message(hours: float) -> str:
    if hours >= 48:
        return f"Último backup há {hours / 24:.0f} dias"
    return f"Último backup há {hours:g} h"


class BackupCheck(BaseCheck):
    """Hours since the last backup."""

    keys = ("backup",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the check."""
        super().__init__(*args, **kwargs)
        self._manager_info: ManagerInfo | None = None
        self._manager_read_at: datetime | None = None

    async def async_run(self, thresholds: dict[str, Threshold]) -> list[CheckResult]:
        """Run the check."""
        threshold = get_threshold(thresholds, "backup")
        if entity_id := self.entry.options.get(CONF_BACKUP_ENTITY):
            return [self._from_entity(entity_id, "option", threshold)]

        info = await self._async_manager_info()
        if info is not None:
            return [self._from_manager(info, threshold)]

        registry = er.async_get(self.hass)
        if entity_id := registry.async_get_entity_id("sensor", "backup", NATIVE_UNIQUE_ID):
            return [self._from_entity(entity_id, "native", threshold)]
        return self.unmonitored("Nenhuma fonte de backup encontrada")

    async def _async_manager_info(self) -> ManagerInfo | None:
        now = dt_util.utcnow()
        if (
            self._manager_read_at is not None
            and now - self._manager_read_at < MANAGER_REFRESH
        ):
            return self._manager_info
        try:
            info = await async_get_manager_info(self.hass)
        except Exception:  # noqa: BLE001 - fall back to the sensor
            _LOGGER.debug("Cannot list backups", exc_info=True)
            info = None
        self._manager_info = info
        self._manager_read_at = now
        return info

    def _from_manager(self, info: ManagerInfo, threshold: Threshold) -> CheckResult:
        details: dict[str, Any] = {
            "source": "manager",
            "backups": info.count,
            "last_backup": info.latest.isoformat() if info.latest else None,
            "last_backup_name": info.latest_name,
        }
        if info.agent_errors:
            details["agent_errors"] = info.agent_errors

        attempted, completed = info.last_attempted_automatic, info.last_completed_automatic
        failed = attempted is not None and (completed is None or attempted > completed)
        details["last_automatic_failed"] = failed

        if info.latest is None:
            return CheckResult(
                "backup", None, "h", HealthLevel.CRITICO, "Nenhum backup encontrado", details
            )
        hours = round(max((dt_util.utcnow() - info.latest).total_seconds(), 0) / 3600, 1)
        level = threshold.level_for(hours)
        message = _age_message(hours)
        if failed:
            level = HealthLevel.CRITICO
            message = f"Última tentativa de backup automático falhou; {message.lower()}"
        return CheckResult("backup", hours, "h", level, message, details)

    def _from_entity(self, entity_id: str, origin: str, threshold: Threshold) -> CheckResult:
        details: dict[str, Any] = {"entity_id": entity_id, "source": origin}
        state = self.hass.states.get(entity_id)
        if state is None or state.state == STATE_UNAVAILABLE:
            return CheckResult(
                "backup", None, "h", HealthLevel.NAO_MONITORADO,
                "Sensor de backup indisponível", details,
            )
        if state.state in (STATE_UNKNOWN, ""):
            return CheckResult(
                "backup", None, "h", HealthLevel.CRITICO, "Nenhum backup registrado", details
            )
        last = dt_util.parse_datetime(state.state)
        if last is None:
            return CheckResult(
                "backup", None, "h", HealthLevel.NAO_MONITORADO,
                "Data do backup em formato inválido", details,
            )
        if last.tzinfo is None:
            last = dt_util.as_utc(last.replace(tzinfo=dt_util.get_default_time_zone()))
        hours = round(max((dt_util.utcnow() - last).total_seconds(), 0) / 3600, 1)
        details["last_backup"] = last.isoformat()
        return CheckResult(
            "backup", hours, "h", threshold.level_for(hours), _age_message(hours), details
        )
