"""Health thresholds.

Phase 3 ships the built-in defaults and level calculation. Remote thresholds
(fetched from ``thresholds_url`` and cached) are added in phase 4.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import HealthLevel


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
