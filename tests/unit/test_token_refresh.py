"""Unit tests for token refresh timeout, retry, and error handling.

Tests cover:
- _token_request() timeout, retry with backoff, and error classification
- Coordinator aiohttp.ClientError handling in _fetch_portfolio_data()
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import aiohttp
import pytest

from contextlib import asynccontextmanager

from custom_components.saxo_portfolio.application_credentials import (
    SaxoAuthImplementation,
)
from custom_components.saxo_portfolio.const import TOKEN_REFRESH_TIMEOUT


@asynccontextmanager
async def _noop_timeout(_delay):
    """No-op replacement for asyncio.timeout in tests."""
    yield


def _make_auth_impl() -> SaxoAuthImplementation:
    """Create a SaxoAuthImplementation with mocked dependencies."""
    hass = MagicMock()
    impl = object.__new__(SaxoAuthImplementation)
    impl.hass = hass
    impl.client_id = "test_id"
    impl.client_secret = "test_secret"
    impl.token_url = "https://example.com/token"
    return impl


def _make_response(
    status: int = 200,
    json_data: dict | None = None,
    content_type: str = "application/json",
) -> AsyncMock:
    """Create a mock aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    resp.content_type = content_type
    resp.json = AsyncMock(return_value=json_data or {})
    resp.request_info = MagicMock()
    resp.history = ()
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = aiohttp.ClientResponseError(
            resp.request_info, resp.history, status=status
        )
    return resp


class TestTokenRequestSuccess:
    """Tests for successful token requests."""

    @pytest.mark.asyncio
    async def test_successful_request_returns_token_with_issued_at(self):
        """Successful request returns token data with token_issued_at."""
        impl = _make_auth_impl()
        token_data = {
            "access_token": "abc",
            "refresh_token": "xyz",
            "expires_in": 1200,
        }
        resp = _make_response(200, token_data)
        session = AsyncMock()
        session.post = AsyncMock(return_value=resp)

        with patch(
            "custom_components.saxo_portfolio.application_credentials.async_get_clientsession",
            return_value=session,
        ):
            result = await impl._token_request({"grant_type": "refresh_token"})

        assert result["access_token"] == "abc"
        assert "token_issued_at" in result
        assert isinstance(result["token_issued_at"], float)

    @pytest.mark.asyncio
    async def test_successful_on_first_attempt_no_info_log(self):
        """No info log when succeeding on the first attempt."""
        impl = _make_auth_impl()
        resp = _make_response(200, {"access_token": "ok"})
        session = AsyncMock()
        session.post = AsyncMock(return_value=resp)

        with (
            patch(
                "custom_components.saxo_portfolio.application_credentials.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.saxo_portfolio.application_credentials._LOGGER"
            ) as mock_logger,
        ):
            await impl._token_request({"grant_type": "refresh_token"})

        mock_logger.info.assert_not_called()


class TestTokenRequestAuthErrors:
    """Tests for 400/401 auth errors (no retry)."""

    @pytest.mark.asyncio
    async def test_400_raises_immediately_no_retry(self):
        """400 auth error raises on first attempt without retrying."""
        impl = _make_auth_impl()
        resp = _make_response(
            400,
            {"error": "invalid_grant", "error_description": "Bad code"},
        )
        session = AsyncMock()
        session.post = AsyncMock(return_value=resp)

        with patch(
            "custom_components.saxo_portfolio.application_credentials.async_get_clientsession",
            return_value=session,
        ):
            with pytest.raises(aiohttp.ClientResponseError) as exc_info:
                await impl._token_request({"grant_type": "authorization_code"})

            assert exc_info.value.status == 400

        # Should only be called once (no retry)
        assert session.post.call_count == 1

    @pytest.mark.asyncio
    async def test_401_raises_immediately_no_retry(self):
        """401 auth error raises on first attempt without retrying."""
        impl = _make_auth_impl()
        resp = _make_response(
            401,
            {"error": "invalid_client", "error_description": "Bad creds"},
        )
        session = AsyncMock()
        session.post = AsyncMock(return_value=resp)

        with patch(
            "custom_components.saxo_portfolio.application_credentials.async_get_clientsession",
            return_value=session,
        ):
            with pytest.raises(aiohttp.ClientResponseError) as exc_info:
                await impl._token_request({"grant_type": "refresh_token"})

            assert exc_info.value.status == 401

        assert session.post.call_count == 1


