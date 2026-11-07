"""Check for unavailable entities."""

from __future__ import annotations

from fnmatch import fnmatchcase

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er

from ..const import CONF_IGNORED_ENTITIES, MAX_DETAIL_ITEMS
from ..models import CheckResult
from ..thresholds import Threshold, get_threshold
from .base import BaseCheck


class UnavailableEntitiesCheck(BaseCheck):
    """Percentage of entities in the unavailable state.

    Entities matching the ``ignored_entities`` glob patterns and the
    integration's own entities are left out of both the count and the total.
    """

    keys = ("unavailable_entities",)
    wait_for_startup = True

    async def async_run(self, thresholds: dict[str, Threshold]) -> list[CheckResult]:
        """Run the check."""
        patterns: list[str] = self.entry.options.get(CONF_IGNORED_ENTITIES, [])
        own = {
            entry.entity_id
            for entry in er.async_entries_for_config_entry(
                er.async_get(self.hass), self.entry.entry_id
            )
        }

        total = 0
        unavailable: list[str] = []
        for state in self.hass.states.async_all():
            entity_id = state.entity_id
            if entity_id in own or any(fnmatchcase(entity_id, p) for p in patterns):
                continue
            total += 1
            if state.state == STATE_UNAVAILABLE:
                unavailable.append(entity_id)

        count = len(unavailable)
        percent = round(count / total * 100, 1) if total else 0.0
        level = get_threshold(thresholds, "unavailable_entities").level_for(percent)
        if count == 0:
            message = "Nenhuma entidade indisponível"
        else:
            noun = "entidade indisponível" if count == 1 else "entidades indisponíveis"
            message = f"{count} {noun} ({percent:g}%)"
        unavailable.sort()
        return [
            CheckResult(
                key="unavailable_entities",
                value=percent,
                unit="%",
                level=level,
                message=message,
                details={
                    "count": count,
                    "total": total,
                    "entities": unavailable[:MAX_DETAIL_ITEMS],
                },
            )
        ]


