"""DataUpdateCoordinator for Saxo Portfolio integration.

This coordinator manages data fetching from the Saxo API and coordinates
updates across all sensors.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, time
import pytz
from typing import Any

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
from .models import CoordinatorData

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

            # Get base URL from environment config
            environment = self.config_entry.data.get("environment", "simulation")
            from .const import ENVIRONMENTS
            base_url = ENVIRONMENTS[environment]["api_base_url"]

            session = async_get_clientsession(self.hass)
            self._api_client = SaxoApiClient(access_token, base_url, session)

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
            eastern = pytz.timezone('US/Eastern')
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
                is_open
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
                    TOKEN_REFRESH_BUFFER
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

        try:
            # Get environment configuration
            environment = self.config_entry.data.get("environment", "simulation")
            from .const import ENVIRONMENTS, OAUTH_TOKEN_ENDPOINT
            auth_base_url = ENVIRONMENTS[environment]["auth_base_url"]

            # Prepare refresh request
            token_url = f"{auth_base_url}{OAUTH_TOKEN_ENDPOINT}"

            # Use Home Assistant's aiohttp session
            session = async_get_clientsession(self.hass)

            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }

            # Add client credentials if available
            app_key = self.config_entry.data.get("app_key")
            app_secret = self.config_entry.data.get("app_secret")

            auth = None
            if app_key and app_secret:
                import aiohttp
                auth = aiohttp.BasicAuth(app_key, app_secret)

            async with session.post(token_url, data=refresh_data, auth=auth) as response:
                if response.status == 200:
                    new_token_data = await response.json()

                    # Calculate expiry time
                    expires_in = new_token_data.get("expires_in", 1200)
                    expires_at = (datetime.now() + timedelta(seconds=expires_in)).timestamp()
                    new_token_data["expires_at"] = expires_at

                    # Update config entry with new token
                    new_data = self.config_entry.data.copy()
                    new_data["token"] = new_token_data

                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=new_data
                    )

                    # Update API client with new token
                    self._api_client = None  # Force recreation with new token

                    # Store refresh success info
                    token_expires = datetime.fromtimestamp(new_token_data["expires_at"])
                    _LOGGER.info(
                        "Successfully refreshed OAuth token (expires: %s)",
                        token_expires.isoformat()
                    )

                    return new_token_data
                else:
                    error_data = await response.text()
                    _LOGGER.error("Token refresh failed: HTTP %d", response.status)
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

            # Fetch data from multiple endpoints concurrently
            async with async_timeout.timeout(COORDINATOR_UPDATE_TIMEOUT):
                # Get balance data (required)
                balance_task = asyncio.create_task(client.get_account_balance())

                # Get positions data
                positions_task = asyncio.create_task(client.get_positions())

                # Get accounts data - need a client key
                # Extract account ID from positions to fetch detailed account information
                # This follows Saxo API pattern where positions contain account references
                balance_data = await balance_task
                positions_data = await positions_task

                # Try to get accounts data if we have positions
                accounts_data = {"__count": 0, "Data": []}
                if positions_data.get("Data"):
                    # Use first position's account ID as client key approximation
                    first_position = positions_data["Data"][0]
                    account_id = first_position["PositionBase"]["AccountId"]
                    try:
                        accounts_task = asyncio.create_task(client.get_accounts(account_id))
                        accounts_data = await accounts_task
                    except Exception as e:
                        _LOGGER.warning("Could not fetch accounts data: %s", type(e).__name__)
                        # Fallback: Create minimal account data from position information
                        # This ensures sensors work even if accounts endpoint is restricted
                        accounts_data = {
                            "__count": 1,
                            "Data": [{
                                "AccountId": account_id,
                                "AccountKey": f"ak_{account_id}",
                                "AccountType": "Normal",
                                "Active": True,
                                "Currency": balance_data.get("Currency", "USD"),
                                "DisplayName": f"Account {account_id}"
                            }]
                        }

                # Create coordinated data model
                coordinator_data = CoordinatorData.from_api_responses(
                    balance_data, positions_data, accounts_data
                )

                return coordinator_data.to_dict()

        except AuthenticationError as e:
            _LOGGER.error("Authentication error: %s", type(e).__name__)
            raise ConfigEntryAuthFailed("Authentication failed") from e

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
                new_interval
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

    def get_portfolio_sensor_data(self, sensor_type: str) -> Any:
        """Get data for portfolio-level sensors.
        
        Args:
            sensor_type: Type of sensor data to retrieve
            
        Returns:
            Sensor value or None if not available

        """
        if not self.data or "portfolio" not in self.data:
            return None

        portfolio_data = self.data["portfolio"]

        sensor_map = {
            "total_value": "total_value",
            "cash_balance": "cash_balance",
            "unrealized_pnl": "unrealized_pnl",
            "positions_count": "positions_count",
            "pnl_percentage": "pnl_percentage"
        }

        field_name = sensor_map.get(sensor_type)
        if field_name:
            return portfolio_data.get(field_name)

        return None

    def get_account_sensor_data(self, account_id: str) -> dict[str, Any] | None:
        """Get data for account-specific sensors.
        
        Args:
            account_id: Account identifier
            
        Returns:
            Account data or None if not found

        """
        if not self.data or "accounts" not in self.data:
            return None

        for account in self.data["accounts"]:
            if account.get("account_id") == account_id:
                return account

        return None

    def get_position_sensor_data(self, position_id: str) -> dict[str, Any] | None:
        """Get data for position-specific sensors.
        
        Args:
            position_id: Position identifier
            
        Returns:
            Position data or None if not found

        """
        if not self.data or "positions" not in self.data:
            return None

        for position in self.data["positions"]:
            if position.get("position_id") == position_id:
                return position

        return None

    def get_currency(self) -> str:
        """Get the portfolio base currency.
        
        Returns:
            Currency code or USD as default

        """
        if self.data and "portfolio" in self.data:
            return self.data["portfolio"].get("currency", "USD")
        return "USD"

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
                new_interval
            )
            self.update_interval = new_interval
