"""Constants for Saxo Portfolio integration."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Final


def _get_version_from_manifest() -> str:
    """Read version from manifest.json."""
    try:
        manifest_path = Path(__file__).parent / "manifest.json"
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
            return manifest.get("version", "0.0.0")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
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
DEFAULT_CURRENCY: Final = "USD"

# Rate limiting
API_RATE_LIMIT_PER_MINUTE: Final = 120
API_RATE_LIMIT_WINDOW: Final = 60  # seconds
MAX_RETRIES: Final = 3
RETRY_BACKOFF_FACTOR: Final = 2

# Market hours (Eastern Time)
MARKET_OPEN_HOUR: Final = 9
MARKET_OPEN_MINUTE: Final = 30
MARKET_CLOSE_HOUR: Final = 16
MARKET_CLOSE_MINUTE: Final = 0

# Weekdays (Monday = 0, Sunday = 6)
MARKET_WEEKDAYS: Final = [0, 1, 2, 3, 4]  # Monday through Friday

# Timezone configuration
CONF_TIMEZONE: Final = "timezone"
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
    "Europe/Frankfurt": "Frankfurt (XETRA)",
    "Asia/Tokyo": "Tokyo (TSE)",
    "Asia/Hong_Kong": "Hong Kong (HKEX)",
    "Asia/Singapore": "Singapore (SGX)",
    "Australia/Sydney": "Sydney (ASX)",
    "any": "Any - Disable intelligent scheduling",
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
    "Europe/Frankfurt": {
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

# Update interval for "any" timezone (no intelligent scheduling)
DEFAULT_UPDATE_INTERVAL_ANY: Final = timedelta(minutes=15)

# Performance data update interval (less frequent since performance changes slowly)
# Increased to 2 hours to reduce API calls and prevent rate limiting
PERFORMANCE_UPDATE_INTERVAL: Final = timedelta(hours=2)


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
# Data storage keys
DATA_COORDINATOR: Final = "coordinator"
DATA_UNSUB: Final = "unsub"

# Services
SERVICE_REFRESH_DATA: Final = "refresh_data"

# Token management
TOKEN_REFRESH_BUFFER: Final = timedelta(
    minutes=5
)  # Refresh token 5 minutes before expiry
TOKEN_MIN_VALIDITY: Final = timedelta(minutes=10)  # Minimum time token should be valid
REFRESH_TOKEN_BUFFER: Final = timedelta(
    minutes=5
)  # Proactively refresh when refresh token has less than 5 minutes left

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
]

# Diagnostics redaction placeholder
DIAGNOSTICS_REDACTED: Final = "**REDACTED**"
