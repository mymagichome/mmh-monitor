"""Repair issues for critical checks.

A check that turns critical opens an issue in Settings > Repairs. The issue
is removed when the check returns to OK or warning. Issues are informational
only (``is_fixable=False``): the integration never changes anything on the
site.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .models import HealthLevel, MonitorData

ISSUE_PREFIX = "critical_"


class RepairManager:
    """Create and remove repair issues as check levels change."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the manager."""
        self.hass = hass
        # issue key -> message currently shown, to avoid rewriting unchanged issues
        self._active: dict[str, str] = {}

    @callback
    def async_update(self, data: MonitorData) -> None:
        """Sync issues with the latest results."""
        for key, result in data.results.items():
            issue_id = f"{ISSUE_PREFIX}{key}"
            if result.level is HealthLevel.CRITICO:
                if self._active.get(issue_id) == result.message:
                    continue
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    is_persistent=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="check_critical",
                    translation_placeholders={"check": key, "message": result.message},
                )
                self._active[issue_id] = result.message
            elif result.level in (HealthLevel.OK, HealthLevel.ATENCAO):
                self._delete(issue_id)

    @callback
    def async_clear(self) -> None:
        """Remove every issue created by this integration."""
        registry = ir.async_get(self.hass)
        for domain, issue_id in list(registry.issues):
            if domain == DOMAIN and issue_id.startswith(ISSUE_PREFIX):
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._active.clear()

    def _delete(self, issue_id: str) -> None:
        if issue_id in self._active or ir.async_get(self.hass).async_get_issue(
            DOMAIN, issue_id
        ):
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._active.pop(issue_id, None)
