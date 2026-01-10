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
    MAX_RETRIES,
    PERFORMANCE_FETCH_TIMEOUT,
    PERFORMANCE_UPDATE_INTERVAL,
    REFRESH_TOKEN_BUFFER,
    RETRY_BACKOFF_FACTOR,
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

    def _extract_error_from_html(self, html_text: str) -> str:
        """Extract meaningful error message from HTML error page.

        Args:
            html_text: Raw HTML error response

        Returns:
            Extracted error message or truncated HTML if extraction fails

        """
        import re

        # Try to extract title from HTML (often contains the error message)
        title_match = re.search(r"<title>([^<]+)</title>", html_text, re.IGNORECASE)
        if title_match:
            return title_match.group(1).strip()

        # Try to extract h1 heading
        h1_match = re.search(r"<h1[^>]*>([^<]+)</h1>", html_text, re.IGNORECASE)
        if h1_match:
            return h1_match.group(1).strip()

        # Fallback: return first 100 chars of text content
        text_only = re.sub(r"<[^>]+>", " ", html_text)
        text_only = " ".join(text_only.split())[:100]
        return text_only if text_only else "Unknown HTML error"

    def _log_refresh_token_status(self) -> None:
        """Log the current refresh token status for debugging."""
        token_data = self.config_entry.data.get("token", {})
        refresh_token_expires_in = token_data.get("refresh_token_expires_in")
        token_issued_at_timestamp = token_data.get("token_issued_at")
        expires_at = token_data.get("expires_at")

        if not expires_at:
            _LOGGER.warning(
                "No token expiry information available - cannot determine token status"
            )
            return

        current_time = dt_util.now()
        expiry_time = dt_util.utc_from_timestamp(expires_at)
        access_token_remaining = expiry_time - current_time

        if refresh_token_expires_in:
            if token_issued_at_timestamp:
                token_issued_at = dt_util.utc_from_timestamp(token_issued_at_timestamp)
            else:
                token_issued_at = expiry_time - timedelta(
                    seconds=token_data.get("expires_in", 1200)
                )

            refresh_token_expires_at = token_issued_at + timedelta(
                seconds=refresh_token_expires_in
            )
            refresh_token_remaining = refresh_token_expires_at - current_time

            _LOGGER.info(
                "Token status - Access token: %s remaining, Refresh token: %s remaining (expires: %s)",
                str(access_token_remaining).split(".")[0],  # Remove microseconds
                str(refresh_token_remaining).split(".")[0],
                refresh_token_expires_at.strftime("%Y-%m-%d %H:%M:%S"),
            )

            if refresh_token_remaining.total_seconds() < 300:  # Less than 5 minutes
                _LOGGER.warning(
                    "CRITICAL: Refresh token expires in %s! Reauthentication may be required soon.",
                    str(refresh_token_remaining).split(".")[0],
                )
        else:
            _LOGGER.info(
                "Token status - Access token: %s remaining (expires: %s). "
                "Note: Refresh token lifetime unknown (not provided by Saxo).",
                str(access_token_remaining).split(".")[0],
                expiry_time.strftime("%Y-%m-%d %H:%M:%S"),
            )

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

    async def _fetch_performance_data_safely(
        self, client: SaxoApiClient
    ) -> dict[str, Any]:
        """Fetch performance and client data with graceful error handling.

        This method wraps all performance/client detail fetching with its own
        timeout. If the fetch times out or fails, cached/default values are
        returned instead of raising an exception.

        This ensures that balance data can be returned successfully even when
        the performance API is slow or unresponsive.

        Args:
            client: The Saxo API client to use for requests

        Returns:
            Dictionary with performance and client data (fresh or cached/default)

        """
        # Use cached values as defaults - these are used if fetch fails
        defaults = {
            "ytd_earnings_percentage": self._performance_data_cache.get(
                "ytd_earnings_percentage", 0.0
            ),
            "investment_performance_percentage": self._performance_data_cache.get(
                "investment_performance_percentage", 0.0
            ),
            "ytd_investment_performance_percentage": self._performance_data_cache.get(
                "ytd_investment_performance_percentage", 0.0
            ),
            "month_investment_performance_percentage": self._performance_data_cache.get(
                "month_investment_performance_percentage", 0.0
            ),
            "quarter_investment_performance_percentage": self._performance_data_cache.get(
                "quarter_investment_performance_percentage", 0.0
            ),
            "cash_transfer_balance": self._performance_data_cache.get(
                "cash_transfer_balance", 0.0
            ),
            "client_id": self._performance_data_cache.get("client_id", "unknown"),
            "account_id": self._performance_data_cache.get("account_id", "unknown"),
            "client_name": self._performance_data_cache.get("client_name", "unknown"),
        }

        # Check if we should update performance data or use cached values
        should_update_performance = self._should_update_performance_data()

        if not should_update_performance:
            _LOGGER.debug("Using cached performance data")
            return defaults

        _LOGGER.debug("Updating performance data (cache expired or missing)")

        try:
            async with async_timeout.timeout(PERFORMANCE_FETCH_TIMEOUT):
                # Initialize values from defaults
                ytd_earnings_percentage = defaults["ytd_earnings_percentage"]
                investment_performance_percentage = defaults[
                    "investment_performance_percentage"
                ]
                ytd_investment_performance_percentage = defaults[
                    "ytd_investment_performance_percentage"
                ]
                month_investment_performance_percentage = defaults[
                    "month_investment_performance_percentage"
                ]
                quarter_investment_performance_percentage = defaults[
                    "quarter_investment_performance_percentage"
                ]
                cash_transfer_balance = defaults["cash_transfer_balance"]
                client_id = defaults["client_id"]
                account_id = defaults["account_id"]
                client_name = defaults["client_name"]

                # Add delay before client details call to prevent burst
                await asyncio.sleep(0.5)

                # Get client details (ClientKey, ClientId, etc.)
                client_details = None
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
                        account_id = client_details.get("DefaultAccountId", "unknown")
                        client_name = client_details.get("Name", "unknown")

                        _LOGGER.debug(
                            "Extracted from client details - ClientId: %s, DefaultAccountId: %s, Name: '%s'",
                            client_id,
                            account_id,
                            client_name,
                        )

                        if client_key:
                            _LOGGER.debug(
                                "Found ClientKey from client details, attempting performance fetch"
                            )
                            # Fetch performance v3 data
                            try:
                                performance_data = await client.get_performance(
                                    client_key
                                )
                                balance_performance = performance_data.get(
                                    "BalancePerformance", {}
                                )
                                accumulated_profit_loss = balance_performance.get(
                                    "AccumulatedProfitLoss", 0.0
                                )
                                ytd_earnings_percentage = accumulated_profit_loss
                                _LOGGER.debug(
                                    "Retrieved performance v3 data, AccumulatedProfitLoss: %s",
                                    accumulated_profit_loss,
                                )
                            except Exception as perf_e:
                                _LOGGER.debug(
                                    "Could not fetch performance v3 data: %s",
                                    type(perf_e).__name__,
                                )

                            # Fetch all v4 performance data in a batch
                            try:
                                await asyncio.sleep(0.5)
                                performance_v4_batch = (
                                    await client.get_performance_v4_batch(client_key)
                                )

                                # Extract AllTime performance data
                                performance_v4_data = performance_v4_batch.get(
                                    "alltime", {}
                                )
                                key_figures = performance_v4_data.get("KeyFigures", {})
                                return_fraction = key_figures.get("ReturnFraction", 0.0)
                                investment_performance_percentage = (
                                    return_fraction * 100.0
                                )

                                # Extract latest CashTransfer value
                                balance = performance_v4_data.get("Balance", {})
                                cash_transfer_list = balance.get("CashTransfer", [])
                                if cash_transfer_list:
                                    latest_cash_transfer = cash_transfer_list[-1]
                                    cash_transfer_balance = latest_cash_transfer.get(
                                        "Value", 0.0
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
                                quarter_data = performance_v4_batch.get("quarter", {})
                                quarter_key_figures = quarter_data.get("KeyFigures", {})
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
                                "No ClientKey found from client details endpoint"
                            )
                    else:
                        _LOGGER.debug("No client details available")
                except Exception as client_e:
                    _LOGGER.debug(
                        "Could not fetch client details: %s - %s",
                        type(client_e).__name__,
                        str(client_e),
                    )

                # Update performance data cache with fresh data
                result = {
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

                # Update cache
                self._performance_data_cache = result.copy()
                self._performance_last_updated = datetime.now()
                _LOGGER.debug("Updated performance data cache")

                # Update config entry title with client ID for better identification
                self._update_config_entry_title_if_needed(client_id)

                return result

        except TimeoutError:
            _LOGGER.warning(
                "Performance data fetch timed out after %ds, using cached/default values. "
                "Balance data will still be available.",
                PERFORMANCE_FETCH_TIMEOUT,
            )
            return defaults

        except Exception as e:
            _LOGGER.debug(
                "Performance data fetch failed: %s, using cached/default values",
                type(e).__name__,
            )
            return defaults

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

        Includes retry logic for transient failures (5xx, network errors).
        Only raises ConfigEntryAuthFailed for permanent failures (401, 403).

        Returns:
            New token data

        Raises:
            ConfigEntryAuthFailed: If token refresh fails permanently
            UpdateFailed: If token refresh fails due to transient issues after retries

        """
        token_data = self.config_entry.data.get("token", {})
        refresh_token = token_data.get("refresh_token")

        if not refresh_token:
            raise ConfigEntryAuthFailed("No refresh token available")

        # Log current token status before attempting refresh
        self._log_refresh_token_status()

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
                _LOGGER.debug(
                    "Using HTTP Basic Auth for token refresh with client_id: %s",
                    client_id[:8] + "..." if len(client_id) > 8 else client_id,
                )

                # Get the correct redirect_uri from the OAuth implementation
                if hasattr(implementation, "redirect_uri"):
                    redirect_uri = implementation.redirect_uri
                    _LOGGER.debug(
                        "Using redirect_uri from OAuth implementation: %s",
                        redirect_uri,
                    )
                else:
                    _LOGGER.warning("OAuth implementation has no redirect_uri property")
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
                _LOGGER.debug("Using redirect_uri from config entry: %s", redirect_uri)
            else:
                _LOGGER.error(
                    "No redirect_uri found in OAuth implementation or config entry. "
                    "This will likely cause token refresh to fail."
                )

        # Build refresh request data
        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        if redirect_uri:
            refresh_data["redirect_uri"] = redirect_uri

        # Token refresh requests should use application/x-www-form-urlencoded
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        # Retry loop for transient failures
        last_error: Exception | None = None
        last_status: int | None = None

        for attempt in range(MAX_RETRIES):
            try:
                _LOGGER.debug(
                    "Token refresh attempt %d/%d to %s",
                    attempt + 1,
                    MAX_RETRIES,
                    token_url,
                )

                async with session.post(
                    token_url, data=refresh_data, headers=headers, auth=auth
                ) as response:
                    last_status = response.status

                    _LOGGER.debug(
                        "Token refresh response: status=%d",
                        response.status,
                    )

                    # Success
                    if response.status in [200, 201]:
                        new_token_data = await response.json()

                        # Calculate expiry time and store when token was issued
                        current_timestamp = datetime.now().timestamp()
                        expires_in = new_token_data.get("expires_in", 1200)
                        expires_at = current_timestamp + expires_in
                        new_token_data["expires_at"] = expires_at
                        new_token_data["token_issued_at"] = current_timestamp

                        # Preserve config data, update token
                        new_data = self.config_entry.data.copy()
                        new_data["token"] = new_token_data

                        self.hass.config_entries.async_update_entry(
                            self.config_entry, data=new_data
                        )

                        # Close old API client before forcing recreation with new token
                        if self._api_client is not None:
                            old_client = self._api_client
                            self._api_client = None
                            self.hass.async_create_task(
                                self._close_old_client(old_client)
                            )
                        else:
                            self._api_client = None

                        token_expires = datetime.fromtimestamp(
                            new_token_data["expires_at"]
                        )
                        _LOGGER.info(
                            "Successfully refreshed OAuth token (expires: %s)",
                            token_expires.isoformat(),
                        )

                        # Log new token status
                        self._log_refresh_token_status()

                        return new_token_data

                    # Permanent auth failures - don't retry
                    if response.status in [401, 403]:
                        error_text = await response.text()

                        # Extract meaningful error from HTML if present
                        if "<html" in error_text.lower():
                            error_message = self._extract_error_from_html(error_text)
                        else:
                            error_message = (
                                error_text[:200] if error_text else "No details"
                            )

                        _LOGGER.error(
                            "Token refresh failed with HTTP %d: %s",
                            response.status,
                            error_message,
                        )

                        if response.status == 401:
                            _LOGGER.error(
                                "401 Unauthorized - Possible causes: "
                                "(1) Refresh token expired - reauthentication required, "
                                "(2) redirect_uri mismatch (%s), "
                                "(3) Invalid client credentials",
                                redirect_uri if redirect_uri else "NOT SET",
                            )
                            _LOGGER.info(
                                "To reauthenticate: Go to Settings > Devices & Services > "
                                "Saxo Portfolio and click 'Reauthenticate'"
                            )

                        raise ConfigEntryAuthFailed(
                            f"Token refresh failed: {error_message}"
                        )

                    # Transient server errors (5xx) - retry with backoff
                    if response.status >= 500:
                        error_text = await response.text()
                        if "<html" in error_text.lower():
                            error_message = self._extract_error_from_html(error_text)
                        else:
                            error_message = (
                                error_text[:200] if error_text else "Server error"
                            )

                        if attempt < MAX_RETRIES - 1:
                            backoff_time = RETRY_BACKOFF_FACTOR**attempt
                            _LOGGER.warning(
                                "Token refresh got HTTP %d (attempt %d/%d): %s. "
                                "Retrying in %d seconds...",
                                response.status,
                                attempt + 1,
                                MAX_RETRIES,
                                error_message,
                                backoff_time,
                            )
                            await asyncio.sleep(backoff_time)
                            continue
                        else:
                            last_error = UpdateFailed(
                                f"Token refresh failed after {MAX_RETRIES} attempts: "
                                f"HTTP {response.status} - {error_message}"
                            )

                    # Other errors (4xx except 401/403)
                    else:
                        error_text = await response.text()
                        if "<html" in error_text.lower():
                            error_message = self._extract_error_from_html(error_text)
                        else:
                            error_message = (
                                error_text[:200] if error_text else "Unknown error"
                            )

                        _LOGGER.error(
                            "Token refresh failed with HTTP %d: %s",
                            response.status,
                            error_message,
                        )
                        raise ConfigEntryAuthFailed(
                            f"Token refresh failed: HTTP {response.status} - {error_message}"
                        )

            except ConfigEntryAuthFailed:
                # Re-raise auth failures immediately
                raise

            except aiohttp.ClientError as e:
                # Network errors - retry with backoff
                if attempt < MAX_RETRIES - 1:
                    backoff_time = RETRY_BACKOFF_FACTOR**attempt
                    _LOGGER.warning(
                        "Token refresh network error (attempt %d/%d): %s. "
                        "Retrying in %d seconds...",
                        attempt + 1,
                        MAX_RETRIES,
                        type(e).__name__,
                        backoff_time,
                    )
                    await asyncio.sleep(backoff_time)
                    continue
                else:
                    last_error = UpdateFailed(
                        f"Token refresh failed after {MAX_RETRIES} attempts: {type(e).__name__}"
                    )

            except TimeoutError:
                # Timeout - retry with backoff
                if attempt < MAX_RETRIES - 1:
                    backoff_time = RETRY_BACKOFF_FACTOR**attempt
                    _LOGGER.warning(
                        "Token refresh timeout (attempt %d/%d). Retrying in %d seconds...",
                        attempt + 1,
                        MAX_RETRIES,
                        backoff_time,
                    )
                    await asyncio.sleep(backoff_time)
                    continue
                else:
                    last_error = UpdateFailed(
                        f"Token refresh timed out after {MAX_RETRIES} attempts"
                    )

        # All retries exhausted
        if last_error:
            _LOGGER.error(
                "Token refresh failed after %d attempts (last status: %s): %s",
                MAX_RETRIES,
                last_status,
                last_error,
            )
            raise last_error

        raise UpdateFailed("Token refresh failed unexpectedly")

    async def _fetch_portfolio_data(self) -> dict[str, Any]:
        """Fetch portfolio data from Saxo API.

        This method implements graceful degradation:
        - Balance data is required and fetched first
        - Performance data is optional and fetched with a separate timeout
        - If performance fetch fails/times out, balance data is still returned

        Returns:
            Portfolio data dictionary

        Raises:
            ConfigEntryAuthFailed: For authentication errors
            UpdateFailed: For other errors (balance fetch failures)

        """
        try:
            # Apply staggered update offset on scheduled updates to prevent multiple accounts
            # from hitting the API simultaneously. Skip during initial setup (called from
            # async_setup_entry) to avoid exceeding Home Assistant's setup timeout.
            # Initial setup is detected by _last_successful_update being None.
            if (
                self._initial_update_offset > 0
                and self._last_successful_update is not None
            ):
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

            _LOGGER.debug(
                "About to fetch balance from: %s%s",
                client.base_url,
                "/port/v1/balances/me",
            )

            fetch_start_time = datetime.now()

            # STEP 1: Fetch balance data (REQUIRED)
            # This must succeed for the update to be successful
            balance_start_time = datetime.now()
            balance_data = await client.get_account_balance()

            balance_duration = (datetime.now() - balance_start_time).total_seconds()
            _LOGGER.debug("Balance data fetch completed in %.2fs", balance_duration)
            _LOGGER.debug(
                "Balance data keys: %s",
                list(balance_data.keys()) if balance_data else "No balance data",
            )

            # Remove detailed margin info to reduce log noise
            if "MarginCollateralNotAvailableDetail" in balance_data:
                del balance_data["MarginCollateralNotAvailableDetail"]

            # STEP 2: Fetch performance data (OPTIONAL - graceful degradation)
            # This has its own timeout and never raises exceptions
            # If it fails/times out, cached/default values are returned
            performance_data = await self._fetch_performance_data_safely(client)

            # STEP 3: Combine balance and performance data
            result = {
                "cash_balance": balance_data.get("CashBalance", 0.0),
                "currency": balance_data.get("Currency", "USD"),
                "total_value": balance_data.get("TotalValue", 0.0),
                "non_margin_positions_value": balance_data.get(
                    "NonMarginPositionsValue", 0.0
                ),
                **performance_data,
                "last_updated": datetime.now().isoformat(),
            }

            # Log total fetch duration
            total_duration = (datetime.now() - fetch_start_time).total_seconds()
            _LOGGER.debug(
                "Complete portfolio data fetch completed in %.2fs", total_duration
            )

            return result

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

    def _update_config_entry_title_if_needed(self, client_id: str) -> None:
        """Update config entry title to include Client ID for identification.

        When multiple integrations are configured, this makes it clear which
        account each integration represents, especially during reauthentication.

        Args:
            client_id: The Saxo Client ID to include in the title

        """
        if client_id == "unknown":
            return

        current_title = self.config_entry.title
        expected_title = f"Saxo Portfolio ({client_id})"

        # Only update if title is still generic (doesn't already include client ID)
        if current_title == "Saxo Portfolio" or (
            "(" not in current_title and client_id not in current_title
        ):
            _LOGGER.info(
                "Updating config entry title from '%s' to '%s' for better identification",
                current_title,
                expected_title,
            )
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                title=expected_title,
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
