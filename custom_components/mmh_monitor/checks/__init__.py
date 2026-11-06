"""Registry of health checks, in execution order."""

from __future__ import annotations

from .backup import BackupCheck
from .base import BaseCheck
from .entities import UnavailableEntitiesCheck
from .integrations import IntegrationsCheck
from .recorder import RecorderCheck
from .system import SystemCheck
from .system_log import SystemLogCheck
from .updates import UpdatesCheck
from .zigbee import ZigbeeCheck

CHECKS: tuple[type[BaseCheck], ...] = (
    IntegrationsCheck,
    UnavailableEntitiesCheck,
    SystemCheck,
    SystemLogCheck,
    RecorderCheck,
    UpdatesCheck,
    BackupCheck,
    ZigbeeCheck,
)

ALL_KEYS: tuple[str, ...] = tuple(key for check in CHECKS for key in check.keys)

__all__ = ["ALL_KEYS", "CHECKS", "BaseCheck"]
