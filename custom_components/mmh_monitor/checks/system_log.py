"""Count errors and warnings logged during each cycle.

A lightweight logging handler on the root logger counts records. This avoids
reading internal structures and does not depend on ``system_log`` firing
events (which requires YAML configuration).
"""

from __future__ import annotations

import logging
import threading
from collections import Counter

from ..models import CheckResult
from ..thresholds import Threshold, get_threshold
from .base import BaseCheck

TOP_LOGGERS = 10


class _CountingHandler(logging.Handler):
    """Thread-safe counter of WARNING and ERROR records. Never blocks."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self._lock = threading.Lock()
        self.errors = 0
        self.warnings = 0
        self.loggers: Counter[str] = Counter()

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            if record.levelno >= logging.ERROR:
                self.errors += 1
            else:
                self.warnings += 1
            self.loggers[record.name] += 1

    def snapshot_and_reset(self) -> tuple[int, int, list[tuple[str, int]]]:
        with self._lock:
            result = (self.errors, self.warnings, self.loggers.most_common(TOP_LOGGERS))
            self.errors = 0
            self.warnings = 0
            self.loggers = Counter()
        return result


class SystemLogCheck(BaseCheck):
    """Errors logged since the previous cycle."""

    keys = ("system_log",)

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the check."""
        super().__init__(*args, **kwargs)
        self._handler = _CountingHandler()

    async def async_setup(self) -> None:
        """Attach the counting handler."""
        logging.getLogger().addHandler(self._handler)

    async def async_shutdown(self) -> None:
        """Detach the counting handler."""
        logging.getLogger().removeHandler(self._handler)

    async def async_run(self, thresholds: dict[str, Threshold]) -> list[CheckResult]:
        """Run the check."""
        errors, warnings, top = self._handler.snapshot_and_reset()
        level = get_threshold(thresholds, "system_log").level_for(errors)
        message = f"{errors} erros e {warnings} avisos no log"
        return [
            CheckResult(
                key="system_log",
                value=errors,
                unit=None,
                level=level,
                message=message,
                details={
                    "warnings": warnings,
                    "top_loggers": [{"logger": n, "count": c} for n, c in top],
                },
            )
        ]
