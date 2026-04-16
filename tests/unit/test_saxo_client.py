"""Comprehensive unit tests for SaxoApiClient.

Tests cover:
- _validate_balance_response: all validation paths
- RateLimiter: wait_if_needed, set_rate_limited_until
- SaxoApiClient.__init__ and _request_headers
- _make_request: success, 401, 400, 429, timeout, network error, retries
- _handle_response_status: all status codes
- _log_unauthorized_details: with/without WWW-Authenticate
- _handle_rate_limited: retry vs max retries
- _compute_timeout_backoff and _compute_client_error_backoff
- All endpoint methods: get_account_balance, get_client_details, get_performance,
  get_performance_v4_batch, get_performance_v4, get_performance_v4_ytd,
  get_performance_v4_month, get_performance_v4_quarter, get_net_positions
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.saxo_portfolio.api.saxo_client import (
    APIError,
    AuthenticationError,
    RateLimitError,
    RateLimiter,
    SaxoApiClient,
    _validate_balance_response,
)
from custom_components.saxo_portfolio.const import (
    API_PERFORMANCE_ENDPOINT,
    ERROR_AUTH_FAILED,
    ERROR_RATE_LIMITED,
    INTEGRATION_VERSION,
    MAX_RETRIES,
    RETRY_BACKOFF_FACTOR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = "https://gateway.saxobank.com/openapi"
TOKEN = "test_access_token_123"


def _mock_response(
    status: int = 200,
    json_data: dict[str, Any] | None = None,
    text_data: str = "",
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Build a mock aiohttp.ClientResponse."""
    resp = MagicMock(spec=aiohttp.ClientResponse)
    resp.status = status
    resp.json = AsyncMock(return_value=json_data if json_data is not None else {})
    resp.text = AsyncMock(return_value=text_data)
    resp.headers = headers or {}
    return resp


@asynccontextmanager
async def _response_ctx(resp: MagicMock):
    """Async context manager wrapping a mock response (for session.get)."""
    yield resp


