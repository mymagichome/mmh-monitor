"""Tests for line protocol formatting and HTTP delivery."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mmh_monitor import publisher
from custom_components.mmh_monitor.models import CheckResult, HealthLevel, MonitorData
from custom_components.mmh_monitor.publisher import (
    FailureLogger,
    InfluxAuthError,
    InfluxBucketError,
    InfluxConnectionError,
    KumaError,
    async_push_kuma,
    async_write_influx,
    build_lines,
    escape_key,
    escape_measurement,
    escape_string_field,
    format_line,
    influx_write_url,
)

from .conftest import INFLUX_URL, INFLUX_WRITE, KUMA_URL, TOKEN

TS = 1_700_000_000


# -- escaping ---------------------------------------------------------------


def test_escape_key() -> None:
    """Commas, equals signs, spaces and backslashes are escaped."""
    assert escape_key("a b,c=d\\e") == "a\\ b\\,c\\=d\\\\e"
    assert escape_key("line\nbreak") == "line\\ break"


def test_escape_measurement() -> None:
    """Equals signs are allowed in measurement names."""
    assert escape_measurement("m a,b=c") == "m\\ a\\,b=c"


def test_escape_string_field() -> None:
    """Quotes and backslashes are escaped and line breaks removed."""
    assert escape_string_field('say "hi" \\ now\n') == '"say \\"hi\\" \\\\ now "'


def test_escape_string_field_truncates() -> None:
    """Very long messages are truncated."""
    assert len(escape_string_field("x" * 1000)) == 250 + 2


# -- format_line ------------------------------------------------------------


def test_format_line_types() -> None:
    """Ints get the i suffix, floats stay floats, strings are quoted."""
    line = format_line(
        "m", {"b": "2", "a": "1"}, {"i": 3, "f": 1.5, "s": "x", "t": True}, TS
    )
    assert line == f'm,a=1,b=2 i=3i,f=1.5,s="x",t=true {TS}'


def test_format_line_drops_empty() -> None:
    """Empty tags, None and non-finite fields are dropped."""
    line = format_line(
        "m", {"a": "", "b": None, "c": "ok"}, {"v": None, "n": float("nan"), "x": 1}, TS
    )
    assert line == f"m,c=ok x=1i {TS}"


def test_format_line_no_fields() -> None:
    """A line without fields is invalid and not produced."""
    assert format_line("m", {"a": "1"}, {"v": None}, TS) is None


# -- build_lines ------------------------------------------------------------


def _data() -> MonitorData:
    return MonitorData(
        results={
            "disk_use": CheckResult("disk_use", 81, "%", HealthLevel.ATENCAO, "Disco em 81%"),
            "zigbee": CheckResult(
                "zigbee", None, None, HealthLevel.NAO_MONITORADO, 'Sem "zigbee"'
            ),
        },
        level=HealthLevel.ATENCAO,
        message="Disco em 81%",
        collected_at=datetime.fromtimestamp(TS, UTC),
    )


def test_build_lines_schema() -> None:
    """Lines follow the documented schema."""
    lines = build_lines(_data(), site="cliente-exemplo", version="0.1.0", ha_version="2026.10.4")
    assert lines == [
        f'mmh_check,check=disk_use,site=cliente-exemplo value=81.0,level=1i,msg="Disco em 81%" {TS}',
        f'mmh_check,check=zigbee,site=cliente-exemplo level=-1i,msg="Sem \\"zigbee\\"" {TS}',
        f'mmh_health,ha_version=2026.10.4,site=cliente-exemplo,version=0.1.0 level=1i,msg="Disco em 81%" {TS}',
    ]


def test_influx_write_url() -> None:
    """Trailing slashes and base paths are handled."""
    assert str(influx_write_url("https://h.example/", "o g", "b")) == (
        "https://h.example/api/v2/write?org=o+g&bucket=b&precision=s"
    )
    assert str(influx_write_url("https://h.example/influx", "o", "b")).startswith(
        "https://h.example/influx/api/v2/write?"
    )


# -- InfluxDB delivery ------------------------------------------------------


async def test_write_influx_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """All lines go in one POST with the token header."""
    aioclient_mock.post(INFLUX_WRITE, status=204)
    await async_write_influx(
        async_get_clientsession(hass),
        url=INFLUX_URL,
        org="mmh",
        bucket="mmh_health",
        token=TOKEN,
        lines=["a x=1i 1", "b x=2i 1"],
    )
    assert aioclient_mock.call_count == 1
    _, _, body, headers = aioclient_mock.mock_calls[0]
    assert body == b"a x=1i 1\nb x=2i 1"
    assert headers["Authorization"] == f"Token {TOKEN}"
    assert headers["Content-Type"] == "text/plain; charset=utf-8"


@pytest.mark.parametrize(
    ("mock_kwargs", "error"),
    [
        ({"status": 401}, InfluxAuthError),
        ({"status": 403}, InfluxAuthError),
        ({"status": 404}, InfluxBucketError),
        ({"status": 500}, InfluxConnectionError),
        ({"exc": aiohttp.ClientConnectionError("boom")}, InfluxConnectionError),
        ({"exc": TimeoutError()}, InfluxConnectionError),
    ],
)
async def test_write_influx_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_kwargs: dict,
    error: type[Exception],
) -> None:
    """Failures raise typed errors whose message never contains the token."""
    aioclient_mock.post(INFLUX_WRITE, **mock_kwargs)
    with pytest.raises(error) as exc_info:
        await async_write_influx(
            async_get_clientsession(hass),
            url=INFLUX_URL,
            org="mmh",
            bucket="mmh_health",
            token=TOKEN,
            lines=["a x=1i 1"],
        )
    assert TOKEN not in str(exc_info.value)
    assert "influx.example.com" in str(exc_info.value)


# -- Uptime Kuma ------------------------------------------------------------


@pytest.mark.parametrize(("up", "status"), [(True, "up"), (False, "down")])
async def test_push_kuma(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, up: bool, status: str
) -> None:
    """The heartbeat carries status, message and an empty ping."""
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    await async_push_kuma(
        async_get_clientsession(hass), push_url=KUMA_URL, up=up, message="ok"
    )
    _, url, _, _ = aioclient_mock.mock_calls[0]
    assert url.query == {"status": status, "msg": "ok", "ping": ""}


async def test_push_kuma_overrides_existing_query(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A push URL copied with Kuma's default query is overridden, not duplicated."""
    aioclient_mock.get(KUMA_URL, json={"ok": True})
    await async_push_kuma(
        async_get_clientsession(hass),
        push_url=f"{KUMA_URL}?status=up&msg=OK&ping=",
        up=False,
        message="critico",
    )
    _, url, _, _ = aioclient_mock.mock_calls[0]
    assert url.query == {"status": "down", "msg": "critico", "ping": ""}


