"""Constants for Saxo Portfolio integration."""

from datetime import timedelta
from typing import Final

# Integration identity
DOMAIN: Final = "saxo_portfolio"
INTEGRATION_NAME: Final = "Saxo Portfolio"
INTEGRATION_VERSION: Final = "1.0.0"

# Saxo API endpoints
SAXO_SIMULATION_BASE_URL: Final = "https://gateway.saxobank.com/sim/openapi"
SAXO_PRODUCTION_BASE_URL: Final = "https://gateway.saxobank.com/openapi"
SAXO_AUTH_SIMULATION_BASE_URL: Final = "https://sim.logonvalidation.net"
SAXO_AUTH_PRODUCTION_BASE_URL: Final = "https://logonvalidation.net"

# OAuth endpoints
OAUTH_AUTHORIZE_ENDPOINT: Final = "/authorize"
OAUTH_TOKEN_ENDPOINT: Final = "/token"

# API endpoints
API_BALANCE_ENDPOINT: Final = "/port/v1/balances/me"
API_POSITIONS_ENDPOINT: Final = "/port/v1/positions"
API_ACCOUNTS_ENDPOINT: Final = "/port/v1/accounts"

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

# Sensor configuration
SENSOR_TYPES: Final = {
    "total_value": {
        "name": "Portfolio Total Value",
        "unit": None,  # Will use currency code
        "device_class": None,  # Avoid device_class + state_class conflict
        "state_class": "measurement",
        "icon": "mdi:chart-line",
        "entity_category": None,
    },
    "cash_balance": {
        "name": "Portfolio Cash Balance",
        "unit": None,  # Will use currency code
        "device_class": "monetary",
        "state_class": None,  # monetary device_class cannot have state_class
        "icon": "mdi:cash",
        "entity_category": None,
    },
    "unrealized_pnl": {
        "name": "Portfolio Unrealized P&L",
        "unit": None,  # Will use currency code
        "device_class": None,
        "state_class": "measurement",
        "icon": "mdi:trending-up",
        "entity_category": None,
    },
    "positions_count": {
        "name": "Portfolio Positions Count",
        "unit": "positions",
        "device_class": None,
        "state_class": "measurement",
        "icon": "mdi:format-list-numbered",
        "entity_category": None,
    },
    "pnl_percentage": {
        "name": "Portfolio P&L Percentage",
        "unit": "%",
        "device_class": None,
        "state_class": "measurement",
        "icon": "mdi:percent",
        "entity_category": None,
    },
}

# Account sensor configuration
ACCOUNT_SENSOR_TYPES: Final = {
    "balance": {
        "name": "Account Balance",
        "unit": None,  # Will use currency code
        "device_class": "monetary",
        "state_class": None,
        "icon": "mdi:bank",
        "entity_category": None,
    }
}

# Position sensor configuration
POSITION_SENSOR_TYPES: Final = {
    "value": {
        "name": "Position Value",
        "unit": None,  # Will use currency code
        "device_class": None,
        "state_class": "measurement",
        "icon": "mdi:cash-multiple",
        "entity_category": None,
    },
    "pnl": {
        "name": "Position P&L",
        "unit": None,  # Will use currency code
        "device_class": None,
        "state_class": "measurement",
        "icon": "mdi:trending-up",
        "entity_category": None,
    },
}

# Configuration flow
CONF_ENVIRONMENT: Final = "environment"
CONF_APP_KEY: Final = "app_key"
CONF_APP_SECRET: Final = "app_secret"

# Environment options
ENV_SIMULATION: Final = "simulation"
ENV_PRODUCTION: Final = "production"

ENVIRONMENTS: Final = {
    ENV_SIMULATION: {
        "name": "Simulation",
        "api_base_url": SAXO_SIMULATION_BASE_URL,
        "auth_base_url": SAXO_AUTH_SIMULATION_BASE_URL,
    },
    ENV_PRODUCTION: {
        "name": "Production",
        "api_base_url": SAXO_PRODUCTION_BASE_URL,
        "auth_base_url": SAXO_AUTH_PRODUCTION_BASE_URL,
    },
}

# Entity configuration
ATTRIBUTION: Final = "Data provided by Saxo Bank"
DEVICE_MANUFACTURER: Final = "Saxo Bank"
DEVICE_MODEL: Final = "OpenAPI"

# Error messages
ERROR_AUTH_FAILED: Final = "Authentication failed. Please reconfigure the integration."
ERROR_API_UNAVAILABLE: Final = "Saxo API is currently unavailable."
ERROR_RATE_LIMITED: Final = "API rate limit exceeded. Please wait before retrying."
ERROR_INVALID_CONFIG: Final = "Invalid configuration. Please check your settings."
ERROR_NETWORK_ERROR: Final = "Network error occurred while fetching data."

# Configuration validation
VALID_ASSET_TYPES: Final = ["FxSpot", "Stock", "Bond", "Option", "Future"]
VALID_ACCOUNT_TYPES: Final = ["Normal", "Margin", "ISA", "SIPP"]
VALID_POSITION_STATUSES: Final = ["Open", "Closed", "Pending"]

# Home Assistant specific
PLATFORMS: Final = ["sensor"]
UNDO_UPDATE_LISTENER: Final = "undo_update_listener"

# Data storage keys
DATA_COORDINATOR: Final = "coordinator"
DATA_UNSUB: Final = "unsub"

# Service names (if implemented)
SERVICE_REFRESH: Final = "refresh_data"

# Diagnostic information
DIAGNOSTICS_REDACTED: Final = "**REDACTED**"

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
COORDINATOR_REQUEST_REFRESH_DELAY: Final = 1  # second

# Logging
LOGGER_NAME: Final = __name__

# Security patterns for sensitive data masking
SENSITIVE_URL_PATTERNS: Final = [
    r"(token=)[^&\s]*",  # token parameters
    r"(access_token=)[^&\s]*",  # access token parameters
    r"(Authorization:\s*Bearer\s+)[^\s]*",  # authorization headers
    r"(app_key=)[^&\s]*",  # app key parameters
    r"(app_secret=)[^&\s]*",  # app secret parameters
]
