"""Performance cache behaviour on failed / partial fetches (issue #15).

A failed or partial performance fetch must not refresh the 2 h cache
timestamp (so the next update retries it), must keep previously fetched
good values, must leave never-fetched values unknown (None) rather than
0.0, and must not block balance data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.saxo_portfolio.api.saxo_client import APIError
from custom_components.saxo_portfolio.const import (
    PERFORMANCE_RETRY_INTERVAL,
    PERFORMANCE_UPDATE_INTERVAL,
)
from custom_components.saxo_portfolio.data import (
    BalanceData,
    ClientInfo,
    PerformanceData,
    SaxoPortfolioData,
)
from custom_components.saxo_portfolio.performance import PerformanceFetcher
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
        "custom_components.saxo_portfolio.performance.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        yield


def _fetcher() -> PerformanceFetcher:
    return PerformanceFetcher(on_client_info=lambda client: None)


async def _fetch(fetcher: PerformanceFetcher, client) -> dict:
    """Run one fetch and return the resulting values by field name."""
    await fetcher.async_update(client)
    return {
        **{key: getattr(fetcher.metrics, key) for key in PERF_KEYS},
        "client_id": fetcher.client.client_id,
        "account_id": fetcher.client.account_id,
        "client_name": fetcher.client.client_name,
    }


def _expire_cache(fetcher: PerformanceFetcher) -> None:
    """Pretend the last good fetch happened longer ago than the cache TTL."""
    fetcher.last_updated = (
        datetime.now() - PERFORMANCE_UPDATE_INTERVAL - PERFORMANCE_UPDATE_INTERVAL
    )


class TestNeverFetched:
    """Without any good fetch, performance values are unknown, not 0.0."""

    def test_defaults_are_none(self):
        metrics = _fetcher().metrics
        assert metrics == PerformanceData()
        for key in PERF_KEYS:
            assert getattr(metrics, key) is None, key

    async def test_startup_failure_leaves_values_unknown(self):
        fetcher = _fetcher()
        client = _client(v3=APIError("x"), v4=APIError("x"))

        result = await _fetch(fetcher, client)

        for key in PERF_KEYS:
            assert result[key] is None, key
        assert fetcher.last_updated is None

    def test_sensors_unknown_without_values(self):
        coord = _bare_coordinator()
        coord.last_update_success = True
        coord.data = SaxoPortfolioData(
            balance=BalanceData(cash_balance=1.0, currency="EUR"),
            performance=coord._performance.metrics,
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


def _after(delta: timedelta):
    """Patch the fetcher's clock to ``delta`` from now."""
    moved = datetime.now() + delta
    return patch(
        "custom_components.saxo_portfolio.performance.datetime",
        **{"now.return_value": moved},
    )


class TestStartupFailureThenRecovery:
    """A failure at startup is retried once the retry backoff has elapsed."""

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
        fetcher = _fetcher()

        await _fetch(fetcher, failing_client)
        assert fetcher.last_updated is None
        # Backing off: the very next poll must not re-hit the API ...
        assert fetcher.should_update() is False
        # ... but once the retry interval has passed it retries.
        with _after(PERFORMANCE_RETRY_INTERVAL + timedelta(seconds=1)):
            assert fetcher.should_update() is True

        good = _client()
        with _after(PERFORMANCE_RETRY_INTERVAL + timedelta(seconds=1)):
            result = await _fetch(fetcher, good)

        good.get_performance_v4_batch.assert_awaited_once()
        assert fetcher.last_updated is not None
        assert result["investment_performance_percentage"] == pytest.approx(10.0)
        assert result["ytd_earnings_percentage"] == 123.0
        assert result["client_id"] == "C1"

    async def test_backoff_issues_no_api_calls_between_retries(self):
        """A permanently failing endpoint is not re-requested on every poll."""
        fetcher = _fetcher()
        failing = _client(v4=APIError("no access"))
        await _fetch(fetcher, failing)
        calls = failing.get_performance_v4_batch.await_count

        for _ in range(3):
            await _fetch(fetcher, failing)

        assert failing.get_performance_v4_batch.await_count == calls

    async def test_complete_fetch_clears_backoff(self):
        fetcher = _fetcher()
        await _fetch(fetcher, _client(v4=APIError("v4 down")))
        with _after(PERFORMANCE_RETRY_INTERVAL + timedelta(seconds=1)):
            await _fetch(fetcher, _client())
        assert fetcher.last_updated is not None
        assert fetcher.should_update() is False  # fresh cache, no backoff left

    async def test_timeout_does_not_refresh_timestamp(self):
        fetcher = _fetcher()
        with patch(
            "custom_components.saxo_portfolio.performance.PERFORMANCE_FETCH_TIMEOUT",
            0.01,
        ):

            async def _hang(*args, **kwargs):
                import asyncio

                await asyncio.Event().wait()

            client = _client()
            client.get_client_details = AsyncMock(side_effect=_hang)
            await _fetch(fetcher, client)

        assert fetcher.last_updated is None
        assert fetcher.should_update() is False  # a timeout backs off too