class TestTokenRequestServerErrors:
    """Tests for 5xx server errors with retry."""

    @pytest.mark.asyncio
    async def test_500_retries_and_succeeds(self):
        """500 error retries and succeeds on second attempt."""
        impl = _make_auth_impl()
        fail_resp = _make_response(500)
        ok_resp = _make_response(200, {"access_token": "recovered"})
        session = AsyncMock()
        session.post = AsyncMock(side_effect=[fail_resp, ok_resp])

        with (
            patch(
                "custom_components.saxo_portfolio.application_credentials.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.saxo_portfolio.application_credentials.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
        ):
            result = await impl._token_request({"grant_type": "refresh_token"})

        assert result["access_token"] == "recovered"
        assert session.post.call_count == 2
        mock_sleep.assert_called_once_with(1)  # 2^(1-1) = 1

    @pytest.mark.asyncio
    async def test_500_exhausts_all_retries(self):
        """500 error exhausts all 5 attempts then raises."""
        impl = _make_auth_impl()
        fail_resp = _make_response(500)
        session = AsyncMock()
        session.post = AsyncMock(return_value=fail_resp)

        with (
            patch(
                "custom_components.saxo_portfolio.application_credentials.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.saxo_portfolio.application_credentials.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
        ):
            with pytest.raises(aiohttp.ClientResponseError):
                await impl._token_request({"grant_type": "refresh_token"})

        assert session.post.call_count == 5
        # Backoff: 2^0=1, 2^1=2, 2^2=4, 2^3=8 (only between attempts, not after last)
        assert mock_sleep.call_count == 4
        mock_sleep.assert_any_call(1)
        mock_sleep.assert_any_call(2)
        mock_sleep.assert_any_call(4)
        mock_sleep.assert_any_call(8)

    @pytest.mark.asyncio
    async def test_503_logs_info_on_retry_success(self):
        """Logs info message when succeeding after retries."""
        impl = _make_auth_impl()
        fail_resp = _make_response(503)
        ok_resp = _make_response(200, {"access_token": "ok"})
        session = AsyncMock()
        session.post = AsyncMock(side_effect=[fail_resp, ok_resp])

        with (
            patch(
                "custom_components.saxo_portfolio.application_credentials.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.saxo_portfolio.application_credentials.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.saxo_portfolio.application_credentials._LOGGER"
            ) as mock_logger,
        ):
            await impl._token_request({"grant_type": "refresh_token"})

        mock_logger.info.assert_called_once()
        # Format string uses %d placeholders
        assert "attempt %d/%d" in mock_logger.info.call_args[0][0]


class TestTokenRequestTimeout:
    """Tests for timeout handling."""

    @pytest.mark.asyncio
    async def test_timeout_retries_and_succeeds(self):
        """Timeout on first attempt, succeeds on second."""
        impl = _make_auth_impl()
        ok_resp = _make_response(200, {"access_token": "ok"})
        session = AsyncMock()
        session.post = AsyncMock(side_effect=[TimeoutError(), ok_resp])

        with (
            patch(
                "custom_components.saxo_portfolio.application_credentials.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.saxo_portfolio.application_credentials.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            # Disable the real asyncio.timeout so our mock TimeoutError propagates
            patch(
                "custom_components.saxo_portfolio.application_credentials.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
        ):
            result = await impl._token_request({"grant_type": "refresh_token"})

        assert result["access_token"] == "ok"
        assert session.post.call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_exhausts_all_retries(self):
        """Timeout on all attempts raises TimeoutError."""
        impl = _make_auth_impl()
        session = AsyncMock()
        session.post = AsyncMock(side_effect=TimeoutError())

        with (
            patch(
                "custom_components.saxo_portfolio.application_credentials.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.saxo_portfolio.application_credentials.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.saxo_portfolio.application_credentials.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
        ):
            with pytest.raises(TimeoutError):
                await impl._token_request({"grant_type": "refresh_token"})

        assert session.post.call_count == 5


class TestTokenRequestNetworkErrors:
    """Tests for aiohttp.ClientError network errors."""

    @pytest.mark.asyncio
    async def test_client_error_retries_and_succeeds(self):
        """Network error retries and succeeds on next attempt."""
        impl = _make_auth_impl()
        ok_resp = _make_response(200, {"access_token": "ok"})
        session = AsyncMock()
        session.post = AsyncMock(
            side_effect=[aiohttp.ClientConnectorError(Mock(), Mock()), ok_resp]
        )

        with (
            patch(
                "custom_components.saxo_portfolio.application_credentials.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.saxo_portfolio.application_credentials.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.saxo_portfolio.application_credentials.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
        ):
            result = await impl._token_request({"grant_type": "refresh_token"})

        assert result["access_token"] == "ok"

    @pytest.mark.asyncio
    async def test_client_error_exhausts_retries(self):
        """Network error on all attempts raises the last exception."""
        impl = _make_auth_impl()
        session = AsyncMock()
        session.post = AsyncMock(side_effect=aiohttp.ServerDisconnectedError())

        with (
            patch(
                "custom_components.saxo_portfolio.application_credentials.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.saxo_portfolio.application_credentials.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.saxo_portfolio.application_credentials.asyncio.timeout",
                side_effect=_noop_timeout,
            ),
        ):
            with pytest.raises(aiohttp.ServerDisconnectedError):
                await impl._token_request({"grant_type": "refresh_token"})

        assert session.post.call_count == 5


class TestTokenRequestBackoffTiming:
    """Tests for exponential backoff timing."""

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self):
        """Backoff delays follow 2^(attempt-1) pattern: 1s, 2s, 4s, 8s."""
        impl = _make_auth_impl()
        fail_resp = _make_response(502)
        session = AsyncMock()
        session.post = AsyncMock(return_value=fail_resp)

        with (
            patch(
                "custom_components.saxo_portfolio.application_credentials.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.saxo_portfolio.application_credentials.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
        ):
            with pytest.raises(aiohttp.ClientResponseError):
                await impl._token_request({"grant_type": "refresh_token"})

        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays == [1, 2, 4, 8]


class TestTokenRefreshTimeoutConstant:
    """Tests for the TOKEN_REFRESH_TIMEOUT constant."""

    def test_timeout_value_is_reasonable(self):
        """Timeout should be > 0 and well under the 60s coordinator timeout."""
        assert TOKEN_REFRESH_TIMEOUT > 0
        assert TOKEN_REFRESH_TIMEOUT < 60
        assert TOKEN_REFRESH_TIMEOUT == 15


class TestCoordinatorClientErrorHandler:
    """Tests for aiohttp.ClientError handling in coordinator._fetch_portfolio_data()."""

    @pytest.mark.asyncio
    async def test_client_error_raises_update_failed(self):
        """aiohttp.ClientError during fetch raises UpdateFailed."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        from custom_components.saxo_portfolio.coordinator import SaxoCoordinator

        coordinator = object.__new__(SaxoCoordinator)
        coordinator._initial_update_offset = 0
        coordinator._last_successful_update = None

        # Make _ensure_token_valid raise aiohttp.ClientError
        # (simulates token refresh network failure bubbling up)
        coordinator._oauth_session = MagicMock()
        coordinator._ensure_token_valid = AsyncMock(
            side_effect=aiohttp.ClientConnectionError("Connection refused")
        )

        with pytest.raises(UpdateFailed, match="Network error"):
            await coordinator._fetch_portfolio_data()

    @pytest.mark.asyncio
    async def test_client_error_logs_warning(self):
        """aiohttp.ClientError is logged as warning with actionable message."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        from custom_components.saxo_portfolio.coordinator import SaxoCoordinator

        coordinator = object.__new__(SaxoCoordinator)
        coordinator._initial_update_offset = 0
        coordinator._last_successful_update = None
        coordinator._oauth_session = MagicMock()
        coordinator._ensure_token_valid = AsyncMock(
            side_effect=aiohttp.ClientConnectionError("Connection refused")
        )

        with (
            patch(
                "custom_components.saxo_portfolio.coordinator._LOGGER"
            ) as mock_logger,
            pytest.raises(UpdateFailed),
        ):
            await coordinator._fetch_portfolio_data()

        mock_logger.warning.assert_called_once()
        log_msg = mock_logger.warning.call_args[0][0]
        assert "Network error" in log_msg
        assert "token refresh" in log_msg.lower() or "connectivity" in log_msg.lower()

    @pytest.mark.asyncio
    async def test_client_error_caught_before_generic_exception(self):
        """aiohttp.ClientError is caught specifically, not by generic Exception."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        from custom_components.saxo_portfolio.coordinator import SaxoCoordinator

        coordinator = object.__new__(SaxoCoordinator)
        coordinator._initial_update_offset = 0
        coordinator._last_successful_update = None
        coordinator._oauth_session = MagicMock()
        coordinator._ensure_token_valid = AsyncMock(
            side_effect=aiohttp.ServerDisconnectedError()
        )

        with pytest.raises(UpdateFailed, match="Network error"):
            await coordinator._fetch_portfolio_data()
        # If it hit the generic handler, the message would be "Unexpected error"