def _session_with_response(resp: MagicMock) -> MagicMock:
    """Return a mock session whose .get() returns the given response."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get = MagicMock(return_value=_response_ctx(resp))
    return session


def _session_with_responses(responses: list[MagicMock]) -> MagicMock:
    """Return a mock session whose .get() returns responses in order."""
    session = MagicMock(spec=aiohttp.ClientSession)
    ctxs = [_response_ctx(r) for r in responses]
    session.get = MagicMock(side_effect=ctxs)
    return session


def _session_with_side_effects(side_effects: list) -> MagicMock:
    """Return a mock session whose .get() raises or returns in order.

    Each entry is either a MagicMock (response) or an Exception instance.
    """
    session = MagicMock(spec=aiohttp.ClientSession)

    async def _side_effect_factory(effect):
        if isinstance(effect, BaseException):
            raise effect
        return effect

    ctxs = []
    for eff in side_effects:
        if isinstance(eff, BaseException):
            # Create an async context manager that raises on __aenter__
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(side_effect=eff)
            cm.__aexit__ = AsyncMock(return_value=False)
            ctxs.append(cm)
        else:
            ctxs.append(_response_ctx(eff))
    session.get = MagicMock(side_effect=ctxs)
    return session


def _make_client(
    session: MagicMock | None = None,
    base_url: str = BASE_URL,
    token: str = TOKEN,
) -> SaxoApiClient:
    """Create a SaxoApiClient with mocked dependencies."""
    return SaxoApiClient(access_token=token, base_url=base_url, session=session)


@asynccontextmanager
async def _noop_timeout(_delay):
    """No-op replacement for asyncio.timeout."""
    yield


# ---------------------------------------------------------------------------
# _validate_balance_response
# ---------------------------------------------------------------------------


class TestValidateBalanceResponse:
    """Tests for _validate_balance_response()."""

    def test_valid_response(self):
        """Accept a well-formed balance response."""
        resp = {"CashBalance": 1000.0, "Currency": "EUR", "TotalValue": 5000.0}
        _validate_balance_response(resp)  # should not raise

    def test_valid_response_with_int_values(self):
        """Accept integer numeric values."""
        resp = {"CashBalance": 1000, "Currency": "USD", "TotalValue": 5000}
        _validate_balance_response(resp)

    def test_valid_response_zero_total(self):
        """Accept zero TotalValue."""
        resp = {"CashBalance": 0.0, "Currency": "EUR", "TotalValue": 0.0}
        _validate_balance_response(resp)

    @pytest.mark.parametrize("missing_field", ["CashBalance", "Currency", "TotalValue"])
    def test_missing_required_field(self, missing_field: str):
        """Raise APIError when a required field is absent."""
        resp = {"CashBalance": 100.0, "Currency": "EUR", "TotalValue": 500.0}
        del resp[missing_field]
        with pytest.raises(APIError, match=f"Missing required field: {missing_field}"):
            _validate_balance_response(resp)

    def test_cash_balance_wrong_type(self):
        """Raise APIError when CashBalance is not numeric."""
        resp = {"CashBalance": "not_a_number", "Currency": "EUR", "TotalValue": 500.0}
        with pytest.raises(APIError, match="CashBalance must be numeric"):
            _validate_balance_response(resp)

    def test_total_value_wrong_type(self):
        """Raise APIError when TotalValue is not numeric."""
        resp = {"CashBalance": 100.0, "Currency": "EUR", "TotalValue": "bad"}
        with pytest.raises(APIError, match="TotalValue must be numeric"):
            _validate_balance_response(resp)

    def test_currency_wrong_type(self):
        """Raise APIError when Currency is not a string."""
        resp = {"CashBalance": 100.0, "Currency": 42, "TotalValue": 500.0}
        with pytest.raises(APIError, match="Currency must be string"):
            _validate_balance_response(resp)

    def test_cash_balance_nan(self):
        """Raise APIError when CashBalance is NaN."""
        resp = {"CashBalance": float("nan"), "Currency": "EUR", "TotalValue": 500.0}
        with pytest.raises(APIError, match="CashBalance is not finite"):
            _validate_balance_response(resp)

    def test_cash_balance_inf(self):
        """Raise APIError when CashBalance is infinite."""
        resp = {"CashBalance": float("inf"), "Currency": "EUR", "TotalValue": 500.0}
        with pytest.raises(APIError, match="CashBalance is not finite"):
            _validate_balance_response(resp)

    def test_total_value_nan(self):
        """Raise APIError when TotalValue is NaN."""
        resp = {"CashBalance": 100.0, "Currency": "EUR", "TotalValue": float("nan")}
        with pytest.raises(APIError, match="TotalValue is not finite"):
            _validate_balance_response(resp)

    def test_total_value_inf(self):
        """Raise APIError when TotalValue is infinite."""
        resp = {"CashBalance": 100.0, "Currency": "EUR", "TotalValue": float("inf")}
        with pytest.raises(APIError, match="TotalValue is not finite"):
            _validate_balance_response(resp)

    def test_total_value_negative(self):
        """Raise APIError when TotalValue is negative."""
        resp = {"CashBalance": 100.0, "Currency": "EUR", "TotalValue": -1.0}
        with pytest.raises(APIError, match="TotalValue cannot be negative"):
            _validate_balance_response(resp)

    def test_negative_inf_total_value(self):
        """Raise APIError for -inf TotalValue (caught by finite check before negative check)."""
        resp = {"CashBalance": 100.0, "Currency": "EUR", "TotalValue": float("-inf")}
        with pytest.raises(APIError, match="TotalValue is not finite"):
            _validate_balance_response(resp)


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    """Tests for the RateLimiter class."""

    @pytest.mark.asyncio
    async def test_first_request_no_wait(self):
        """First request should not block."""
        rl = RateLimiter(max_requests=10, window=60)
        # Should complete instantly (no sleep)
        await rl.wait_if_needed()
        assert len(rl.requests) == 1

    @pytest.mark.asyncio
    async def test_within_limit(self):
        """Requests within limit should not block."""
        rl = RateLimiter(max_requests=5, window=60)
        for _ in range(4):
            await rl.wait_if_needed()
        assert len(rl.requests) == 4

    @pytest.mark.asyncio
    async def test_exceeds_limit_triggers_sleep(self):
        """When the window is full, the limiter should sleep."""
        rl = RateLimiter(max_requests=2, window=60)
        # Fill the window
        rl.requests = [time.time(), time.time()]

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            await rl.wait_if_needed()
            mock_sleep.assert_called_once()
            # The sleep time should be positive
            assert mock_sleep.call_args[0][0] > 0

    @pytest.mark.asyncio
    async def test_old_requests_pruned(self):
        """Requests outside the window should be pruned."""
        rl = RateLimiter(max_requests=2, window=60)
        # Add old requests outside window
        old_time = time.time() - 120
        rl.requests = [old_time, old_time]

        await rl.wait_if_needed()
        # Old requests pruned, only current one remains
        assert len(rl.requests) == 1

    @pytest.mark.asyncio
    async def test_server_rate_limited_state(self):
        """When server rate limited, should wait until the limit expires."""
        rl = RateLimiter(max_requests=100, window=60)
        rl.set_rate_limited_until(5)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            await rl.wait_if_needed()
            # Should have slept for the rate limited duration
            mock_sleep.assert_called_once()
            sleep_time = mock_sleep.call_args[0][0]
            # Should be close to 5 seconds (some time passes between set and check)
            assert 4.0 < sleep_time <= 5.1

    def test_set_rate_limited_until(self):
        """set_rate_limited_until should set the timestamp correctly."""
        rl = RateLimiter()
        before = time.time()
        rl.set_rate_limited_until(10)
        after = time.time()
        assert before + 10 <= rl._rate_limited_until <= after + 10


# ---------------------------------------------------------------------------
# SaxoApiClient.__init__ and _request_headers
# ---------------------------------------------------------------------------


class TestSaxoApiClientInit:
    """Tests for SaxoApiClient construction and header building."""

    def test_init_stores_fields(self):
        """Constructor should store token, base_url, session."""
        session = MagicMock()
        client = SaxoApiClient(
            access_token="tok", base_url="https://api", session=session
        )
        assert client.access_token == "tok"
        assert client.base_url == "https://api"
        assert client._session is session

    def test_init_defaults(self):
        """Constructor defaults for base_url and session should be None."""
        client = SaxoApiClient(access_token="tok")
        assert client.base_url is None
        assert client._session is None

    def test_request_headers(self):
        """_request_headers should include Authorization, Content-Type, User-Agent."""
        client = _make_client()
        headers = client._request_headers
        assert headers["Authorization"] == f"Bearer {TOKEN}"
        assert headers["Content-Type"] == "application/json"
        assert (
            headers["User-Agent"]
            == f"HomeAssistant-SaxoPortfolio/{INTEGRATION_VERSION}"
        )

    def test_request_headers_updates_with_token(self):
        """Headers should reflect current access_token when it changes."""
        client = _make_client()
        client.access_token = "new_token"
        assert client._request_headers["Authorization"] == "Bearer new_token"


# ---------------------------------------------------------------------------
# _make_request
# ---------------------------------------------------------------------------


class TestMakeRequest:
    """Tests for _make_request including retries."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Successful 200 response should return JSON body."""
        resp = _mock_response(200, json_data={"key": "value"})
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
            side_effect=_noop_timeout,
        ):
            result = await client._make_request("/test")

        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_no_base_url(self):
        """Should raise APIError when base_url is not set."""
        client = _make_client(session=MagicMock(), base_url=None)
        client.base_url = None
        with pytest.raises(APIError, match="Base URL not configured"):
            await client._make_request("/test")

    @pytest.mark.asyncio
    async def test_no_session(self):
        """Should raise APIError when session is not set."""
        client = _make_client(session=None)
        with pytest.raises(APIError, match="HTTP session not configured"):
            await client._make_request("/test")

    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self):
        """401 should raise AuthenticationError immediately."""
        resp = _mock_response(401, headers={})
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            pytest.raises(AuthenticationError, match=ERROR_AUTH_FAILED),
        ):
            await client._make_request("/test")

    @pytest.mark.asyncio
    async def test_400_raises_api_error(self):
        """400 should raise APIError with error text."""
        resp = _mock_response(400, text_data="Bad param")
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            pytest.raises(APIError, match="HTTP 400 Bad Request: Bad param"),
        ):
            await client._make_request("/test")

    @pytest.mark.asyncio
    async def test_429_retries_then_succeeds(self):
        """429 on first attempt should retry and succeed on second."""
        resp_429 = _mock_response(
            429, headers={"Retry-After": "1", "X-RateLimit-Reset": "12345"}
        )
        resp_200 = _mock_response(200, json_data={"ok": True})
        session = _session_with_responses([resp_429, resp_200])
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            result = await client._make_request("/test")

        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_429_max_retries_raises_rate_limit(self):
        """429 on all attempts should raise RateLimitError."""
        responses = [
            _mock_response(429, headers={"Retry-After": "1", "X-RateLimit-Reset": "99"})
            for _ in range(MAX_RETRIES)
        ]
        session = _session_with_responses(responses)
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(RateLimitError, match=ERROR_RATE_LIMITED),
        ):
            await client._make_request("/test")

    @pytest.mark.asyncio
    async def test_timeout_retries_then_succeeds(self):
        """TimeoutError on first attempt should retry and succeed."""
        resp_200 = _mock_response(200, json_data={"ok": True})
        # First call raises TimeoutError, second returns success
        session = _session_with_side_effects([TimeoutError(), resp_200])
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            result = await client._make_request("/test")

        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_timeout_max_retries_raises(self):
        """TimeoutError on all attempts should raise APIError."""
        side_effects = [TimeoutError() for _ in range(MAX_RETRIES)]
        session = _session_with_side_effects(side_effects)
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(
                APIError, match=f"Request timeout after {MAX_RETRIES} attempts"
            ),
        ):
            await client._make_request("/test")

    @pytest.mark.asyncio
    async def test_network_error_retries_then_succeeds(self):
        """aiohttp.ClientError on first attempt should retry and succeed."""
        resp_200 = _mock_response(200, json_data={"data": 1})
        session = _session_with_side_effects(
            [aiohttp.ClientError("conn fail"), resp_200]
        )
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            result = await client._make_request("/test")

        assert result == {"data": 1}

    @pytest.mark.asyncio
    async def test_network_error_max_retries_raises(self):
        """aiohttp.ClientError on all attempts should raise APIError."""
        side_effects = [aiohttp.ClientError("fail") for _ in range(MAX_RETRIES)]
        session = _session_with_side_effects(side_effects)
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(APIError, match="Network error"),
        ):
            await client._make_request("/test")

    @pytest.mark.asyncio
    async def test_unknown_status_raises_api_error(self):
        """Non-200/400/401/429 status should raise APIError."""
        resp = _mock_response(503, text_data="Service Unavailable")
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            pytest.raises(APIError, match="HTTP 503: Service Unavailable"),
        ):
            await client._make_request("/test")

    @pytest.mark.asyncio
    async def test_params_passed_to_session(self):
        """Query params should be passed through to session.get()."""
        resp = _mock_response(200, json_data={})
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
            side_effect=_noop_timeout,
        ):
            await client._make_request("/test", params={"foo": "bar"})

        call_kwargs = session.get.call_args
        assert call_kwargs[1]["params"] == {"foo": "bar"}


