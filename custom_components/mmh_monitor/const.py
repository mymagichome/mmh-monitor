"""Constants for the MMH Monitor integration."""

from __future__ import annotations

import re
from typing import Final

DOMAIN: Final = "mmh_monitor"

# Config entry data
CONF_SITE_SLUG: Final = "site_slug"
CONF_INFLUX_URL: Final = "influx_url"
CONF_INFLUX_ORG: Final = "influx_org"
CONF_INFLUX_BUCKET: Final = "influx_bucket"
CONF_INFLUX_TOKEN: Final = "influx_token"
CONF_KUMA_PUSH_URL: Final = "kuma_push_url"
CONF_GATEWAY_URL: Final = "gateway_url"

# Enrollment by code (form field only, never stored)
CONF_ENROLLMENT_CODE: Final = "enrollment_code"
DEFAULT_GATEWAY_URL: Final = "https://mcp.mymagichome.com.br"
ENROLL_TIMEOUT: Final = 30  # seconds

# Options
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_THRESHOLDS_URL: Final = "thresholds_url"
CONF_IGNORED_ENTITIES: Final = "ignored_entities"
CONF_ZIGBEE_ENTITIES: Final = "zigbee_entities"
CONF_BACKUP_ENTITY: Final = "backup_entity"
CONF_KUMA_DOWN_ON_CRITICAL: Final = "kuma_down_on_critical"

DEFAULT_INFLUX_ORG: Final = "mmh"
DEFAULT_INFLUX_BUCKET: Final = "mmh_health"
DEFAULT_SCAN_INTERVAL: Final = 300
MIN_SCAN_INTERVAL: Final = 60
MAX_SCAN_INTERVAL: Final = 3600

SITE_SLUG_PATTERN: Final = re.compile(r"^[a-z0-9_-]+$")

# Network
HTTP_TIMEOUT: Final = 10  # seconds
# Repeated identical network failures are logged at most once per this period.
LOG_REPEAT_INTERVAL: Final = 3600  # seconds

# After Home Assistant reports it has started, checks that depend on other
# integrations wait this long before being evaluated.
STARTUP_GRACE: Final = 300  # seconds

# Limits
MAX_DETAIL_ITEMS: Final = 20
MAX_MESSAGE_LENGTH: Final = 250

# InfluxDB measurements
MEASUREMENT_CHECK: Final = "mmh_check"
MEASUREMENT_HEALTH: Final = "mmh_health"
MEASUREMENT_SETUP: Final = "mmh_monitor_setup"
