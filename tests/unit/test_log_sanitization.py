"""Log sanitization tests (issue #14).

A user must be able to enable debug logging and share the log publicly
without exposing identifiers or financial figures. These tests run a full
coordinator update against fixture API responses with DEBUG logging on and
assert that none of the fixture's identifiers or amounts end up in the logs.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.saxo_portfolio.api.saxo_client import APIError, SaxoApiClient
from custom_components.saxo_portfolio.const import (
    API_BALANCE_ENDPOINT,
    API_CLIENT_DETAILS_ENDPOINT,
    API_NET_POSITIONS_ENDPOINT,
    API_PERFORMANCE_ENDPOINT,
    API_PERFORMANCE_V4_ENDPOINT,
    SAXO_API_BASE_URL,
)
from custom_components.saxo_portfolio.coordinator import SaxoCoordinator

# ---------------------------------------------------------------------------
# Fixture data — every value below is distinctive so it can be searched for.
# ---------------------------------------------------------------------------

CLIENT_ID = "8812345"
CLIENT_KEY = "QkFfixtureClientKey7Zq|xx"
ACCOUNT_ID = "ACC-99887766"
ACCOUNT_KEY = "AccKeyFixture55a1b"
CLIENT_NAME = "Jane Fixturesson"

BALANCE = {
    "CashBalance": 12345.67,
    "Currency": "EUR",
    "TotalValue": 98765.43,
    "NonMarginPositionsValue": 86419.76,
    "MarginCollateralNotAvailableDetail": {"Foo": 1},
}

CLIENT_DETAILS = {
    "ClientId": CLIENT_ID,
    "ClientKey": CLIENT_KEY,
    "DefaultAccountId": ACCOUNT_ID,
    "DefaultAccountKey": ACCOUNT_KEY,
    "Name": CLIENT_NAME,
}

PERFORMANCE_V3 = {"BalancePerformance": {"AccumulatedProfitLoss": 4321.09}}

V4_ALLTIME = {
    "KeyFigures": {"ReturnFraction": 0.123456},
    "Balance": {"CashTransfer": [{"Date": "2026-01-01", "Value": 13579.24}]},
}
V4_YTD = {
    "KeyFigures": {"ReturnFraction": 0.065432},
    "Balance": {
        "YearlyProfitLoss": [{"Date": "2026-12-31", "Value": 2468.13}],
        "CashTransfer": [{"Date": "2026-04-01", "Value": 1122.33}],
    },
}
V4_MONTH = {"KeyFigures": {"ReturnFraction": 0.017283}}
V4_QUARTER = {"KeyFigures": {"ReturnFraction": 0.042871}}

POSITIONS = {
    "__count": 1,
    "Data": [
        {
            "NetPositionId": "NPID-FIXTURE-4455",
            "NetPositionBase": {
                "Uic": 211,
                "AssetType": "Stock",
                "Amount": 173.25,
                "AccountId": ACCOUNT_ID,
            },
            "NetPositionView": {
                "CurrentPrice": 0.0,
                "CurrentPriceType": "None",
                "CalculationReliability": "ApproximatedPrice",
                "ProfitLossOnTrade": 555.55,
                "MarketValueOpen": -35000.12,
                "Exposure": 36622.85,
            },
            "DisplayAndFormat": {
                "Symbol": "AAPL:xnas",
                "Description": "Apple Inc.",
                "Currency": "USD",
            },
        }
    ],
}

# Strings that must never appear in any captured log record.
FORBIDDEN = [
    CLIENT_ID,
    CLIENT_KEY,
    CLIENT_KEY[:10],
    ACCOUNT_ID,
    ACCOUNT_KEY,
    CLIENT_NAME,
    "NPID-FIXTURE-4455",
    "12345.67",
    "98765.43",
    "86419.76",
    "4321.09",
    "13579.24",
    "2468.13",
    "1122.33",
    "12.3456",
    "6.5432",
    "1.7283",
    "4.2871",
    "173.25",
    "555.55",
    "35000.12",
    "36622.85",
    "test_access_token",
    "test_refresh_token",
]


def _route(url: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Return the fixture JSON for a given request."""
    path = url.removeprefix(SAXO_API_BASE_URL)
    if path == API_BALANCE_ENDPOINT:
        return BALANCE
    if path == API_CLIENT_DETAILS_ENDPOINT:
        return CLIENT_DETAILS
    if path == f"{API_PERFORMANCE_ENDPOINT}{CLIENT_KEY}":
        return PERFORMANCE_V3
    if path == API_NET_POSITIONS_ENDPOINT:
        return POSITIONS
    if path == API_PERFORMANCE_V4_ENDPOINT:
        params = params or {}
        if "FromDate" in params:
            return V4_YTD
        return {
            "AllTime": V4_ALLTIME,
            "Month": V4_MONTH,
            "Quarter": V4_QUARTER,
        }[params["StandardPeriod"]]
    raise AssertionError(f"Unexpected request path in test: {path}")


