"""Diagnostics for MMH Monitor. Secrets are redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_INFLUX_TOKEN, CONF_KUMA_PUSH_URL, CONF_THRESHOLDS_URL
from .coordinator import MMHMonitorConfigEntry

# The thresholds URL may embed an access key, so it is redacted as well.
TO_REDACT = {CONF_INFLUX_TOKEN, CONF_KUMA_PUSH_URL, CONF_THRESHOLDS_URL}


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MMHMonitorConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    thresholds = coordinator.threshold_manager
    data = coordinator.data
    status = coordinator.publish_status

    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "version": coordinator.version,
        "thresholds": {
            "source": thresholds.source,
            "remote_configured": bool(thresholds.url),
            "last_fetch": _iso(thresholds.last_fetch),
            "last_error": thresholds.last_error,
            "values": {
                key: {"atencao": t.atencao, "critico": t.critico}
                for key, t in sorted(thresholds.current.items())
            },
        },
        "health": None
        if data is None
        else {
            "level": data.level.state,
            "message": data.message,
            "collected_at": data.collected_at.isoformat(),
            "results": {
                key: {
                    "value": r.value,
                    "unit": r.unit,
                    "level": r.level.state,
                    "message": r.message,
                    "details": r.details,
                }
                for key, r in data.results.items()
            },
        },
        "publish": {key: _iso(value) for key, value in asdict(status).items()},
    }