@pytest.mark.parametrize(
    "mock_kwargs",
    [
        {"status": 404, "json": {"ok": False, "msg": "Monitor not found"}},
        {"status": 200, "json": {"ok": False}},
        {"exc": aiohttp.ClientConnectionError()},
        {"exc": TimeoutError()},
    ],
)
async def test_push_kuma_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_kwargs: dict
) -> None:
    """Failures raise KumaError without the secret push token."""
    aioclient_mock.get(KUMA_URL, **mock_kwargs)
    with pytest.raises(KumaError) as exc_info:
        await async_push_kuma(
            async_get_clientsession(hass), push_url=KUMA_URL, up=True, message="ok"
        )
    assert "SECRETPUSHTOKEN" not in str(exc_info.value)


# -- rate-limited logging ---------------------------------------------------


def test_failure_logger_rate_limit(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated failures are logged once per interval; recovery once."""
    now = [1000.0]
    monkeypatch.setattr(publisher.time, "monotonic", lambda: now[0])
    log = FailureLogger("InfluxDB")
    caplog.set_level(logging.INFO)

    log.failure("timeout")
    log.failure("timeout")
    now[0] += 60
    log.failure("timeout")
    assert caplog.text.count("Sending to InfluxDB failed: timeout") == 1

    log.failure("HTTP 500")
    assert caplog.text.count("failed: HTTP 500") == 1

    now[0] += 3600
    log.failure("HTTP 500")
    assert caplog.text.count("failed: HTTP 500") == 2

    log.success()
    log.success()
    assert caplog.text.count("Sending to InfluxDB recovered") == 1
