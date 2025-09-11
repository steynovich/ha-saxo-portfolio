"""Constants for Saxo Portfolio integration."""

from datetime import timedelta
from typing import Final

# Integration identity
DOMAIN: Final = "saxo_portfolio"
INTEGRATION_NAME: Final = "Saxo Portfolio"
INTEGRATION_VERSION: Final = "1.0.0"

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
PLATFORMS: Final = ["sensor"]
# Data storage keys
DATA_COORDINATOR: Final = "coordinator"
DATA_UNSUB: Final = "unsub"

# Token management
TOKEN_REFRESH_BUFFER: Final = timedelta(
    minutes=5
)  # Refresh token 5 minutes before expiry
TOKEN_MIN_VALIDITY: Final = timedelta(minutes=10)  # Minimum time token should be valid

# API timeouts
API_TIMEOUT_CONNECT: Final = 10  # seconds
API_TIMEOUT_READ: Final = 30  # seconds
API_TIMEOUT_TOTAL: Final = 45  # seconds

# Coordinator configuration
COORDINATOR_UPDATE_TIMEOUT: Final = 30  # seconds

# Security patterns for sensitive data masking
SENSITIVE_URL_PATTERNS: Final = [
    r"(token=)[^&\s]*",  # token parameters
    r"(access_token=)[^&\s]*",  # access token parameters
    r"(Authorization:\s*Bearer\s+)[^\s]*",  # authorization headers
    r"(app_key=)[^&\s]*",  # app key parameters
    r"(app_secret=)[^&\s]*",  # app secret parameters
]
