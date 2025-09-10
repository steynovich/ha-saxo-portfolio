"""Saxo API client for portfolio data retrieval.

This client handles authentication, rate limiting, and data fetching
from the Saxo OpenAPI endpoints.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp
import async_timeout

from ..const import (
    API_ACCOUNTS_ENDPOINT,
    API_BALANCE_ENDPOINT,
    API_POSITIONS_ENDPOINT,
    API_RATE_LIMIT_PER_MINUTE,
    API_RATE_LIMIT_WINDOW,
    API_TIMEOUT_CONNECT,
    API_TIMEOUT_READ,
    API_TIMEOUT_TOTAL,
    ERROR_AUTH_FAILED,
    ERROR_NETWORK_ERROR,
    ERROR_RATE_LIMITED,
    MAX_RETRIES,
    RETRY_BACKOFF_FACTOR,
)

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


class RateLimiter:
    """Rate limiter for API requests."""

    def __init__(self, max_requests: int = API_RATE_LIMIT_PER_MINUTE, window: int = API_RATE_LIMIT_WINDOW):
        self.max_requests = max_requests
        self.window = window
        self.requests = []
        self._lock = asyncio.Lock()
        self._rate_limited_until = 0  # Timestamp when rate limiting ends

    async def wait_if_needed(self, endpoint_group: str = "default") -> None:
        """Wait if rate limit would be exceeded."""
        async with self._lock:
            now = time.time()

            # Check if we're in a rate-limited state from server response
            if self._rate_limited_until > now:
                sleep_time = self._rate_limited_until - now
                _LOGGER.debug("Server rate limit active, waiting %.2f seconds", sleep_time)
                await asyncio.sleep(sleep_time)
                self._rate_limited_until = 0

            window_start = now - self.window

            # Remove old requests
            self.requests = [req_time for req_time in self.requests if req_time > window_start]

            # Check if we need to wait for client-side rate limiting
            if len(self.requests) >= self.max_requests:
                sleep_time = self.window - (now - self.requests[0])
                if sleep_time > 0:
                    _LOGGER.debug("Client rate limit reached, waiting %.2f seconds", sleep_time)
                    await asyncio.sleep(sleep_time)
                    # Clean up after waiting
                    now = time.time()
                    window_start = now - self.window
                    self.requests = [req_time for req_time in self.requests if req_time > window_start]

            # Record this request
            self.requests.append(now)

    def set_rate_limited_until(self, retry_after_seconds: int) -> None:
        """Set rate limiting based on server response."""
        self._rate_limited_until = time.time() + retry_after_seconds


class SaxoApiClient:
    """Client for Saxo OpenAPI endpoints."""

    def __init__(self, access_token: str, base_url: str = None, session: aiohttp.ClientSession = None):
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

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(
                connect=API_TIMEOUT_CONNECT,
                sock_read=API_TIMEOUT_READ,
                total=API_TIMEOUT_TOTAL
            )
            # Create SSL-secure connector (explicit SSL verification)
            connector = aiohttp.TCPConnector(
                ssl=True,  # Ensure SSL verification is enabled
                limit=100,  # Connection pool limit
                limit_per_host=30  # Per-host connection limit
            )

            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "HomeAssistant-SaxoPortfolio/1.0"
                }
            )
        return self._session

    async def _make_request(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
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
                async with async_timeout.timeout(API_TIMEOUT_TOTAL):
                    async with self.session.get(url, params=params) as response:
                        from ..models import mask_url_for_logging
                        _LOGGER.debug(
                            "API request: %s %s -> %d",
                            "GET", mask_url_for_logging(url), response.status
                        )

                        if response.status == 200:
                            data = await response.json()
                            return data
                        elif response.status == 401:
                            raise AuthenticationError(ERROR_AUTH_FAILED)
                        elif response.status == 429:
                            # Handle rate limiting with server-specified retry time
                            retry_after = int(response.headers.get("Retry-After", 60))
                            rate_limit_reset = response.headers.get("X-RateLimit-Reset")

                            _LOGGER.warning(
                                "Rate limited (attempt %d/%d), retry after %d seconds",
                                attempt + 1, MAX_RETRIES, retry_after
                            )

                            # Update rate limiter with server response
                            self._rate_limiter.set_rate_limited_until(retry_after)

                            if attempt < MAX_RETRIES - 1:
                                # Use exponential backoff with server retry time as base
                                backoff_time = min(retry_after * (RETRY_BACKOFF_FACTOR ** attempt), 300)
                                await asyncio.sleep(backoff_time)
                                continue
                            else:
                                error_msg = f"{ERROR_RATE_LIMITED} (reset: {rate_limit_reset})"
                                raise RateLimitError(error_msg)
                        else:
                            error_text = await response.text()
                            raise APIError(f"HTTP {response.status}: {error_text}")

            except TimeoutError:
                if attempt < MAX_RETRIES - 1:
                    backoff_time = min(RETRY_BACKOFF_FACTOR ** attempt, 30)  # Cap at 30 seconds
                    _LOGGER.warning(
                        "Request timeout (attempt %d/%d), retrying in %d seconds",
                        attempt + 1, MAX_RETRIES, backoff_time
                    )
                    await asyncio.sleep(backoff_time)
                    continue
                else:
                    raise APIError(f"Request timeout after {MAX_RETRIES} attempts")

            except aiohttp.ClientError as e:
                # Categorize different types of client errors
                error_type = type(e).__name__

                if attempt < MAX_RETRIES - 1:
                    # Different backoff for different error types
                    error_msg = str(e)
                    if "DNS" in error_msg or "resolve" in error_msg.lower():
                        backoff_time = min(5 * (RETRY_BACKOFF_FACTOR ** attempt), 60)
                    else:
                        backoff_time = min(RETRY_BACKOFF_FACTOR ** attempt, 30)

                    _LOGGER.warning(
                        "Network error %s (attempt %d/%d), retrying in %d seconds",
                        error_type, attempt + 1, MAX_RETRIES, backoff_time
                    )
                    await asyncio.sleep(backoff_time)
                    continue
                else:
                    raise APIError(f"{ERROR_NETWORK_ERROR} ({error_type})")

        raise APIError(f"Max retries ({MAX_RETRIES}) exceeded for {endpoint}")

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

            # Validate required fields from contract
            required_fields = ["CashBalance", "Currency", "TotalValue"]
            for field in required_fields:
                if field not in response:
                    raise APIError(f"Missing required field: {field}")

            # Validate data types
            if not isinstance(response["CashBalance"], (int, float)):
                raise APIError("CashBalance must be numeric")
            if not isinstance(response["TotalValue"], (int, float)):
                raise APIError("TotalValue must be numeric")
            if not isinstance(response["Currency"], str):
                raise APIError("Currency must be string")

            # Validate financial data
            import math
            if not math.isfinite(response["CashBalance"]):
                raise APIError("CashBalance is not finite")
            if not math.isfinite(response["TotalValue"]):
                raise APIError("TotalValue is not finite")
            if response["TotalValue"] < 0:
                raise APIError("TotalValue cannot be negative")

            return response

        except (AuthenticationError, RateLimitError):
            raise
        except Exception as e:
            _LOGGER.error("Error fetching account balance: %s", type(e).__name__)
            raise APIError("Failed to fetch account balance")

    async def get_positions(self, client_key: str | None = None) -> dict[str, Any]:
        """Get positions from Saxo API.
        
        Args:
            client_key: Optional client key for filtering
            
        Returns:
            Positions data matching contract schema
            
        Raises:
            AuthenticationError: For authentication failures
            APIError: For other API errors

        """
        try:
            params = {}
            if client_key:
                params["ClientKey"] = client_key

            response = await self._make_request(API_POSITIONS_ENDPOINT, params)

            # Validate response structure
            if "__count" not in response or "Data" not in response:
                raise APIError("Invalid positions response structure")

            if not isinstance(response["__count"], int):
                raise APIError("__count must be integer")
            if not isinstance(response["Data"], list):
                raise APIError("Data must be list")

            # Validate position data
            valid_asset_types = ["FxSpot", "Stock", "Bond", "Option", "Future"]
            valid_statuses = ["Open", "Closed", "Pending"]

            for position in response["Data"]:
                # Validate structure
                if "NetPositionId" not in position:
                    raise APIError("Missing NetPositionId")
                if "PositionBase" not in position or "PositionView" not in position:
                    raise APIError("Missing PositionBase or PositionView")

                position_base = position["PositionBase"]
                position_view = position["PositionView"]

                # Validate required fields
                required_base_fields = ["AccountId", "Amount", "AssetType", "OpenPrice", "Status"]
                for field in required_base_fields:
                    if field not in position_base:
                        raise APIError(f"Missing PositionBase field: {field}")

                required_view_fields = ["CurrentPrice", "ProfitLossOnTrade"]
                for field in required_view_fields:
                    if field not in position_view:
                        raise APIError(f"Missing PositionView field: {field}")

                # Validate enums
                if position_base["AssetType"] not in valid_asset_types:
                    raise APIError(f"Invalid AssetType: {position_base['AssetType']}")
                if position_base["Status"] not in valid_statuses:
                    raise APIError(f"Invalid Status: {position_base['Status']}")

                # Validate numeric data
                import math
                if not math.isfinite(position_base["OpenPrice"]) or position_base["OpenPrice"] <= 0:
                    raise APIError("Invalid OpenPrice")
                if not math.isfinite(position_view["CurrentPrice"]) or position_view["CurrentPrice"] <= 0:
                    raise APIError("Invalid CurrentPrice")
                if not math.isfinite(position_view["ProfitLossOnTrade"]):
                    raise APIError("Invalid ProfitLossOnTrade")

            return response

        except (AuthenticationError, RateLimitError):
            raise
        except Exception as e:
            _LOGGER.error("Error fetching positions: %s", type(e).__name__)
            raise APIError("Failed to fetch positions")

    async def get_accounts(self, client_key: str) -> dict[str, Any]:
        """Get accounts from Saxo API.
        
        Args:
            client_key: Required client key parameter
            
        Returns:
            Accounts data matching contract schema
            
        Raises:
            AuthenticationError: For authentication failures
            APIError: For other API errors

        """
        if not client_key:
            raise APIError("ClientKey is required for accounts endpoint")

        try:
            params = {"ClientKey": client_key}
            response = await self._make_request(API_ACCOUNTS_ENDPOINT, params)

            # Validate response structure
            if "__count" not in response or "Data" not in response:
                raise APIError("Invalid accounts response structure")

            if not isinstance(response["__count"], int):
                raise APIError("__count must be integer")
            if not isinstance(response["Data"], list):
                raise APIError("Data must be list")

            # Validate account data
            valid_account_types = ["Normal", "Margin", "ISA", "SIPP"]
            account_ids = set()
            account_keys = set()

            for account in response["Data"]:
                # Validate required fields
                required_fields = ["AccountId", "AccountKey", "Active", "AccountType"]
                for field in required_fields:
                    if field not in account:
                        raise APIError(f"Missing account field: {field}")

                # Validate data types
                if not isinstance(account["AccountId"], str) or not account["AccountId"]:
                    raise APIError("AccountId must be non-empty string")
                if not isinstance(account["AccountKey"], str) or not account["AccountKey"]:
                    raise APIError("AccountKey must be non-empty string")
                if not isinstance(account["Active"], bool):
                    raise APIError("Active must be boolean")
                if account["AccountType"] not in valid_account_types:
                    raise APIError(f"Invalid AccountType: {account['AccountType']}")

                # Validate currency if present
                if "Currency" in account:
                    currency = account["Currency"]
                    if not isinstance(currency, str) or len(currency) != 3 or not currency.isupper():
                        raise APIError(f"Invalid currency format: {currency}")

                # Check for duplicates
                if account["AccountId"] in account_ids:
                    raise APIError(f"Duplicate AccountId: {account['AccountId']}")
                if account["AccountKey"] in account_keys:
                    raise APIError(f"Duplicate AccountKey: {account['AccountKey']}")

                account_ids.add(account["AccountId"])
                account_keys.add(account["AccountKey"])

            return response

        except (AuthenticationError, RateLimitError):
            raise
        except Exception as e:
            _LOGGER.error("Error fetching accounts: %s", type(e).__name__)
            raise APIError("Failed to fetch accounts")

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
