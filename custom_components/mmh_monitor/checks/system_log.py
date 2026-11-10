"""Count errors and warnings logged during each cycle.

The level follows the number of errors, but it is only critical when they come
from several loggers (``SYSTEM_LOG_MIN_SOURCES``): a single source repeating
the same error is one problem and stays at attention.

A lightweight logging handler on the root logger counts records. This avoids
reading internal structures and does not depend on ``system_log`` firing
events (which requires YAML configuration).
"""

from __future__ import annotations

import logging
import threading
from collections import Counter

from ..models import CheckResult, HealthLevel
from ..thresholds import SYSTEM_LOG_MIN_SOURCES, Threshold, get_threshold
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
        self.error_loggers: Counter[str] = Counter()

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            if record.levelno >= logging.ERROR:
                self.errors += 1
                self.error_loggers[record.name] += 1
            else:
                self.warnings += 1
            self.loggers[record.name] += 1

    def snapshot_and_reset(
        self,
    ) -> tuple[int, int, list[tuple[str, int]], list[tuple[str, int]]]:
        with self._lock:
            result = (
                self.errors,
                self.warnings,
                self.loggers.most_common(TOP_LOGGERS),
                self.error_loggers.most_common(),
            )
            self.errors = 0
            self.warnings = 0
            self.loggers = Counter()
            self.error_loggers = Counter()
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
        errors, warnings, top, error_sources = self._handler.snapshot_and_reset()
        sources = len(error_sources)
        level = get_threshold(thresholds, "system_log").level_for(errors)
        if level is HealthLevel.CRITICO and sources < SYSTEM_LOG_MIN_SOURCES:
            level = HealthLevel.ATENCAO
        message = f"{errors} erros e {warnings} avisos no log"
        if sources == 1:
            message += f", todos de {error_sources[0][0]}"
        elif sources > 1:
            message += f", de {sources} origens"
        return [
            CheckResult(
                key="system_log",
                value=errors,
                unit=None,
                level=level,
                message=message,
                details={
                    "warnings": warnings,
                    "error_sources": sources,
                    "top_error_sources": [
                        {"logger": n, "count": c} for n, c in error_sources[:TOP_LOGGERS]
                    ],
                    "top_loggers": [{"logger": n, "count": c} for n, c in top],
                },
            )
        ]
