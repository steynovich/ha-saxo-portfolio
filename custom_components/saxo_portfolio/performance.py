"""Performance data for the Saxo Portfolio integration.

Fetches client details plus the v3 and v4 performance endpoints, parses
them into typed data, and caches the result for
``PERFORMANCE_UPDATE_INTERVAL`` (2 h).

Failures degrade gracefully: they never raise, so balance data still
updates. Only a *complete* fetch (client details, v3 and v4 all
succeeded) refreshes the cache timestamp. A failed or partial fetch keeps
the last known good value for every field that could not be fetched and
leaves the timestamp alone so it is retried (#15), but no sooner than
``PERFORMANCE_RETRY_INTERVAL`` (15 min) after the failed attempt, so a
permanently failing endpoint does not cost extra calls on every poll (#37).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
import logging
from typing import Any

from homeassistant.util import dt as dt_util

from .api.saxo_client import SaxoApiClient
from .const import (
    API_REQUEST_DELAY,
    PERFORMANCE_FETCH_TIMEOUT,
    PERFORMANCE_RETRY_INTERVAL,
    PERFORMANCE_UPDATE_INTERVAL,
)
from .data import UNKNOWN, ClientInfo, PerformanceData, numeric_or_none

_LOGGER = logging.getLogger(__name__)


def parse_client_details(details: dict[str, Any]) -> ClientInfo:
    """Build the client identity from a ``/port/v1/clients/me`` response."""
    return ClientInfo(
        client_id=str(details.get("ClientId", UNKNOWN)),
        account_id=str(details.get("DefaultAccountId", UNKNOWN)),
        client_name=str(details.get("Name", UNKNOWN)),
    )


def apply_v3_performance(
    metrics: PerformanceData, performance: dict[str, Any]
) -> PerformanceData:
    """Return ``metrics`` updated from a v3 ``/hist/v3/perf`` response."""
    accumulated_profit_loss = performance.get("BalancePerformance", {}).get(
        "AccumulatedProfitLoss", 0.0
    )
    return replace(
        metrics, ytd_earnings_percentage=numeric_or_none(accumulated_profit_loss)
    )


def current_year_bucket(
    series: list[dict[str, Any]], year: int | None = None
) -> float | None:
    """Value of the calendar-year bucket matching the current year.

    ``YearlyProfitLoss`` returns one bucket per calendar year. Match on the
    year rather than assuming a single-element list, so a response spanning
    a year boundary cannot select the wrong bucket. Pass ``year`` to match
    the year the request window was built from; it defaults to today.
    """
    current_year = str(year if year is not None else dt_util.now().year)
    for point in series:
        if str(point.get("Date", "")).startswith(current_year):
            value = point.get("Value")
            if isinstance(value, int | float):
                return float(value)
    return None


def last_series_value(series: list[dict[str, Any]]) -> float | None:
    """Last numeric value of a TimeValuePair series, or None."""
    for point in reversed(series):
        value = point.get("Value")
        if isinstance(value, int | float):
            return float(value)
    return None


def apply_v4_batch(
    metrics: PerformanceData,
    v4_batch: dict[str, dict[str, Any]],
    year: int | None = None,
) -> PerformanceData:
    """Return ``metrics`` updated from the batched v4 performance responses.

    ``v4_batch`` maps ``alltime``/``ytd``/``month``/``quarter`` to their
    ``/hist/v4/performance/timeseries`` responses. The all-time cash
    transfer balance is only replaced when the response carries a
    ``CashTransfer`` series. ``year`` is the year the YTD window was
    requested for. Raises if a response is malformed, leaving ``metrics``
    untouched.
    """
    alltime = v4_batch.get("alltime", {})
    alltime_return = alltime.get("KeyFigures", {}).get("ReturnFraction", 0.0)
    updates: dict[str, float | None] = {
        "investment_performance_percentage": numeric_or_none(alltime_return * 100.0)
    }

    cash_transfer_list = alltime.get("Balance", {}).get("CashTransfer", [])
    if cash_transfer_list:
        updates["cash_transfer_balance"] = numeric_or_none(
            cash_transfer_list[-1].get("Value", 0.0)
        )

    # No YTD key figures means "no data", not a 0% return.
    ytd_return = v4_batch.get("ytd", {}).get("KeyFigures", {}).get("ReturnFraction")
    updates["ytd_investment_performance_percentage"] = (
        numeric_or_none(ytd_return * 100.0)
        if isinstance(ytd_return, int | float)
        else None
    )

    for period_key, field_name in (
        ("month", "month_investment_performance_percentage"),
        ("quarter", "quarter_investment_performance_percentage"),
    ):
        period_return = (
            v4_batch.get(period_key, {})
            .get("KeyFigures", {})
            .get("ReturnFraction", 0.0)
        )
        updates[field_name] = numeric_or_none(period_return * 100.0)

    # Currency-denominated YTD metrics, from the Jan-1 anchored window.
    # These default to None rather than 0.0: on a money sensor a zero reads
    # as "you earned nothing this year" rather than "no data".
    ytd_balance = v4_batch.get("ytd", {}).get("Balance", {})
    updates["ytd_profit_loss"] = current_year_bucket(
        ytd_balance.get("YearlyProfitLoss", []), year
    )
    updates["ytd_cash_transfer"] = last_series_value(
        ytd_balance.get("CashTransfer", [])
    )

    return replace(metrics, **updates)


class PerformanceFetcher:
    """Fetches and caches client details and performance metrics."""

    def __init__(self, on_client_info: Callable[[ClientInfo], None]) -> None:
        """Initialize with nothing fetched yet.

        Args:
            on_client_info: Called with the client identity after each fetch
                that ran to completion (complete or partial), e.g. to put the
                client ID in the config entry title

        """
        self._on_client_info = on_client_info
        self.client = ClientInfo()
        self.metrics = PerformanceData()
        self.last_updated: datetime | None = None
        self._retry_not_before: datetime | None = None

    def should_update(self) -> bool:
        """Return True if a fetch is due.

        A fetch is due when the cache is empty or older than the cache TTL,
        unless a recent incomplete fetch is still backing off.
        """
        if (
            self._retry_not_before is not None
            and datetime.now() < self._retry_not_before
        ):
            _LOGGER.debug(
                "Performance fetch backing off until %s after an incomplete fetch",
                self._retry_not_before,
            )
            return False

        if self.last_updated is None:
            # No cached data, should update
            return True

        time_since_last_update = datetime.now() - self.last_updated
        should_update = time_since_last_update >= PERFORMANCE_UPDATE_INTERVAL

        _LOGGER.debug(
            "Performance cache age: %s, should_update: %s",
            time_since_last_update,
            should_update,
        )

        return should_update

    async def async_update(self, client: SaxoApiClient) -> None:
        """Refresh ``client`` and ``metrics`` if the cache is stale.

        Never raises: on a timeout or unexpected error the cached values are
        kept, so balance data can still be returned when the performance API
        is slow or unresponsive.
        """
        if not self.should_update():
            _LOGGER.debug("Using cached performance data")
            return

        _LOGGER.debug("Updating performance data (cache expired or missing)")

        # Assume failure; a complete fetch clears the backoff below.
        self._retry_not_before = datetime.now() + PERFORMANCE_RETRY_INTERVAL
        try:
            async with asyncio.timeout(PERFORMANCE_FETCH_TIMEOUT):
                # Delay before client details call to prevent burst
                await asyncio.sleep(API_REQUEST_DELAY)
                client_info, metrics, complete = await self._fetch(client)

            self.client = client_info
            self.metrics = metrics
            if complete:
                self.last_updated = datetime.now()
                self._retry_not_before = None
                _LOGGER.debug("Updated performance data cache")
            else:
                # Fields that failed to fetch still hold their last known good
                # value; the timestamp is left alone and the fetch is retried
                # once the backoff has elapsed.
                _LOGGER.debug(
                    "Performance data fetch incomplete, keeping last known values; "
                    "will retry in %s",
                    PERFORMANCE_RETRY_INTERVAL,
                )
            self._on_client_info(client_info)

        except TimeoutError:
            _LOGGER.warning(
                "Performance data fetch timed out after %ds, using cached/default values. "
                "Balance data will still be available.",
                PERFORMANCE_FETCH_TIMEOUT,
            )

        except Exception as e:
            # Anything that's NOT a timeout here is unexpected — log at WARNING
            # so real bugs in performance parsing don't hide behind the
            # "graceful degradation" curtain.
            _LOGGER.warning(
                "Performance data fetch failed with %s, using cached/default values",
                type(e).__name__,
            )

    async def _fetch(
        self, client: SaxoApiClient
    ) -> tuple[ClientInfo, PerformanceData, bool]:
        """Fetch client details and performance metrics, starting from the cache.

        Any exception in the client-details path is caught, so the caller
        gets the values fetched so far (which start as the cached values).

        Returns:
            The client identity, the metrics, and True only if client
            details, v3 and v4 performance all succeeded.

        """
        client_info = self.client
        metrics = self.metrics
        try:
            client_details = await client.get_client_details()
            if not client_details:
                _LOGGER.debug("No client details available")
                return client_info, metrics, False

            client_key = client_details.get("ClientKey")
            client_info = parse_client_details(client_details)
            _LOGGER.debug(
                "Client details fetched - ClientId present: %s, "
                "DefaultAccountId present: %s, Name present: %s",
                client_info.client_id != UNKNOWN,
                client_info.account_id != UNKNOWN,
                client_info.client_name != UNKNOWN,
            )

            if not client_key:
                _LOGGER.debug("No ClientKey found from client details endpoint")
                return client_info, metrics, False

            _LOGGER.debug(
                "Found ClientKey from client details, attempting performance fetch"
            )
            metrics, complete = await self._fetch_metrics(client, client_key, metrics)
            return client_info, metrics, complete
        except Exception as client_e:
            _LOGGER.debug(
                "Could not fetch client details: %s",
                type(client_e).__name__,
            )
            return client_info, metrics, False

    async def _fetch_metrics(
        self, client: SaxoApiClient, client_key: str, metrics: PerformanceData
    ) -> tuple[PerformanceData, bool]:
        """Fetch v3 and batched v4 performance metrics on top of ``metrics``.

        Each endpoint has its own graceful-degradation try/except, so a
        failure on one does not prevent the other from updating ``metrics``.

        Returns:
            The updated metrics, and True if both the v3 and v4 fetch succeeded.

        """
        v3_ok = False
        v4_ok = False

        # v3 performance — AccumulatedProfitLoss only
        try:
            performance_data = await client.get_performance(client_key)
            metrics = apply_v3_performance(metrics, performance_data)
            _LOGGER.debug(
                "Retrieved performance v3 data, AccumulatedProfitLoss present: %s",
                "AccumulatedProfitLoss"
                in performance_data.get("BalancePerformance", {}),
            )
            v3_ok = True
        except Exception as perf_e:
            _LOGGER.debug(
                "Could not fetch performance v3 data: %s",
                type(perf_e).__name__,
            )

        # v4 batch — four periods in one call
        try:
            await asyncio.sleep(API_REQUEST_DELAY)
            now = dt_util.now()
            v4_batch = await client.get_performance_v4_batch(
                client_key,
                ytd_from=f"{now.year:04d}-01-01",
                ytd_to=now.date().isoformat(),
            )
            metrics = apply_v4_batch(metrics, v4_batch, now.year)
            _LOGGER.debug(
                "Retrieved batched performance v4 data - periods: %s, "
                "YTD currency metrics present: %s",
                sorted(v4_batch.keys()),
                metrics.ytd_profit_loss is not None,
            )
            v4_ok = True
        except Exception as perf_v4_e:
            _LOGGER.debug(
                "Could not fetch batched performance v4 data: %s",
                type(perf_v4_e).__name__,
            )

        return metrics, v3_ok and v4_ok
