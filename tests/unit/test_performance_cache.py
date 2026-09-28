"""Performance cache behaviour on failed / partial fetches (issue #15).

A failed or partial performance fetch must not refresh the 2 h cache
timestamp (so the next update retries it), must keep previously fetched
good values, must leave never-fetched values unknown (None) rather than
0.0, and must not block balance data.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.saxo_portfolio.api.saxo_client import APIError
from custom_components.saxo_portfolio.const import PERFORMANCE_UPDATE_INTERVAL
from custom_components.saxo_portfolio.data import (
    BalanceData,
    ClientInfo,
    PerformanceData,
    SaxoPortfolioData,
)
from custom_components.saxo_portfolio.sensor import (
    SaxoAccumulatedProfitLossSensor,
    SaxoInvestmentPerformanceSensor,
)

from .test_coordinator import _bare_coordinator

PERF_KEYS = (
    "ytd_earnings_percentage",
    "investment_performance_percentage",
    "ytd_investment_performance_percentage",
    "month_investment_performance_percentage",
    "quarter_investment_performance_percentage",
    "cash_transfer_balance",
    "ytd_profit_loss",
    "ytd_cash_transfer",
)

CLIENT_DETAILS = {
    "ClientKey": "ck1",
    "ClientId": "C1",
    "DefaultAccountId": "A1",
    "Name": "Test User",
}


def _v4_batch(scale: float = 1.0) -> dict:
    return {
        "alltime": {
            "KeyFigures": {"ReturnFraction": 0.10 * scale},
            "Balance": {"CashTransfer": [{"Value": 1000.0 * scale}]},
        },
        "ytd": {
            "KeyFigures": {"ReturnFraction": 0.05 * scale},
            "Balance": {
                "YearlyProfitLoss": [
                    {"Date": f"{datetime.now().year}-12-31", "Value": 500.0 * scale}
                ],
                "CashTransfer": [{"Value": 200.0 * scale}],
            },
        },
        "month": {"KeyFigures": {"ReturnFraction": 0.02 * scale}},
        "quarter": {"KeyFigures": {"ReturnFraction": 0.03 * scale}},
    }


def _client(
    *,
    details: object = CLIENT_DETAILS,
    v3: object = None,
    v4: object = None,
) -> AsyncMock:
    """Build a mock API client; pass an Exception instance to make a call fail."""
    client = AsyncMock()
    client.access_token = "tok"
    client.get_client_details = AsyncMock(return_value=details)

    if isinstance(v3, Exception):
        client.get_performance = AsyncMock(side_effect=v3)
    else:
        client.get_performance = AsyncMock(
            return_value=v3 or {"BalancePerformance": {"AccumulatedProfitLoss": 123.0}}
        )

    if isinstance(v4, Exception):
        client.get_performance_v4_batch = AsyncMock(side_effect=v4)
    else:
        client.get_performance_v4_batch = AsyncMock(return_value=v4 or _v4_batch())
    return client


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch(
        "custom_components.saxo_portfolio.coordinator.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        yield


def _expire_cache(coord) -> None:
    """Pretend the last good fetch happened longer ago than the cache TTL."""
    coord._performance_last_updated = (
        datetime.now() - PERFORMANCE_UPDATE_INTERVAL - PERFORMANCE_UPDATE_INTERVAL
    )


class TestNeverFetched:
    """Without any good fetch, performance values are unknown, not 0.0."""

    def test_defaults_are_none(self):
        coord = _bare_coordinator()
        defaults = coord._build_performance_defaults()
        for key in PERF_KEYS:
            assert defaults[key] is None, key

    async def test_startup_failure_leaves_values_unknown(self):
        coord = _bare_coordinator()
        client = _client(v3=APIError("x"), v4=APIError("x"))

        result = await coord._fetch_performance_data_safely(client)

        for key in PERF_KEYS:
            assert result[key] is None, key
        assert coord._performance_last_updated is None

    def test_typed_data_is_none_without_values(self):
        coord = _bare_coordinator()
        performance = coord._to_performance_data(coord._build_performance_defaults())
        assert performance == PerformanceData()
        for key in PERF_KEYS:
            assert getattr(performance, key) is None, key

    def test_sensors_unknown_without_values(self):
        coord = _bare_coordinator()
        coord.last_update_success = True
        coord.data = SaxoPortfolioData(
            balance=BalanceData(cash_balance=1.0, currency="EUR"),
            performance=coord._to_performance_data(coord._build_performance_defaults()),
            client=ClientInfo(client_id="C1"),
            last_updated=datetime.now(),
        )

        coord.last_update_success = True
        for sensor in (
            SaxoInvestmentPerformanceSensor(coord),
            SaxoAccumulatedProfitLossSensor(coord),
        ):
            # Unknown (available, no value) rather than 0.0 or unavailable
            assert sensor.native_value is None
            assert sensor.available is True


class TestStartupFailureThenRecovery:
    """A failure at startup is retried on the very next update cycle."""

    @pytest.mark.parametrize(
        "failing_client",
        [
            _client(details=None),
            _client(v4=APIError("v4 down")),
            _client(v3=APIError("v3 down")),
        ],
        ids=["client_details", "v4", "v3"],
    )
    async def test_retry_next_cycle(self, failing_client):
        coord = _bare_coordinator()

        await coord._fetch_performance_data_safely(failing_client)
        assert coord._performance_last_updated is None
        assert coord._should_update_performance_data() is True

        good = _client()
        result = await coord._fetch_performance_data_safely(good)

        good.get_performance_v4_batch.assert_awaited_once()
        assert coord._performance_last_updated is not None
        assert result["investment_performance_percentage"] == pytest.approx(10.0)
        assert result["ytd_earnings_percentage"] == 123.0
        assert result["client_id"] == "C1"

    async def test_timeout_does_not_refresh_timestamp(self):
        coord = _bare_coordinator()
        with patch(
            "custom_components.saxo_portfolio.coordinator.PERFORMANCE_FETCH_TIMEOUT",
            0.01,
        ):

            async def _hang(*args, **kwargs):
                import asyncio

                await asyncio.Event().wait()

            client = _client()
            client.get_client_details = AsyncMock(side_effect=_hang)
            await coord._fetch_performance_data_safely(client)

        assert coord._performance_last_updated is None


class TestFailureAfterGoodFetch:
    """A later failure keeps the last known good values."""

    async def test_total_failure_keeps_old_values(self):
        coord = _bare_coordinator()
        first = await coord._fetch_performance_data_safely(_client())
        good_timestamp = coord._performance_last_updated
        _expire_cache(coord)
        stale_timestamp = coord._performance_last_updated

        result = await coord._fetch_performance_data_safely(
            _client(details=None, v3=APIError("x"), v4=APIError("x"))
        )

        assert good_timestamp is not None
        for key in PERF_KEYS:
            assert result[key] == first[key], key
        assert result["client_id"] == "C1"
        assert result["client_name"] == "Test User"
        # Not refreshed: the next cycle retries.
        assert coord._performance_last_updated == stale_timestamp
        assert coord._should_update_performance_data() is True

    async def test_v4_failure_keeps_old_v4_values_updates_v3(self):
        coord = _bare_coordinator()
        first = await coord._fetch_performance_data_safely(_client())
        _expire_cache(coord)
        stale_timestamp = coord._performance_last_updated

        result = await coord._fetch_performance_data_safely(
            _client(
                v3={"BalancePerformance": {"AccumulatedProfitLoss": 999.0}},
                v4=APIError("v4 down"),
            )
        )

        assert result["ytd_earnings_percentage"] == 999.0
        for key in PERF_KEYS:
            if key != "ytd_earnings_percentage":
                assert result[key] == first[key], key
        assert coord._performance_last_updated == stale_timestamp

    async def test_v3_failure_keeps_old_v3_value_updates_v4(self):
        coord = _bare_coordinator()
        await coord._fetch_performance_data_safely(_client())
        _expire_cache(coord)
        stale_timestamp = coord._performance_last_updated

        result = await coord._fetch_performance_data_safely(
            _client(v3=APIError("v3 down"), v4=_v4_batch(scale=2.0))
        )

        assert result["ytd_earnings_percentage"] == 123.0
        assert result["investment_performance_percentage"] == pytest.approx(20.0)
        assert result["ytd_profit_loss"] == pytest.approx(1000.0)
        assert coord._performance_last_updated == stale_timestamp

    async def test_client_details_failure_keeps_everything(self):
        coord = _bare_coordinator()
        first = await coord._fetch_performance_data_safely(_client())
        _expire_cache(coord)
        stale_timestamp = coord._performance_last_updated

        client = _client(details=None)
        result = await coord._fetch_performance_data_safely(client)

        client.get_performance.assert_not_awaited()
        for key in (*PERF_KEYS, "client_id", "account_id", "client_name"):
            assert result[key] == first[key], key
        assert coord._performance_last_updated == stale_timestamp

    async def test_cached_values_served_between_fetches(self):
        """Partial values are also served on the next cycle if it fails too."""
        coord = _bare_coordinator()
        await coord._fetch_performance_data_safely(_client(v4=APIError("x")))
        result = await coord._fetch_performance_data_safely(
            _client(v3=APIError("x"), v4=APIError("x"))
        )
        assert result["ytd_earnings_percentage"] == 123.0
        assert result["investment_performance_percentage"] is None
        assert coord._performance_last_updated is None


class TestBalanceUnaffected:
    """Balance data still updates when performance calls fail."""

    async def test_balance_updates_when_performance_fails(self):
        coord = _bare_coordinator()
        coord._last_successful_update = datetime.now()
        client = _client(details=None, v3=APIError("x"), v4=APIError("x"))
        coord._api_client = client
        coord._oauth_session.token = {"access_token": "tok"}

        with (
            patch.object(coord, "_ensure_token_valid", new_callable=AsyncMock),
            patch.object(
                coord,
                "_fetch_balance_with_logging",
                new_callable=AsyncMock,
                return_value={
                    "CashBalance": 1000.0,
                    "Currency": "EUR",
                    "TotalValue": 5000.0,
                    "NonMarginPositionsValue": 4000.0,
                },
            ),
        ):
            result = await coord._fetch_portfolio_data()

        assert result.balance.cash_balance == 1000.0
        assert result.balance.total_value == 5000.0
        assert result.performance == PerformanceData()
        assert coord._performance_last_updated is None
