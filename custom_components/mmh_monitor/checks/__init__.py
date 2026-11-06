"""Registry of health checks."""

from __future__ import annotations

from .base import BaseCheck
from .integrations import IntegrationsCheck

CHECKS: tuple[type[BaseCheck], ...] = (IntegrationsCheck,)

__all__ = ["CHECKS", "BaseCheck"]
