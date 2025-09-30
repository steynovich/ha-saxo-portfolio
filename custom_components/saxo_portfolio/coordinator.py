"""DataUpdateCoordinator for Saxo Portfolio integration.

This coordinator manages data fetching from the Saxo API and coordinates
updates across all sensors.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
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
    API_TIMEOUT_BALANCE,
    API_TIMEOUT_CLIENT_INFO,
    API_TIMEOUT_PERFORMANCE,
    CONF_TIMEZONE,
    COORDINATOR_UPDATE_TIMEOUT,
    DEFAULT_TIMEZONE,
    DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
    DEFAULT_UPDATE_INTERVAL_ANY,
    DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
    DOMAIN,
    MARKET_HOURS,
    PERFORMANCE_UPDATE_INTERVAL,
    TOKEN_MIN_VALIDITY,
    TOKEN_REFRESH_BUFFER,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class PerformanceCache:
    """Cache for performance data."""

    ytd_earnings_percentage: float = 0.0
    investment_performance_percentage: float = 0.0
    ytd_investment_performance_percentage: float = 0.0
    month_investment_performance_percentage: float = 0.0
    quarter_investment_performance_percentage: float = 0.0
    cash_transfer_balance: float = 0.0
    client_id: str = "unknown"
    account_id: str = "unknown"
    client_name: str = "unknown"
    last_updated: datetime | None = None


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
        self._performance_cache = PerformanceCache()

        # Track if sensors were skipped due to unknown client name
        self._sensors_initialized = False
        self._last_known_client_name = "unknown"

        # Track startup phase for better error messaging
        self._is_startup_phase = True
        self._successful_updates_count = 0

        # Get configured timezone
        self._timezone = config_entry.data.get(CONF_TIMEZONE, DEFAULT_TIMEZONE)

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

    def _should_recreate_api_client(self, access_token: str) -> bool:
        """Check if API client needs recreation due to token change.

        Args:
            access_token: Current access token from config

        Returns:
            True if client should be recreated

        """
        if self._api_client is None:
            return True

        current_token = getattr(self._api_client, "access_token", None)
        if current_token != access_token:
            _LOGGER.debug("Token changed, API client needs recreation")
            return True

        return False

    def _create_api_client(self, access_token: str) -> SaxoApiClient:
        """Create new API client with token.

        Args:
            access_token: OAuth access token

        Returns:
            New SaxoApiClient instance

        """
        from .const import SAXO_API_BASE_URL

        token_data = self.config_entry.data.get("token", {})
        token_type = token_data.get("token_type", "unknown")
        expires_at = token_data.get("expires_at")

        if expires_at:
            expires_datetime = datetime.fromtimestamp(expires_at)
            is_expired = datetime.now() > expires_datetime
            _LOGGER.debug(
                "Creating API client - token type: %s, expires: %s, is_expired: %s",
                token_type,
                expires_datetime.isoformat(),
                is_expired,
            )
        else:
            _LOGGER.debug(
                "Creating API client - token type: %s, no expiry info", token_type
            )

        return SaxoApiClient(access_token, SAXO_API_BASE_URL)

    @property
    def api_client(self) -> SaxoApiClient:
        """Get API client, creating or recreating as needed."""
        token_data = self.config_entry.data.get("token", {})
        access_token = token_data.get("access_token")

        if not access_token:
            raise ConfigEntryAuthFailed("No access token available")

        # Check if client needs recreation
        if self._should_recreate_api_client(access_token):
            # Close old client if it exists
            if self._api_client is not None:
                old_client = self._api_client
                self._api_client = None
                self.hass.async_create_task(self._close_old_client(old_client))

            # Create new client
            self._api_client = self._create_api_client(access_token)

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
        if self._performance_cache.last_updated is None:
            # No cached data, should update
            return True

        time_since_last_update = datetime.now() - self._performance_cache.last_updated
        should_update = time_since_last_update >= PERFORMANCE_UPDATE_INTERVAL

        _LOGGER.debug(
            "Performance cache age: %s, should_update: %s",
            time_since_last_update,
            should_update,
        )

        return should_update

    async def _fetch_performance_data(
        self, client: SaxoApiClient, client_key: str, period_name: str, method_name: str
    ) -> float:
        """Fetch performance data with consistent error handling.

        Args:
            client: API client instance
            client_key: Client key for API calls
            period_name: Human-readable period name for logging
            method_name: API client method name to call

        Returns:
            Performance percentage or 0.0 if unavailable

        """
        try:
            method = getattr(client, method_name)
            async with async_timeout.timeout(API_TIMEOUT_PERFORMANCE):
                performance_data = await method(client_key)

            key_figures = performance_data.get("KeyFigures", {})
            return_fraction = key_figures.get("ReturnFraction", 0.0)
            performance_percentage = return_fraction * 100.0

            _LOGGER.debug(
                "Retrieved %s performance v4 data - ReturnFraction: %s%%",
                period_name,
                performance_percentage,
            )
            return performance_percentage

        except Exception as e:
            _LOGGER.debug(
                "Could not fetch %s performance v4 data: %s",
                period_name,
                type(e).__name__,
            )
            return 0.0

    def _is_market_hours(self) -> bool:
        """Check if current time is during market hours.

        Returns:
            True if market is currently open

        """
        # If timezone is "any", market hours don't apply
        if self._timezone == "any":
            return False

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
                return False

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
                current_time.strftime("%H:%M:%S"),
                now_local.weekday(),
                is_open,
            )

            return is_open

        except Exception as e:
            _LOGGER.error("Error checking market hours: %s", type(e).__name__)
            # Default to after-hours if we can't determine market status
            return False

    async def _fetch_balance_data(self, client: SaxoApiClient) -> dict[str, Any]:
        """Fetch balance data from Saxo API.

        Args:
            client: API client instance

        Returns:
            Balance data dictionary with keys: CashBalance, TotalValue, Currency, etc.

        """
        balance_start_time = datetime.now()
        async with async_timeout.timeout(API_TIMEOUT_BALANCE):
            balance_data = await client.get_account_balance()

        balance_duration = (datetime.now() - balance_start_time).total_seconds()
        _LOGGER.debug("Balance data fetch completed in %.2fs", balance_duration)

        # Remove detailed margin info to reduce log noise
        if "MarginCollateralNotAvailableDetail" in balance_data:
            del balance_data["MarginCollateralNotAvailableDetail"]

        return balance_data

    async def _fetch_client_details_cached(
        self, client: SaxoApiClient
    ) -> dict[str, Any] | None:
        """Fetch client details with consistent error handling.

        Args:
            client: API client instance

        Returns:
            Client details dictionary or None if unavailable

        """
        try:
            async with async_timeout.timeout(API_TIMEOUT_CLIENT_INFO):
                client_details = await client.get_client_details()

            if client_details:
                _LOGGER.debug(
                    "Client details response keys: %s",
                    list(client_details.keys()),
                )
            return client_details

        except Exception as e:
            _LOGGER.debug(
                "Could not fetch client details: %s",
                type(e).__name__,
            )
            return None

    async def _fetch_performance_metrics(
        self, client: SaxoApiClient, client_key: str
    ) -> PerformanceCache:
        """Fetch all performance metrics from Saxo API.

        Args:
            client: API client instance
            client_key: Client key for API calls

        Returns:
            PerformanceCache with all performance metrics

        """
        cache = PerformanceCache()

        # Fetch v3 performance data (AccumulatedProfitLoss)
        try:
            async with async_timeout.timeout(API_TIMEOUT_PERFORMANCE):
                performance_data = await client.get_performance(client_key)

            balance_performance = performance_data.get("BalancePerformance", {})
            cache.ytd_earnings_percentage = balance_performance.get(
                "AccumulatedProfitLoss", 0.0
            )

            _LOGGER.debug(
                "Retrieved performance data, AccumulatedProfitLoss: %s",
                cache.ytd_earnings_percentage,
            )

        except Exception as e:
            _LOGGER.debug(
                "Could not fetch performance data: %s",
                type(e).__name__,
            )

        # Fetch v4 performance data (all-time)
        try:
            async with async_timeout.timeout(API_TIMEOUT_PERFORMANCE):
                performance_v4_data = await client.get_performance_v4(client_key)

            key_figures = performance_v4_data.get("KeyFigures", {})
            return_fraction = key_figures.get("ReturnFraction", 0.0)
            cache.investment_performance_percentage = return_fraction * 100.0

            # Extract latest CashTransfer value
            balance = performance_v4_data.get("Balance", {})
            cash_transfer_list = balance.get("CashTransfer", [])
            if cash_transfer_list:
                latest_cash_transfer = cash_transfer_list[-1]
                cache.cash_transfer_balance = latest_cash_transfer.get("Value", 0.0)

            _LOGGER.debug(
                "Retrieved performance v4 data - ReturnFraction: %s%%, CashTransfer: %s",
                cache.investment_performance_percentage,
                cache.cash_transfer_balance,
            )

        except Exception as e:
            _LOGGER.debug(
                "Could not fetch performance v4 data: %s",
                type(e).__name__,
            )

        # Fetch additional performance periods
        cache.ytd_investment_performance_percentage = (
            await self._fetch_performance_data(
                client, client_key, "YTD", "get_performance_v4_ytd"
            )
        )
        cache.month_investment_performance_percentage = (
            await self._fetch_performance_data(
                client, client_key, "Month", "get_performance_v4_month"
            )
        )
        cache.quarter_investment_performance_percentage = (
            await self._fetch_performance_data(
                client, client_key, "Quarter", "get_performance_v4_quarter"
            )
        )

        cache.last_updated = datetime.now()
        return cache

    async def _check_and_refresh_token(self) -> None:
        """Check token expiry and refresh if needed."""
        async with self._token_refresh_lock:
            token_data = self.config_entry.data.get("token", {})
            expires_at = token_data.get("expires_at")

            if not expires_at:
                _LOGGER.warning("No token expiry information available")
                return

            # Check if token needs refresh
            expiry_time = datetime.fromtimestamp(expires_at)
            refresh_time = expiry_time - TOKEN_REFRESH_BUFFER
            current_time = datetime.now()

            if current_time >= refresh_time:
                _LOGGER.debug(
                    "Token needs refresh (expires at %s, refresh buffer %s)",
                    expiry_time.isoformat(),
                    TOKEN_REFRESH_BUFFER,
                )

                # Validate token still has minimum validity
                if current_time >= (expiry_time - TOKEN_MIN_VALIDITY):
                    _LOGGER.debug("Token expires very soon, immediate refresh needed")

                await self._refresh_oauth_token()

                # Update last token check time
                self._last_token_check = current_time

    def _get_refresh_token(self) -> str:
        """Extract and validate refresh token from config entry.

        Returns:
            Refresh token string

        Raises:
            ConfigEntryAuthFailed: If no refresh token available

        """
        token_data = self.config_entry.data.get("token", {})
        refresh_token = token_data.get("refresh_token")

        if not refresh_token:
            raise ConfigEntryAuthFailed("No refresh token available")

        return refresh_token

    def _mask_sensitive_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Mask sensitive token data for logging.

        Args:
            data: Dictionary potentially containing sensitive data

        Returns:
            Dictionary with sensitive values masked

        """
        masked = {}
        for key, value in data.items():
            if key in ["access_token", "refresh_token", "client_secret"]:
                if value and len(str(value)) > 4:
                    masked[key] = f"***{value[-4:]}"
                else:
                    masked[key] = "***"
            else:
                masked[key] = value
        return masked

    async def _get_oauth_basic_auth(self) -> aiohttp.BasicAuth | None:
        """Get HTTP Basic Auth for OAuth token refresh.

        Returns:
            BasicAuth object or None if unavailable

        """
        try:
            from homeassistant.helpers.config_entry_oauth2_flow import (
                async_get_config_entry_implementation,
            )

            implementation = await async_get_config_entry_implementation(
                self.hass, self.config_entry
            )
            if implementation:
                _LOGGER.debug(
                    "Using HTTP Basic Auth for token refresh (Saxo preferred method)"
                )
                return aiohttp.BasicAuth(
                    implementation.client_id, implementation.client_secret
                )
            else:
                _LOGGER.warning("Could not get OAuth implementation for Basic Auth")
                return None

        except Exception as e:
            _LOGGER.error("Failed to set up HTTP Basic Auth: %s", type(e).__name__)
            return None

    def _build_token_refresh_data(self, refresh_token: str) -> dict[str, str]:
        """Build token refresh request data.

        Args:
            refresh_token: Refresh token

        Returns:
            Dictionary with refresh request data

        """
        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        # Get redirect_uri from the original OAuth flow (required by Saxo)
        redirect_uri = self.config_entry.data.get("redirect_uri")
        if not redirect_uri:
            redirect_uri = "https://my.home-assistant.io/redirect/oauth"
            _LOGGER.info(
                "No redirect_uri in config entry, using fallback: %s (consider reconfiguring integration)",
                redirect_uri,
            )

        refresh_data["redirect_uri"] = redirect_uri
        return refresh_data

    async def _execute_token_refresh_request(
        self, refresh_data: dict[str, str], auth: aiohttp.BasicAuth | None
    ) -> dict[str, Any]:
        """Execute the HTTP request to refresh OAuth token.

        Args:
            refresh_data: Request data
            auth: HTTP Basic Auth

        Returns:
            New token data from API response

        Raises:
            ConfigEntryAuthFailed: If token refresh fails

        """
        from .const import SAXO_AUTH_BASE_URL, OAUTH_TOKEN_ENDPOINT

        token_url = f"{SAXO_AUTH_BASE_URL}{OAUTH_TOKEN_ENDPOINT}"
        session = async_get_clientsession(self.hass)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        _LOGGER.debug(
            "Token refresh request: URL=%s, has_basic_auth=%s, data=%s",
            token_url,
            auth is not None,
            self._mask_sensitive_data(refresh_data),
        )

        async with session.post(
            token_url, data=refresh_data, headers=headers, auth=auth
        ) as response:
            _LOGGER.debug("Token refresh response: status=%d", response.status)

            if response.status in [200, 201]:
                new_token_data = await response.json()

                # Calculate expiry time
                expires_in = new_token_data.get("expires_in", 1200)
                expires_at = (
                    datetime.now() + timedelta(seconds=expires_in)
                ).timestamp()
                new_token_data["expires_at"] = expires_at

                return new_token_data
            else:
                error_text = await response.text()
                _LOGGER.error(
                    "Token refresh failed: HTTP %d - %s",
                    response.status,
                    error_text[:500] if error_text else "No error details",
                )
                raise ConfigEntryAuthFailed("Failed to refresh access token")

    def _update_config_entry_with_token(self, new_token_data: dict[str, Any]) -> None:
        """Update config entry with new token data.

        Args:
            new_token_data: New token data to store

        """
        new_data = self.config_entry.data.copy()
        new_data["token"] = new_token_data

        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

        # Force API client recreation with new token
        self._api_client = None

        # Log success
        token_expires = datetime.fromtimestamp(new_token_data["expires_at"])
        _LOGGER.info(
            "Successfully refreshed OAuth token (expires: %s)",
            token_expires.isoformat(),
        )
        _LOGGER.debug(
            "New token data structure: %s",
            self._mask_sensitive_data(new_token_data),
        )

    async def _refresh_oauth_token(self) -> dict[str, Any]:
        """Refresh OAuth access token using refresh token.

        Returns:
            New token data

        Raises:
            ConfigEntryAuthFailed: If token refresh fails

        """
        try:
            # Extract refresh token
            refresh_token = self._get_refresh_token()

            # Get OAuth credentials
            auth = await self._get_oauth_basic_auth()

            # Build refresh request
            refresh_data = self._build_token_refresh_data(refresh_token)

            # Execute refresh request
            new_token_data = await self._execute_token_refresh_request(
                refresh_data, auth
            )

            # Update config entry
            self._update_config_entry_with_token(new_token_data)

            return new_token_data

        except ConfigEntryAuthFailed:
            raise
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
        fetch_start_time = datetime.now()

        try:
            # Check and refresh token if needed
            await self._check_and_refresh_token()

            # Get API client
            client = self.api_client

            # Validate we're using the expected production URL
            expected_base_url = "https://gateway.saxobank.com/openapi"
            if client.base_url != expected_base_url:
                _LOGGER.error(
                    "API client base URL mismatch! Expected: %s, Got: %s",
                    expected_base_url,
                    client.base_url,
                )

            async with async_timeout.timeout(COORDINATOR_UPDATE_TIMEOUT):
                # Fetch balance data (always required)
                balance_data = await self._fetch_balance_data(client)

                # Check if we should update performance data or use cached values
                should_update_performance = self._should_update_performance_data()

                if should_update_performance:
                    _LOGGER.debug(
                        "Updating performance data (cache expired or missing)"
                    )

                    # Fetch client details
                    client_details = await self._fetch_client_details_cached(client)

                    if client_details:
                        client_key = client_details.get("ClientKey")
                        self._performance_cache.client_id = client_details.get(
                            "ClientId", "unknown"
                        )
                        self._performance_cache.account_id = client_details.get(
                            "DefaultAccountId", "unknown"
                        )
                        self._performance_cache.client_name = client_details.get(
                            "Name", "unknown"
                        )

                        _LOGGER.debug(
                            "Extracted from client details - ClientId: %s, DefaultAccountId: %s, Name: '%s'",
                            self._performance_cache.client_id,
                            self._performance_cache.account_id,
                            self._performance_cache.client_name,
                        )

                        if client_key:
                            _LOGGER.debug(
                                "Found ClientKey, fetching performance metrics"
                            )
                            # Fetch all performance metrics and update cache
                            self._performance_cache = (
                                await self._fetch_performance_metrics(
                                    client, client_key
                                )
                            )
                            # Preserve client info (it was set above)
                            self._performance_cache.client_id = client_details.get(
                                "ClientId", "unknown"
                            )
                            self._performance_cache.account_id = client_details.get(
                                "DefaultAccountId", "unknown"
                            )
                            self._performance_cache.client_name = client_details.get(
                                "Name", "unknown"
                            )
                            _LOGGER.debug("Updated performance data cache")
                        else:
                            _LOGGER.debug(
                                "No ClientKey found, performance data not available"
                            )
                    else:
                        _LOGGER.debug("No client details available")
                else:
                    _LOGGER.debug("Using cached performance data")

                # Build response from balance data and cached performance
                response = {
                    "cash_balance": balance_data.get("CashBalance", 0.0),
                    "currency": balance_data.get("Currency", "USD"),
                    "total_value": balance_data.get("TotalValue", 0.0),
                    "non_margin_positions_value": balance_data.get(
                        "NonMarginPositionsValue", 0.0
                    ),
                    "ytd_earnings_percentage": self._performance_cache.ytd_earnings_percentage,
                    "investment_performance_percentage": self._performance_cache.investment_performance_percentage,
                    "ytd_investment_performance_percentage": self._performance_cache.ytd_investment_performance_percentage,
                    "month_investment_performance_percentage": self._performance_cache.month_investment_performance_percentage,
                    "quarter_investment_performance_percentage": self._performance_cache.quarter_investment_performance_percentage,
                    "cash_transfer_balance": self._performance_cache.cash_transfer_balance,
                    "client_id": self._performance_cache.client_id,
                    "account_id": self._performance_cache.account_id,
                    "client_name": self._performance_cache.client_name,
                    "last_updated": datetime.now().isoformat(),
                }

                # Log total fetch duration
                total_duration = (datetime.now() - fetch_start_time).total_seconds()
                _LOGGER.debug(
                    "Complete portfolio data fetch completed in %.2fs", total_duration
                )

                return response

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
            current_client_name = data.get("client_name", "unknown")
            if (
                self._last_known_client_name == "unknown"
                and current_client_name != "unknown"
                and not self._sensors_initialized
            ):
                _LOGGER.info(
                    "Client name is now available ('%s') - scheduling config entry reload to initialize sensors",
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
