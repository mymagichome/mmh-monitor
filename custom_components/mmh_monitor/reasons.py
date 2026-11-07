"""Human-readable explanations of why a check is not OK.

Every reason states the level, what was measured and which limits apply, e.g.
"Atenção — Disco em 81% (atenção a partir de 75%, crítico a partir de 90%)".
"""

from __future__ import annotations

from .models import CheckResult, HealthLevel
from .thresholds import Threshold

LABELS: dict[str, str] = {
    "integrations": "Integrações com falha",
    "unavailable_entities": "Entidades indisponíveis",
    "disk_use": "Disco",
    "memory_use": "Memória",
    "load_1m": "CPU",
    "host_uptime": "Tempo ligado do host",
    "ha_uptime": "Tempo ligado do HA",
    "system_log": "Erros no log",
    "recorder": "Banco de dados",
    "updates": "Atualizações",
    "backup": "Backup",
    "zigbee": "Zigbee",
}

LEVEL_LABELS: dict[HealthLevel, str] = {
    HealthLevel.OK: "OK",
    HealthLevel.ATENCAO: "Atenção",
    HealthLevel.CRITICO: "Crítico",
    HealthLevel.NAO_MONITORADO: "Não monitorado",
}


def label(key: str) -> str:
    """Return the Portuguese name of a check."""
    return LABELS.get(key, key)


def format_limit(key: str, value: float, unit: str | None) -> str:
    """Format a threshold value the way people read it."""
    if key == "backup" or unit == "h":
        days = value / 24
        return f"{days:g} dias" if days >= 2 else f"{value:g} h"
    if unit == "%":
        return f"{value:g}%"
    if unit == "MB" and value >= 1000:
        return f"{value / 1000:g} GB"
    if unit:
        return f"{value:g} {unit}"
    return f"{value:g}"


def limits_text(key: str, threshold: Threshold, unit: str | None) -> str:
    """'atenção a partir de 75%, crítico a partir de 90%' (only the limits that exist)."""
    parts = []
    if threshold.atencao is not None:
        parts.append(f"atenção a partir de {format_limit(key, threshold.atencao, unit)}")
    if threshold.critico is not None:
        parts.append(f"crítico a partir de {format_limit(key, threshold.critico, unit)}")
    return ", ".join(parts)


def describe(result: CheckResult, threshold: Threshold) -> str:
    """One line explaining a result: level, measurement and limits."""
    text = f"{LEVEL_LABELS[result.level]} — {result.message}"
    if result.value is not None:
        limits = limits_text(result.key, threshold, result.unit)
        if limits:
            text += f" ({limits})"
    return text
