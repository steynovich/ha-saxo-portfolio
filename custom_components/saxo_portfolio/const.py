"""Constants for Saxo Portfolio integration."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Final


def _get_version_from_manifest() -> str:
    """Read version from manifest.json."""
    try:
        manifest_path = Path(__file__).parent / "manifest.json"
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
            return str(manifest.get("version", "0.0.0"))
    except FileNotFoundError, json.JSONDecodeError, KeyError:
        return "0.0.0"


# Integration identity
DOMAIN: Final = "saxo_portfolio"
INTEGRATION_NAME: Final = "Saxo Portfolio"
INTEGRATION_VERSION: Final = _get_version_from_manifest()

# Saxo API endpoints - Production only
SAXO_API_BASE_URL: Final = "https://gateway.saxobank.com/openapi"
SAXO_AUTH_BASE_URL: Final = "https://live.logonvalidation.net"

# OAuth endpoints
OAUTH_AUTHORIZE_ENDPOINT: Final = "/authorize"
OAUTH_TOKEN_ENDPOINT: Final = "/token"

# API endpoints
API_BALANCE_ENDPOINT: Final = "/port/v1/balances/me"
API_CLIENT_DETAILS_ENDPOINT: Final = "/port/v1/clients/me"
API_PERFORMANCE_ENDPOINT: Final = "/hist/v3/perf/"
API_PERFORMANCE_V4_ENDPOINT: Final = "/hist/v4/performance/timeseries"
API_NET_POSITIONS_ENDPOINT: Final = "/port/v1/netpositions/me"


# Default configuration
DEFAULT_UPDATE_INTERVAL_MARKET_HOURS: Final = timedelta(minutes=5)
DEFAULT_UPDATE_INTERVAL_AFTER_HOURS: Final = timedelta(minutes=30)
DEFAULT_TIMEOUT: Final = 30  # seconds

# Sticky availability (docs/adr/0002): sensors go unavailable after
# max(FLOOR, MULTIPLIER x update interval) of consecutive failures
AVAILABILITY_FAILURE_FLOOR: Final = timedelta(minutes=15)
AVAILABILITY_FAILURE_INTERVAL_MULTIPLIER: Final = 3
AVAILABILITY_FALLBACK_UPDATE_INTERVAL: Final = DEFAULT_UPDATE_INTERVAL_MARKET_HOURS
DEFAULT_CURRENCY: Final = "USD"

# Rate limiting
API_RATE_LIMIT_PER_MINUTE: Final = 120
API_RATE_LIMIT_WINDOW: Final = 60  # seconds
# Delay between consecutive batched API calls to avoid request bursts
API_REQUEST_DELAY: Final = 0.5  # seconds
MAX_RETRIES: Final = 3
RETRY_BACKOFF_FACTOR: Final = 2
DEFAULT_RETRY_AFTER_SECONDS: Final = 60  # when a 429 has no usable Retry-After
RETRY_AFTER_MAX_SECONDS: Final = 300  # cap on a single 429 wait

# Default access-token lifetime when the token carries no expires_in
TOKEN_DEFAULT_EXPIRES_IN: Final = 1200  # seconds

# Coordinator internals
MARKET_HOURS_CACHE_TTL: Final = 1.0  # seconds a market-hours check stays cached
TIMEOUT_WARNING_THROTTLE: Final = 300  # seconds between repeated timeout warnings
STARTUP_SUCCESSFUL_UPDATES: Final = 3  # successful updates that end the startup phase
INITIAL_UPDATE_STAGGER_MAX: Final = 30  # seconds, max random start offset per account

# Market hours (Eastern Time)
MARKET_OPEN_HOUR: Final = 9
MARKET_OPEN_MINUTE: Final = 30
MARKET_CLOSE_HOUR: Final = 16
MARKET_CLOSE_MINUTE: Final = 0

# Weekdays (Monday = 0, Sunday = 6)
MARKET_WEEKDAYS: Final = [0, 1, 2, 3, 4]  # Monday through Friday

# Timezone configuration
CONF_TIMEZONE: Final = "timezone"
# Timezone option that disables market-hours-aware scheduling
TIMEZONE_ANY: Final = "any"
DEFAULT_TIMEZONE: Final = "America/New_York"

# Position sensors configuration
CONF_ENABLE_POSITION_SENSORS: Final = "enable_position_sensors"
DEFAULT_ENABLE_POSITION_SENSORS: Final = False

# Available timezones for market hours detection
TIMEZONE_OPTIONS: Final = {
    "America/New_York": "New York (NYSE/NASDAQ)",
    "Europe/London": "London (LSE)",
    "Europe/Amsterdam": "Amsterdam (Euronext)",
    "Europe/Paris": "Paris (Euronext)",
    "Europe/Berlin": "Frankfurt (XETRA)",
    "Asia/Tokyo": "Tokyo (TSE)",
    "Asia/Hong_Kong": "Hong Kong (HKEX)",
    "Asia/Singapore": "Singapore (SGX)",
    "Australia/Sydney": "Sydney (ASX)",
    TIMEZONE_ANY: "Any - Disable intelligent scheduling",
}

# Market hours per timezone (local time)
MARKET_HOURS: Final = {
    "America/New_York": {
        "open": (9, 30),
        "close": (16, 0),
        "weekdays": [0, 1, 2, 3, 4],
    },
    "Europe/London": {
        "open": (8, 0),
        "close": (16, 30),
        "weekdays": [0, 1, 2, 3, 4],
    },
    "Europe/Amsterdam": {
        "open": (9, 0),
        "close": (17, 30),
        "weekdays": [0, 1, 2, 3, 4],
    },
    "Europe/Paris": {
        "open": (9, 0),
        "close": (17, 30),
        "weekdays": [0, 1, 2, 3, 4],
    },
    "Europe/Berlin": {
        "open": (9, 0),
        "close": (17, 30),
        "weekdays": [0, 1, 2, 3, 4],
    },
    "Asia/Tokyo": {
        "open": (9, 0),
        "close": (15, 0),
        "weekdays": [0, 1, 2, 3, 4],
    },
    "Asia/Hong_Kong": {
        "open": (9, 30),
        "close": (16, 0),
        "weekdays": [0, 1, 2, 3, 4],
    },
    "Asia/Singapore": {
        "open": (9, 0),
        "close": (17, 0),
        "weekdays": [0, 1, 2, 3, 4],
    },
    "Australia/Sydney": {
        "open": (10, 0),
        "close": (16, 0),
        "weekdays": [0, 1, 2, 3, 4],
    },
}


# Update-mode labels shown in the update-configuration sensor attributes
UPDATE_MODE_FIXED: Final = "Fixed interval"
UPDATE_MODE_MARKET_HOURS: Final = "Market hours detection"
UPDATE_MODE_UNKNOWN: Final = "Unknown configuration"


def market_hours_attributes(timezone: str) -> dict[str, Any]:
    """Return open/close/trading-day attributes for a MARKET_HOURS timezone."""
    info = MARKET_HOURS[timezone]
    open_h, open_m = info["open"]
    close_h, close_m = info["close"]
    return {
        "market_open": f"{open_h:02d}:{open_m:02d}",
        "market_close": f"{close_h:02d}:{close_m:02d}",
        "trading_days": info["weekdays"],
    }


# Update interval for "any" timezone (no intelligent scheduling)
DEFAULT_UPDATE_INTERVAL_ANY: Final = timedelta(minutes=15)

# Performance data update interval (less frequent since performance changes slowly)
# Increased to 2 hours to reduce API calls and prevent rate limiting
PERFORMANCE_UPDATE_INTERVAL: Final = timedelta(hours=2)

# Minimum wait before re-requesting performance data after an incomplete fetch,
# so a permanently failing endpoint costs API calls every 15 min, not every poll
PERFORMANCE_RETRY_INTERVAL: Final = timedelta(minutes=15)

# Spans of Saxo's trailing StandardPeriod windows. These are rolling windows
# ending at the last completed day, not calendar month/quarter-to-date
# (observed against /hist/v4/performance/timeseries; Saxo does not document
# the exact span). See docs/superpowers/specs/2026-08-04-ytd-sensors-design.md.
STANDARD_PERIOD_MONTH_SPAN: Final = timedelta(days=28)
STANDARD_PERIOD_QUARTER_SPAN: Final = timedelta(days=90)


# Configuration flow
CONF_ENTITY_PREFIX: Final = "entity_prefix"

# Default values
DEFAULT_ENTITY_PREFIX: Final = "saxo"

# Entity configuration
ATTRIBUTION: Final = "Data provided by Saxo Bank"
DEVICE_MANUFACTURER: Final = "Saxo Bank"
DEVICE_MODEL: Final = "OpenAPI"

# Error messages
ERROR_AUTH_FAILED: Final = "Authentication failed. Please reconfigure the integration."
ERROR_RATE_LIMITED: Final = "API rate limit exceeded. Please wait before retrying."
ERROR_NETWORK_ERROR: Final = "Network error occurred while fetching data."


# Home Assistant specific
PLATFORMS: Final = ["button", "sensor"]
# Services
SERVICE_REFRESH_DATA: Final = "refresh_data"

# Token management
TOKEN_REFRESH_TIMEOUT: Final = 15  # seconds - conservative to leave budget for data fetching within 60s coordinator timeout
OAUTH_TERMINAL_TOKEN_ERRORS: Final = frozenset(
    {"invalid_grant", "invalid_client"}
)  # credentials/refresh token are dead

TOKEN_REFRESH_BUFFER: Final = timedelta(
    minutes=5
)  # Refresh token 5 minutes before expiry
TOKEN_MIN_VALIDITY: Final = timedelta(minutes=10)  # Minimum time token should be valid
REFRESH_TOKEN_BUFFER: Final = timedelta(
    minutes=5
)  # Proactively refresh when refresh token has less than 5 minutes left
# Force a token refresh once this fraction of the refresh-token lifetime has elapsed,
# regardless of whether the access token is about to expire. This keeps the refresh
# token "young" so Saxo outages up to (1 - fraction) * refresh_token_expires_in can
# be survived without forcing the user to reauthenticate.
REFRESH_TOKEN_REFRESH_AT_FRACTION: Final = 0.5

# API timeouts
API_TIMEOUT_CONNECT: Final = 10  # seconds
API_TIMEOUT_READ: Final = 30  # seconds
API_TIMEOUT_TOTAL: Final = 45  # seconds

# Coordinator configuration
COORDINATOR_UPDATE_TIMEOUT: Final = (
    60  # seconds - enough for multiple sequential API calls
)

# Performance data fetch timeout (separate from coordinator to allow graceful degradation)
# If performance fetch times out, balance data is still returned successfully
PERFORMANCE_FETCH_TIMEOUT: Final = 30  # seconds

# Security patterns for sensitive data masking
SENSITIVE_URL_PATTERNS: Final = [
    r"(token=)[^&\s]*",  # token parameters
    r"(access_token=)[^&\s]*",  # access token parameters
    r"(Authorization:\s*Bearer\s+)[^\s]*",  # authorization headers
    r"(app_key=)[^&\s]*",  # app key parameters
    r"(app_secret=)[^&\s]*",  # app secret parameters
    r"(ClientKey=)[^&\s]*",  # client key query parameters
    r"(AccountKey=)[^&\s]*",  # account key query parameters
    r"(/hist/v3/perf/)[^/?&\s]+",  # client key embedded in the v3 perf path
]

# Diagnostics redaction placeholder
DIAGNOSTICS_REDACTED: Final = "**REDACTED**"
