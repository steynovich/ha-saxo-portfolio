"""Saxo API client for portfolio data retrieval.

This client handles authentication, rate limiting, and data fetching
from the Saxo OpenAPI endpoints.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any

import aiohttp

from ..const import (
    API_BALANCE_ENDPOINT,
    API_CLIENT_DETAILS_ENDPOINT,
    API_NET_POSITIONS_ENDPOINT,
    API_PERFORMANCE_ENDPOINT,
    API_PERFORMANCE_V4_ENDPOINT,
    API_RATE_LIMIT_PER_MINUTE,
    API_RATE_LIMIT_WINDOW,
    API_TIMEOUT_CONNECT,
    API_TIMEOUT_READ,
    API_TIMEOUT_TOTAL,
    ERROR_AUTH_FAILED,
    ERROR_NETWORK_ERROR,
    ERROR_RATE_LIMITED,
    INTEGRATION_VERSION,
    MAX_RETRIES,
    RETRY_BACKOFF_FACTOR,
)
from ..models import mask_url_for_logging

_LOGGER = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Exception raised for authentication errors."""

    pass


class RateLimitError(Exception):
    """Exception raised when API rate limit is exceeded."""

    pass


class APIError(Exception):
    """Exception raised for general API errors."""

    pass


def _validate_balance_response(response: dict[str, Any]) -> None:
    """Validate the Saxo balance endpoint response shape and values.

    Raises:
        APIError: If a required field is missing, a value has the wrong type,
            a numeric value is non-finite, or TotalValue is negative.

    """
    for field in ("CashBalance", "Currency", "TotalValue"):
        if field not in response:
            raise APIError(f"Missing required field: {field}")

    if not isinstance(response["CashBalance"], int | float):
        raise APIError("CashBalance must be numeric")
    if not isinstance(response["TotalValue"], int | float):
        raise APIError("TotalValue must be numeric")
    if not isinstance(response["Currency"], str):
        raise APIError("Currency must be string")

    if not math.isfinite(response["CashBalance"]):
        raise APIError("CashBalance is not finite")
    if not math.isfinite(response["TotalValue"]):
        raise APIError("TotalValue is not finite")
    if response["TotalValue"] < 0:
        raise APIError("TotalValue cannot be negative")


class RateLimiter:
    """Rate limiter for API requests."""

    def __init__(
        self,
        max_requests: int = API_RATE_LIMIT_PER_MINUTE,
        window: int = API_RATE_LIMIT_WINDOW,
    ):
        """Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed per window
            window: Time window in seconds

        """
        self.max_requests = max_requests
        self.window = window
        self.requests = []
        self._lock = asyncio.Lock()
        self._rate_limited_until = 0  # Timestamp when rate limiting ends

    async def wait_if_needed(self) -> None:
        """Wait if rate limit would be exceeded."""
        async with self._lock:
            now = time.time()

            # Check if we're in a rate-limited state from server response
            if self._rate_limited_until > now:
                sleep_time = self._rate_limited_until - now
                _LOGGER.debug(
                    "Server rate limit active, waiting %.2f seconds", sleep_time
                )
                await asyncio.sleep(sleep_time)
                self._rate_limited_until = 0

            window_start = now - self.window

            # Remove old requests
            self.requests = [
                req_time for req_time in self.requests if req_time > window_start
            ]

            # Check if we need to wait for client-side rate limiting
            if len(self.requests) >= self.max_requests:
                sleep_time = self.window - (now - self.requests[0])
                if sleep_time > 0:
                    _LOGGER.debug(
                        "Client rate limit reached, waiting %.2f seconds", sleep_time
                    )
                    await asyncio.sleep(sleep_time)
                    # Clean up after waiting
                    now = time.time()
                    window_start = now - self.window
                    self.requests = [
                        req_time
                        for req_time in self.requests
                        if req_time > window_start
                    ]

            # Record this request
            self.requests.append(now)

    def set_rate_limited_until(self, retry_after_seconds: int) -> None:
        """Set rate limiting based on server response."""
        self._rate_limited_until = time.time() + retry_after_seconds


