"""Delivery of health data to InfluxDB (line protocol) and Uptime Kuma.

Security notes:
- The InfluxDB token is only ever placed in the Authorization header.
- The Kuma push URL embeds a secret token in its path, so it is never logged.
- Log messages only mention the InfluxDB host and an HTTP status or error type.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Iterable, Mapping

import aiohttp
from yarl import URL

from .const import (
    HTTP_TIMEOUT,
    LOG_REPEAT_INTERVAL,
    MAX_MESSAGE_LENGTH,
    MEASUREMENT_CHECK,
    MEASUREMENT_HEALTH,
    MEASUREMENT_SETUP,
)
from .models import MonitorData

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class PublishError(Exception):
    """Base error for delivery failures. The message is safe to log."""


class InfluxConnectionError(PublishError):
    """InfluxDB could not be reached or answered unexpectedly."""


class InfluxAuthError(PublishError):
    """InfluxDB rejected the token."""


class InfluxBucketError(PublishError):
    """InfluxDB did not find the organization or bucket."""


class KumaError(PublishError):
    """Uptime Kuma did not accept the heartbeat."""


# --------------------------------------------------------------------------
# Line protocol
# --------------------------------------------------------------------------


def _clean(text: str) -> str:
    """Replace line breaks, which line protocol does not allow in keys."""
    return text.replace("\r", " ").replace("\n", " ")


def escape_measurement(name: str) -> str:
    """Escape a measurement name (commas and spaces)."""
    return _clean(name).replace("\\", "\\\\").replace(",", "\\,").replace(" ", "\\ ")


def escape_key(text: str) -> str:
    """Escape a tag key, tag value or field key (commas, equals, spaces)."""
    return (
        _clean(text)
        .replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace("=", "\\=")
        .replace(" ", "\\ ")
    )


def escape_string_field(text: str) -> str:
    """Escape and quote a string field value."""
    text = _clean(text)[:MAX_MESSAGE_LENGTH]
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _format_field(value: float | int | bool | str) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"{value}i"
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return repr(value)
    return escape_string_field(str(value))


def format_line(
    measurement: str,
    tags: Mapping[str, str | None],
    fields: Mapping[str, float | int | bool | str | None],
    timestamp: int,
) -> str | None:
    """Build one line protocol record with second precision.

    Tags with empty values and fields with ``None`` or non-finite values are
    dropped. Returns ``None`` when no field is left, since such a line is
    invalid.
    """
    tag_part = "".join(
        f",{escape_key(key)}={escape_key(str(value))}"
        for key, value in sorted(tags.items())
        if value not in (None, "")
    )
    field_items = []
    for key, value in fields.items():
        if value is None:
            continue
        formatted = _format_field(value)
        if formatted is not None:
            field_items.append(f"{escape_key(key)}={formatted}")
    if not field_items:
        return None
    return f"{escape_measurement(measurement)}{tag_part} {','.join(field_items)} {timestamp}"


def build_lines(
    data: MonitorData,
    *,
    site: str,
    version: str,
    ha_version: str,
    timestamp: int | None = None,
) -> list[str]:
    """Build every line for one cycle.

    Schema (see README):
      mmh_check,check=<key>,site=<slug> value=<float>,level=<int>i,msg="..." <ts>
      mmh_health,ha_version=<v>,site=<slug>,version=<v> level=<int>i,msg="..." <ts>

    ``value`` is always sent as a float so the field type never changes
    between cycles; checks without a numeric value omit it.
    """
    ts = timestamp if timestamp is not None else int(data.collected_at.timestamp())
    lines: list[str] = []
    for result in data.results.values():
        value = None if result.value is None else float(result.value)
        line = format_line(
            MEASUREMENT_CHECK,
            {"site": site, "check": result.key},
            {"value": value, "level": int(result.level), "msg": result.message},
            ts,
        )
        if line:
            lines.append(line)
    health = format_line(
        MEASUREMENT_HEALTH,
        {"site": site, "version": version, "ha_version": ha_version},
        {"level": int(data.level), "msg": data.message},
        ts,
    )
    if health:
        lines.append(health)
    return lines


# --------------------------------------------------------------------------
# HTTP delivery
# --------------------------------------------------------------------------


def influx_write_url(base_url: str, org: str, bucket: str) -> URL:
    """Return the InfluxDB v2 write endpoint."""
    return URL(base_url.rstrip("/") + "/api/v2/write").with_query(
        {"org": org, "bucket": bucket, "precision": "s"}
    )


def url_host(url: str) -> str:
    """Return only the host of a URL, for log messages."""
    try:
        return URL(url).host or "?"
    except ValueError:
        return "?"


async def async_write_influx(
    session: aiohttp.ClientSession,
    *,
    url: str,
    org: str,
    bucket: str,
    token: str,
    lines: Iterable[str],
) -> None:
    """Send lines to InfluxDB in a single request.

    Raises a PublishError subclass with a log-safe message on failure.
    """
    body = "\n".join(lines)
    host = url_host(url)
    try:
        async with session.post(
            influx_write_url(url, org, bucket),
            data=body.encode(),
            headers={
                "Authorization": f"Token {token}",
                "Content-Type": "text/plain; charset=utf-8",
            },
            timeout=_TIMEOUT,
        ) as resp:
            status = resp.status
    except TimeoutError as err:
        raise InfluxConnectionError(f"timeout connecting to {host}") from err
    except aiohttp.ClientError as err:
        raise InfluxConnectionError(
            f"cannot connect to {host} ({type(err).__name__})"
        ) from err
    except ValueError as err:
        raise InfluxConnectionError("invalid InfluxDB URL") from err

    if status in (200, 204):
        return
    if status in (401, 403):
        raise InfluxAuthError(f"{host} rejected the token (HTTP {status})")
    if status == 404:
        raise InfluxBucketError(f"{host} did not find the org or bucket (HTTP 404)")
    raise InfluxConnectionError(f"{host} answered HTTP {status}")


async def async_test_influx(
    session: aiohttp.ClientSession,
    *,
    url: str,
    org: str,
    bucket: str,
    token: str,
    site: str,
    version: str,
) -> None:
    """Write a single setup point to validate the connection settings."""
    line = format_line(
        MEASUREMENT_SETUP,
        {"site": site, "version": version},
        {"ok": 1},
        int(time.time()),
    )
    assert line is not None
    await async_write_influx(
        session, url=url, org=org, bucket=bucket, token=token, lines=[line]
    )


async def async_push_kuma(
    session: aiohttp.ClientSession,
    *,
    push_url: str,
    up: bool,
    message: str,
) -> None:
    """Send a heartbeat to an Uptime Kuma push monitor."""
    try:
        url = URL(push_url).update_query(
            {"status": "up" if up else "down", "msg": message, "ping": ""}
        )
    except ValueError as err:
        raise KumaError("invalid Uptime Kuma URL") from err
    try:
        async with session.get(url, timeout=_TIMEOUT) as resp:
            status = resp.status
            try:
                payload = await resp.json(content_type=None)
            except (ValueError, aiohttp.ContentTypeError):
                payload = None
    except TimeoutError as err:
        raise KumaError("timeout connecting to Uptime Kuma") from err
    except aiohttp.ClientError as err:
        raise KumaError(f"cannot connect to Uptime Kuma ({type(err).__name__})") from err

    if status != 200:
        raise KumaError(f"Uptime Kuma answered HTTP {status}")
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise KumaError("Uptime Kuma rejected the heartbeat")


# --------------------------------------------------------------------------
# Rate-limited logging
# --------------------------------------------------------------------------


class FailureLogger:
    """Log delivery failures without flooding the log.

    A failure is logged when it first happens, when its message changes, or
    when it has persisted for LOG_REPEAT_INTERVAL. Recovery is logged once.
    """

    def __init__(self, target: str) -> None:
        """Initialize for a named delivery target."""
        self._target = target
        self._last_message: str | None = None
        self._last_logged = 0.0

    def failure(self, message: str) -> None:
        """Record a failure."""
        now = time.monotonic()
        if (
            message != self._last_message
            or now - self._last_logged >= LOG_REPEAT_INTERVAL
        ):
            _LOGGER.warning("Sending to %s failed: %s", self._target, message)
            self._last_logged = now
        self._last_message = message

    def success(self) -> None:
        """Record a success."""
        if self._last_message is not None:
            _LOGGER.info("Sending to %s recovered", self._target)
        self._last_message = None
