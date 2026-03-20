"""DataUpdateCoordinator for Saxo Portfolio integration.

This coordinator manages data fetching from the Saxo API and coordinates
updates across all sensors.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time
import zoneinfo
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

import aiohttp

from .api.saxo_client import SaxoApiClient, AuthenticationError, APIError
from .const import (
    CONF_ENABLE_POSITION_SENSORS,
    CONF_TIMEZONE,
    COORDINATOR_UPDATE_TIMEOUT,
    DEFAULT_ENABLE_POSITION_SENSORS,
    DEFAULT_TIMEZONE,
    DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
    DEFAULT_UPDATE_INTERVAL_ANY,
    DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
    DOMAIN,
    MARKET_HOURS,
    PERFORMANCE_FETCH_TIMEOUT,
    PERFORMANCE_UPDATE_INTERVAL,
    REFRESH_TOKEN_BUFFER,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class PositionData:
    """Data class for a single portfolio position."""

    position_id: str
    symbol: str
    description: str
    asset_type: str
    amount: float
    current_price: float
    market_value: float
    profit_loss: float
    uic: int
    currency: str = "USD"

    @staticmethod
    def generate_slug(symbol: str, asset_type: str) -> str:
        """Generate a URL-safe slug for the position.

        Args:
            symbol: The position symbol (e.g., "AAPL", "EUR/USD")
            asset_type: The asset type (e.g., "Stock", "FxSpot")

        Returns:
            A lowercase slug suitable for entity IDs (e.g., "aapl_stock", "eur_usd_fxspot")

        """
        # Clean and lowercase the symbol
        clean_symbol = re.sub(r"[^a-zA-Z0-9]", "_", symbol.lower())
        # Remove consecutive underscores and strip leading/trailing underscores
        clean_symbol = re.sub(r"_+", "_", clean_symbol).strip("_")

        # Clean and lowercase the asset type
        clean_asset_type = re.sub(r"[^a-zA-Z0-9]", "_", asset_type.lower())
        clean_asset_type = re.sub(r"_+", "_", clean_asset_type).strip("_")

        return f"{clean_symbol}_{clean_asset_type}"


@dataclass
class PositionsCache:
    """Cache for portfolio positions data."""

    positions: dict[str, PositionData] = field(default_factory=dict)
    last_updated: datetime | None = None
    position_ids: list[str] = field(default_factory=list)


class SaxoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Saxo Portfolio data coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        oauth_session: config_entry_oauth2_flow.OAuth2Session,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            config_entry: Configuration entry with OAuth token
            oauth_session: OAuth2 session for automatic token management

        """
        self.config_entry = config_entry
        self._oauth_session = oauth_session
        self._api_client: SaxoApiClient | None = None
        self._last_successful_update: datetime | None = None

        # Performance data caching
        self._performance_data_cache: dict[str, Any] = {}
        self._performance_last_updated: datetime | None = None

        # Positions data caching
        self._positions_cache = PositionsCache()
        self._enable_position_sensors = config_entry.options.get(
            CONF_ENABLE_POSITION_SENSORS,
            config_entry.data.get(
                CONF_ENABLE_POSITION_SENSORS, DEFAULT_ENABLE_POSITION_SENSORS
            ),
        )
        self._position_market_data_warning_logged = False
        self._has_market_data_access: bool | None = None  # None = unknown/not checked

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
        token_data = self._oauth_session.token
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
            async with asyncio.timeout(PERFORMANCE_FETCH_TIMEOUT):
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

    async def _fetch_positions_data_safely(
        self, client: SaxoApiClient
    ) -> dict[str, PositionData]:
        """Fetch positions data with graceful error handling.

        This method wraps positions fetching with error handling. If the fetch
        fails, an empty dictionary is returned instead of raising an exception.

        Args:
            client: The Saxo API client to use for requests

        Returns:
            Dictionary mapping position IDs to PositionData objects

        """
        if not self._enable_position_sensors:
            _LOGGER.debug("Position sensors disabled, skipping fetch")
            return {}

        try:
            # Add delay before positions call to prevent rate limiting
            await asyncio.sleep(0.5)

            positions_response = await client.get_net_positions()

            # Parse positions from API response
            positions: dict[str, PositionData] = {}
            raw_positions = positions_response.get("Data", [])

            _LOGGER.debug(
                "Fetched %d raw positions from API, response keys: %s",
                len(raw_positions) if raw_positions else 0,
                list(positions_response.keys()),
            )

            # Log first position structure for debugging
            if raw_positions:
                _LOGGER.debug(
                    "Processing %d positions for market data access check",
                    len(raw_positions),
                )
                _LOGGER.debug(
                    "First raw position structure: %s",
                    raw_positions[0],
                )

                # Check for market data access by inspecting first position
                first_view = raw_positions[0].get("NetPositionView", {})
                current_price_type = first_view.get("CurrentPriceType", "")
                calc_reliability = first_view.get("CalculationReliability", "")

                _LOGGER.debug(
                    "Market data access check - CurrentPriceType: %r, CalculationReliability: %r",
                    current_price_type,
                    calc_reliability,
                )

                has_market_access = not (
                    current_price_type == "None"
                    or calc_reliability in ("NoMarketAccess", "ApproximatedPrice")
                )
                self._has_market_data_access = has_market_access

                _LOGGER.debug(
                    "Market data access determined: %s",
                    "Available" if has_market_access else "Unavailable",
                )

                # Log warning once if no market data access
                if (
                    not has_market_access
                    and not self._position_market_data_warning_logged
                ):
                    _LOGGER.warning(
                        "Market data access not available for positions API. "
                        "Position prices are calculated from P/L data and may not "
                        "reflect real-time values. Real-time market data may require "
                        "a separate market data subscription on your Saxo account. "
                        "Contact Saxo support for more information"
                    )
                    self._position_market_data_warning_logged = True
            else:
                _LOGGER.debug(
                    "No positions in portfolio - cannot determine market data access status"
                )

            for raw_position in raw_positions:
                try:
                    # Log the raw position structure for debugging
                    _LOGGER.debug(
                        "Raw position keys: %s",
                        list(raw_position.keys()),
                    )

                    # Extract base position data
                    net_position_base = raw_position.get("NetPositionBase", {})
                    net_position_view = raw_position.get("NetPositionView", {})
                    display_and_format = raw_position.get("DisplayAndFormat", {})

                    # Also check for PositionView (individual position data with prices)
                    position_view = raw_position.get("PositionView", {})

                    _LOGGER.debug(
                        "Position data - NetPositionView: %s, PositionView: %s",
                        net_position_view,
                        position_view,
                    )

                    # Extract required fields
                    position_id = raw_position.get("NetPositionId", "")
                    uic = net_position_base.get("Uic", 0)
                    asset_type = net_position_base.get("AssetType", "Unknown")
                    amount = net_position_base.get("Amount", 0.0)

                    # Extract display info
                    symbol = display_and_format.get("Symbol", "")
                    description = display_and_format.get("Description", "")
                    currency = display_and_format.get("Currency", "USD")

                    # Extract profit/loss first (needed for price calculation)
                    profit_loss = (
                        net_position_view.get("ProfitLossOnTrade")
                        or net_position_view.get("ProfitLossOnTradeInBaseCurrency")
                        or 0.0
                    )

                    # MarketValueOpen is the cost basis (negative = money spent)
                    # Current market value = abs(cost basis) + profit/loss
                    market_value_open = net_position_view.get("MarketValueOpen", 0.0)

                    # Calculate current market value from cost basis + P/L
                    if market_value_open != 0.0:
                        market_value = abs(market_value_open) + profit_loss
                    else:
                        # Fallback to Exposure if available
                        market_value = net_position_view.get("Exposure", 0.0)

                    # Try to get CurrentPrice directly first
                    current_price = net_position_view.get("CurrentPrice", 0.0)

                    # If CurrentPrice is 0.0, calculate from market value and amount
                    if current_price == 0.0 and market_value != 0.0 and amount != 0.0:
                        current_price = market_value / abs(amount)
                        _LOGGER.debug(
                            "Calculated price: (cost=%s + pnl=%s) / amount=%s = %s",
                            abs(market_value_open),
                            profit_loss,
                            amount,
                            current_price,
                        )

                    # Skip if no symbol
                    if not symbol:
                        _LOGGER.debug("Skipping position %s: no symbol", position_id)
                        continue

                    # Generate a unique slug for this position
                    slug = PositionData.generate_slug(symbol, asset_type)

                    position_data = PositionData(
                        position_id=position_id,
                        symbol=symbol,
                        description=description,
                        asset_type=asset_type,
                        amount=amount,
                        current_price=current_price,
                        market_value=market_value,
                        profit_loss=profit_loss,
                        uic=uic,
                        currency=currency,
                    )

                    positions[slug] = position_data

                    _LOGGER.debug(
                        "Parsed position: %s (%s) - %s units @ %s",
                        symbol,
                        asset_type,
                        amount,
                        current_price,
                    )

                except Exception as pos_error:
                    _LOGGER.debug(
                        "Error parsing position: %s",
                        type(pos_error).__name__,
                    )
                    continue

            # Update cache
            self._positions_cache.positions = positions
            self._positions_cache.position_ids = list(positions.keys())
            self._positions_cache.last_updated = datetime.now()

            _LOGGER.debug(
                "Updated positions cache with %d positions: %s",
                len(positions),
                list(positions.keys()),
            )

            return positions

        except Exception as e:
            _LOGGER.debug(
                "Positions data fetch failed: %s, returning cached/empty",
                type(e).__name__,
            )
            return self._positions_cache.positions

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

    async def _ensure_token_valid(self) -> None:
        """Ensure the OAuth token is valid, refreshing if needed.

        Checks Saxo-specific refresh token expiry (HA doesn't handle this),
        then delegates access token refresh to OAuth2Session.

        Raises:
            ConfigEntryAuthFailed: If refresh token has expired

        """
        token_data = self._oauth_session.token

        # Check Saxo-specific refresh token expiry
        refresh_token_expires_in = token_data.get("refresh_token_expires_in")
        if refresh_token_expires_in:
            token_issued_at_timestamp = token_data.get("token_issued_at")
            expires_at = token_data.get("expires_at")

            if token_issued_at_timestamp:
                token_issued_at = datetime.fromtimestamp(token_issued_at_timestamp)
            elif expires_at:
                token_issued_at = datetime.fromtimestamp(expires_at) - timedelta(
                    seconds=token_data.get("expires_in", 1200)
                )
            else:
                token_issued_at = datetime.now()

            refresh_token_expires_at = token_issued_at + timedelta(
                seconds=refresh_token_expires_in
            )

            current_time = datetime.now()

            if current_time >= refresh_token_expires_at:
                _LOGGER.error(
                    "Refresh token has expired (expired at %s). Reauth required.",
                    refresh_token_expires_at.isoformat(),
                )
                raise ConfigEntryAuthFailed(
                    "Refresh token expired - please reauthenticate in Settings > Devices & Services"
                )

            remaining = refresh_token_expires_at - current_time
            if remaining <= REFRESH_TOKEN_BUFFER:
                _LOGGER.warning(
                    "Refresh token will expire soon (%s remaining). Triggering proactive refresh.",
                    str(remaining).split(".")[0],
                )

        # Delegate access token refresh to OAuth2Session
        await self._oauth_session.async_ensure_token_valid()

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

            # Ensure OAuth token is valid (refresh if needed)
            await self._ensure_token_valid()

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

            # STEP 3: Fetch positions data (OPTIONAL - only if enabled)
            # This also uses graceful degradation
            await self._fetch_positions_data_safely(client)

            # STEP 4: Combine balance and performance data
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

        except aiohttp.ClientError as e:
            _LOGGER.warning(
                "Network error during portfolio update (%s). "
                "This may be caused by a token refresh failure or Saxo API connectivity issue. "
                "The integration will automatically retry on the next update cycle.",
                type(e).__name__,
            )
            raise UpdateFailed(
                "Network error - check connectivity and try again"
            ) from e

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

    def get_positions(self) -> dict[str, PositionData]:
        """Get all cached positions.

        Returns:
            Dictionary mapping position slugs to PositionData objects

        """
        return self._positions_cache.positions

    def get_position(self, slug: str) -> PositionData | None:
        """Get a specific position by slug.

        Args:
            slug: The position slug (e.g., "aapl_stock")

        Returns:
            PositionData for the position, or None if not found

        """
        return self._positions_cache.positions.get(slug)

    def get_position_ids(self) -> list[str]:
        """Get list of all position slugs.

        Returns:
            List of position slugs

        """
        return self._positions_cache.position_ids

    def has_market_data_access(self) -> bool | None:
        """Check if the API has access to real-time market data.

        Returns:
            True if market data access is available,
            False if prices are calculated from P/L data,
            None if not yet determined (no positions fetched)

        """
        return self._has_market_data_access

    @property
    def position_sensors_enabled(self) -> bool:
        """Check if position sensors are enabled.

        Returns:
            True if position sensors are enabled

        """
        return self._enable_position_sensors

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