# ---------------------------------------------------------------------------
# _handle_response_status
# ---------------------------------------------------------------------------


class TestHandleResponseStatus:
    """Tests for _handle_response_status."""

    @pytest.mark.asyncio
    async def test_200_returns_json(self):
        """200 should return parsed JSON dict."""
        resp = _mock_response(200, json_data={"balance": 42})
        client = _make_client()
        result = await client._handle_response_status(resp, "https://api/test", 0)
        assert result == {"balance": 42}

    @pytest.mark.asyncio
    async def test_401_raises(self):
        """401 should raise AuthenticationError."""
        resp = _mock_response(401, headers={})
        client = _make_client()
        with pytest.raises(AuthenticationError):
            await client._handle_response_status(resp, "https://api/test", 0)

    @pytest.mark.asyncio
    async def test_400_raises(self):
        """400 should raise APIError with error text."""
        resp = _mock_response(400, text_data="invalid")
        client = _make_client()
        with pytest.raises(APIError, match="HTTP 400"):
            await client._handle_response_status(resp, "https://api/test", 0)

    @pytest.mark.asyncio
    async def test_400_truncates_long_error(self):
        """400 error text should be truncated to 500 chars in log."""
        long_text = "x" * 1000
        resp = _mock_response(400, text_data=long_text)
        client = _make_client()
        with pytest.raises(APIError):
            await client._handle_response_status(resp, "https://api/test", 0)

    @pytest.mark.asyncio
    async def test_400_empty_error(self):
        """400 with empty error text should still raise."""
        resp = _mock_response(400, text_data="")
        client = _make_client()
        with pytest.raises(APIError, match="HTTP 400"):
            await client._handle_response_status(resp, "https://api/test", 0)

    @pytest.mark.asyncio
    async def test_429_returns_float(self):
        """429 on non-last attempt should return backoff seconds (float)."""
        resp = _mock_response(429, headers={"Retry-After": "5"})
        client = _make_client()
        result = await client._handle_response_status(
            resp, "https://api/test", attempt=0
        )
        assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_429_last_attempt_raises(self):
        """429 on last attempt should raise RateLimitError."""
        resp = _mock_response(
            429, headers={"Retry-After": "5", "X-RateLimit-Reset": "999"}
        )
        client = _make_client()
        with pytest.raises(RateLimitError):
            await client._handle_response_status(
                resp, "https://api/test", attempt=MAX_RETRIES - 1
            )

    @pytest.mark.asyncio
    async def test_500_raises_api_error(self):
        """500 should raise APIError."""
        resp = _mock_response(500, text_data="Internal Server Error")
        client = _make_client()
        with pytest.raises(APIError, match="HTTP 500"):
            await client._handle_response_status(resp, "https://api/test", 0)


