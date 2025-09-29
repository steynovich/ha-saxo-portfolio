"""DataUpdateCoordinator for Saxo Portfolio integration.

This coordinator manages data fetching from the Saxo API and coordinates
updates across all sensors.
"""

from __future__ import annotations

import asyncio
import logging
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
        self._last_known_client_name = "unknown"

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

            # Saxo requires: grant_type, refresh_token, and redirect_uri
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }

            # Get redirect_uri from the original OAuth flow (required by Saxo)
            redirect_uri = self.config_entry.data.get("redirect_uri")
            if not redirect_uri:
                # Fallback to default Home Assistant OAuth redirect URI
                redirect_uri = "https://my.home-assistant.io/redirect/oauth"
                _LOGGER.info(
                    "No redirect_uri in config entry, using fallback: %s (consider reconfiguring integration)",
                    redirect_uri,
                )

            refresh_data["redirect_uri"] = redirect_uri
            _LOGGER.debug("Added redirect_uri to refresh request: %s", redirect_uri)

            # Get client credentials for HTTP Basic Auth (Saxo's preferred method)
            auth = None
            try:
                from homeassistant.helpers.config_entry_oauth2_flow import (
                    async_get_config_entry_implementation,
                )

                # Get the OAuth implementation from the config entry
                implementation = await async_get_config_entry_implementation(
                    self.hass, self.config_entry
                )
                if implementation:
                    auth = aiohttp.BasicAuth(
                        implementation.client_id, implementation.client_secret
                    )
                    _LOGGER.debug(
                        "Using HTTP Basic Auth for token refresh (Saxo preferred method)"
                    )
                else:
                    _LOGGER.warning("Could not get OAuth implementation for Basic Auth")
            except Exception as e:
                _LOGGER.error("Failed to set up HTTP Basic Auth: %s", type(e).__name__)
                _LOGGER.debug("Exception details: %s", str(e))

            _LOGGER.debug("Attempting Saxo-compliant token refresh")

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

                    # Calculate expiry time
                    expires_in = new_token_data.get("expires_in", 1200)
                    expires_at = (
                        datetime.now() + timedelta(seconds=expires_in)
                    ).timestamp()
                    new_token_data["expires_at"] = expires_at

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

                    # Update API client with new token
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
            async with async_timeout.timeout(COORDINATOR_UPDATE_TIMEOUT):
                # Get balance data (only required endpoint)
                balance_data = await client.get_account_balance()
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

                                # Also try to fetch v4 performance data
                                try:
                                    performance_v4_data = (
                                        await client.get_performance_v4(client_key)
                                    )

                                    # Extract ReturnFraction from KeyFigures (multiply by 100 for percentage)
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
                                        # Get the latest entry (last in the list)
                                        latest_cash_transfer = cash_transfer_list[-1]
                                        cash_transfer_balance = (
                                            latest_cash_transfer.get("Value", 0.0)
                                        )

                                    _LOGGER.debug(
                                        "Retrieved performance v4 data - ReturnFraction: %s%%, CashTransfer: %s",
                                        investment_performance_percentage,
                                        cash_transfer_balance,
                                    )

                                except Exception as perf_v4_e:
                                    _LOGGER.debug(
                                        "Could not fetch performance v4 data: %s",
                                        type(perf_v4_e).__name__,
                                    )

                                # Fetch additional performance periods using helper method
                                ytd_investment_performance_percentage = (
                                    await self._fetch_performance_data(
                                        client,
                                        client_key,
                                        "YTD",
                                        "get_performance_v4_ytd",
                                    )
                                )
                                month_investment_performance_percentage = (
                                    await self._fetch_performance_data(
                                        client,
                                        client_key,
                                        "Month",
                                        "get_performance_v4_month",
                                    )
                                )
                                quarter_investment_performance_percentage = (
                                    await self._fetch_performance_data(
                                        client,
                                        client_key,
                                        "Quarter",
                                        "get_performance_v4_quarter",
                                    )
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
                    except Exception:
                        _LOGGER.debug("Could not fetch client details for account info")

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
            _LOGGER.error("Timeout fetching portfolio data")
            raise UpdateFailed("Timeout fetching portfolio data") from e

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
