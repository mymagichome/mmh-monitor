"""Data models for MMH Monitor."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any


class HealthLevel(IntEnum):
    """Health level of a check. The integer value is what is sent to InfluxDB."""

    NAO_MONITORADO = -1
    OK = 0
    ATENCAO = 1
    CRITICO = 2

    @property
    def state(self) -> str:
        """Return the string used for entity states and attributes."""
        return self.name.lower()


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Result of a single health measurement."""

    key: str
    value: float | int | None
    unit: str | None
    level: HealthLevel
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def worst_level(results: list[CheckResult]) -> HealthLevel:
    """Return the worst level among results, ignoring unmonitored checks."""
    levels = [r.level for r in results if r.level is not HealthLevel.NAO_MONITORADO]
    return max(levels, default=HealthLevel.OK)


@dataclass(slots=True)
class MonitorData:
    """Outcome of one coordinator cycle."""

    results: dict[str, CheckResult]
    level: HealthLevel
    message: str
    collected_at: datetime
    #: One explanation per check in warning or critical, critical first.
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PublishStatus:
    """Outcome of the most recent deliveries to the central services."""

    influx_ok: bool | None = None
    influx_last_success: datetime | None = None
    influx_last_error: str | None = None
    kuma_ok: bool | None = None
    kuma_last_error: str | None = None