# ---------------------------------------------------------------------------
# _log_unauthorized_details
# ---------------------------------------------------------------------------


class TestLogUnauthorizedDetails:
    """Tests for _log_unauthorized_details."""

    def test_with_token(self):
        """Should log token presence and length."""
        client = _make_client(token="secrettoken")
        resp = _mock_response(401, headers={})
        # Should not raise
        client._log_unauthorized_details(resp)

    def test_empty_token(self):
        """Should log has_bearer_token=False with empty token."""
        client = _make_client(token="")
        resp = _mock_response(401, headers={})
        client._log_unauthorized_details(resp)

    def test_with_www_authenticate(self):
        """Should log WWW-Authenticate header when present."""
        client = _make_client()
        resp = _mock_response(401, headers={"WWW-Authenticate": "Bearer realm='saxo'"})
        client._log_unauthorized_details(resp)

    def test_without_www_authenticate(self):
        """Should not crash when WWW-Authenticate header is absent."""
        client = _make_client()
        resp = _mock_response(401, headers={})
        client._log_unauthorized_details(resp)


# ---------------------------------------------------------------------------
# _handle_rate_limited
# ---------------------------------------------------------------------------


class TestHandleRateLimited:
    """Tests for _handle_rate_limited."""

    def test_returns_backoff_on_first_attempt(self):
        """First attempt should return float backoff, not raise."""
        resp = _mock_response(429, headers={"Retry-After": "10"})
        client = _make_client()
        result = client._handle_rate_limited(resp, attempt=0)
        # backoff = min(10 * 2^0, 300) = 10.0
        assert result == 10.0

    def test_returns_backoff_on_middle_attempt(self):
        """Middle attempt should return exponential backoff."""
        resp = _mock_response(429, headers={"Retry-After": "10"})
        client = _make_client()
        result = client._handle_rate_limited(resp, attempt=1)
        # backoff = min(10 * 2^1, 300) = 20.0
        assert result == 20.0

    def test_backoff_capped_at_300(self):
        """Backoff should be capped at 300 seconds."""
        resp = _mock_response(429, headers={"Retry-After": "200"})
        # Use attempt=1 (not last) with high Retry-After to test cap
        # backoff = min(200 * 2^1, 300) = min(400, 300) = 300
        client = _make_client()
        result = client._handle_rate_limited(resp, attempt=1)
        assert result == 300.0

    def test_raises_on_last_attempt(self):
        """Last attempt should raise RateLimitError."""
        resp = _mock_response(
            429, headers={"Retry-After": "10", "X-RateLimit-Reset": "1234"}
        )
        client = _make_client()
        with pytest.raises(RateLimitError, match=ERROR_RATE_LIMITED):
            client._handle_rate_limited(resp, attempt=MAX_RETRIES - 1)

    def test_default_retry_after(self):
        """Missing Retry-After header should default to 60."""
        resp = _mock_response(429, headers={})
        client = _make_client()
        result = client._handle_rate_limited(resp, attempt=0)
        # backoff = min(60 * 2^0, 300) = 60.0
        assert result == 60.0

    def test_sets_rate_limiter_state(self):
        """Should update rate limiter state."""
        resp = _mock_response(429, headers={"Retry-After": "15"})
        client = _make_client()
        before = time.time()
        client._handle_rate_limited(resp, attempt=0)
        assert client._rate_limiter._rate_limited_until >= before + 15


# ---------------------------------------------------------------------------
# Backoff helpers
# ---------------------------------------------------------------------------


