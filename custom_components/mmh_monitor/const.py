"""Constants for the MMH Monitor integration."""

from __future__ import annotations

import re
from typing import Final

DOMAIN: Final = "mmh_monitor"

CONF_SITE_SLUG: Final = "site_slug"

SITE_SLUG_PATTERN: Final = re.compile(r"^[a-z0-9_-]+$")
