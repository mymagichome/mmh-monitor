"""Base class for health checks."""

from __future__ import annotations

from abc import ABC, abstractmethod

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..models import CheckResult, HealthLevel
from ..thresholds import Threshold


class BaseCheck(ABC):
    """A health check producing one or more results per cycle.

    Checks only read state; they must never change anything in Home Assistant.
    """

    #: Result keys this check produces. Used to report every key as
    #: unmonitored when the check raises.
    keys: tuple[str, ...] = ()

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the check."""
        self.hass = hass
        self.entry = entry

    async def async_setup(self) -> None:  # noqa: B027 - optional hook
        """Prepare the check (e.g. subscribe to events). Optional."""

    async def async_shutdown(self) -> None:  # noqa: B027 - optional hook
        """Release resources acquired in async_setup. Optional."""

    @abstractmethod
    async def async_run(self, thresholds: dict[str, Threshold]) -> list[CheckResult]:
        """Run the check and return its results."""

    def unmonitored(self, message: str) -> list[CheckResult]:
        """Return an unmonitored result for every key of this check."""
        return [
            CheckResult(
                key=key,
                value=None,
                unit=None,
                level=HealthLevel.NAO_MONITORADO,
                message=message,
            )
            for key in self.keys
        ]