class TestComputeTimeoutBackoff:
    """Tests for _compute_timeout_backoff."""

    def test_attempt_0(self):
        """First attempt should be RETRY_BACKOFF_FACTOR^0 = 1."""
        assert SaxoApiClient._compute_timeout_backoff(0) == float(
            min(RETRY_BACKOFF_FACTOR**0, 30)
        )

    def test_attempt_1(self):
        """Second attempt should be RETRY_BACKOFF_FACTOR^1."""
        assert SaxoApiClient._compute_timeout_backoff(1) == float(
            min(RETRY_BACKOFF_FACTOR**1, 30)
        )

    def test_capped_at_30(self):
        """Should be capped at 30 seconds for high attempts."""
        assert SaxoApiClient._compute_timeout_backoff(100) == 30.0


class TestComputeClientErrorBackoff:
    """Tests for _compute_client_error_backoff."""

    def test_normal_error(self):
        """Non-DNS error should use standard backoff."""
        err = aiohttp.ClientError("connection reset")
        assert SaxoApiClient._compute_client_error_backoff(err, 0) == float(
            min(RETRY_BACKOFF_FACTOR**0, 30)
        )

    def test_dns_error_uppercase(self):
        """DNS error should use wider backoff (5x multiplier)."""
        err = aiohttp.ClientError("DNS resolution failed")
        result = SaxoApiClient._compute_client_error_backoff(err, 0)
        assert result == float(min(5 * RETRY_BACKOFF_FACTOR**0, 60))

    def test_dns_error_lowercase_resolve(self):
        """Error with 'resolve' should use wider backoff."""
        err = aiohttp.ClientError("Could not resolve hostname")
        result = SaxoApiClient._compute_client_error_backoff(err, 0)
        assert result == float(min(5 * RETRY_BACKOFF_FACTOR**0, 60))

    def test_dns_error_capped_at_60(self):
        """DNS backoff should be capped at 60 seconds."""
        err = aiohttp.ClientError("DNS failure")
        result = SaxoApiClient._compute_client_error_backoff(err, 100)
        assert result == 60.0

    def test_normal_error_capped_at_30(self):
        """Normal error backoff should be capped at 30 seconds."""
        err = aiohttp.ClientError("timeout")
        result = SaxoApiClient._compute_client_error_backoff(err, 100)
        assert result == 30.0


# ---------------------------------------------------------------------------
# Endpoint: get_account_balance
# ---------------------------------------------------------------------------


class TestGetAccountBalance:
    """Tests for get_account_balance."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Should return validated balance data."""
        data = {"CashBalance": 1000.0, "Currency": "EUR", "TotalValue": 5000.0}
        resp = _mock_response(200, json_data=data)
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
            side_effect=_noop_timeout,
        ):
            result = await client.get_account_balance()

        assert result == data

    @pytest.mark.asyncio
    async def test_auth_error_propagates(self):
        """AuthenticationError from _make_request should propagate."""
        resp = _mock_response(401, headers={})
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            pytest.raises(AuthenticationError),
        ):
            await client.get_account_balance()

    @pytest.mark.asyncio
    async def test_rate_limit_error_propagates(self):
        """RateLimitError should propagate through."""
        responses = [
            _mock_response(429, headers={"Retry-After": "1", "X-RateLimit-Reset": "99"})
            for _ in range(MAX_RETRIES)
        ]
        session = _session_with_responses(responses)
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(RateLimitError),
        ):
            await client.get_account_balance()

    @pytest.mark.asyncio
    async def test_validation_failure_wraps_in_api_error(self):
        """Validation failure should be wrapped in APIError."""
        # Missing TotalValue -> _validate_balance_response raises APIError
        # which is caught by the generic except and re-raised as APIError
        data = {"CashBalance": 1000.0, "Currency": "EUR"}
        resp = _mock_response(200, json_data=data)
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            pytest.raises(APIError, match="Failed to fetch account balance"),
        ):
            await client.get_account_balance()

    @pytest.mark.asyncio
    async def test_unexpected_exception_wraps_in_api_error(self):
        """Unexpected exceptions should be wrapped in APIError."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=ValueError("boom"),
            ),
            pytest.raises(APIError, match="Failed to fetch account balance"),
        ):
            await client.get_account_balance()


# ---------------------------------------------------------------------------
# Endpoint: get_client_details
# ---------------------------------------------------------------------------


class TestGetClientDetails:
    """Tests for get_client_details."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Should return client details dict."""
        data = {"ClientKey": "abcdef1234567890", "ClientId": "12345", "Name": "Test"}
        resp = _mock_response(200, json_data=data)
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
            side_effect=_noop_timeout,
        ):
            result = await client.get_client_details()

        assert result == data

    @pytest.mark.asyncio
    async def test_short_client_key(self):
        """ClientKey shorter than 10 chars should not truncate."""
        data = {"ClientKey": "short", "ClientId": "123"}
        resp = _mock_response(200, json_data=data)
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
            side_effect=_noop_timeout,
        ):
            result = await client.get_client_details()

        assert result == data

    @pytest.mark.asyncio
    async def test_no_client_key(self):
        """Missing ClientKey should still return the response."""
        data = {"Name": "Test"}
        resp = _mock_response(200, json_data=data)
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
            side_effect=_noop_timeout,
        ):
            result = await client.get_client_details()

        assert result == data

    @pytest.mark.asyncio
    async def test_auth_error_propagates(self):
        """AuthenticationError should propagate."""
        resp = _mock_response(401, headers={})
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            pytest.raises(AuthenticationError),
        ):
            await client.get_client_details()

    @pytest.mark.asyncio
    async def test_rate_limit_error_propagates(self):
        """RateLimitError should propagate."""
        responses = [
            _mock_response(429, headers={"Retry-After": "1", "X-RateLimit-Reset": "99"})
            for _ in range(MAX_RETRIES)
        ]
        session = _session_with_responses(responses)
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(RateLimitError),
        ):
            await client.get_client_details()

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_none(self):
        """Other exceptions should return None."""
        client = _make_client(session=MagicMock())
        with patch.object(
            client,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=ValueError("boom"),
        ):
            result = await client.get_client_details()
        assert result is None

    @pytest.mark.asyncio
    async def test_non_dict_response_returns_none(self):
        """Non-dict response should return None."""
        # _make_request returns a list instead of dict
        client = _make_client(session=MagicMock())
        with patch.object(
            client, "_make_request", new_callable=AsyncMock, return_value=[1, 2, 3]
        ):
            result = await client.get_client_details()
        assert result is None


