"""Pending updates."""

from __future__ import annotations

from homeassistant.const import STATE_ON

from ..const import MAX_DETAIL_ITEMS
from ..models import CheckResult, HealthLevel
from ..thresholds import Threshold, get_threshold
from .base import BaseCheck

CORE_UPDATE_ENTITY = "update.home_assistant_core_update"
CORE_TITLE = "Home Assistant Core"


class UpdatesCheck(BaseCheck):
    """Count update entities that are on. At most a warning, never critical."""

    keys = ("updates",)

    async def async_run(self, thresholds: dict[str, Threshold]) -> list[CheckResult]:
        """Run the check."""
        pending = sorted(
            (s for s in self.hass.states.async_all("update") if s.state == STATE_ON),
            key=lambda s: s.entity_id,
        )
        core = next(
            (
                s
                for s in pending
                if s.entity_id == CORE_UPDATE_ENTITY
                or s.attributes.get("title") == CORE_TITLE
            ),
            None,
        )
        count = len(pending)
        level = min(
            get_threshold(thresholds, "updates").level_for(count), HealthLevel.ATENCAO
        )
        if count == 0:
            message = "Nenhuma atualização pendente"
        elif core is not None:
            message = (
                f"{count} atualizações pendentes, incluindo o HA Core "
                f"{core.attributes.get('latest_version', '')}".rstrip()
            )
        else:
            message = f"{count} atualizações pendentes"
        details = {
            "core_update": core is not None,
            "core_latest_version": core.attributes.get("latest_version") if core else None,
            "entities": [s.entity_id for s in pending[:MAX_DETAIL_ITEMS]],
        }
        return [CheckResult("updates", count, None, level, message, details)]