class SaxoApiClient:
    """Client for Saxo OpenAPI endpoints."""

    def __init__(
        self,
        access_token: str,
        base_url: str | None = None,
        session: aiohttp.ClientSession | None = None,
    ):
        """Initialize Saxo API client.

        Args:
            access_token: OAuth access token
            base_url: Base URL for API endpoints
            session: Optional aiohttp session (for testing)

        """
        self.access_token = access_token
        self.base_url = base_url
        self._session = session
        self._rate_limiter = RateLimiter()
        self._last_request_time = 0

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb):
        """Async context manager exit."""
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            if self._session is not None and self._session.closed:
                _LOGGER.debug("Previous session was closed, creating new session")

            timeout = aiohttp.ClientTimeout(
                connect=API_TIMEOUT_CONNECT,
                sock_read=API_TIMEOUT_READ,
                total=API_TIMEOUT_TOTAL,
            )
            # Create SSL-secure connector (explicit SSL verification)
            connector = aiohttp.TCPConnector(
                ssl=True,  # Ensure SSL verification is enabled
                limit=100,  # Connection pool limit
                limit_per_host=30,  # Per-host connection limit
            )

            auth_header = f"Bearer {self.access_token}"
            headers = {
                "Authorization": auth_header,
                "Content-Type": "application/json",
                "User-Agent": f"HomeAssistant-SaxoPortfolio/{INTEGRATION_VERSION}",
            }

            _LOGGER.debug(
                "Creating new API session with auth header length: %d, user-agent: %s",
                len(auth_header),
                headers["User-Agent"],
            )

            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers=headers,
            )
        return self._session

    async def _make_request(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make authenticated request to Saxo API.

        Args:
            endpoint: API endpoint path
            params: Optional query parameters

        Returns:
            API response data

        Raises:
            AuthenticationError: For 401 errors
            RateLimitError: For 429 errors
            APIError: For other HTTP errors

        """
        if not self.base_url:
            raise APIError("Base URL not configured")

        url = f"{self.base_url}{endpoint}"

        # Apply rate limiting
        await self._rate_limiter.wait_if_needed()

        for attempt in range(MAX_RETRIES):
            try:
                async with (
                    asyncio.timeout(API_TIMEOUT_TOTAL),
                    self.session.get(url, params=params) as response,
                ):
                    result = await self._handle_response_status(response, url, attempt)
                if isinstance(result, dict):
                    return result
                # 429 retry: `result` is the backoff delay in seconds
                await asyncio.sleep(result)
                continue

            except TimeoutError:
                if attempt >= MAX_RETRIES - 1:
                    raise APIError(f"Request timeout after {MAX_RETRIES} attempts")
                backoff_time = self._compute_timeout_backoff(attempt)
                _LOGGER.warning(
                    "Request timeout (attempt %d/%d), retrying in %d seconds",
                    attempt + 1,
                    MAX_RETRIES,
                    backoff_time,
                )
                await asyncio.sleep(backoff_time)

            except aiohttp.ClientError as e:
                error_type = type(e).__name__
                if attempt >= MAX_RETRIES - 1:
                    raise APIError(f"{ERROR_NETWORK_ERROR} ({error_type})")
                backoff_time = self._compute_client_error_backoff(e, attempt)
                _LOGGER.warning(
                    "Network error %s (attempt %d/%d), retrying in %d seconds",
                    error_type,
                    attempt + 1,
                    MAX_RETRIES,
                    backoff_time,
                )
                await asyncio.sleep(backoff_time)

        raise APIError(f"Max retries ({MAX_RETRIES}) exceeded for {endpoint}")

    async def _handle_response_status(
        self, response: aiohttp.ClientResponse, url: str, attempt: int
    ) -> dict[str, Any] | float:
        """Route an HTTP response to success/retry/raise.

        Returns:
            The decoded JSON body on 200, or the backoff delay (seconds) when
            a 429 should be retried.

        Raises:
            AuthenticationError: On 401.
            RateLimitError: On 429 when no retries remain.
            APIError: On 400 or any other non-200 status.

        """
        _LOGGER.debug(
            "API request: %s %s -> %d",
            "GET",
            mask_url_for_logging(url),
            response.status,
        )

        if response.status == 200:
            return await response.json()

        if response.status == 401:
            self._log_unauthorized_details(response)
            raise AuthenticationError(ERROR_AUTH_FAILED)

        if response.status == 400:
            error_text = await response.text()
            _LOGGER.error(
                "400 Bad Request for %s: %s",
                mask_url_for_logging(url),
                error_text[:500] if error_text else "No error details",
            )
            raise APIError(f"HTTP 400 Bad Request: {error_text}")

        if response.status == 429:
            return self._handle_rate_limited(response, attempt)

        error_text = await response.text()
        raise APIError(f"HTTP {response.status}: {error_text}")

    def _log_unauthorized_details(self, response: aiohttp.ClientResponse) -> None:
        """Log diagnostic info for a 401 response (no secrets)."""
        auth_header = self.session.headers.get("Authorization", "")
        has_bearer = auth_header.startswith("Bearer ")
        token_length = len(auth_header.replace("Bearer ", "")) if has_bearer else 0
        _LOGGER.debug(
            "401 Unauthorized - has_bearer_token: %s, token_length: %d, user_agent: %s",
            has_bearer,
            token_length,
            self.session.headers.get("User-Agent", "unknown"),
        )
        www_auth = response.headers.get("WWW-Authenticate", "")
        if www_auth:
            _LOGGER.debug("WWW-Authenticate header: %s", www_auth)

    def _handle_rate_limited(
        self, response: aiohttp.ClientResponse, attempt: int
    ) -> float:
        """Handle a 429 response: log, update the limiter, and return backoff seconds.

        Raises RateLimitError when no retries remain.
        """
        retry_after = int(response.headers.get("Retry-After", 60))
        rate_limit_reset = response.headers.get("X-RateLimit-Reset")

        if attempt == 0:
            _LOGGER.debug(
                "Rate limited by Saxo API (attempt %d/%d), retry after %d seconds. "
                "This is normal during startup or high API usage periods.",
                attempt + 1,
                MAX_RETRIES,
                retry_after,
            )
        else:
            _LOGGER.warning(
                "Rate limited by Saxo API (attempt %d/%d), retry after %d seconds. "
                "Multiple rate limit hits may indicate network issues or high API load.",
                attempt + 1,
                MAX_RETRIES,
                retry_after,
            )

        self._rate_limiter.set_rate_limited_until(retry_after)

        if attempt >= MAX_RETRIES - 1:
            raise RateLimitError(f"{ERROR_RATE_LIMITED} (reset: {rate_limit_reset})")

        return min(retry_after * (RETRY_BACKOFF_FACTOR**attempt), 300)

    @staticmethod
    def _compute_timeout_backoff(attempt: int) -> float:
        """Exponential backoff for timeouts, capped at 30 seconds."""
        return min(RETRY_BACKOFF_FACTOR**attempt, 30)

    @staticmethod
    def _compute_client_error_backoff(
        error: aiohttp.ClientError, attempt: int
    ) -> float:
        """Exponential backoff for network errors, with DNS-aware widening."""
        error_msg = str(error)
        if "DNS" in error_msg or "resolve" in error_msg.lower():
            return min(5 * (RETRY_BACKOFF_FACTOR**attempt), 60)
        return min(RETRY_BACKOFF_FACTOR**attempt, 30)

    async def get_account_balance(self) -> dict[str, Any]:
        """Get account balance from Saxo API.

        Returns:
            Balance data matching contract schema

        Raises:
            AuthenticationError: For authentication failures
            APIError: For other API errors

        """
        try:
            response = await self._make_request(API_BALANCE_ENDPOINT)
            _validate_balance_response(response)
            return response

        except AuthenticationError, RateLimitError:
            raise
        except Exception as e:
            _LOGGER.error("Error fetching account balance: %s", type(e).__name__)
            raise APIError("Failed to fetch account balance")

    async def get_client_details(self) -> dict[str, Any] | None:
        """Get client details including ClientKey and ClientId.

        Returns:
            Client details dict or None if not available

        Raises:
            AuthenticationError: For authentication failures
            APIError: For other API errors

        """
        try:
            response = await self._make_request(API_CLIENT_DETAILS_ENDPOINT)

            # Validate response structure
            if not isinstance(response, dict):
                _LOGGER.debug("Invalid client details response structure")
                return None

            # Extract ClientKey and ClientId
            client_key = response.get("ClientKey")
            client_id = response.get("ClientId")

            if client_key:
                _LOGGER.debug(
                    "Found ClientKey from client details endpoint: %s",
                    client_key[:10] + "..." if len(client_key) > 10 else client_key,
                )
            if client_id:
                _LOGGER.debug(
                    "Found ClientId from client details endpoint: %s", client_id
                )

            return response

        except AuthenticationError, RateLimitError:
            raise
        except Exception as e:
            _LOGGER.debug("Error fetching client details: %s", type(e).__name__)
            return None

    async def get_performance(self, client_key: str) -> dict[str, Any]:
        """Get performance data from Saxo v3 performance API.

        Args:
            client_key: Client key for the request

        Returns:
            Performance data containing AccumulatedProfitLoss from BalancePerformance

        Raises:
            AuthenticationError: For authentication failures
            APIError: For other API errors

        """
        try:
            endpoint = f"{API_PERFORMANCE_ENDPOINT}{client_key}"
            params = {"StandardPeriod": "AllTime"}

            response = await self._make_request(endpoint, params)

            # Validate response structure
            if not isinstance(response, dict):
                raise APIError("Invalid performance response format")

            _LOGGER.debug(
                "Performance API response structure: %s",
                list(response.keys()) if response else "empty",
            )

            return response

        except AuthenticationError, RateLimitError:
            raise
        except Exception as e:
            _LOGGER.error("Error fetching performance data: %s", type(e).__name__)
            raise APIError("Failed to fetch performance data")

    async def get_performance_v4_batch(
        self, client_key: str
    ) -> dict[str, dict[str, Any]]:
        """Get all performance timeseries data from Saxo v4 performance API.

        Fetches AllTime, Year, Month, and Quarter performance data with delays
        between calls to prevent rate limiting.

        Args:
            client_key: Client key for the request

        Returns:
            Dictionary with keys: 'alltime', 'ytd', 'month', 'quarter'
            Each containing performance timeseries data

        Raises:
            AuthenticationError: For authentication failures
            APIError: For other API errors

        """
        periods = [
            ("AllTime", "alltime"),
            ("Year", "ytd"),
            ("Month", "month"),
            ("Quarter", "quarter"),
        ]

        results: dict[str, dict[str, Any]] = {}

        for i, (standard_period, key) in enumerate(periods):
            try:
                params = {
                    "ClientKey": client_key,
                    "StandardPeriod": standard_period,
                    "FieldGroups": "Balance_CashTransfer,KeyFigures",
                }

                response = await self._make_request(API_PERFORMANCE_V4_ENDPOINT, params)

                # Validate response structure
                if not isinstance(response, dict):
                    raise APIError(
                        f"Invalid performance v4 {standard_period} response format"
                    )

                _LOGGER.debug(
                    "Performance v4 %s API response structure: %s",
                    standard_period,
                    list(response.keys()) if response else "empty",
                )

                results[key] = response

                # Add delay between calls (except after last one) to prevent rate limiting
                if i < len(periods) - 1:
                    await asyncio.sleep(0.5)

            except AuthenticationError, RateLimitError:
                raise
            except Exception as e:
                _LOGGER.error(
                    "Error fetching performance v4 %s data: %s",
                    standard_period,
                    type(e).__name__,
                )
                raise APIError(f"Failed to fetch performance v4 {standard_period} data")

        return results

    async def get_performance_v4(self, client_key: str) -> dict[str, Any]:
        """Get performance timeseries data from Saxo v4 performance API.

        Args:
            client_key: Client key for the request

        Returns:
            Performance timeseries data containing ReturnFraction and CashTransfer

        Raises:
            AuthenticationError: For authentication failures
            APIError: For other API errors

        """
        try:
            params = {
                "ClientKey": client_key,
                "StandardPeriod": "AllTime",
                "FieldGroups": "Balance_CashTransfer,KeyFigures",
            }

            response = await self._make_request(API_PERFORMANCE_V4_ENDPOINT, params)

            # Validate response structure
            if not isinstance(response, dict):
                raise APIError("Invalid performance v4 response format")

            _LOGGER.debug(
                "Performance v4 API response structure: %s",
                list(response.keys()) if response else "empty",
            )

            return response

        except AuthenticationError, RateLimitError:
            raise
        except Exception as e:
            _LOGGER.error("Error fetching performance v4 data: %s", type(e).__name__)
            raise APIError("Failed to fetch performance v4 data")

    async def get_performance_v4_ytd(self, client_key: str) -> dict[str, Any]:
        """Fetch YTD performance timeseries data using v4 API.

        Args:
            client_key: Client key for the request

        Returns:
            YTD Performance timeseries data containing ReturnFraction and CashTransfer

        Raises:
            AuthenticationError: For authentication failures
            APIError: For other API errors

        """
        try:
            params = {
                "ClientKey": client_key,
                "StandardPeriod": "Year",
                "FieldGroups": "Balance_CashTransfer,KeyFigures",
            }

            response = await self._make_request(API_PERFORMANCE_V4_ENDPOINT, params)

            # Validate response structure
            if not isinstance(response, dict):
                raise APIError("Invalid performance v4 YTD response format")

            _LOGGER.debug(
                "Performance v4 YTD API response structure: %s",
                list(response.keys()) if response else "empty",
            )

            return response

        except AuthenticationError, RateLimitError:
            raise
        except Exception as e:
            _LOGGER.error(
                "Error fetching performance v4 YTD data: %s", type(e).__name__
            )
            raise APIError("Failed to fetch performance v4 YTD data")

    async def get_performance_v4_month(self, client_key: str) -> dict[str, Any]:
        """Fetch Month performance timeseries data using v4 API.

        Args:
            client_key: Client key for the request

        Returns:
            Month Performance timeseries data containing ReturnFraction and CashTransfer

        Raises:
            AuthenticationError: For authentication failures
            APIError: For other API errors

        """
        try:
            params = {
                "ClientKey": client_key,
                "StandardPeriod": "Month",
                "FieldGroups": "Balance_CashTransfer,KeyFigures",
            }

            response = await self._make_request(API_PERFORMANCE_V4_ENDPOINT, params)

            # Validate response structure
            if not isinstance(response, dict):
                raise APIError("Invalid performance v4 Month response format")

            _LOGGER.debug(
                "Performance v4 Month API response structure: %s",
                list(response.keys()) if response else "empty",
            )

            return response

        except AuthenticationError, RateLimitError:
            raise
        except Exception as e:
            _LOGGER.error(
                "Error fetching performance v4 Month data: %s", type(e).__name__
            )
            raise APIError("Failed to fetch performance v4 Month data")

    async def get_performance_v4_quarter(self, client_key: str) -> dict[str, Any]:
        """Fetch Quarter performance timeseries data using v4 API.

        Args:
            client_key: Client key for the request

        Returns:
            Quarter Performance timeseries data containing ReturnFraction and CashTransfer

        Raises:
            AuthenticationError: For authentication failures
            APIError: For other API errors

        """
        try:
            params = {
                "ClientKey": client_key,
                "StandardPeriod": "Quarter",
                "FieldGroups": "Balance_CashTransfer,KeyFigures",
            }

            response = await self._make_request(API_PERFORMANCE_V4_ENDPOINT, params)

            # Validate response structure
            if not isinstance(response, dict):
                raise APIError("Invalid performance v4 Quarter response format")

            _LOGGER.debug(
                "Performance v4 Quarter API response structure: %s",
                list(response.keys()) if response else "empty",
            )

            return response

        except AuthenticationError, RateLimitError:
            raise
        except Exception as e:
            _LOGGER.error(
                "Error fetching performance v4 Quarter data: %s", type(e).__name__
            )
            raise APIError("Failed to fetch performance v4 Quarter data")

    async def get_net_positions(self) -> dict[str, Any]:
        """Get net positions from Saxo API.

        Returns:
            Net positions data containing open positions with FieldGroups data

        Raises:
            AuthenticationError: For authentication failures
            APIError: For other API errors

        """
        try:
            # NetPositionFieldGroup valid values: NetPositionBase, NetPositionView, DisplayAndFormat
            # Pricing fields are in NetPositionView
            params = {
                "FieldGroups": "NetPositionBase,NetPositionView,DisplayAndFormat",
            }

            response = await self._make_request(API_NET_POSITIONS_ENDPOINT, params)

            # Validate response structure
            if not isinstance(response, dict):
                raise APIError("Invalid net positions response format")

            _LOGGER.debug(
                "Net positions API response structure: %s",
                list(response.keys()) if response else "empty",
            )

            return response

        except AuthenticationError, RateLimitError:
            raise
        except Exception as e:
            _LOGGER.error("Error fetching net positions: %s", type(e).__name__)
            raise APIError("Failed to fetch net positions")

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            _LOGGER.debug("Closing HTTP session")
            try:
                await self._session.close()
                _LOGGER.debug("HTTP session closed successfully")
            except Exception as e:
                _LOGGER.warning("Error closing HTTP session: %s", e, exc_info=True)
        else:
            _LOGGER.debug("HTTP session already closed or None")