# ---------------------------------------------------------------------------
# Endpoint: get_performance
# ---------------------------------------------------------------------------


class TestGetPerformance:
    """Tests for get_performance."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Should return performance data."""
        data = {"BalancePerformance": {"AccumulatedProfitLoss": 150.0}}
        resp = _mock_response(200, json_data=data)
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
            side_effect=_noop_timeout,
        ):
            result = await client.get_performance("client_key_123")

        assert result == data

    @pytest.mark.asyncio
    async def test_uses_correct_endpoint_and_params(self):
        """Should call correct endpoint with StandardPeriod=AllTime."""
        resp = _mock_response(200, json_data={})
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
            side_effect=_noop_timeout,
        ):
            await client.get_performance("ck_123")

        url = session.get.call_args[0][0]
        assert url == f"{BASE_URL}{API_PERFORMANCE_ENDPOINT}ck_123"
        assert session.get.call_args[1]["params"] == {"StandardPeriod": "AllTime"}

    @pytest.mark.asyncio
    async def test_auth_error_propagates(self):
        """AuthenticationError should propagate."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=AuthenticationError("auth"),
            ),
            pytest.raises(AuthenticationError),
        ):
            await client.get_performance("ck")

    @pytest.mark.asyncio
    async def test_rate_limit_error_propagates(self):
        """RateLimitError should propagate."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=RateLimitError("rate"),
            ),
            pytest.raises(RateLimitError),
        ):
            await client.get_performance("ck")

    @pytest.mark.asyncio
    async def test_non_dict_response_raises(self):
        """Non-dict response should raise APIError."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                return_value="not_a_dict",
            ),
            pytest.raises(APIError, match="Failed to fetch performance data"),
        ):
            await client.get_performance("ck")

    @pytest.mark.asyncio
    async def test_unexpected_error_wraps(self):
        """Unexpected exceptions should be wrapped in APIError."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=RuntimeError("oops"),
            ),
            pytest.raises(APIError, match="Failed to fetch performance data"),
        ):
            await client.get_performance("ck")


# ---------------------------------------------------------------------------
# Endpoint: get_performance_v4_batch
# ---------------------------------------------------------------------------


