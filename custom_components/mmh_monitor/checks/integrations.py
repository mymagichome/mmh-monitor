"""Check for config entries that failed to set up."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState

from ..const import MAX_DETAIL_ITEMS
from ..models import CheckResult, HealthLevel
from ..thresholds import Threshold, get_threshold
from .base import BaseCheck

FAILED_STATES = (
    ConfigEntryState.SETUP_ERROR,
    ConfigEntryState.SETUP_RETRY,
    ConfigEntryState.MIGRATION_ERROR,
    ConfigEntryState.FAILED_UNLOAD,
)


class IntegrationsCheck(BaseCheck):
    """Count config entries in a failed state, ignoring disabled ones."""

    keys = ("integrations",)

    async def async_run(self, thresholds: dict[str, Threshold]) -> list[CheckResult]:
        """Run the check."""
        failed = [
            entry
            for entry in self.hass.config_entries.async_entries()
            if entry.disabled_by is None and entry.state in FAILED_STATES
        ]
        count = len(failed)
        level = get_threshold(thresholds, "integrations").level_for(count)
        if count == 0:
            message = "Nenhuma integração com falha"
        elif count == 1:
            message = f"1 integração com falha: {failed[0].domain}"
        else:
            message = f"{count} integrações com falha"
        details = {
            "entries": [
                {"domain": e.domain, "title": e.title, "state": e.state.value}
                for e in failed[:MAX_DETAIL_ITEMS]
            ]
        }
        return [
            CheckResult(
                key="integrations",
                value=count,
                unit=None,
                level=level if count else HealthLevel.OK,
                message=message,
                details=details,
            )
        ]