def _fake_session() -> MagicMock:
    """Build a fake aiohttp session that serves the fixture data."""

    @asynccontextmanager
    async def _get(url: str, params: dict[str, Any] | None = None, headers=None):
        resp = MagicMock(spec=aiohttp.ClientResponse)
        resp.status = 200
        resp.json = AsyncMock(return_value=_route(url, params))
        resp.headers = {}
        yield resp

    session = MagicMock(spec=aiohttp.ClientSession)
    session.get = MagicMock(side_effect=_get)
    return session


def _all_log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Join every captured message (with args interpolated) and exception."""
    parts: list[str] = []
    for record in caplog.records:
        parts.append(record.getMessage())
        if record.exc_info and record.exc_info[1] is not None:
            parts.append(str(record.exc_info[1]))
    return "\n".join(parts)


@pytest.fixture
def debug_caplog(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Capture DEBUG logs from the integration."""
    caplog.set_level(logging.DEBUG, logger="custom_components.saxo_portfolio")
    return caplog


class TestFullUpdateLogSanitization:
    """A full coordinator update must not leak fixture identifiers/amounts."""

    async def test_full_update_logs_are_sanitized(
        self, mock_hass, mock_config_entry, mock_oauth_session, debug_caplog
    ) -> None:
        """Run a full update at DEBUG level and scan the captured logs."""
        mock_config_entry.options = {"enable_position_sensors": True}
        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
        coordinator.config_entry = mock_config_entry
        # Simulate the name resolving after setup, which triggers a reload log.
        coordinator.mark_setup_complete()

        with (
            patch(
                "custom_components.saxo_portfolio.coordinator.async_get_clientsession",
                return_value=_fake_session(),
            ),
            patch(
                "custom_components.saxo_portfolio.coordinator.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.saxo_portfolio.api.saxo_client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            data = await coordinator._async_update_data()

        # Sanity: the update really did go through every step with fixture data.
        assert data["client_id"] == CLIENT_ID
        assert data["cash_balance"] == 12345.67
        assert data["ytd_profit_loss"] == pytest.approx(2468.13)
        assert len(coordinator.get_positions()) == 1

        log_text = _all_log_text(debug_caplog)
        leaked = [value for value in FORBIDDEN if value in log_text]
        assert not leaked, f"Sensitive fixture values leaked into logs: {leaked}"

        # Logs still describe what happened.
        assert "client details fetched" in log_text.lower()
        assert "1 positions parsed" in log_text.lower()

        # The title still identifies the account, but it is never logged.
        mock_hass.config_entries.async_update_entry.assert_called()


class TestApiErrorBodies:
    """Raw API error bodies must not reach logs or exception messages."""

    @pytest.mark.parametrize("status", [400, 500, 503])
    async def test_error_body_not_logged_or_embedded(
        self, status: int, debug_caplog
    ) -> None:
        """An error body echoing account data is summarised, not copied."""
        body = (
            '{"ErrorCode": "InvalidRequest", "Message": "Account '
            f'{ACCOUNT_ID} for client {CLIENT_KEY} has balance 12345.67"}}'
        )

        @asynccontextmanager
        async def _get(url, params=None, headers=None):
            resp = MagicMock(spec=aiohttp.ClientResponse)
            resp.status = status
            resp.text = AsyncMock(return_value=body)
            resp.headers = {}
            yield resp

        session = MagicMock(spec=aiohttp.ClientSession)
        session.get = MagicMock(side_effect=_get)
        client = SaxoApiClient("test_access_token", SAXO_API_BASE_URL, session)

        with pytest.raises(APIError) as exc_info:
            await client._make_request(f"{API_PERFORMANCE_ENDPOINT}{CLIENT_KEY}")

        message = str(exc_info.value)
        assert f"HTTP {status}" in message
        assert "InvalidRequest" in message

        combined = message + "\n" + _all_log_text(debug_caplog)
        for value in (ACCOUNT_ID, CLIENT_KEY, CLIENT_KEY[:10], "12345.67"):
            assert value not in combined

    async def test_non_json_error_body_not_embedded(self, debug_caplog) -> None:
        """A plain-text body is reduced to its length."""
        resp = MagicMock(spec=aiohttp.ClientResponse)
        resp.status = 400
        resp.text = AsyncMock(return_value=f"bad account {ACCOUNT_ID}")
        resp.headers = {}
        client = SaxoApiClient("test_access_token", SAXO_API_BASE_URL, MagicMock())

        with pytest.raises(APIError) as exc_info:
            await client._handle_response_status(resp, "https://x/y", 0)

        assert ACCOUNT_ID not in str(exc_info.value)
        assert ACCOUNT_ID not in _all_log_text(debug_caplog)
