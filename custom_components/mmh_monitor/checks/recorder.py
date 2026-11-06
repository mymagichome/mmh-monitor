"""Size of the recorder database (SQLite only)."""

from __future__ import annotations

import os

from ..models import CheckResult
from ..thresholds import Threshold, get_threshold
from .base import BaseCheck

SQLITE_PREFIX = "sqlite://"


def _sizes_mb(path: str) -> tuple[float, float]:
    """Return database and WAL file sizes in MB. Blocking."""
    size = os.path.getsize(path)
    try:
        wal = os.path.getsize(f"{path}-wal")
    except OSError:
        wal = 0
    return round(size / 1_000_000, 1), round(wal / 1_000_000, 1)


class RecorderCheck(BaseCheck):
    """Measure the SQLite database file; other engines are not monitored."""

    keys = ("recorder",)

    def _db_url(self) -> str | None:
        if "recorder" not in self.hass.config.components:
            return None
        from homeassistant.components.recorder import get_instance  # noqa: PLC0415

        try:
            return get_instance(self.hass).db_url
        except KeyError:
            return None

    async def async_run(self, thresholds: dict[str, Threshold]) -> list[CheckResult]:
        """Run the check."""
        db_url = self._db_url()
        if db_url is None:
            return self.unmonitored("Recorder não está ativo")
        if not db_url.startswith(SQLITE_PREFIX) or db_url == SQLITE_PREFIX:
            engine = db_url.split(":", 1)[0]
            return self.unmonitored(f"Banco {engine} não é monitorado")
        path = db_url.removeprefix(SQLITE_PREFIX)
        if path.startswith("/:memory:") or path == ":memory:":
            return self.unmonitored("Banco em memória não é monitorado")
        try:
            size, wal = await self.hass.async_add_executor_job(_sizes_mb, path)
        except OSError:
            return self.unmonitored("Arquivo do banco não encontrado")
        level = get_threshold(thresholds, "recorder").level_for(size)
        return [
            CheckResult(
                key="recorder",
                value=size,
                unit="MB",
                level=level,
                message=f"Banco de dados com {size:g} MB",
                details={"wal_mb": wal},
            )
        ]


