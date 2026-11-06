"""Coordinator that runs the health checks and publishes the results."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import CALLBACK_TYPE, CoreState, Event, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .checks import CHECKS, BaseCheck
from .const import (
    CONF_INFLUX_BUCKET,
    CONF_INFLUX_ORG,
    CONF_INFLUX_TOKEN,
    CONF_INFLUX_URL,
    CONF_KUMA_DOWN_ON_CRITICAL,
    CONF_KUMA_PUSH_URL,
    CONF_SCAN_INTERVAL,
    CONF_SITE_SLUG,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    STARTUP_GRACE,
)
from .models import CheckResult, HealthLevel, MonitorData, PublishStatus, worst_level
from .publisher import (
    FailureLogger,
    PublishError,
    async_push_kuma,
    async_write_influx,
    build_lines,
)
from .repairs import RepairManager
from .thresholds import ThresholdManager

_LOGGER = logging.getLogger(__name__)

type MMHMonitorConfigEntry = ConfigEntry[MMHMonitorCoordinator]


class MMHMonitorCoordinator(DataUpdateCoordinator[MonitorData]):
    """Run all checks every cycle and push the results to the central services."""

    config_entry: MMHMonitorConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MMHMonitorConfigEntry,
        version: str,
        threshold_manager: ThresholdManager,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.version = version
        self.site: str = entry.data[CONF_SITE_SLUG]
        self.checks: list[BaseCheck] = [cls(hass, entry) for cls in CHECKS]
        self.threshold_manager = threshold_manager
        self.repairs = RepairManager(hass)
        self.publish_status = PublishStatus()
        self._session = async_get_clientsession(hass)
        self._influx_log = FailureLogger("InfluxDB")
        self._kuma_log = FailureLogger("Uptime Kuma")
        # True until HA has started and the grace period has passed. When the
        # integration is set up on a running HA (install, reload), there is no
        # startup to wait for.
        self.starting = hass.state is not CoreState.running
        self._unsub_started: CALLBACK_TYPE | None = None
        self._unsub_grace: CALLBACK_TYPE | None = None
        if self.starting:
            self._unsub_started = hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._async_ha_started
            )

    @callback
    def _async_ha_started(self, _event: Event) -> None:
        self._unsub_started = None  # a fired one-time listener must not be removed
        self._unsub_grace = async_call_later(
            self.hass, STARTUP_GRACE, self._async_grace_over
        )

    async def _async_grace_over(self, _now: Any) -> None:
        self._unsub_grace = None
        self.starting = False
        await self.async_request_refresh()

    async def async_setup_checks(self) -> None:
        """Set up every check."""
        for check in self.checks:
            await check.async_setup()

    async def async_shutdown(self) -> None:
        """Shut down the checks and the coordinator."""
        for check in self.checks:
            try:
                await check.async_shutdown()
            except Exception:  # noqa: BLE001 - shutdown must not fail unload
                _LOGGER.debug("Error shutting down %s", type(check).__name__, exc_info=True)
        for unsub in (self._unsub_started, self._unsub_grace):
            if unsub:
                unsub()
        self._unsub_started = self._unsub_grace = None
        self.threshold_manager.async_shutdown()
        self.repairs.async_clear()
        await super().async_shutdown()

    async def _async_update_data(self) -> MonitorData:
        """Run the checks and publish. Never raises for check or network errors."""
        data = await self._async_run_checks()
        self.repairs.async_update(data)
        await self._async_publish(data)
        return data

    async def _async_run_checks(self) -> MonitorData:
        results: dict[str, CheckResult] = {}
        for check in self.checks:
            if self.starting and check.wait_for_startup:
                for result in check.unmonitored("Aguardando o Home Assistant estabilizar após o início"):
                    results[result.key] = result
                continue
            try:
                check_results = await check.async_run(self.threshold_manager.current)
            except Exception:  # noqa: BLE001 - one check must not break the others
                _LOGGER.warning(
                    "Check %s failed; reporting it as not monitored",
                    type(check).__name__,
                    exc_info=True,
                )
                check_results = check.unmonitored("Falha ao executar a checagem")
            for result in check_results:
                results[result.key] = result

        level = worst_level(list(results.values()))
        reasons = [
            r.message
            for r in results.values()
            if r.level in (HealthLevel.ATENCAO, HealthLevel.CRITICO)
        ]
        message = "; ".join(reasons) if reasons else "Tudo OK"
        return MonitorData(
            results=results,
            level=level,
            message=message,
            collected_at=dt_util.utcnow(),
        )

    async def _async_publish(self, data: MonitorData) -> None:
        """Send to InfluxDB and Uptime Kuma independently of each other."""
        await asyncio.gather(self._async_publish_influx(data), self._async_publish_kuma(data))

    async def _async_publish_influx(self, data: MonitorData) -> None:
        entry_data = self.config_entry.data
        lines = build_lines(
            data, site=self.site, version=self.version, ha_version=HA_VERSION
        )
        status = self.publish_status
        try:
            await async_write_influx(
                self._session,
                url=entry_data[CONF_INFLUX_URL],
                org=entry_data[CONF_INFLUX_ORG],
                bucket=entry_data[CONF_INFLUX_BUCKET],
                token=entry_data[CONF_INFLUX_TOKEN],
                lines=lines,
            )
        except PublishError as err:
            status.influx_ok = False
            status.influx_last_error = str(err)
            self._influx_log.failure(str(err))
        except Exception:  # noqa: BLE001 - network issues must never affect HA
            status.influx_ok = False
            status.influx_last_error = "unexpected error"
            _LOGGER.exception("Unexpected error sending to InfluxDB")
        else:
            status.influx_ok = True
            status.influx_last_error = None
            status.influx_last_success = dt_util.utcnow()
            self._influx_log.success()

    async def _async_publish_kuma(self, data: MonitorData) -> None:
        push_url = self.config_entry.data.get(CONF_KUMA_PUSH_URL)
        if not push_url:
            return
        down = (
            self.config_entry.options.get(CONF_KUMA_DOWN_ON_CRITICAL, False)
            and data.level is HealthLevel.CRITICO
        )
        message = f"{data.level.state}: {data.message}" if down else data.level.state
        status = self.publish_status
        try:
            await async_push_kuma(
                self._session, push_url=push_url, up=not down, message=message
            )
        except PublishError as err:
            status.kuma_ok = False
            status.kuma_last_error = str(err)
            self._kuma_log.failure(str(err))
        except Exception:  # noqa: BLE001 - network issues must never affect HA
            status.kuma_ok = False
            status.kuma_last_error = "unexpected error"
            _LOGGER.exception("Unexpected error sending to Uptime Kuma")
        else:
            status.kuma_ok = True
            status.kuma_last_error = None
            self._kuma_log.success()
