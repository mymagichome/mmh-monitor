"""Health thresholds: built-in defaults plus optional remote overrides.

Remote thresholds come from a JSON file at ``thresholds_url``, fetched every
6 hours. The last valid file is cached with ``Store`` so a site keeps its
limits across restarts and network outages. Precedence, per field:
``sites.<slug>`` > ``checks`` > built-in default.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CONF_SITE_SLUG, CONF_THRESHOLDS_URL, DOMAIN, HTTP_TIMEOUT
from .models import HealthLevel

_LOGGER = logging.getLogger(__name__)

REFRESH_INTERVAL = timedelta(hours=6)
STORAGE_VERSION = 1
SCHEMA_VERSION = 1
LIMIT_FIELDS = ("atencao", "critico")


@dataclass(frozen=True, slots=True)
class Threshold:
    """Warning and critical limits. A value at or above a limit reaches it."""

    atencao: float | None = None
    critico: float | None = None

    def level_for(self, value: float | None) -> HealthLevel:
        """Classify a value against this threshold."""
        if value is None:
            return HealthLevel.NAO_MONITORADO
        if self.critico is not None and value >= self.critico:
            return HealthLevel.CRITICO
        if self.atencao is not None and value >= self.atencao:
            return HealthLevel.ATENCAO
        return HealthLevel.OK


DEFAULT_THRESHOLDS: dict[str, Threshold] = {
    "integrations": Threshold(atencao=1, critico=3),
    "unavailable_entities": Threshold(atencao=5, critico=15),  # percent
    "system_log": Threshold(atencao=5, critico=20),  # errors per cycle
    "disk_use": Threshold(atencao=75, critico=90),  # percent
    "memory_use": Threshold(atencao=85, critico=95),  # percent
    "load_1m": Threshold(atencao=1.5, critico=3.0),  # load per CPU
    "recorder": Threshold(atencao=2000, critico=5000),  # MB
    "backup": Threshold(atencao=48, critico=168),  # hours
    "updates": Threshold(atencao=1),  # never critical
    "zigbee": Threshold(critico=1),  # coordinator problems
}


def get_threshold(thresholds: dict[str, Threshold], key: str) -> Threshold:
    """Return the threshold for a check, or one that never triggers."""
    return thresholds.get(key, Threshold())


# --------------------------------------------------------------------------
# Remote thresholds
# --------------------------------------------------------------------------


class InvalidThresholds(ValueError):
    """The remote thresholds file does not follow the expected format."""


class ThresholdsFetchError(Exception):
    """The remote thresholds file could not be downloaded."""


def _validate_limits(path: str, limits: Any) -> dict[str, float | None]:
    if not isinstance(limits, Mapping):
        raise InvalidThresholds(f"{path} must be an object")
    unknown = set(limits) - set(LIMIT_FIELDS)
    if unknown:
        raise InvalidThresholds(f"{path} has unknown fields: {sorted(unknown)}")
    cleaned: dict[str, float | None] = {}
    for field in LIMIT_FIELDS:
        if field not in limits:
            continue
        value = limits[field]
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            raise InvalidThresholds(f"{path}.{field} must be a number or null")
        cleaned[field] = None if value is None else float(value)
    return cleaned


def _validate_section(path: str, section: Any) -> dict[str, dict[str, float | None]]:
    if not isinstance(section, Mapping):
        raise InvalidThresholds(f"{path} must be an object")
    return {
        str(key): _validate_limits(f"{path}.{key}", limits)
        for key, limits in section.items()
    }


def validate_payload(payload: Any) -> dict[str, Any]:
    """Validate a remote thresholds document and return a normalized copy."""
    if not isinstance(payload, Mapping):
        raise InvalidThresholds("document must be a JSON object")
    if payload.get("version") != SCHEMA_VERSION:
        raise InvalidThresholds(f"version must be {SCHEMA_VERSION}")
    checks = _validate_section("checks", payload.get("checks", {}))
    sites_raw = payload.get("sites", {})
    if not isinstance(sites_raw, Mapping):
        raise InvalidThresholds("sites must be an object")
    sites = {
        str(slug): _validate_section(f"sites.{slug}", section)
        for slug, section in sites_raw.items()
    }
    return {"version": SCHEMA_VERSION, "checks": checks, "sites": sites}


def merge_thresholds(
    defaults: Mapping[str, Threshold], payload: Mapping[str, Any] | None, site: str
) -> dict[str, Threshold]:
    """Apply a validated payload over the defaults, field by field.

    A field set to ``null`` disables that limit.
    """
    merged = dict(defaults)
    if not payload:
        return merged
    layers = (payload.get("checks", {}), payload.get("sites", {}).get(site, {}))
    for layer in layers:
        for key, limits in layer.items():
            merged[key] = replace(merged.get(key, Threshold()), **limits)
    return merged


class ThresholdManager:
    """Keep the effective thresholds for this site up to date."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.url: str | None = entry.options.get(CONF_THRESHOLDS_URL)
        self.site: str = entry.data[CONF_SITE_SLUG]
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.thresholds"
        )
        self.current: dict[str, Threshold] = dict(DEFAULT_THRESHOLDS)
        self.source = "default"
        self.last_fetch: datetime | None = None
        self.last_error: str | None = None
        self._unsub: Callable[[], None] | None = None
        self._logged_error: str | None = None

    async def async_setup(self) -> None:
        """Load the cache and schedule refreshes. Does not wait for the network."""
        if not self.url:
            return
        cached = await self._store.async_load()
        if cached and cached.get("url") == self.url:
            try:
                payload = validate_payload(cached.get("payload"))
            except InvalidThresholds:
                _LOGGER.warning("Ignoring invalid cached thresholds")
            else:
                self._apply(payload, "cache")
                fetched = cached.get("fetched_at")
                self.last_fetch = dt_util.parse_datetime(fetched) if fetched else None
        self._unsub = async_track_time_interval(
            self.hass, self._async_scheduled_refresh, REFRESH_INTERVAL
        )

    @callback
    def async_shutdown(self) -> None:
        """Stop periodic refreshes."""
        if self._unsub:
            self._unsub()
            self._unsub = None

    async def _async_scheduled_refresh(self, _now: datetime) -> None:
        await self.async_refresh()

    async def async_refresh(self) -> None:
        """Fetch the remote file; keep the current values on any failure."""
        if not self.url:
            return
        try:
            payload = await self._async_fetch()
        except InvalidThresholds as err:
            self._failure(f"invalid thresholds file: {err}")
            return
        except ThresholdsFetchError as err:
            self._failure(f"cannot fetch thresholds ({err})")
            return
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            self._failure(f"cannot fetch thresholds ({type(err).__name__})")
            return
        except Exception:  # noqa: BLE001 - a background refresh must never crash
            _LOGGER.exception("Unexpected error fetching remote thresholds")
            self.last_error = "unexpected error"
            return
        self._apply(payload, "remote")
        self.last_fetch = dt_util.utcnow()
        self.last_error = None
        if self._logged_error:
            _LOGGER.info("Remote thresholds fetched again")
            self._logged_error = None
        await self._store.async_save(
            {"url": self.url, "fetched_at": self.last_fetch.isoformat(), "payload": payload}
        )

    async def _async_fetch(self) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        async with session.get(
            self.url, timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        ) as resp:
            if resp.status != 200:
                raise ThresholdsFetchError(f"HTTP {resp.status}")
            data = await resp.json(content_type=None)
        return validate_payload(data)

    def _apply(self, payload: dict[str, Any], source: str) -> None:
        self.current = merge_thresholds(DEFAULT_THRESHOLDS, payload, self.site)
        self.source = source

    def _failure(self, message: str) -> None:
        self.last_error = message
        if message != self._logged_error:
            # The URL may embed a secret, so it is never logged.
            _LOGGER.warning(
                "Remote thresholds not updated, keeping %s values: %s",
                self.source,
                message,
            )
            self._logged_error = message