class TestGetPerformanceV4Batch:
    """Tests for get_performance_v4_batch."""

    @pytest.mark.asyncio
    async def test_success_all_periods(self):
        """Should fetch all four periods and return dict with correct keys."""
        alltime = {"KeyFigures": {"AllTime": True}}
        ytd = {"KeyFigures": {"YTD": True}}
        month = {"KeyFigures": {"Month": True}}
        quarter = {"KeyFigures": {"Quarter": True}}

        responses = [alltime, ytd, month, quarter]
        call_idx = 0

        async def mock_make_request(endpoint, params=None):
            nonlocal call_idx
            result = responses[call_idx]
            call_idx += 1
            return result

        client = _make_client(session=MagicMock())
        with (
            patch.object(client, "_make_request", side_effect=mock_make_request),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            result = await client.get_performance_v4_batch("ck_123")

        assert "alltime" in result
        assert "ytd" in result
        assert "month" in result
        assert "quarter" in result
        assert result["alltime"] == alltime
        assert result["ytd"] == ytd

    @pytest.mark.asyncio
    async def test_delays_between_calls(self):
        """Should sleep between API calls (but not after last)."""
        client = _make_client(session=MagicMock())

        call_count = 0

        async def mock_make_request(endpoint, params=None):
            nonlocal call_count
            call_count += 1
            return {"data": call_count}

        with (
            patch.object(client, "_make_request", side_effect=mock_make_request),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
        ):
            await client.get_performance_v4_batch("ck")

        # Sleep should be called 3 times (between 4 calls)
        assert mock_sleep.call_count == 3
        for call in mock_sleep.call_args_list:
            assert call[0][0] == 0.5

    @pytest.mark.asyncio
    async def test_auth_error_propagates(self):
        """AuthenticationError on any period should propagate."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=AuthenticationError("auth"),
            ),
            pytest.raises(AuthenticationError),
        ):
            await client.get_performance_v4_batch("ck")

    @pytest.mark.asyncio
    async def test_rate_limit_error_propagates(self):
        """RateLimitError should propagate."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=RateLimitError("rate"),
            ),
            pytest.raises(RateLimitError),
        ):
            await client.get_performance_v4_batch("ck")

    @pytest.mark.asyncio
    async def test_non_dict_response_raises(self):
        """Non-dict response for a period should raise APIError."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client, "_make_request", new_callable=AsyncMock, return_value="not_dict"
            ),
            pytest.raises(
                APIError, match="Failed to fetch performance v4 AllTime data"
            ),
        ):
            await client.get_performance_v4_batch("ck")

    @pytest.mark.asyncio
    async def test_error_on_second_period(self):
        """Error on second period should raise APIError."""
        call_idx = 0

        async def mock_make_request(endpoint, params=None):
            nonlocal call_idx
            call_idx += 1
            if call_idx == 2:
                raise RuntimeError("boom")
            return {"data": call_idx}

        client = _make_client(session=MagicMock())
        with (
            patch.object(client, "_make_request", side_effect=mock_make_request),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(APIError, match="Failed to fetch performance v4 Year data"),
        ):
            await client.get_performance_v4_batch("ck")


# ---------------------------------------------------------------------------
# Endpoint: get_performance_v4
# ---------------------------------------------------------------------------


class TestGetPerformanceV4:
    """Tests for get_performance_v4."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Should return AllTime performance data."""
        data = {"KeyFigures": {"ReturnFraction": 0.15}}
        client = _make_client(session=MagicMock())
        with patch.object(
            client, "_make_request", new_callable=AsyncMock, return_value=data
        ):
            result = await client.get_performance_v4("ck")
        assert result == data

    @pytest.mark.asyncio
    async def test_correct_params(self):
        """Should call with StandardPeriod=AllTime and correct FieldGroups."""
        client = _make_client(session=MagicMock())
        with patch.object(
            client, "_make_request", new_callable=AsyncMock, return_value={}
        ) as mock_req:
            await client.get_performance_v4("ck_123")
        args, _ = mock_req.call_args
        # _make_request(endpoint, params) - params is second positional arg
        params = args[1]
        assert params["StandardPeriod"] == "AllTime"
        assert params["ClientKey"] == "ck_123"
        assert "Balance_CashTransfer" in params["FieldGroups"]

    @pytest.mark.asyncio
    async def test_auth_error_propagates(self):
        """AuthenticationError should propagate."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=AuthenticationError("auth"),
            ),
            pytest.raises(AuthenticationError),
        ):
            await client.get_performance_v4("ck")

    @pytest.mark.asyncio
    async def test_rate_limit_error_propagates(self):
        """RateLimitError should propagate."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=RateLimitError("rate"),
            ),
            pytest.raises(RateLimitError),
        ):
            await client.get_performance_v4("ck")

    @pytest.mark.asyncio
    async def test_non_dict_raises(self):
        """Non-dict response should raise APIError."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client, "_make_request", new_callable=AsyncMock, return_value=[1]
            ),
            pytest.raises(APIError, match="Failed to fetch performance v4 data"),
        ):
            await client.get_performance_v4("ck")

    @pytest.mark.asyncio
    async def test_unexpected_error_wraps(self):
        """Unexpected exceptions wrapped in APIError."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=ValueError("x"),
            ),
            pytest.raises(APIError, match="Failed to fetch performance v4 data"),
        ):
            await client.get_performance_v4("ck")


# ---------------------------------------------------------------------------
# Endpoint: get_performance_v4_ytd
# ---------------------------------------------------------------------------


