"""Zigbee coordinator connectivity."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState

from ..const import CONF_ZIGBEE_ENTITIES
from ..models import CheckResult, HealthLevel
from ..thresholds import Threshold, get_threshold
from .base import BaseCheck

# States that mean the bridge/coordinator is not working.
PROBLEM_STATES = {
    "off",
    "unavailable",
    "unknown",
    "offline",
    "disconnected",
    "error",
    "false",
}


class ZigbeeCheck(BaseCheck):
    """Check configured coordinator entities, or the ZHA config entry."""

    keys = ("zigbee",)

    async def async_run(self, thresholds: dict[str, Threshold]) -> list[CheckResult]:
        """Run the check."""
        threshold = get_threshold(thresholds, "zigbee")
        entity_ids: list[str] = self.entry.options.get(CONF_ZIGBEE_ENTITIES, [])
        if entity_ids:
            return [self._from_entities(entity_ids, threshold)]

        zha = [
            e
            for e in self.hass.config_entries.async_entries("zha")
            if e.disabled_by is None
        ]
        if zha:
            return [self._from_zha(zha[0].state, threshold)]
        return self.unmonitored("Nenhum coordenador Zigbee configurado")

    def _from_entities(self, entity_ids: list[str], threshold: Threshold) -> CheckResult:
        problems: dict[str, str] = {}
        for entity_id in entity_ids:
            state = self.hass.states.get(entity_id)
            value = "não encontrada" if state is None else state.state
            if state is None or state.state.lower() in PROBLEM_STATES:
                problems[entity_id] = value
        count = len(problems)
        if count:
            message = "Coordenador Zigbee com problema: " + ", ".join(
                f"{e} ({s})" for e, s in problems.items()
            )
        else:
            message = "Coordenador Zigbee conectado"
        return CheckResult(
            "zigbee",
            count,
            None,
            threshold.level_for(count),
            message,
            {"source": "entities", "problems": problems},
        )

    def _from_zha(self, state: ConfigEntryState, threshold: Threshold) -> CheckResult:
        # Setup in progress is a normal transient state at startup.
        ok = state in (ConfigEntryState.LOADED, ConfigEntryState.SETUP_IN_PROGRESS)
        count = 0 if ok else 1
        message = "ZHA conectado" if ok else f"ZHA com problema ({state.value})"
        return CheckResult(
            "zigbee",
            count,
            None,
            threshold.level_for(count) if not ok else HealthLevel.OK,
            message,
            {"source": "zha", "state": state.value},
        )
