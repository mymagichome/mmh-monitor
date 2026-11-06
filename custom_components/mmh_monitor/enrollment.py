"""Enrollment by code: exchange a one-time code for the central settings.

The MMH gateway creates a write-only InfluxDB token for the site and returns it
with the InfluxDB URL, organization and bucket. Nobody has to copy a token.
"""

from __future__ import annotations

from typing import Any

import aiohttp
from yarl import URL

from .const import ENROLL_TIMEOUT


class EnrollmentError(Exception):
    """Enrollment failed. ``key`` is a config-flow error key; ``detail`` is safe to show."""

    def __init__(self, key: str, detail: str = "") -> None:
        """Initialize the error."""
        super().__init__(detail or key)
        self.key = key
        self.detail = detail


def enroll_url(gateway_url: str) -> URL:
    """Return the gateway's monitor enrollment endpoint."""
    url = URL(gateway_url.strip().rstrip("/"))
    if url.scheme != "https" or not url.host:
        raise EnrollmentError("invalid_url")
    return url / "monitor" / "enroll"


async def async_enroll(
    session: aiohttp.ClientSession,
    *,
    gateway_url: str,
    code: str,
    slug: str,
    version: str,
) -> dict[str, str]:
    """Return influx_url, influx_org, influx_bucket and influx_token for the site."""
    url = enroll_url(gateway_url)
    try:
        async with session.post(
            url,
            json={"code": code.strip(), "slug": slug, "integration_version": version},
            timeout=aiohttp.ClientTimeout(total=ENROLL_TIMEOUT),
        ) as resp:
            status = resp.status
            try:
                body: Any = await resp.json(content_type=None)
            except ValueError:
                body = None
    except (aiohttp.ClientError, TimeoutError) as err:
        raise EnrollmentError("cannot_connect_gateway") from err

    if not isinstance(body, dict):
        body = {}
    detail = str(body.get("error") or "")[:200]
    if status == 200 and body.get("ok"):
        influx = body.get("influx")
        if not isinstance(influx, dict) or not all(
            isinstance(influx.get(k), str) and influx.get(k) for k in ("url", "org", "bucket", "token")
        ):
            raise EnrollmentError("gateway_error", "resposta incompleta do gateway")
        return {
            "influx_url": influx["url"],
            "influx_org": influx["org"],
            "influx_bucket": influx["bucket"],
            "influx_token": influx["token"],
        }
    if status == 403:
        raise EnrollmentError("invalid_code")
    if status == 409:
        raise EnrollmentError("wrong_site", detail)
    if status == 429:
        raise EnrollmentError("too_many_attempts")
    raise EnrollmentError("gateway_error", detail or f"HTTP {status}")