class TestGetPerformanceV4Ytd:
    """Tests for get_performance_v4_ytd."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Should return YTD performance data."""
        data = {"KeyFigures": {"ReturnFraction": 0.05}}
        client = _make_client(session=MagicMock())
        with patch.object(
            client, "_make_request", new_callable=AsyncMock, return_value=data
        ):
            result = await client.get_performance_v4_ytd("ck")
        assert result == data

    @pytest.mark.asyncio
    async def test_correct_params(self):
        """Should call with StandardPeriod=Year."""
        client = _make_client(session=MagicMock())
        with patch.object(
            client, "_make_request", new_callable=AsyncMock, return_value={}
        ) as mock_req:
            await client.get_performance_v4_ytd("ck")
        args, _ = mock_req.call_args
        assert args[1]["StandardPeriod"] == "Year"

    @pytest.mark.asyncio
    async def test_auth_error_propagates(self):
        """AuthenticationError should propagate."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=AuthenticationError("a"),
            ),
            pytest.raises(AuthenticationError),
        ):
            await client.get_performance_v4_ytd("ck")

    @pytest.mark.asyncio
    async def test_rate_limit_error_propagates(self):
        """RateLimitError should propagate."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=RateLimitError("r"),
            ),
            pytest.raises(RateLimitError),
        ):
            await client.get_performance_v4_ytd("ck")

    @pytest.mark.asyncio
    async def test_non_dict_raises(self):
        """Non-dict response should raise APIError."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client, "_make_request", new_callable=AsyncMock, return_value="str"
            ),
            pytest.raises(APIError, match="Failed to fetch performance v4 YTD data"),
        ):
            await client.get_performance_v4_ytd("ck")


# ---------------------------------------------------------------------------
# Endpoint: get_performance_v4_month
# ---------------------------------------------------------------------------


class TestGetPerformanceV4Month:
    """Tests for get_performance_v4_month."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Should return Month performance data."""
        data = {"KeyFigures": {"ReturnFraction": 0.02}}
        client = _make_client(session=MagicMock())
        with patch.object(
            client, "_make_request", new_callable=AsyncMock, return_value=data
        ):
            result = await client.get_performance_v4_month("ck")
        assert result == data

    @pytest.mark.asyncio
    async def test_correct_params(self):
        """Should call with StandardPeriod=Month."""
        client = _make_client(session=MagicMock())
        with patch.object(
            client, "_make_request", new_callable=AsyncMock, return_value={}
        ) as mock_req:
            await client.get_performance_v4_month("ck")
        args, _ = mock_req.call_args
        assert args[1]["StandardPeriod"] == "Month"

    @pytest.mark.asyncio
    async def test_auth_error_propagates(self):
        """AuthenticationError should propagate."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=AuthenticationError("a"),
            ),
            pytest.raises(AuthenticationError),
        ):
            await client.get_performance_v4_month("ck")

    @pytest.mark.asyncio
    async def test_rate_limit_error_propagates(self):
        """RateLimitError should propagate."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=RateLimitError("r"),
            ),
            pytest.raises(RateLimitError),
        ):
            await client.get_performance_v4_month("ck")

    @pytest.mark.asyncio
    async def test_non_dict_raises(self):
        """Non-dict response should raise APIError."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client, "_make_request", new_callable=AsyncMock, return_value=42
            ),
            pytest.raises(APIError, match="Failed to fetch performance v4 Month data"),
        ):
            await client.get_performance_v4_month("ck")


# ---------------------------------------------------------------------------
# Endpoint: get_performance_v4_quarter
# ---------------------------------------------------------------------------


class TestGetPerformanceV4Quarter:
    """Tests for get_performance_v4_quarter."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Should return Quarter performance data."""
        data = {"KeyFigures": {"ReturnFraction": 0.04}}
        client = _make_client(session=MagicMock())
        with patch.object(
            client, "_make_request", new_callable=AsyncMock, return_value=data
        ):
            result = await client.get_performance_v4_quarter("ck")
        assert result == data

    @pytest.mark.asyncio
    async def test_correct_params(self):
        """Should call with StandardPeriod=Quarter."""
        client = _make_client(session=MagicMock())
        with patch.object(
            client, "_make_request", new_callable=AsyncMock, return_value={}
        ) as mock_req:
            await client.get_performance_v4_quarter("ck")
        args, _ = mock_req.call_args
        assert args[1]["StandardPeriod"] == "Quarter"

    @pytest.mark.asyncio
    async def test_auth_error_propagates(self):
        """AuthenticationError should propagate."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=AuthenticationError("a"),
            ),
            pytest.raises(AuthenticationError),
        ):
            await client.get_performance_v4_quarter("ck")

    @pytest.mark.asyncio
    async def test_rate_limit_error_propagates(self):
        """RateLimitError should propagate."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=RateLimitError("r"),
            ),
            pytest.raises(RateLimitError),
        ):
            await client.get_performance_v4_quarter("ck")

    @pytest.mark.asyncio
    async def test_non_dict_raises(self):
        """Non-dict response should raise APIError."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client, "_make_request", new_callable=AsyncMock, return_value=None
            ),
            pytest.raises(
                APIError, match="Failed to fetch performance v4 Quarter data"
            ),
        ):
            await client.get_performance_v4_quarter("ck")


# ---------------------------------------------------------------------------
# Endpoint: get_net_positions
# ---------------------------------------------------------------------------


class TestGetNetPositions:
    """Tests for get_net_positions."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Should return net positions data."""
        data = {"Data": [{"NetPositionId": "123"}]}
        resp = _mock_response(200, json_data=data)
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
            side_effect=_noop_timeout,
        ):
            result = await client.get_net_positions()

        assert result == data

    @pytest.mark.asyncio
    async def test_correct_params(self):
        """Should pass FieldGroups param."""
        resp = _mock_response(200, json_data={})
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with patch(
            "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
            side_effect=_noop_timeout,
        ):
            await client.get_net_positions()

        params = session.get.call_args[1]["params"]
        assert "NetPositionBase" in params["FieldGroups"]
        assert "NetPositionView" in params["FieldGroups"]
        assert "DisplayAndFormat" in params["FieldGroups"]

    @pytest.mark.asyncio
    async def test_auth_error_propagates(self):
        """AuthenticationError should propagate."""
        resp = _mock_response(401, headers={})
        session = _session_with_response(resp)
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            pytest.raises(AuthenticationError),
        ):
            await client.get_net_positions()

    @pytest.mark.asyncio
    async def test_rate_limit_error_propagates(self):
        """RateLimitError should propagate."""
        responses = [
            _mock_response(429, headers={"Retry-After": "1", "X-RateLimit-Reset": "99"})
            for _ in range(MAX_RETRIES)
        ]
        session = _session_with_responses(responses)
        client = _make_client(session=session)

        with (
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(RateLimitError),
        ):
            await client.get_net_positions()

    @pytest.mark.asyncio
    async def test_non_dict_raises(self):
        """Non-dict response should raise APIError."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client, "_make_request", new_callable=AsyncMock, return_value=[]
            ),
            pytest.raises(APIError, match="Failed to fetch net positions"),
        ):
            await client.get_net_positions()

    @pytest.mark.asyncio
    async def test_unexpected_error_wraps(self):
        """Unexpected exceptions should be wrapped in APIError."""
        client = _make_client(session=MagicMock())
        with (
            patch.object(
                client,
                "_make_request",
                new_callable=AsyncMock,
                side_effect=KeyError("k"),
            ),
            pytest.raises(APIError, match="Failed to fetch net positions"),
        ):
            await client.get_net_positions()
