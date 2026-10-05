"""DataUpdateCoordinator for Saxo Portfolio integration.

The coordinator schedules updates (market-hours aware, with a stagger across
accounts), keeps the OAuth token valid, and assembles the typed
:class:`SaxoPortfolioData` that sensors read. Parsing of the Saxo API
responses lives in ``data.py`` (balance), ``performance.py`` (client
details and performance) and ``positions.py`` (net positions).
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, time
import zoneinfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

import aiohttp

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.saxo_client import SaxoApiClient, AuthenticationError, APIError
from .data import BalanceData, ClientInfo, SaxoPortfolioData
from .performance import PerformanceFetcher
from .positions import PositionData, PositionsFetcher
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
    REFRESH_TOKEN_BUFFER,
    REFRESH_TOKEN_REFRESH_AT_FRACTION,
)

_LOGGER = logging.getLogger(__name__)


class SaxoCoordinator(DataUpdateCoordinator[SaxoPortfolioData]):
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

        # Performance data (cached for PERFORMANCE_UPDATE_INTERVAL)
        self._performance = PerformanceFetcher(
            on_client_info=lambda client: self._update_config_entry_title_if_needed(
                client.client_id
            )
        )

        # Positions data (only fetched when position sensors are enabled)
        self._positions = PositionsFetcher(
            enabled=bool(
                config_entry.options.get(
                    CONF_ENABLE_POSITION_SENSORS,
                    config_entry.data.get(
                        CONF_ENABLE_POSITION_SENSORS, DEFAULT_ENABLE_POSITION_SENSORS
                    ),
                )
            )
        )

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
        self._timezone: str = config_entry.data.get(CONF_TIMEZONE, DEFAULT_TIMEZONE)
        # What the entry holds, kept apart from _timezone which is normalised
        # to the default when the configured value is unknown
        self._configured_timezone = self._timezone

        # Cache market hours check to avoid repeated calculations
        self._market_hours_cache: bool | None = None
        self._market_hours_cache_time: datetime | None = None
        self._last_timeout_warning: datetime | None = None
        self._warned_unknown_timezone: str | None = None

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
        """Get or create API client, using HA's shared HTTP session."""
        token_data = self._oauth_session.token
        access_token = token_data.get("access_token")

        if not access_token:
            raise ConfigEntryAuthFailed("No access token available")

        # A rotated token is handed to the existing client so its rate-limit
        # state (request window, Retry-After) survives token refreshes.
        if self._api_client is not None:
            self._api_client.access_token = access_token

        if self._api_client is None:
            from .const import SAXO_API_BASE_URL

            session = async_get_clientsession(self.hass)
            self._api_client = SaxoApiClient(access_token, SAXO_API_BASE_URL, session)
            _LOGGER.debug(
                "Created API client with HA session, base_url: %s",
                SAXO_API_BASE_URL,
            )

        return self._api_client

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
            timezone = self._timezone
            market_config = MARKET_HOURS.get(timezone)
            if not market_config:
                # Fall back to the default timezone without changing the
                # configured one
                if self._warned_unknown_timezone != timezone:
                    self._warned_unknown_timezone = timezone
                    _LOGGER.warning(
                        "Unknown timezone %s, falling back to %s",
                        timezone,
                        DEFAULT_TIMEZONE,
                    )
                timezone = DEFAULT_TIMEZONE
                market_config = MARKET_HOURS[DEFAULT_TIMEZONE]

            # Convert to market timezone
            tz = zoneinfo.ZoneInfo(timezone)
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

                # Close is exclusive: at exactly the close time, the market is
                # considered closed (e.g., 17:00:00 reads as "After Hours").
                is_open = market_open <= current_time < market_close

            _LOGGER.debug(
                "Market hours check for %s: %s, weekday: %s, is_open: %s",
                timezone,
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
        """Ensure the OAuth token is valid, refreshing proactively when needed.

        Strategy for surviving Saxo downtime:
        1. Once more than REFRESH_TOKEN_REFRESH_AT_FRACTION of the refresh-token
           lifetime has elapsed, force a refresh so the rotated refresh token has
           a full lifetime again. This caps the worst-case age of our refresh
           token, giving the integration runway against an outage.
        2. Transient failures during the proactive refresh (network errors,
           timeouts, 5xx from Saxo) are swallowed. The existing tokens are still
           valid on Saxo's side and the next coordinator cycle will retry.
        3. Only a hard `invalid_grant` style failure (HTTP 400/401) triggers
           ConfigEntryAuthFailed. We no longer preemptively declare the refresh
           token dead based on client-side math alone.
        4. After any proactive refresh attempt, fall through to OAuth2Session's
           async_ensure_token_valid() as a safety net for the access token.

        Raises:
            ConfigEntryAuthFailed: If Saxo explicitly rejects the refresh with
                an auth-level error (400/401 - invalid_grant or invalid_client).

        """
        token_data = self._oauth_session.token

        # Decide whether to force a proactive refresh based on refresh-token age.
        refresh_token_expires_in = token_data.get("refresh_token_expires_in")
        if refresh_token_expires_in:
            token_issued_at_timestamp = token_data.get("token_issued_at")
            expires_at = token_data.get("expires_at")

            # Token-age math runs in UTC so DST transitions don't distort elapsed.
            if token_issued_at_timestamp:
                token_issued_at = datetime.fromtimestamp(
                    token_issued_at_timestamp, tz=dt_util.UTC
                )
            elif expires_at:
                token_issued_at = datetime.fromtimestamp(
                    expires_at, tz=dt_util.UTC
                ) - timedelta(seconds=token_data.get("expires_in", 1200))
            else:
                token_issued_at = dt_util.utcnow()

            refresh_token_expires_at = token_issued_at + timedelta(
                seconds=refresh_token_expires_in
            )
            current_time = dt_util.utcnow()
            elapsed = current_time - token_issued_at
            half_life = timedelta(
                seconds=refresh_token_expires_in * REFRESH_TOKEN_REFRESH_AT_FRACTION
            )
            remaining = refresh_token_expires_at - current_time

            # Log a warning when the refresh token is near expiry - useful during
            # sustained Saxo outages where proactive refreshes keep failing.
            if timedelta(0) < remaining <= REFRESH_TOKEN_BUFFER:
                _LOGGER.warning(
                    "Refresh token will expire soon (%s remaining).",
                    str(remaining).split(".")[0],
                )

            if elapsed >= half_life:
                await self._proactive_refresh_token()
                # _proactive_refresh_token either succeeded (token rotated),
                # swallowed a transient error, or raised ConfigEntryAuthFailed.
                # Either way, fall through to the safety net below.

        # Safety net: delegate access token refresh to OAuth2Session. This is a
        # no-op if the access token is still valid (which it usually is after
        # a successful proactive refresh).
        await self._oauth_session.async_ensure_token_valid()

    async def _proactive_refresh_token(self) -> None:
        """Force a refresh of the OAuth token and persist the new token.

        Transient failures (network, timeout, 5xx) are logged and swallowed -
        our existing tokens remain usable and the next coordinator cycle will
        retry. Auth-level failures (400/401) are reclassified as
        ConfigEntryAuthFailed to trigger reauthentication.

        Raises:
            ConfigEntryAuthFailed: On invalid_grant / invalid_client responses.

        """
        implementation = self._oauth_session.implementation
        try:
            _LOGGER.debug(
                "Proactive token refresh triggered (refresh token past half-life)"
            )
            new_token = await implementation.async_refresh_token(
                self._oauth_session.token
            )
        except aiohttp.ClientResponseError as err:
            if err.status in (400, 401):
                _LOGGER.error(
                    "Proactive token refresh rejected by Saxo (HTTP %s) - "
                    "reauthentication required",
                    err.status,
                )
                raise ConfigEntryAuthFailed(
                    "Saxo rejected the refresh token - please reauthenticate in "
                    "Settings > Devices & Services"
                ) from err
            _LOGGER.warning(
                "Proactive token refresh deferred - Saxo returned HTTP %s. "
                "Existing token still valid, will retry on next update cycle.",
                err.status,
            )
            return
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.warning(
                "Proactive token refresh deferred - Saxo unreachable (%s). "
                "Existing token still valid, will retry on next update cycle.",
                type(err).__name__,
            )
            return

        # Persist the rotated token to the config entry so it survives HA
        # restarts during a subsequent outage. Mirrors what
        # OAuth2Session.async_ensure_token_valid does internally.
        assert self.config_entry is not None
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={**self.config_entry.data, "token": new_token},
        )
        _LOGGER.debug("Proactive token refresh succeeded, new token persisted")

    async def _fetch_portfolio_data(self) -> SaxoPortfolioData:
        """Fetch portfolio data from Saxo API.

        This method implements graceful degradation:
        - Balance data is required and fetched first
        - Performance data is optional and fetched with a separate timeout
        - If performance fetch fails/times out, balance data is still returned

        Returns:
            Typed portfolio data

        Raises:
            ConfigEntryAuthFailed: For authentication errors
            UpdateFailed: For other errors (balance fetch failures)

        """
        fetch_start_time: datetime | None = None
        try:
            await self._apply_initial_stagger_offset()

            # Bound the actual work (token refresh incl. retries, API calls) by an
            # overall timeout. The stagger sleep above is deliberately outside it.
            async with asyncio.timeout(COORDINATOR_UPDATE_TIMEOUT):
                # Ensure OAuth token is valid (refresh if needed)
                await self._ensure_token_valid()

                client = self.api_client
                _LOGGER.debug(
                    "Starting data fetch with client base_url: %s (production)",
                    client.base_url,
                )

                fetch_start_time = datetime.now()

                # STEP 1: Fetch balance data (REQUIRED)
                balance = await self._fetch_balance_with_logging(client)

                # STEP 2: Fetch performance data (OPTIONAL - graceful degradation)
                await self._performance.async_update(client)

                # STEP 3: Fetch positions data (OPTIONAL - only if enabled)
                await self._positions.async_fetch(client)

                # STEP 4: Combine balance and performance data
                result = SaxoPortfolioData(
                    balance=balance,
                    performance=self._performance.metrics,
                    client=self._performance.client,
                    last_updated=datetime.now(),
                )

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
            self._log_portfolio_timeout(fetch_start_time)
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

    async def _apply_initial_stagger_offset(self) -> None:
        """Sleep the one-shot stagger offset on the first scheduled update.

        Skips during initial setup (detected by ``_last_successful_update is None``)
        to avoid exceeding Home Assistant's setup timeout.
        """
        if self._initial_update_offset > 0 and self._last_successful_update is not None:
            _LOGGER.debug(
                "Applying initial update offset of %.1fs to stagger multiple accounts",
                self._initial_update_offset,
            )
            await asyncio.sleep(self._initial_update_offset)
            self._initial_update_offset = 0  # Only apply once

    async def _fetch_balance_with_logging(self, client: SaxoApiClient) -> BalanceData:
        """Fetch and parse the balance endpoint, logging timing and field names."""
        _LOGGER.debug("About to fetch balance from: %s", client.base_url)
        balance_start_time = datetime.now()
        balance_data = await client.get_account_balance()

        balance_duration = (datetime.now() - balance_start_time).total_seconds()
        _LOGGER.debug("Balance data fetch completed in %.2fs", balance_duration)
        _LOGGER.debug(
            "Balance data keys: %s",
            list(balance_data.keys()) if balance_data else "No balance data",
        )

        # Only the typed fields are kept; noisy extras such as
        # MarginCollateralNotAvailableDetail are dropped here.
        return BalanceData.from_api(balance_data)

    def _log_portfolio_timeout(self, fetch_start_time: datetime | None) -> None:
        """Log a portfolio-fetch timeout, rate-limiting repeats to debug level."""
        if fetch_start_time is not None:
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
            self._last_timeout_warning is None
            or (datetime.now() - self._last_timeout_warning).total_seconds() > 300
        ):  # 5 minutes
            _LOGGER.warning(timeout_msg)
            self._last_timeout_warning = datetime.now()
        else:
            _LOGGER.debug(timeout_msg)

    async def _async_update_data(self) -> SaxoPortfolioData:
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
            current_client_name = data.client.client_name

            # Debug logging to understand reload trigger
            _LOGGER.debug(
                "Reload check - last_known_name_set: %s, current_name_set: %s, "
                "sensors_init: %s, setup_complete: %s",
                self._last_known_client_name != "unknown",
                current_client_name != "unknown",
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
                    "Client name is now available after being unknown - "
                    "scheduling config entry reload to initialize sensors"
                )
                self._last_known_client_name = current_client_name

                # Schedule config entry reload to create sensors
                assert self.config_entry is not None
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
        self._api_client = None
        await super().async_shutdown()

    @property
    def last_successful_update_time(self) -> datetime | None:
        """Get the last successful update time."""
        return self._last_successful_update

    @property
    def timezone(self) -> str:
        """Return the configured market timezone ("any" for a fixed schedule)."""
        return self._timezone

    @property
    def is_market_hours(self) -> bool:
        """Return True if the configured market is currently open."""
        return self._is_market_hours()

    @property
    def performance_last_updated(self) -> datetime | None:
        """Return when performance data was last fetched, if ever."""
        return self._performance.last_updated

    @property
    def client_info(self) -> ClientInfo:
        """Return the client identity, "unknown" fields before the first update."""
        return self.data.client if self.data is not None else ClientInfo()

    def get_positions(self) -> dict[str, PositionData]:
        """Get all cached positions.

        Returns:
            Dictionary mapping position slugs to PositionData objects

        """
        return self._positions.cache.positions

    def get_position(self, slug: str) -> PositionData | None:
        """Get a specific position by slug.

        Args:
            slug: The position slug (e.g., "aapl_stock")

        Returns:
            PositionData for the position, or None if not found

        """
        return self._positions.cache.positions.get(slug)

    def get_position_ids(self) -> list[str]:
        """Get list of all position slugs.

        Returns:
            List of position slugs

        """
        return self._positions.cache.position_ids

    def has_market_data_access(self) -> bool | None:
        """Check if the API has access to real-time market data.

        Returns:
            True if market data access is available,
            False if prices are calculated from P/L data,
            None if not yet determined (no positions fetched)

        """
        return self._positions.has_market_data_access

    @property
    def position_sensors_enabled(self) -> bool:
        """Check if position sensors are enabled.

        Returns:
            True if position sensors are enabled

        """
        return self._positions.enabled

    def mark_sensors_initialized(self) -> None:
        """Mark that sensors have been successfully initialized.

        This prevents unnecessary config entry reloads once sensors are created.
        """
        assert self.config_entry is not None
        self._sensors_initialized = True
        _LOGGER.debug(
            "Marked sensors as initialized for entry %s", self.config_entry.entry_id
        )

    def mark_setup_complete(self) -> None:
        """Mark that initial setup is complete (platforms loaded).

        This allows the reload logic to work correctly for genuinely skipped sensors.
        """
        assert self.config_entry is not None
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
        assert self.config_entry is not None

        current_title = self.config_entry.title
        expected_title = f"Saxo Portfolio ({client_id})"

        # Only update if title is still generic (doesn't already include client ID)
        if current_title == "Saxo Portfolio" or (
            "(" not in current_title and client_id not in current_title
        ):
            _LOGGER.info(
                "Updating config entry title to include the client identifier "
                "for entry %s",
                self.config_entry.entry_id,
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

    async def async_apply_options(self) -> None:
        """Apply a changed market timezone without reloading the entry."""
        assert self.config_entry is not None
        timezone: str = self.config_entry.data.get(CONF_TIMEZONE, DEFAULT_TIMEZONE)
        if timezone != self._configured_timezone:
            _LOGGER.info("Market timezone changed to %s", timezone)
            self._configured_timezone = timezone
            self._timezone = timezone
            self._market_hours_cache = None
            self._market_hours_cache_time = None
            await self.async_update_interval_if_needed()
            # always_update=False skips notifying when a refresh returns equal
            # data, so tell the Timezone sensor explicitly
            self.async_update_listeners()
            await self.async_request_refresh()

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
