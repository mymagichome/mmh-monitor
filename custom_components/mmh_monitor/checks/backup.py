"""Time since the last successful backup."""

from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from ..const import CONF_BACKUP_ENTITY
from ..models import CheckResult, HealthLevel
from ..thresholds import Threshold, get_threshold
from .base import BaseCheck

NATIVE_UNIQUE_ID = "last_successful_automatic_backup"


class BackupCheck(BaseCheck):
    """Hours since the last backup.

    Source priority: the ``backup_entity`` option, then the native backup
    integration's "last successful automatic backup" sensor.
    """

    keys = ("backup",)

    def _source(self) -> tuple[str, str] | None:
        if entity_id := self.entry.options.get(CONF_BACKUP_ENTITY):
            return entity_id, "option"
        registry = er.async_get(self.hass)
        if entity_id := registry.async_get_entity_id("sensor", "backup", NATIVE_UNIQUE_ID):
            return entity_id, "native"
        return None

    async def async_run(self, thresholds: dict[str, Threshold]) -> list[CheckResult]:
        """Run the check."""
        source = self._source()
        if source is None:
            return self.unmonitored("Nenhuma fonte de backup encontrada")
        entity_id, origin = source
        details = {"entity_id": entity_id, "source": origin}

        state = self.hass.states.get(entity_id)
        if state is None or state.state == STATE_UNAVAILABLE:
            return [
                CheckResult(
                    "backup", None, "h", HealthLevel.NAO_MONITORADO,
                    "Sensor de backup indisponível", details,
                )
            ]
        if state.state in (STATE_UNKNOWN, ""):
            return [
                CheckResult(
                    "backup", None, "h", HealthLevel.CRITICO,
                    "Nenhum backup registrado", details,
                )
            ]
        last = dt_util.parse_datetime(state.state)
        if last is None:
            return [
                CheckResult(
                    "backup", None, "h", HealthLevel.NAO_MONITORADO,
                    "Data do backup em formato inválido", details,
                )
            ]
        if last.tzinfo is None:
            last = dt_util.as_utc(last.replace(tzinfo=dt_util.get_default_time_zone()))
        hours = round(max((dt_util.utcnow() - last).total_seconds(), 0) / 3600, 1)
        level = get_threshold(thresholds, "backup").level_for(hours)
        details["last_backup"] = last.isoformat()
        return [
            CheckResult(
                "backup", hours, "h", level, f"Último backup há {hours:g} h", details
            )
        ]
