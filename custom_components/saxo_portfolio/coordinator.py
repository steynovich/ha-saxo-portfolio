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
    COORDINATOR_UPDATE_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
    DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
    DOMAIN,
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MINUTE,
    MARKET_WEEKDAYS,
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
        # Determine initial update interval
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

        self.config_entry = config_entry
        self._api_client: SaxoApiClient | None = None
        self._last_token_check = datetime.now()
        self._token_refresh_lock = asyncio.Lock()
        self._last_successful_update = None

    @property
    def api_client(self) -> SaxoApiClient:
        """Get or create API client."""
        if self._api_client is None:
            token_data = self.config_entry.data.get("token", {})
            access_token = token_data.get("access_token")

            if not access_token:
                raise ConfigEntryAuthFailed("No access token available")

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

    def _is_market_hours(self) -> bool:
        """Check if current time is during market hours.

        Market hours: Monday-Friday, 9:30 AM - 4:00 PM ET
        Properly handles Eastern Time with DST conversion.

        Returns:
            True if market is currently open

        """
        try:
            # Get current time and convert to Eastern Time
            now_utc = dt_util.utcnow()
            eastern = zoneinfo.ZoneInfo("America/New_York")
            now_et = now_utc.astimezone(eastern)

            # Check if it's a weekday (Monday = 0, Sunday = 6)
            if now_et.weekday() not in MARKET_WEEKDAYS:
                return False

            # Market hours in Eastern Time
            market_open = time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)  # 9:30 AM
            market_close = time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)  # 4:00 PM

            current_time = now_et.time()

            is_open = market_open <= current_time <= market_close

            _LOGGER.debug(
                "Market hours check: %s ET, weekday: %s, is_open: %s",
                current_time.strftime("%H:%M:%S"),
                now_et.weekday(),
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
                    _LOGGER.warning("Token expires very soon, immediate refresh needed")

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
            if redirect_uri:
                refresh_data["redirect_uri"] = redirect_uri
                _LOGGER.debug("Added redirect_uri to refresh request")
            else:
                _LOGGER.warning(
                    "No redirect_uri found in config entry - this may cause refresh to fail"
                )

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
                import json

                del balance_data["MarginCollateralNotAvailableDetail"]
                _LOGGER.debug(
                    "Balance data: %s",
                    json.dumps(balance_data, indent=4, sort_keys=True)
                    if balance_data
                    else "No balance data",
                )

                # Try to fetch client details and performance data
                ytd_earnings_percentage = 0.0
                investment_performance_percentage = 0.0
                cash_transfer_balance = 0.0
                client_id = "unknown"

                # Get client details (ClientKey, ClientId, etc.)
                try:
                    client_details = await client.get_client_details()
                    if client_details:
                        client_key = client_details.get("ClientKey")
                        client_id = client_details.get("ClientId", "unknown")

                        _LOGGER.debug("Found client details - ClientId: %s", client_id)

                        if client_key:
                            _LOGGER.debug(
                                "Found ClientKey from client details, attempting performance fetch"
                            )
                            try:
                                performance_data = await client.get_performance(
                                    client_key
                                )

                                # Extract AccumulatedProfitLoss from BalancePerformance
                                balance_performance = performance_data.get(
                                    "BalancePerformance", {}
                                )
                                accumulated_profit_loss = balance_performance.get(
                                    "AccumulatedProfitLoss", 0.0
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
                                performance_v4_data = await client.get_performance_v4(
                                    client_key
                                )

                                # Extract ReturnFraction from KeyFigures (multiply by 100 for percentage)
                                key_figures = performance_v4_data.get("KeyFigures", {})
                                return_fraction = key_figures.get("ReturnFraction", 0.0)
                                investment_performance_percentage = (
                                    return_fraction * 100.0
                                )

                                # Extract latest CashTransfer value
                                balance = performance_v4_data.get("Balance", {})
                                cash_transfer_list = balance.get("CashTransfer", [])
                                if cash_transfer_list:
                                    # Get the latest entry (last in the list)
                                    latest_cash_transfer = cash_transfer_list[-1]
                                    cash_transfer_balance = latest_cash_transfer.get(
                                        "Value", 0.0
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
                        else:
                            _LOGGER.debug(
                                "No ClientKey found from client details endpoint, performance data not available"
                            )
                    else:
                        _LOGGER.debug("No client details available")
                except Exception as client_e:
                    _LOGGER.debug(
                        "Could not fetch client details: %s", type(client_e).__name__
                    )

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
                    "cash_transfer_balance": cash_transfer_balance,
                    "client_id": client_id,
                    "last_updated": balance_data.get("LastUpdated"),
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
                "Switched to %s mode - updating refresh interval from %s to %s",
                market_status,
                self.update_interval,
                new_interval,
            )
            self.update_interval = new_interval

        # Fetch the portfolio data
        return await self._fetch_portfolio_data()

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator and cleanup resources."""
        if self._api_client:
            await self._api_client.close()
            self._api_client = None

        await super().async_shutdown()

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

    async def async_update_interval_if_needed(self) -> None:
        """Check and update the refresh interval based on current market status.

        This can be called manually to force an interval check without waiting
        for the next scheduled update.
        """
        is_market_open = self._is_market_hours()
        new_interval = (
            DEFAULT_UPDATE_INTERVAL_MARKET_HOURS
            if is_market_open
            else DEFAULT_UPDATE_INTERVAL_AFTER_HOURS
        )

        if new_interval != self.update_interval:
            market_status = "market hours" if is_market_open else "after hours"
            _LOGGER.info(
                "Manual interval check: Switched to %s mode - updating refresh interval from %s to %s",
                market_status,
                self.update_interval,
                new_interval,
            )
            self.update_interval = new_interval
