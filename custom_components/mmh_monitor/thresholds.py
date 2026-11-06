"""Health thresholds.

Phase 2 ships the built-in defaults and level calculation. Remote thresholds
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
}


def get_threshold(thresholds: dict[str, Threshold], key: str) -> Threshold:
    """Return the threshold for a check, or one that never triggers."""
    return thresholds.get(key, Threshold())
