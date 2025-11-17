"""DataUpdateCoordinator for Saxo Portfolio integration.

This coordinator manages data fetching from the Saxo API and coordinates
updates across all sensors.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, time
import zoneinfo
from typing import Any

import aiohttp
import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api.saxo_client import SaxoApiClient, AuthenticationError, APIError
from .const import (
    CONF_TIMEZONE,
    COORDINATOR_UPDATE_TIMEOUT,
    DEFAULT_TIMEZONE,
    DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
    DEFAULT_UPDATE_INTERVAL_ANY,
    DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
    DOMAIN,
    MARKET_HOURS,
    PERFORMANCE_UPDATE_INTERVAL,
    REFRESH_TOKEN_BUFFER,
    TOKEN_MIN_VALIDITY,
    TOKEN_REFRESH_BUFFER,
)

_LOGGER = logging.getLogger(__name__)


class SaxoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Saxo Portfolio data coordinator."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            config_entry: Configuration entry with OAuth token

        """
        self.config_entry = config_entry
        self._api_client: SaxoApiClient | None = None
        self._last_token_check = datetime.now()
        self._token_refresh_lock = asyncio.Lock()
        self._last_successful_update: datetime | None = None

        # Performance data caching
        self._performance_data_cache: dict[str, Any] = {}
        self._performance_last_updated: datetime | None = None

        # Track if sensors were skipped due to unknown client name
        self._sensors_initialized = False
        # Initialize as unknown - will be updated after first successful refresh
        self._last_known_client_name = "unknown"
        # Track if initial setup is complete (platforms loaded)
        self._setup_complete = False

        # Track startup phase for better error messaging
        self._is_startup_phase = True
        self._successful_updates_count = 0

        # Add random offset for multiple accounts to prevent simultaneous updates
        # This spreads updates across 0-30 seconds to reduce rate limiting risk
        self._initial_update_offset = random.uniform(0, 30)

        # Get configured timezone
        self._timezone = config_entry.data.get(CONF_TIMEZONE, DEFAULT_TIMEZONE)

        # Cache market hours check to avoid repeated calculations
        self._market_hours_cache: bool | None = None
        self._market_hours_cache_time: datetime | None = None

        # Determine initial update interval
        if self._timezone == "any":
            update_interval = DEFAULT_UPDATE_INTERVAL_ANY
        else:
            update_interval = (
                DEFAULT_UPDATE_INTERVAL_MARKET_HOURS
                if self._is_market_hours()
                else DEFAULT_UPDATE_INTERVAL_AFTER_HOURS
            )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            always_update=False,
        )

    @property
    def api_client(self) -> SaxoApiClient:
        """Get or create API client."""
        # Check if we need to recreate the client (token refresh case)
        token_data = self.config_entry.data.get("token", {})
        access_token = token_data.get("access_token")

        if not access_token:
            raise ConfigEntryAuthFailed("No access token available")

        # If client exists but token might have changed, close old client first
        if self._api_client is not None:
            # Simple check: if the current token is different from the client's token
            # we need to recreate the client
            current_token = getattr(self._api_client, "access_token", None)
            if current_token != access_token:
                _LOGGER.debug(
                    "Token changed, closing old API client and creating new one"
                )
                # Store reference to old client and schedule safe closure
                old_client = self._api_client
                self._api_client = None
                # Create task to close the old client safely with error handling
                if old_client:
                    self.hass.async_create_task(self._close_old_client(old_client))

        if self._api_client is None:
            # Debug token details (without exposing the actual token)
            token_type = token_data.get("token_type", "unknown")
            expires_at = token_data.get("expires_at")
            has_refresh_token = bool(token_data.get("refresh_token"))

            if expires_at:
                expires_datetime = datetime.fromtimestamp(expires_at)
                is_expired = datetime.now() > expires_datetime
                _LOGGER.debug(
                    "Token details - type: %s, expires_at: %s, is_expired: %s, has_refresh: %s",
                    token_type,
                    expires_datetime.isoformat(),
                    is_expired,
                    has_refresh_token,
                )
            else:
                _LOGGER.debug(
                    "Token details - type: %s, no expiry info, has_refresh: %s",
                    token_type,
                    has_refresh_token,
                )

            # Get base URL - always use production
            from .const import SAXO_API_BASE_URL

            base_url = SAXO_API_BASE_URL

            _LOGGER.debug(
                "Creating API client for production environment, base_url: %s, token_length: %d",
                base_url,
                len(access_token) if access_token else 0,
            )

            # Don't pass session - let API client create its own with auth headers
            self._api_client = SaxoApiClient(access_token, base_url)

        return self._api_client

    async def _close_old_client(self, client: SaxoApiClient) -> None:
        """Safely close an old API client with proper error handling."""
        try:
            if client:
                _LOGGER.debug("Closing old API client session")
                await client.close()
                _LOGGER.debug("Successfully closed old API client session")
        except Exception as e:
            _LOGGER.warning("Error while closing old API client: %s", e, exc_info=True)

    def _should_update_performance_data(self) -> bool:
        """Check if performance data should be updated based on cache age.

        Returns:
            True if performance data should be fetched (cache is stale or empty)

        """
        if self._performance_last_updated is None:
            # No cached data, should update
            return True

        time_since_last_update = datetime.now() - self._performance_last_updated
        should_update = time_since_last_update >= PERFORMANCE_UPDATE_INTERVAL

        _LOGGER.debug(
            "Performance cache age: %s, should_update: %s",
            time_since_last_update,
            should_update,
        )

        return should_update

    def _is_market_hours(self) -> bool:
        """Check if current time is during market hours.

        Uses caching to avoid repeated calculations within the same second.

        Returns:
            True if market is currently open

        """
        # If timezone is "any", market hours don't apply
        if self._timezone == "any":
            return False

        # Check cache - if we checked within the last second, return cached result
        now = datetime.now()
        if (
            self._market_hours_cache is not None
            and self._market_hours_cache_time is not None
            and (now - self._market_hours_cache_time).total_seconds() < 1.0
        ):
            return self._market_hours_cache

        try:
            # Get current time and convert to configured timezone
            now_utc = dt_util.utcnow()

            # Get market hours for configured timezone
            market_config = MARKET_HOURS.get(self._timezone)
            if not market_config:
                # Fallback to default timezone if not found
                _LOGGER.warning(
                    "Unknown timezone %s, falling back to %s",
                    self._timezone,
                    DEFAULT_TIMEZONE,
                )
                self._timezone = DEFAULT_TIMEZONE
                market_config = MARKET_HOURS[DEFAULT_TIMEZONE]

            # Convert to configured timezone
            tz = zoneinfo.ZoneInfo(self._timezone)
            now_local = now_utc.astimezone(tz)

            # Check if it's a weekday
            if now_local.weekday() not in market_config["weekdays"]:
                is_open = False
            else:
                # Get market hours
                open_hour, open_minute = market_config["open"]
                close_hour, close_minute = market_config["close"]

                market_open = time(open_hour, open_minute)
                market_close = time(close_hour, close_minute)

                current_time = now_local.time()

                is_open = market_open <= current_time <= market_close

            _LOGGER.debug(
                "Market hours check for %s: %s, weekday: %s, is_open: %s",
                self._timezone,
                now_local.time().strftime("%H:%M:%S"),
                now_local.weekday(),
                is_open,
            )

            # Cache the result
            self._market_hours_cache = is_open
            self._market_hours_cache_time = now

            return is_open

        except Exception as e:
            _LOGGER.error("Error checking market hours: %s", type(e).__name__)
            # Default to after-hours if we can't determine market status
            return False

    async def _check_and_refresh_token(self) -> None:
        """Check token expiry and refresh if needed.

        This method checks both refresh token and access token expiry:
        1. First checks if refresh token will expire soon (proactive refresh)
        2. Then checks if access token needs refresh

        This ensures we refresh the access token before the refresh token expires,
        allowing us to get a new refresh token (if Saxo supports refresh token rotation).
        """
        async with self._token_refresh_lock:
            token_data = self.config_entry.data.get("token", {})
            expires_at = token_data.get("expires_at")

            if not expires_at:
                _LOGGER.warning("No token expiry information available")
                return

            current_time = datetime.now()
            expiry_time = datetime.fromtimestamp(expires_at)

            # STEP 1: Check if refresh token will expire soon (CRITICAL)
            # We need to check this FIRST, independently of access token expiry
            refresh_token_expires_in = token_data.get("refresh_token_expires_in")
            if refresh_token_expires_in:
                # Calculate when the refresh token expires
                # Use stored token_issued_at timestamp if available, otherwise calculate from expiry
                token_issued_at_timestamp = token_data.get("token_issued_at")

                if token_issued_at_timestamp:
                    # Use the stored timestamp (most accurate)
                    token_issued_at = datetime.fromtimestamp(token_issued_at_timestamp)
                else:
                    # Fallback: calculate from access token expiry (legacy behavior)
                    token_issued_at = expiry_time - timedelta(
                        seconds=token_data.get("expires_in", 1200)
                    )

                refresh_token_expires_at = token_issued_at + timedelta(
                    seconds=refresh_token_expires_in
                )
                refresh_token_refresh_time = (
                    refresh_token_expires_at - REFRESH_TOKEN_BUFFER
                )

                _LOGGER.debug(
                    "Refresh token expires at %s (will refresh at %s, lifetime: %d seconds)",
                    refresh_token_expires_at.isoformat(),
                    refresh_token_refresh_time.isoformat(),
                    refresh_token_expires_in,
                )

                # Check if refresh token has ALREADY expired
                if current_time >= refresh_token_expires_at:
                    _LOGGER.error(
                        "Refresh token has expired (expired at %s, current time %s). Cannot refresh - reauth required.",
                        refresh_token_expires_at.isoformat(),
                        current_time.isoformat(),
                    )
                    _LOGGER.info(
                        "Please re-authenticate: Go to Settings > Devices & Services > Saxo Portfolio and click the 'Reauthenticate' button"
                    )
                    raise ConfigEntryAuthFailed(
                        "Refresh token expired - please click the reauthentication button in Settings > Devices & Services"
                    )

                # Check if refresh token WILL expire soon (proactive refresh)
                if current_time >= refresh_token_refresh_time:
                    _LOGGER.warning(
                        "Refresh token will expire soon (%s remaining). Proactively refreshing to get new refresh token.",
                        refresh_token_expires_at - current_time,
                    )
                    await self._refresh_oauth_token()
                    self._last_token_check = current_time
                    return  # Done - we refreshed proactively

            # STEP 2: Check if access token needs refresh (normal flow)
            refresh_time = expiry_time - TOKEN_REFRESH_BUFFER

            if current_time >= refresh_time:
                _LOGGER.debug(
                    "Access token needs refresh (expires at %s, refresh buffer %s)",
                    expiry_time.isoformat(),
                    TOKEN_REFRESH_BUFFER,
                )

                # Validate token still has minimum validity
                if current_time >= (expiry_time - TOKEN_MIN_VALIDITY):
                    _LOGGER.debug(
                        "Access token expires very soon, immediate refresh needed"
                    )

                await self._refresh_oauth_token()
                self._last_token_check = current_time

    async def _refresh_oauth_token(self) -> dict[str, Any]:
        """Refresh OAuth access token using refresh token.

        Returns:
            New token data

        Raises:
            ConfigEntryAuthFailed: If token refresh fails

        """
        token_data = self.config_entry.data.get("token", {})
        refresh_token = token_data.get("refresh_token")

        if not refresh_token:
            raise ConfigEntryAuthFailed("No refresh token available")

        # Debug token data structure (with sensitive data masked)
        masked_token_data = {}
        for key, value in token_data.items():
            if key in ["access_token", "refresh_token"]:
                masked_token_data[key] = (
                    f"***{value[-4:]}" if value and len(str(value)) > 4 else "***"
                )
            else:
                masked_token_data[key] = value

        _LOGGER.debug(
            "Starting token refresh: token_data_keys=%s", list(masked_token_data.keys())
        )
        _LOGGER.debug("Token data structure: %s", masked_token_data)

        try:
            # Use production endpoints
            from .const import SAXO_AUTH_BASE_URL, OAUTH_TOKEN_ENDPOINT

            # Prepare refresh request
            token_url = f"{SAXO_AUTH_BASE_URL}{OAUTH_TOKEN_ENDPOINT}"

            # Use Home Assistant's aiohttp session
            session = async_get_clientsession(self.hass)

            # Get client credentials and redirect_uri from OAuth implementation
            auth = None
            redirect_uri = None
            client_id = None
            try:
                from homeassistant.helpers.config_entry_oauth2_flow import (
                    async_get_config_entry_implementation,
                )

                # Get the OAuth implementation from the config entry
                implementation = await async_get_config_entry_implementation(
                    self.hass, self.config_entry
                )
                if implementation:
                    client_id = implementation.client_id
                    auth = aiohttp.BasicAuth(
                        implementation.client_id, implementation.client_secret
                    )
                    _LOGGER.info(
                        "Using HTTP Basic Auth for token refresh with client_id: %s",
                        client_id[:8] + "..." if len(client_id) > 8 else client_id,
                    )

                    # Get the correct redirect_uri from the OAuth implementation
                    # This ensures we use the same redirect_uri that was used during initial authorization
                    if hasattr(implementation, "redirect_uri"):
                        redirect_uri = implementation.redirect_uri
                        _LOGGER.info(
                            "Using redirect_uri from OAuth implementation: %s",
                            redirect_uri,
                        )
                    else:
                        _LOGGER.warning(
                            "OAuth implementation has no redirect_uri property"
                        )
                else:
                    _LOGGER.error("Could not get OAuth implementation for Basic Auth")
            except Exception as e:
                _LOGGER.error(
                    "Failed to get OAuth implementation: %s: %s",
                    type(e).__name__,
                    str(e),
                )

            # Fallback to stored redirect_uri if we couldn't get it from implementation
            if not redirect_uri:
                redirect_uri = self.config_entry.data.get("redirect_uri")
                if redirect_uri:
                    _LOGGER.info(
                        "Using redirect_uri from config entry: %s", redirect_uri
                    )
                else:
                    _LOGGER.error(
                        "No redirect_uri found in OAuth implementation or config entry. This will likely cause token refresh to fail."
                    )
                    _LOGGER.error(
                        "Please reconfigure the integration or check your Saxo application redirect_uri configuration."
                    )

            # Build refresh request data
            # According to Saxo documentation, we need: grant_type, refresh_token, redirect_uri
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }

            # Only add redirect_uri if we have one
            if redirect_uri:
                refresh_data["redirect_uri"] = redirect_uri
                _LOGGER.info("Token refresh will use redirect_uri: %s", redirect_uri)
            else:
                _LOGGER.warning("Token refresh without redirect_uri (may fail)")

            # Log client_id being used (for debugging auth issues)
            if client_id:
                _LOGGER.info(
                    "Token refresh using client_id: %s",
                    client_id[:8] + "..." if len(client_id) > 8 else client_id,
                )
            else:
                _LOGGER.error("No client_id available for token refresh")

            # Debug logging with masked sensitive data
            masked_data = refresh_data.copy()
            if "refresh_token" in masked_data:
                masked_data["refresh_token"] = (
                    f"***{masked_data['refresh_token'][-4:]}"
                    if len(masked_data["refresh_token"]) > 4
                    else "***"
                )
            if "client_secret" in masked_data:
                masked_data["client_secret"] = "***MASKED***"

            _LOGGER.debug(
                "Token refresh request: URL=%s, has_basic_auth=%s, headers=%s, data=%s",
                token_url,
                auth is not None,
                {"Content-Type": "application/x-www-form-urlencoded"},
                masked_data,
            )

            # Token refresh requests should use application/x-www-form-urlencoded
            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            async with session.post(
                token_url, data=refresh_data, headers=headers, auth=auth
            ) as response:
                _LOGGER.debug(
                    "Token refresh response: status=%d, headers=%s",
                    response.status,
                    dict(response.headers),
                )

                if response.status in [200, 201]:  # Accept both 200 OK and 201 Created
                    new_token_data = await response.json()

                    # Calculate expiry time and store when token was issued
                    current_timestamp = datetime.now().timestamp()
                    expires_in = new_token_data.get("expires_in", 1200)
                    expires_at = current_timestamp + expires_in
                    new_token_data["expires_at"] = expires_at
                    new_token_data["token_issued_at"] = current_timestamp

                    # Preserve any existing data from original token (like redirect_uri)
                    # Saxo may provide a new refresh_token, so we use the response data
                    new_data = self.config_entry.data.copy()

                    # Update with new token data while preserving config data
                    if "token" in new_data:
                        # Keep any non-token config data, update token data
                        new_data["token"] = new_token_data
                    else:
                        new_data["token"] = new_token_data

                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=new_data
                    )

                    # Close old API client before forcing recreation with new token
                    if self._api_client is not None:
                        old_client = self._api_client
                        self._api_client = None
                        # Close old client in background to avoid blocking
                        self.hass.async_create_task(self._close_old_client(old_client))
                    else:
                        self._api_client = None  # Force recreation with new token

                    # Store refresh success info with debug details
                    token_expires = datetime.fromtimestamp(new_token_data["expires_at"])
                    _LOGGER.info(
                        "Successfully refreshed OAuth token (expires: %s)",
                        token_expires.isoformat(),
                    )

                    # Debug log new token data structure (with sensitive data masked)
                    masked_new_token_data = {}
                    for key, value in new_token_data.items():
                        if key in ["access_token", "refresh_token"]:
                            masked_new_token_data[key] = (
                                f"***{value[-4:]}"
                                if value and len(str(value)) > 4
                                else "***"
                            )
                        else:
                            masked_new_token_data[key] = value
                    _LOGGER.debug("New token data structure: %s", masked_new_token_data)

                    return new_token_data
                else:
                    error_text = await response.text()
                    _LOGGER.error(
                        "Token refresh failed: HTTP %d - %s",
                        response.status,
                        error_text[:500] if error_text else "No error details",
                    )

                    # Provide helpful guidance for 401 errors
                    if response.status == 401:
                        _LOGGER.error(
                            "401 Unauthorized error during token refresh. Possible causes:"
                        )
                        _LOGGER.error(
                            "1. redirect_uri mismatch: The redirect_uri used (%s) may not match what's configured in your Saxo application",
                            redirect_uri if redirect_uri else "NONE",
                        )
                        _LOGGER.error(
                            "2. Invalid client credentials: Check that your Saxo App Key and App Secret are correct in Application Credentials"
                        )
                        _LOGGER.error(
                            "3. Try reconfiguring the integration: Go to Settings > Devices & Services > Saxo Portfolio > Configure"
                        )

                    raise ConfigEntryAuthFailed("Failed to refresh access token")

        except Exception as e:
            _LOGGER.error("Error refreshing token: %s", type(e).__name__)
            raise ConfigEntryAuthFailed("Token refresh error")

    async def _fetch_portfolio_data(self) -> dict[str, Any]:
        """Fetch portfolio data from Saxo API.

        Returns:
            Portfolio data dictionary

        Raises:
            ConfigEntryAuthFailed: For authentication errors
            UpdateFailed: For other errors

        """
        try:
            # Apply staggered update offset on first update to prevent multiple accounts
            # from hitting the API simultaneously
            if self._initial_update_offset > 0:
                _LOGGER.debug(
                    "Applying initial update offset of %.1fs to stagger multiple accounts",
                    self._initial_update_offset,
                )
                await asyncio.sleep(self._initial_update_offset)
                self._initial_update_offset = 0  # Only apply once

            # Check and refresh token if needed
            await self._check_and_refresh_token()

            # Get API client
            client = self.api_client

            _LOGGER.debug(
                "Starting data fetch with client base_url: %s (production)",
                client.base_url,
            )

            # Validate we're using the expected production URL
            expected_base_url = "https://gateway.saxobank.com/openapi"
            if client.base_url != expected_base_url:
                _LOGGER.error(
                    "API client base URL mismatch! Expected: %s, Got: %s",
                    expected_base_url,
                    client.base_url,
                )

            _LOGGER.debug(
                "About to fetch balance from: %s%s",
                client.base_url,
                "/port/v1/balances/me",
            )

            # Fetch balance data only
            fetch_start_time = datetime.now()
            async with async_timeout.timeout(COORDINATOR_UPDATE_TIMEOUT):
                # Get balance data (only required endpoint)
                balance_start_time = datetime.now()
                balance_data = await client.get_account_balance()

                balance_duration = (datetime.now() - balance_start_time).total_seconds()
                _LOGGER.debug("Balance data fetch completed in %.2fs", balance_duration)
                _LOGGER.debug(
                    "Balance data keys: %s",
                    list(balance_data.keys()) if balance_data else "No balance data",
                )

                # Check if balance data contains any date fields that might be inception-related
                if balance_data:
                    date_fields = [
                        key
                        for key in balance_data
                        if any(
                            date_word in key.lower()
                            for date_word in [
                                "date",
                                "day",
                                "inception",
                                "created",
                                "start",
                            ]
                        )
                    ]
                    if date_fields:
                        _LOGGER.debug(
                            "Balance data contains potential date fields: %s",
                            {field: balance_data[field] for field in date_fields},
                        )

                # Remove detailed margin info to reduce log noise
                if "MarginCollateralNotAvailableDetail" in balance_data:
                    del balance_data["MarginCollateralNotAvailableDetail"]

                # Try to fetch client details and performance data
                ytd_earnings_percentage = 0.0
                investment_performance_percentage = 0.0
                ytd_investment_performance_percentage = 0.0
                month_investment_performance_percentage = 0.0
                quarter_investment_performance_percentage = 0.0
                cash_transfer_balance = 0.0
                client_id = "unknown"
                account_id = "unknown"
                client_name = "unknown"

                # Check if we should update performance data or use cached values
                should_update_performance = self._should_update_performance_data()

                if should_update_performance:
                    _LOGGER.debug(
                        "Updating performance data (cache expired or missing)"
                    )
                else:
                    _LOGGER.debug("Using cached performance data")
                    # Use cached performance values
                    ytd_earnings_percentage = self._performance_data_cache.get(
                        "ytd_earnings_percentage", 0.0
                    )
                    investment_performance_percentage = (
                        self._performance_data_cache.get(
                            "investment_performance_percentage", 0.0
                        )
                    )
                    ytd_investment_performance_percentage = (
                        self._performance_data_cache.get(
                            "ytd_investment_performance_percentage", 0.0
                        )
                    )
                    month_investment_performance_percentage = (
                        self._performance_data_cache.get(
                            "month_investment_performance_percentage", 0.0
                        )
                    )
                    quarter_investment_performance_percentage = (
                        self._performance_data_cache.get(
                            "quarter_investment_performance_percentage", 0.0
                        )
                    )
                    cash_transfer_balance = self._performance_data_cache.get(
                        "cash_transfer_balance", 0.0
                    )
                    client_id = self._performance_data_cache.get("client_id", "unknown")
                    account_id = self._performance_data_cache.get(
                        "account_id", "unknown"
                    )
                    client_name = self._performance_data_cache.get(
                        "client_name", "unknown"
                    )

                # Get client details for both performance and account data
                client_details = None

                # Only fetch performance data if cache is stale
                if should_update_performance:
                    # Add delay between balance and client details calls to prevent burst
                    await asyncio.sleep(0.5)

                    # Get client details (ClientKey, ClientId, etc.)
                    try:
                        client_details = await client.get_client_details()
                        if client_details:
                            _LOGGER.debug(
                                "Client details response keys: %s",
                                list(client_details.keys())
                                if client_details
                                else "No data",
                            )

                            client_key = client_details.get("ClientKey")
                            client_id = client_details.get("ClientId", "unknown")
                            default_account_id = client_details.get(
                                "DefaultAccountId", "unknown"
                            )
                            client_name = client_details.get("Name", "unknown")

                            _LOGGER.debug(
                                "Extracted from client details - ClientId: %s, DefaultAccountId: %s, Name: '%s'",
                                client_id,
                                default_account_id,
                                client_name,
                            )

                            if client_key:
                                _LOGGER.debug(
                                    "Found ClientKey from client details, attempting performance fetch"
                                )
                                try:
                                    performance_data = await client.get_performance(
                                        client_key
                                    )

                                    # Log performance data structure for debugging
                                    _LOGGER.debug(
                                        "Performance v3 data keys: %s",
                                        list(performance_data.keys())
                                        if performance_data
                                        else "No data",
                                    )

                                    # Extract AccumulatedProfitLoss from BalancePerformance
                                    balance_performance = performance_data.get(
                                        "BalancePerformance", {}
                                    )
                                    accumulated_profit_loss = balance_performance.get(
                                        "AccumulatedProfitLoss", 0.0
                                    )

                                    # Check if there's an inception date in the v3 performance data
                                    if "InceptionDate" in performance_data:
                                        inception_day = performance_data.get(
                                            "InceptionDate"
                                        )
                                        _LOGGER.debug(
                                            "Found InceptionDate in performance v3 data: %s",
                                            inception_day,
                                        )
                                    elif "FirstTradingDay" in performance_data:
                                        inception_day = performance_data.get(
                                            "FirstTradingDay"
                                        )
                                        _LOGGER.debug(
                                            "Found FirstTradingDay in performance v3 data: %s",
                                            inception_day,
                                        )

                                    # Use AccumulatedProfitLoss as YTD earnings percentage
                                    ytd_earnings_percentage = accumulated_profit_loss
                                    _LOGGER.debug(
                                        "Retrieved performance data, AccumulatedProfitLoss: %s",
                                        accumulated_profit_loss,
                                    )

                                except Exception as perf_e:
                                    _LOGGER.debug(
                                        "Could not fetch performance data: %s",
                                        type(perf_e).__name__,
                                    )

                                # Fetch all v4 performance data in a single batched call with rate limiting
                                try:
                                    # Add small delay before performance calls to prevent burst
                                    await asyncio.sleep(0.5)

                                    performance_v4_batch = (
                                        await client.get_performance_v4_batch(
                                            client_key
                                        )
                                    )

                                    # Extract AllTime performance data
                                    performance_v4_data = performance_v4_batch.get(
                                        "alltime", {}
                                    )
                                    key_figures = performance_v4_data.get(
                                        "KeyFigures", {}
                                    )
                                    return_fraction = key_figures.get(
                                        "ReturnFraction", 0.0
                                    )
                                    investment_performance_percentage = (
                                        return_fraction * 100.0
                                    )

                                    # Extract latest CashTransfer value
                                    balance = performance_v4_data.get("Balance", {})
                                    cash_transfer_list = balance.get("CashTransfer", [])
                                    if cash_transfer_list:
                                        latest_cash_transfer = cash_transfer_list[-1]
                                        cash_transfer_balance = (
                                            latest_cash_transfer.get("Value", 0.0)
                                        )

                                    # Extract YTD performance data
                                    ytd_data = performance_v4_batch.get("ytd", {})
                                    ytd_key_figures = ytd_data.get("KeyFigures", {})
                                    ytd_return_fraction = ytd_key_figures.get(
                                        "ReturnFraction", 0.0
                                    )
                                    ytd_investment_performance_percentage = (
                                        ytd_return_fraction * 100.0
                                    )

                                    # Extract Month performance data
                                    month_data = performance_v4_batch.get("month", {})
                                    month_key_figures = month_data.get("KeyFigures", {})
                                    month_return_fraction = month_key_figures.get(
                                        "ReturnFraction", 0.0
                                    )
                                    month_investment_performance_percentage = (
                                        month_return_fraction * 100.0
                                    )

                                    # Extract Quarter performance data
                                    quarter_data = performance_v4_batch.get(
                                        "quarter", {}
                                    )
                                    quarter_key_figures = quarter_data.get(
                                        "KeyFigures", {}
                                    )
                                    quarter_return_fraction = quarter_key_figures.get(
                                        "ReturnFraction", 0.0
                                    )
                                    quarter_investment_performance_percentage = (
                                        quarter_return_fraction * 100.0
                                    )

                                    _LOGGER.debug(
                                        "Retrieved batched performance v4 data - AllTime: %s%%, YTD: %s%%, Month: %s%%, Quarter: %s%%, CashTransfer: %s",
                                        investment_performance_percentage,
                                        ytd_investment_performance_percentage,
                                        month_investment_performance_percentage,
                                        quarter_investment_performance_percentage,
                                        cash_transfer_balance,
                                    )

                                except Exception as perf_v4_e:
                                    _LOGGER.debug(
                                        "Could not fetch batched performance v4 data: %s",
                                        type(perf_v4_e).__name__,
                                    )

                            else:
                                _LOGGER.debug(
                                    "No ClientKey found from client details endpoint, performance data not available"
                                )
                        else:
                            _LOGGER.debug("No client details available")
                    except Exception as client_e:
                        _LOGGER.debug(
                            "Could not fetch client details: %s",
                            type(client_e).__name__,
                        )

                # Get account id and client name from client details or cache
                if not client_details:
                    try:
                        client_details = await client.get_client_details()
                        if client_details:
                            _LOGGER.debug(
                                "Fetched client details keys for account info: %s",
                                list(client_details.keys()),
                            )
                    except Exception as e:
                        _LOGGER.debug(
                            "Could not fetch client details for account info: %s - %s",
                            type(e).__name__,
                            str(e),
                        )

                if client_details:
                    account_id = client_details.get("DefaultAccountId", account_id)
                    client_name = client_details.get("Name", client_name)
                    _LOGGER.debug(
                        "Final extracted values - AccountId: %s, Name: '%s'",
                        account_id,
                        client_name,
                    )
                else:
                    _LOGGER.debug(
                        "No client details available - using cached/default values: AccountId: %s, Name: '%s'",
                        account_id,
                        client_name,
                    )

                # Update performance data cache if we fetched new data
                if should_update_performance:
                    self._performance_data_cache = {
                        "ytd_earnings_percentage": ytd_earnings_percentage,
                        "investment_performance_percentage": investment_performance_percentage,
                        "ytd_investment_performance_percentage": ytd_investment_performance_percentage,
                        "month_investment_performance_percentage": month_investment_performance_percentage,
                        "quarter_investment_performance_percentage": quarter_investment_performance_percentage,
                        "cash_transfer_balance": cash_transfer_balance,
                        "client_id": client_id,
                        "account_id": account_id,
                        "client_name": client_name,
                    }
                    self._performance_last_updated = datetime.now()
                    _LOGGER.debug("Updated performance data cache")

                # Create simple data structure for balance sensors
                return {
                    "cash_balance": balance_data.get("CashBalance", 0.0),
                    "currency": balance_data.get("Currency", "USD"),
                    "total_value": balance_data.get("TotalValue", 0.0),
                    "non_margin_positions_value": balance_data.get(
                        "NonMarginPositionsValue", 0.0
                    ),
                    "ytd_earnings_percentage": ytd_earnings_percentage,
                    "investment_performance_percentage": investment_performance_percentage,
                    "ytd_investment_performance_percentage": ytd_investment_performance_percentage,
                    "month_investment_performance_percentage": month_investment_performance_percentage,
                    "quarter_investment_performance_percentage": quarter_investment_performance_percentage,
                    "cash_transfer_balance": cash_transfer_balance,
                    "client_id": client_id,
                    "account_id": account_id,
                    "client_name": client_name,
                    "last_updated": datetime.now().isoformat(),
                }

                # Log total fetch duration
                total_duration = (datetime.now() - fetch_start_time).total_seconds()
                _LOGGER.debug(
                    "Complete portfolio data fetch completed in %.2fs", total_duration
                )

        except AuthenticationError as e:
            _LOGGER.error(
                "Authentication error for production environment: %s. "
                "Check that OAuth credentials are valid production credentials.",
                type(e).__name__,
            )
            raise ConfigEntryAuthFailed(
                "Authentication failed for production environment. "
                "Ensure OAuth credentials are valid production credentials."
            ) from e

        except TimeoutError as e:
            # Calculate how long the fetch attempt took
            if "fetch_start_time" in locals():
                actual_duration = (datetime.now() - fetch_start_time).total_seconds()
                timeout_msg = (
                    f"Timeout fetching portfolio data after {actual_duration:.1f}s "
                    f"(limit: {COORDINATOR_UPDATE_TIMEOUT}s). "
                    f"This may indicate network connectivity issues or high Saxo API load. "
                    f"The integration will automatically retry on the next update cycle."
                )
            else:
                timeout_msg = (
                    f"Timeout fetching portfolio data after {COORDINATOR_UPDATE_TIMEOUT}s. "
                    f"This may indicate network connectivity issues or high Saxo API load. "
                    f"The integration will automatically retry on the next update cycle."
                )

            # First occurrence as warning, subsequent as debug to reduce noise
            if (
                not hasattr(self, "_last_timeout_warning")
                or (datetime.now() - self._last_timeout_warning).total_seconds() > 300
            ):  # 5 minutes
                _LOGGER.warning(timeout_msg)
                self._last_timeout_warning = datetime.now()
            else:
                _LOGGER.debug(timeout_msg)

            raise UpdateFailed(
                "Network timeout - check connectivity and try again"
            ) from e

        except APIError as e:
            _LOGGER.error("API error fetching portfolio data: %s", type(e).__name__)
            raise UpdateFailed("API error") from e

        except ConfigEntryAuthFailed:
            # Re-raise authentication failures to trigger reauth flow in Home Assistant
            # This must be caught before the generic Exception handler
            _LOGGER.info(
                "Authentication failed - Home Assistant will display reauthentication prompt"
            )
            raise

        except Exception as e:
            _LOGGER.exception("Unexpected error fetching portfolio data")
            raise UpdateFailed("Unexpected error") from e

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data from Saxo API.

        This is called by the DataUpdateCoordinator on the configured interval.
        Dynamically adjusts update frequency based on market hours.

        Returns:
            Updated portfolio data

        """
        # For "any" timezone, use fixed interval
        if self._timezone == "any":
            new_interval = DEFAULT_UPDATE_INTERVAL_ANY
            # Log only if interval changed
            if new_interval != self.update_interval:
                _LOGGER.info(
                    "Using fixed update interval (no market hours) - %s",
                    new_interval,
                )
                self.update_interval = new_interval
        else:
            # Check current market status and determine appropriate interval
            is_market_open = self._is_market_hours()
            new_interval = (
                DEFAULT_UPDATE_INTERVAL_MARKET_HOURS
                if is_market_open
                else DEFAULT_UPDATE_INTERVAL_AFTER_HOURS
            )

            # Update interval if it has changed
            if new_interval != self.update_interval:
                market_status = "market hours" if is_market_open else "after hours"
                _LOGGER.info(
                    "Switched to %s mode for %s - updating refresh interval from %s to %s",
                    market_status,
                    self._timezone,
                    self.update_interval,
                    new_interval,
                )
                self.update_interval = new_interval

        # Fetch the portfolio data
        data = await self._fetch_portfolio_data()

        # Store the last successful update time
        if data is not None:
            self._last_successful_update = dt_util.utcnow()

            # Track successful updates and exit startup phase after a few successes
            self._successful_updates_count += 1
            if (
                self._successful_updates_count >= 3
            ):  # Exit startup after 3 successful updates
                if self._is_startup_phase:  # Only log once when exiting startup
                    _LOGGER.debug(
                        "Integration startup phase completed after %d successful updates",
                        self._successful_updates_count,
                    )
                self._is_startup_phase = False

            # Check if client name has changed from unknown to a valid name
            # This indicates that sensor setup should be attempted again
            # BUT: Only trigger reload if this is NOT the initial setup (where coordinator.last_update_success would be None)
            # and sensors haven't been initialized yet
            current_client_name = data.get("client_name", "unknown")

            # Debug logging to understand reload trigger
            _LOGGER.debug(
                "Reload check - last_known: '%s', current: '%s', sensors_init: %s, setup_complete: %s",
                self._last_known_client_name,
                current_client_name,
                self._sensors_initialized,
                self._setup_complete,
            )

            # Only consider reload if:
            # 1. We had a previous unknown client name
            # 2. Now have a valid client name
            # 3. Sensors weren't initialized (means they were skipped)
            # 4. Initial setup is complete (platforms already loaded)
            should_reload = (
                self._last_known_client_name == "unknown"
                and current_client_name != "unknown"
                and not self._sensors_initialized
                and self._setup_complete
            )

            if should_reload:
                _LOGGER.info(
                    "Client name is now available ('%s') after being unknown - scheduling config entry reload to initialize sensors",
                    current_client_name,
                )
                self._last_known_client_name = current_client_name

                # Schedule config entry reload to create sensors
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(self.config_entry.entry_id)
                )
            else:
                # Update last known client name for future comparisons
                self._last_known_client_name = current_client_name

        return data

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator and cleanup resources."""
        _LOGGER.debug("Shutting down Saxo coordinator")

        if self._api_client:
            try:
                await self._api_client.close()
                _LOGGER.debug("Successfully closed API client during shutdown")
            except Exception as e:
                _LOGGER.warning(
                    "Error closing API client during shutdown: %s", e, exc_info=True
                )
            finally:
                self._api_client = None

        await super().async_shutdown()

    @property
    def last_successful_update_time(self) -> datetime | None:
        """Get the last successful update time."""
        return self._last_successful_update

    def get_cash_balance(self) -> float:
        """Get cash balance from data.

        Returns:
            Cash balance value or 0.0 if not available

        """
        if not self.data:
            return 0.0
        return self.data.get("cash_balance", 0.0)

    def get_total_value(self) -> float:
        """Get total portfolio value from data.

        Returns:
            Total value or 0.0 if not available

        """
        if not self.data:
            return 0.0
        return self.data.get("total_value", 0.0)

    def get_non_margin_positions_value(self) -> float:
        """Get non-margin positions value from data.

        Returns:
            Non-margin positions value or 0.0 if not available

        """
        if not self.data:
            return 0.0
        return self.data.get("non_margin_positions_value", 0.0)

    def get_currency(self) -> str:
        """Get the portfolio base currency.

        Returns:
            Currency code or USD as default

        """
        if self.data:
            return self.data.get("currency", "USD")
        return "USD"

    def get_ytd_earnings_percentage(self) -> float:
        """Get YTD earnings percentage from performance data.

        Returns:
            YTD earnings percentage or 0.0 if not available

        """
        if not self.data:
            return 0.0
        return self.data.get("ytd_earnings_percentage", 0.0)

    def get_client_id(self) -> str:
        """Get ClientId from client details.

        Returns:
            ClientId or 'unknown' if not available

        """
        if not self.data:
            return "unknown"
        return self.data.get("client_id", "unknown")

    def get_investment_performance_percentage(self) -> float:
        """Get investment performance percentage from v4 performance API.

        Returns:
            Investment performance percentage (ReturnFraction * 100) or 0.0 if not available

        """
        if not self.data:
            return 0.0
        return self.data.get("investment_performance_percentage", 0.0)

    def get_cash_transfer_balance(self) -> float:
        """Get latest cash transfer balance from v4 performance API.

        Returns:
            Latest cash transfer balance value or 0.0 if not available

        """
        if not self.data:
            return 0.0
        return self.data.get("cash_transfer_balance", 0.0)

    def get_ytd_investment_performance_percentage(self) -> float:
        """Get YTD investment performance percentage from v4 performance API.

        Returns:
            YTD investment performance percentage (ReturnFraction * 100) or 0.0 if not available

        """
        if not self.data:
            return 0.0
        return self.data.get("ytd_investment_performance_percentage", 0.0)

    def get_month_investment_performance_percentage(self) -> float:
        """Get Month investment performance percentage from v4 performance API.

        Returns:
            Month investment performance percentage (ReturnFraction * 100) or 0.0 if not available

        """
        if not self.data:
            return 0.0
        return self.data.get("month_investment_performance_percentage", 0.0)

    def get_quarter_investment_performance_percentage(self) -> float:
        """Get Quarter investment performance percentage from v4 performance API.

        Returns:
            Quarter investment performance percentage (ReturnFraction * 100) or 0.0 if not available

        """
        if not self.data:
            return 0.0
        return self.data.get("quarter_investment_performance_percentage", 0.0)

    def get_account_id(self) -> str:
        """Get AccountId from account data.

        Returns:
            AccountId or 'unknown' if not available

        """
        if not self.data:
            return "unknown"
        return self.data.get("account_id", "unknown")

    def get_client_name(self) -> str:
        """Get client Name from client data.

        Returns:
            Client Name or 'unknown' if not available

        """
        if not self.data:
            return "unknown"
        return self.data.get("client_name", "unknown")

    def mark_sensors_initialized(self) -> None:
        """Mark that sensors have been successfully initialized.

        This prevents unnecessary config entry reloads once sensors are created.
        """
        self._sensors_initialized = True
        _LOGGER.debug(
            "Marked sensors as initialized for entry %s", self.config_entry.entry_id
        )

    def mark_setup_complete(self) -> None:
        """Mark that initial setup is complete (platforms loaded).

        This allows the reload logic to work correctly for genuinely skipped sensors.
        """
        self._setup_complete = True
        _LOGGER.debug(
            "Marked setup as complete for entry %s", self.config_entry.entry_id
        )

    @property
    def is_startup_phase(self) -> bool:
        """Check if the coordinator is still in startup phase.

        Returns:
            True if still in startup phase (first few updates), False otherwise

        """
        return self._is_startup_phase

    async def async_update_interval_if_needed(self) -> None:
        """Check and update the refresh interval based on current market status.

        This can be called manually to force an interval check without waiting
        for the next scheduled update.
        """
        # For "any" timezone, use fixed interval
        if self._timezone == "any":
            new_interval = DEFAULT_UPDATE_INTERVAL_ANY
            if new_interval != self.update_interval:
                _LOGGER.info(
                    "Manual interval check: Using fixed update interval (no market hours) - %s",
                    new_interval,
                )
                self.update_interval = new_interval
        else:
            is_market_open = self._is_market_hours()
            new_interval = (
                DEFAULT_UPDATE_INTERVAL_MARKET_HOURS
                if is_market_open
                else DEFAULT_UPDATE_INTERVAL_AFTER_HOURS
            )

            if new_interval != self.update_interval:
                market_status = "market hours" if is_market_open else "after hours"
                _LOGGER.info(
                    "Manual interval check: Switched to %s mode for %s - updating refresh interval from %s to %s",
                    market_status,
                    self._timezone,
                    self.update_interval,
                    new_interval,
                )
                self.update_interval = new_interval
