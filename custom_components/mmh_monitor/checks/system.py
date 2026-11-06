"""Host resource checks: disk, memory, load and uptimes.

All file and /proc access runs in the executor. Each metric is independent:
one that cannot be read is reported as not monitored without affecting the
others.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from ..models import CheckResult, HealthLevel
from ..thresholds import Threshold, get_threshold
from .base import BaseCheck

_LOGGER = logging.getLogger(__name__)

PROC = Path("/proc")


def read_disk_use(path: str) -> float:
    """Return the used percentage of the filesystem holding ``path``."""
    usage = shutil.disk_usage(path)
    return round(usage.used / usage.total * 100, 1)


def read_memory_use(proc: Path = PROC) -> float:
    """Return used memory percentage from /proc/meminfo."""
    values: dict[str, int] = {}
    for line in (proc / "meminfo").read_text().splitlines():
        name, _, rest = line.partition(":")
        if name in ("MemTotal", "MemAvailable"):
            values[name] = int(rest.split()[0])
    total, available = values["MemTotal"], values["MemAvailable"]
    return round((total - available) / total * 100, 1)


def read_load_per_cpu() -> float:
    """Return the 1-minute load average divided by the CPU count."""
    return round(os.getloadavg()[0] / (os.cpu_count() or 1), 2)


def read_host_uptime(proc: Path = PROC) -> float:
    """Return host uptime in seconds."""
    return float((proc / "uptime").read_text().split()[0])


def read_process_uptime(proc: Path = PROC) -> float:
    """Return how long this process (Home Assistant) has been running, in seconds."""
    stat = (proc / "self" / "stat").read_text()
    # Fields after the command name, which is in parentheses and may contain
    # spaces. starttime is field 22 overall, i.e. index 19 after ")".
    start_ticks = int(stat.rpartition(")")[2].split()[19])
    started_after_boot = start_ticks / os.sysconf("SC_CLK_TCK")
    return round(read_host_uptime(proc) - started_after_boot)


METRICS = ("disk_use", "memory_use", "load_1m", "host_uptime", "ha_uptime")


def collect(config_dir: str, proc: Path = PROC) -> dict[str, float | None]:
    """Collect every metric. Blocking: call from the executor."""
    readers = {
        "disk_use": lambda: read_disk_use(config_dir),
        "memory_use": lambda: read_memory_use(proc),
        "load_1m": read_load_per_cpu,
        "host_uptime": lambda: read_host_uptime(proc),
        "ha_uptime": lambda: read_process_uptime(proc),
    }
    values: dict[str, float | None] = {}
    for key, reader in readers.items():
        try:
            values[key] = reader()
        except (OSError, ValueError, KeyError, IndexError, ZeroDivisionError) as err:
            _LOGGER.debug("Cannot read %s: %s", key, err)
            values[key] = None
    return values


def _duration(seconds: float) -> str:
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return f"{days}d {hours}h"
    return f"{hours}h {rest // 60}min"


class SystemCheck(BaseCheck):
    """Disk, memory, load and uptime of the host."""

    keys = METRICS

    async def async_run(self, thresholds: dict[str, Threshold]) -> list[CheckResult]:
        """Run the check."""
        values = await self.hass.async_add_executor_job(
            collect, self.hass.config.config_dir
        )
        return [self._result(key, values[key], thresholds) for key in METRICS]

    @staticmethod
    def _result(
        key: str, value: float | None, thresholds: dict[str, Threshold]
    ) -> CheckResult:
        if value is None:
            return CheckResult(
                key, None, None, HealthLevel.NAO_MONITORADO, "Não disponível neste sistema"
            )
        if key in ("host_uptime", "ha_uptime"):
            label = "Host" if key == "host_uptime" else "Home Assistant"
            # Metrics only: no level of their own.
            return CheckResult(
                key, value, "s", HealthLevel.OK, f"{label} ligado há {_duration(value)}"
            )
        level = get_threshold(thresholds, key).level_for(value)
        if key == "load_1m":
            return CheckResult(key, value, None, level, f"Carga de CPU {value:g} por núcleo")
        label = "Disco" if key == "disk_use" else "Memória"
        return CheckResult(key, value, "%", level, f"{label} em {value:g}%")
