"""Unit tests for performance.py: parsing, fetching and the performance cache.

Cache semantics on failed / partial fetches (#15) are covered end to end in
test_performance_cache.py; these tests focus on the individual pieces.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.saxo_portfolio.const import PERFORMANCE_UPDATE_INTERVAL
from custom_components.saxo_portfolio.data import ClientInfo, PerformanceData
from custom_components.saxo_portfolio.performance import (
    PerformanceFetcher,
    apply_v3_performance,
    apply_v4_batch,
    current_year_bucket,
    last_series_value,
    parse_client_details,
)

NOW = "custom_components.saxo_portfolio.performance.dt_util.now"


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch(
        "custom_components.saxo_portfolio.performance.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        yield


def _fetcher() -> PerformanceFetcher:
    return PerformanceFetcher(on_client_info=MagicMock())


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParseClientDetails:
    def test_full_details(self):
        client = parse_client_details(
            {
                "ClientKey": "ck1",
                "ClientId": "C1",
                "DefaultAccountId": "A1",
                "Name": "Test User",
            }
        )
        assert client == ClientInfo(
            client_id="C1", account_id="A1", client_name="Test User"
        )

    def test_missing_fields_are_unknown(self):
        assert parse_client_details({"ClientKey": "ck1"}) == ClientInfo()

    def test_values_are_strings(self):
        assert parse_client_details({"ClientId": 12345}).client_id == "12345"


class TestApplyV3Performance:
    def test_accumulated_profit_loss(self):
        metrics = apply_v3_performance(
            PerformanceData(),
            {"BalancePerformance": {"AccumulatedProfitLoss": 123.4}},
        )
        assert metrics == PerformanceData(ytd_earnings_percentage=123.4)

    def test_missing_value_defaults_to_zero(self):
        metrics = apply_v3_performance(PerformanceData(), {})
        assert metrics.ytd_earnings_percentage == 0.0

    def test_non_numeric_value_is_unknown(self):
        metrics = apply_v3_performance(
            PerformanceData(ytd_earnings_percentage=5.0),
            {"BalancePerformance": {"AccumulatedProfitLoss": "n/a"}},
        )
        assert metrics.ytd_earnings_percentage is None

    def test_other_fields_untouched(self):
        start = PerformanceData(investment_performance_percentage=7.0)
        metrics = apply_v3_performance(
            start, {"BalancePerformance": {"AccumulatedProfitLoss": 1}}
        )
        assert metrics.investment_performance_percentage == 7.0
        assert start.ytd_earnings_percentage is None  # input not mutated


class TestSeriesHelpers:
    def test_last_series_value_skips_non_numeric(self):
        assert last_series_value([{"Value": 1}, {"Value": None}]) == 1.0

    def test_last_series_value_empty(self):
        assert last_series_value([]) is None

    def test_current_year_bucket(self):
        with patch(NOW, return_value=datetime(2026, 8, 4, 12, 0)):
            assert (
                current_year_bucket(
                    [
                        {"Date": "2025-12-31", "Value": 999.0},
                        {"Date": "2026-12-31", "Value": 111},
                    ]
                )
                == 111.0
            )

    def test_current_year_bucket_missing(self):
        with patch(NOW, return_value=datetime(2026, 8, 4, 12, 0)):
            assert current_year_bucket([{"Date": "2024-12-31", "Value": 5}]) is None


class TestApplyV4Batch:
    def test_full_response(self):
        """Full v4 batch response is parsed into all metrics."""
        v4_batch = {
            "alltime": {
                "KeyFigures": {"ReturnFraction": 0.12},
                "Balance": {"CashTransfer": [{"Value": 500}, {"Value": 1000}]},
            },
            "ytd": {"KeyFigures": {"ReturnFraction": 0.05}},
            "month": {"KeyFigures": {"ReturnFraction": 0.02}},
            "quarter": {"KeyFigures": {"ReturnFraction": 0.03}},
        }
        metrics = apply_v4_batch(PerformanceData(), v4_batch)
        assert metrics.investment_performance_percentage == pytest.approx(12.0)
        assert metrics.cash_transfer_balance == 1000
        assert metrics.ytd_investment_performance_percentage == pytest.approx(5.0)
        assert metrics.month_investment_performance_percentage == pytest.approx(2.0)
        assert metrics.quarter_investment_performance_percentage == pytest.approx(3.0)

    def test_empty_response(self):
        """Empty batch response yields zero returns and keeps the cash transfer."""
        metrics = apply_v4_batch(PerformanceData(), {})
        assert metrics.investment_performance_percentage == 0.0
        assert metrics.ytd_investment_performance_percentage == 0.0
        assert metrics.cash_transfer_balance is None

    def test_empty_cash_transfer_list_keeps_previous_value(self):
        """Empty CashTransfer list does not replace the cash transfer balance."""
        v4_batch = {"alltime": {"Balance": {"CashTransfer": []}}}
        metrics = apply_v4_batch(PerformanceData(cash_transfer_balance=42.0), v4_batch)
        assert metrics.cash_transfer_balance == 42.0

    def test_ytd_profit_loss_and_transfers(self):
        """YTD currency metrics come from the Jan-1 anchored response."""
        v4_batch = {
            "alltime": {
                "KeyFigures": {"ReturnFraction": 0.32},
                "Balance": {"CashTransfer": [{"Value": 500}, {"Value": 1000}]},
            },
            "ytd": {
                "KeyFigures": {"ReturnFraction": 0.09},
                "Balance": {
                    "YearlyProfitLoss": [
                        {"Date": "2026-12-31", "Value": 1234.56},
                    ],
                    "CashTransfer": [
                        {"Date": "2026-01-02", "Value": 0},
                        {"Date": "2026-04-01", "Value": 250.0},
                    ],
                },
            },
            "month": {"KeyFigures": {"ReturnFraction": 0.02}},
            "quarter": {"KeyFigures": {"ReturnFraction": 0.03}},
        }
        with patch(NOW, return_value=datetime(2026, 8, 4, 12, 0)):
            metrics = apply_v4_batch(PerformanceData(), v4_batch)

        assert metrics.ytd_profit_loss == pytest.approx(1234.56)
        assert metrics.ytd_cash_transfer == pytest.approx(250.0)
        assert metrics.ytd_investment_performance_percentage == pytest.approx(9.0)

    def test_ytd_profit_loss_picks_current_year_bucket(self):
        """A multi-year bucket list must select the current calendar year."""
        v4_batch = {
            "ytd": {
                "Balance": {
                    "YearlyProfitLoss": [
                        {"Date": "2025-12-31", "Value": 999.0},
                        {"Date": "2026-12-31", "Value": 111.0},
                    ]
                }
            }
        }
        with patch(NOW, return_value=datetime(2026, 8, 4, 12, 0)):
            metrics = apply_v4_batch(PerformanceData(), v4_batch)

        assert metrics.ytd_profit_loss == pytest.approx(111.0)

    def test_ytd_metrics_none_when_absent(self):
        """Missing YTD balance data yields None, not 0.0."""
        v4_batch = {"ytd": {"KeyFigures": {"ReturnFraction": 0.09}}}
        metrics = apply_v4_batch(
            PerformanceData(ytd_profit_loss=1.0, ytd_cash_transfer=2.0), v4_batch
        )

        assert metrics.ytd_profit_loss is None
        assert metrics.ytd_cash_transfer is None

    def test_ytd_profit_loss_none_when_no_matching_year(self):
        """A bucket list without the current year yields None."""
        v4_batch = {
            "ytd": {
                "Balance": {"YearlyProfitLoss": [{"Date": "2024-12-31", "Value": 5.0}]}
            }
        }
        with patch(NOW, return_value=datetime(2026, 8, 4, 12, 0)):
            metrics = apply_v4_batch(PerformanceData(), v4_batch)

        assert metrics.ytd_profit_loss is None

    def test_ytd_cash_transfer_skips_non_numeric(self):
        """Non-numeric trailing entries are skipped, not returned."""
        v4_batch = {
            "ytd": {
                "Balance": {
                    "CashTransfer": [
                        {"Date": "2026-01-02", "Value": 100.0},
                        {"Date": "2026-04-01", "Value": None},
                    ]
                }
            }
        }
        metrics = apply_v4_batch(PerformanceData(), v4_batch)

        assert metrics.ytd_cash_transfer == pytest.approx(100.0)

    def test_malformed_response_raises(self):
        """A malformed period fails the whole batch rather than half-applying it."""
        with pytest.raises(TypeError):
            apply_v4_batch(
                PerformanceData(), {"alltime": {"KeyFigures": {"ReturnFraction": None}}}
            )

    def test_ytd_earnings_untouched(self):
        metrics = apply_v4_batch(PerformanceData(ytd_earnings_percentage=3.0), {})
        assert metrics.ytd_earnings_percentage == 3.0


# ---------------------------------------------------------------------------
# PerformanceFetcher
# ---------------------------------------------------------------------------


class TestShouldUpdate:
    """Tests for the cache-age check."""

    def test_no_cache_returns_true(self):
        """No cached data should trigger an update."""
        assert _fetcher().should_update() is True

    def test_stale_cache_returns_true(self):
        """Cache older than PERFORMANCE_UPDATE_INTERVAL should trigger an update."""
        fetcher = _fetcher()
        fetcher.last_updated = (
            datetime.now() - PERFORMANCE_UPDATE_INTERVAL - timedelta(minutes=1)
        )
        assert fetcher.should_update() is True

    def test_fresh_cache_returns_false(self):
        """Recent cache should not trigger an update."""
        fetcher = _fetcher()
        fetcher.last_updated = datetime.now() - timedelta(minutes=5)
        assert fetcher.should_update() is False


class TestInitialState:
    def test_nothing_fetched(self):
        fetcher = _fetcher()
        assert fetcher.client == ClientInfo()
        assert fetcher.metrics == PerformanceData()
        assert fetcher.last_updated is None


class TestAsyncUpdate:
    """Tests for PerformanceFetcher.async_update."""

    async def test_uses_cache_when_fresh(self):
        """Fresh cache keeps cached data without an API call."""
        fetcher = _fetcher()
        fetcher.last_updated = datetime.now()
        fetcher.client = ClientInfo(client_id="cached")
        client = AsyncMock()

        await fetcher.async_update(client)

        assert fetcher.client.client_id == "cached"
        client.get_client_details.assert_not_called()
        fetcher._on_client_info.assert_not_called()

    async def test_fetches_when_stale(self):
        """Stale or missing cache triggers a fresh fetch."""
        fetcher = _fetcher()
        with patch.object(
            fetcher,
            "_fetch",
            new_callable=AsyncMock,
            return_value=(ClientInfo(client_id="C1"), PerformanceData(), True),
        ) as fetch:
            await fetcher.async_update(AsyncMock())
        fetch.assert_awaited_once()
        assert fetcher.client.client_id == "C1"
        assert fetcher.last_updated is not None

    async def test_complete_fetch_reports_client_info(self):
        """A complete fetch passes the client identity to the callback."""
        fetcher = _fetcher()
        client_info = ClientInfo(client_id="C1")
        with patch.object(
            fetcher,
            "_fetch",
            new_callable=AsyncMock,
            return_value=(client_info, PerformanceData(), True),
        ):
            await fetcher.async_update(AsyncMock())
        fetcher._on_client_info.assert_called_once_with(client_info)

    async def test_partial_fetch_reports_client_info_without_timestamp(self):
        """A partial fetch stores values and reports, but keeps the timestamp."""
        fetcher = _fetcher()
        client_info = ClientInfo(client_id="C1")
        metrics = PerformanceData(ytd_earnings_percentage=1.0)
        with patch.object(
            fetcher,
            "_fetch",
            new_callable=AsyncMock,
            return_value=(client_info, metrics, False),
        ):
            await fetcher.async_update(AsyncMock())
        assert fetcher.metrics == metrics
        assert fetcher.client == client_info
        assert fetcher.last_updated is None
        fetcher._on_client_info.assert_called_once_with(client_info)

    async def test_timeout_keeps_cache(self):
        """Timeout during fetch keeps the cached values."""
        fetcher = _fetcher()

        async def slow_fetch(*args, **kwargs):
            await asyncio.Event().wait()

        with (
            patch.object(fetcher, "_fetch", side_effect=slow_fetch),
            patch(
                "custom_components.saxo_portfolio.performance.PERFORMANCE_FETCH_TIMEOUT",
                0.01,
            ),
        ):
            await fetcher.async_update(MagicMock())

        assert fetcher.client.client_id == "unknown"
        assert fetcher.last_updated is None
        fetcher._on_client_info.assert_not_called()

    async def test_exception_keeps_cache(self):
        """Unexpected exception during fetch keeps the cached values."""
        fetcher = _fetcher()
        with patch.object(
            fetcher,
            "_fetch",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            await fetcher.async_update(MagicMock())

        assert fetcher.client.client_id == "unknown"
        assert fetcher.last_updated is None
        fetcher._on_client_info.assert_not_called()


class TestFetch:
    """Tests for the client-details path of PerformanceFetcher._fetch."""

    async def test_populates_client_details(self):
        """Client details are parsed into the client identity."""
        fetcher = _fetcher()
        client = AsyncMock()
        client.get_client_details = AsyncMock(
            return_value={
                "ClientKey": "ck1",
                "ClientId": "C1",
                "DefaultAccountId": "A1",
                "Name": "Test User",
            }
        )
        with patch.object(
            fetcher,
            "_fetch_metrics",
            new_callable=AsyncMock,
            return_value=(PerformanceData(), True),
        ) as fetch_metrics:
            client_info, _, complete = await fetcher._fetch(client)
        assert client_info == ClientInfo(
            client_id="C1", account_id="A1", client_name="Test User"
        )
        assert complete is True
        assert fetch_metrics.call_args.args[1] == "ck1"

    async def test_no_client_details(self):
        """None client details keeps the cached values, incomplete."""
        fetcher = _fetcher()
        fetcher.client = ClientInfo(client_id="cached")
        client = AsyncMock()
        client.get_client_details = AsyncMock(return_value=None)
        client_info, metrics, complete = await fetcher._fetch(client)
        assert client_info.client_id == "cached"
        assert metrics == PerformanceData()
        assert complete is False

    async def test_no_client_key(self):
        """Missing ClientKey skips the performance metrics fetch."""
        fetcher = _fetcher()
        client = AsyncMock()
        client.get_client_details = AsyncMock(
            return_value={
                "ClientId": "C1",
                "DefaultAccountId": "A1",
                "Name": "User",
            }
        )
        with patch.object(
            fetcher, "_fetch_metrics", new_callable=AsyncMock
        ) as fetch_metrics:
            client_info, _, complete = await fetcher._fetch(client)
        fetch_metrics.assert_not_called()
        assert client_info.client_id == "C1"
        assert complete is False

    async def test_exception_caught(self):
        """Exception in client details is caught gracefully."""
        fetcher = _fetcher()
        client = AsyncMock()
        client.get_client_details = AsyncMock(side_effect=RuntimeError("fail"))
        client_info, _, complete = await fetcher._fetch(client)
        assert client_info.client_id == "unknown"
        assert complete is False


class TestFetchMetrics:
    """Tests for PerformanceFetcher._fetch_metrics."""

    async def test_v3_and_v4_success(self):
        """Both v3 and v4 endpoints succeed and populate the metrics."""
        client = AsyncMock()
        client.get_performance = AsyncMock(
            return_value={
                "BalancePerformance": {"AccumulatedProfitLoss": 123.4},
            }
        )
        v4_data = {
            "alltime": {"KeyFigures": {"ReturnFraction": 0.1}},
            "ytd": {"KeyFigures": {"ReturnFraction": 0.05}},
            "month": {"KeyFigures": {"ReturnFraction": 0.02}},
            "quarter": {"KeyFigures": {"ReturnFraction": 0.03}},
        }
        client.get_performance_v4_batch = AsyncMock(return_value=v4_data)
        metrics, complete = await _fetcher()._fetch_metrics(
            client, "ck1", PerformanceData()
        )
        assert metrics.ytd_earnings_percentage == 123.4
        assert metrics.investment_performance_percentage == pytest.approx(10.0)
        assert complete is True

    async def test_v3_failure_v4_succeeds(self):
        """V3 failure does not block v4 from succeeding."""
        client = AsyncMock()
        client.get_performance = AsyncMock(side_effect=RuntimeError("v3 fail"))
        client.get_performance_v4_batch = AsyncMock(
            return_value={
                "alltime": {"KeyFigures": {"ReturnFraction": 0.2}},
            }
        )
        metrics, complete = await _fetcher()._fetch_metrics(
            client, "ck1", PerformanceData(ytd_earnings_percentage=9.0)
        )
        # v3 kept its last known value
        assert metrics.ytd_earnings_percentage == 9.0
        assert metrics.investment_performance_percentage == pytest.approx(20.0)
        assert complete is False

    async def test_v4_failure_v3_succeeds(self):
        """V4 failure does not block v3 from succeeding."""
        client = AsyncMock()
        client.get_performance = AsyncMock(
            return_value={
                "BalancePerformance": {"AccumulatedProfitLoss": 50.0},
            }
        )
        client.get_performance_v4_batch = AsyncMock(side_effect=RuntimeError("v4 fail"))
        metrics, complete = await _fetcher()._fetch_metrics(
            client, "ck1", PerformanceData()
        )
        assert metrics.ytd_earnings_percentage == 50.0
        assert metrics.investment_performance_percentage is None
        assert complete is False

    async def test_batch_called_with_january_first_anchor(self):
        """The YTD window must start on 1 January of the current year."""
        client = AsyncMock()
        client.get_performance = AsyncMock(return_value={})
        client.get_performance_v4_batch = AsyncMock(
            return_value={"alltime": {}, "ytd": {}, "month": {}, "quarter": {}}
        )

        with patch(NOW, return_value=datetime(2026, 8, 4, 12, 0)):
            await _fetcher()._fetch_metrics(client, "ck1", PerformanceData())

        kwargs = client.get_performance_v4_batch.call_args.kwargs
        assert kwargs["ytd_from"] == "2026-01-01"
        assert kwargs["ytd_to"] == "2026-08-04"