class TestFailureAfterGoodFetch:
    """A later failure keeps the last known good values."""

    async def test_total_failure_keeps_old_values(self):
        fetcher = _fetcher()
        first = await _fetch(fetcher, _client())
        good_timestamp = fetcher.last_updated
        _expire_cache(fetcher)
        stale_timestamp = fetcher.last_updated

        result = await _fetch(
            fetcher, _client(details=None, v3=APIError("x"), v4=APIError("x"))
        )

        assert good_timestamp is not None
        for key in PERF_KEYS:
            assert result[key] == first[key], key
        assert result["client_id"] == "C1"
        assert result["client_name"] == "Test User"
        # Not refreshed: retried once the backoff has elapsed.
        assert fetcher.last_updated == stale_timestamp
        assert fetcher.should_update() is False
        with _after(PERFORMANCE_RETRY_INTERVAL + timedelta(seconds=1)):
            assert fetcher.should_update() is True

    async def test_v4_failure_keeps_old_v4_values_updates_v3(self):
        fetcher = _fetcher()
        first = await _fetch(fetcher, _client())
        _expire_cache(fetcher)
        stale_timestamp = fetcher.last_updated

        result = await _fetch(
            fetcher,
            _client(
                v3={"BalancePerformance": {"AccumulatedProfitLoss": 999.0}},
                v4=APIError("v4 down"),
            ),
        )

        assert result["ytd_earnings_percentage"] == 999.0
        for key in PERF_KEYS:
            if key != "ytd_earnings_percentage":
                assert result[key] == first[key], key
        assert fetcher.last_updated == stale_timestamp

    async def test_v3_failure_keeps_old_v3_value_updates_v4(self):
        fetcher = _fetcher()
        await _fetch(fetcher, _client())
        _expire_cache(fetcher)
        stale_timestamp = fetcher.last_updated

        result = await _fetch(
            fetcher, _client(v3=APIError("v3 down"), v4=_v4_batch(scale=2.0))
        )

        assert result["ytd_earnings_percentage"] == 123.0
        assert result["investment_performance_percentage"] == pytest.approx(20.0)
        assert result["ytd_profit_loss"] == pytest.approx(1000.0)
        assert fetcher.last_updated == stale_timestamp

    async def test_client_details_failure_keeps_everything(self):
        fetcher = _fetcher()
        first = await _fetch(fetcher, _client())
        _expire_cache(fetcher)
        stale_timestamp = fetcher.last_updated

        client = _client(details=None)
        result = await _fetch(fetcher, client)

        client.get_performance.assert_not_awaited()
        for key in (*PERF_KEYS, "client_id", "account_id", "client_name"):
            assert result[key] == first[key], key
        assert fetcher.last_updated == stale_timestamp

    async def test_cached_values_served_between_fetches(self):
        """Partial values are also served on the next cycle if it fails too."""
        fetcher = _fetcher()
        await _fetch(fetcher, _client(v4=APIError("x")))
        result = await _fetch(fetcher, _client(v3=APIError("x"), v4=APIError("x")))
        assert result["ytd_earnings_percentage"] == 123.0
        assert result["investment_performance_percentage"] is None
        assert fetcher.last_updated is None


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
                return_value=BalanceData(
                    cash_balance=1000.0,
                    currency="EUR",
                    total_value=5000.0,
                    non_margin_positions_value=4000.0,
                ),
            ),
        ):
            result = await coord._fetch_portfolio_data()

        assert result.balance.cash_balance == 1000.0
        assert result.balance.total_value == 5000.0
        assert result.performance == PerformanceData()
        assert coord.performance_last_updated is None
