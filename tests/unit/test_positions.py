"""Unit tests for positions.py: parsing, market-data access and the cache."""

from __future__ import annotations

from datetime import datetime
import logging
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.saxo_portfolio.positions import (
    PositionData,
    PositionsCache,
    PositionsFetcher,
    has_market_data_access,
    parse_position,
)


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch(
        "custom_components.saxo_portfolio.positions.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        yield


def _position(symbol: str = "AAPL") -> PositionData:
    return PositionData(
        position_id="P1",
        symbol=symbol,
        description="Apple",
        asset_type="Stock",
        amount=10,
        current_price=150.0,
        market_value=1500.0,
        profit_loss=100.0,
        uic=123,
    )


# ---------------------------------------------------------------------------
# PositionData / PositionsCache
# ---------------------------------------------------------------------------


class TestPositionDataGenerateSlug:
    """Tests for PositionData.generate_slug static method."""

    def test_simple_stock(self):
        """Simple stock symbol generates lowercase slug."""
        assert PositionData.generate_slug("AAPL", "Stock") == "aapl_stock"

    def test_fx_pair_with_slash(self):
        """FX pair with slash converts slash to underscore."""
        assert PositionData.generate_slug("EUR/USD", "FxSpot") == "eur_usd_fxspot"

    def test_special_characters_collapsed(self):
        """Consecutive special characters collapse to single underscore."""
        assert PositionData.generate_slug("A--B//C", "T$$ype") == "a_b_c_t_ype"


class TestPositionsCache:
    """Tests for PositionsCache defaults."""

    def test_defaults(self):
        """Default PositionsCache has empty positions and no timestamp."""
        cache = PositionsCache()
        assert cache.positions == {}
        assert cache.last_updated is None
        assert cache.position_ids == []


# ---------------------------------------------------------------------------
# has_market_data_access
# ---------------------------------------------------------------------------


class TestHasMarketDataAccess:
    def test_has_access(self):
        """Tradable price type with Ok reliability means access is available."""
        position = {
            "NetPositionView": {
                "CurrentPriceType": "Tradable",
                "CalculationReliability": "Ok",
            },
        }
        assert has_market_data_access(position) is True

    @pytest.mark.parametrize(
        ("price_type", "reliability"),
        [
            ("None", "Ok"),
            ("Tradable", "NoMarketAccess"),
            ("Tradable", "ApproximatedPrice"),
        ],
    )
    def test_no_access(self, price_type, reliability):
        position = {
            "NetPositionView": {
                "CurrentPriceType": price_type,
                "CalculationReliability": reliability,
            },
        }
        assert has_market_data_access(position) is False

    def test_missing_view_counts_as_access(self):
        assert has_market_data_access({}) is True


# ---------------------------------------------------------------------------
# parse_position
# ---------------------------------------------------------------------------


class TestParsePosition:
    """Tests for parse_position."""

    def test_parse_success(self):
        """Valid position raw data is parsed into slug and PositionData."""
        raw = {
            "NetPositionId": "P1",
            "NetPositionBase": {"Uic": 100, "AssetType": "Stock", "Amount": 5},
            "NetPositionView": {
                "CurrentPrice": 200.0,
                "MarketValueOpen": -900.0,
                "ProfitLossOnTrade": 100.0,
            },
            "DisplayAndFormat": {
                "Symbol": "MSFT",
                "Description": "Microsoft",
                "Currency": "USD",
            },
            "PositionView": {},
        }
        result = parse_position(raw)
        assert result is not None
        slug, pos = result
        assert slug == "msft_stock"
        assert pos == PositionData(
            position_id="P1",
            symbol="MSFT",
            description="Microsoft",
            asset_type="Stock",
            amount=5,
            current_price=200.0,
            market_value=1000.0,  # abs(-900) + 100
            profit_loss=100.0,
            uic=100,
            currency="USD",
        )

    def test_no_symbol_returns_none(self):
        """Position with empty symbol is skipped."""
        raw = {
            "NetPositionId": "P1",
            "NetPositionBase": {"Uic": 100, "AssetType": "Stock", "Amount": 5},
            "NetPositionView": {},
            "DisplayAndFormat": {"Symbol": "", "Description": "No symbol"},
        }
        assert parse_position(raw) is None

    def test_calculated_price_when_zero(self):
        """CurrentPrice of zero triggers calculation from market value and amount."""
        raw = {
            "NetPositionId": "P1",
            "NetPositionBase": {"Uic": 100, "AssetType": "Stock", "Amount": 10},
            "NetPositionView": {
                "CurrentPrice": 0.0,
                "MarketValueOpen": -1000.0,
                "ProfitLossOnTrade": 200.0,
            },
            "DisplayAndFormat": {
                "Symbol": "TEST",
                "Description": "Test Stock",
                "Currency": "EUR",
            },
        }
        result = parse_position(raw)
        assert result is not None
        _slug, pos = result
        # market_value = abs(-1000) + 200 = 1200
        # current_price = 1200 / abs(10) = 120
        assert pos.current_price == pytest.approx(120.0)
        assert pos.market_value == pytest.approx(1200.0)
        assert pos.currency == "EUR"

    def test_exposure_fallback(self):
        """Zero MarketValueOpen falls back to Exposure for market value."""
        raw = {
            "NetPositionId": "P1",
            "NetPositionBase": {"Uic": 100, "AssetType": "FxSpot", "Amount": 1000},
            "NetPositionView": {
                "CurrentPrice": 1.1,
                "MarketValueOpen": 0.0,
                "ProfitLossOnTrade": 0.0,
                "Exposure": 5000.0,
            },
            "DisplayAndFormat": {
                "Symbol": "EUR/USD",
                "Description": "Euro/US Dollar",
                "Currency": "USD",
            },
        }
        result = parse_position(raw)
        assert result is not None
        slug, pos = result
        assert slug == "eur_usd_fxspot"
        assert pos.market_value == 5000.0

    def test_profit_loss_fallback_to_base_currency(self):
        """ProfitLossOnTradeInBaseCurrency is used when ProfitLossOnTrade is absent."""
        raw = {
            "NetPositionId": "P1",
            "NetPositionBase": {"Uic": 100, "AssetType": "Stock", "Amount": 10},
            "NetPositionView": {
                "CurrentPrice": 100.0,
                "MarketValueOpen": -900.0,
                "ProfitLossOnTradeInBaseCurrency": 50.0,
            },
            "DisplayAndFormat": {
                "Symbol": "SYM",
                "Description": "Sym",
                "Currency": "USD",
            },
        }
        result = parse_position(raw)
        assert result is not None
        _, pos = result
        assert pos.profit_loss == 50.0

    def test_defaults_for_missing_fields(self):
        raw = {"DisplayAndFormat": {"Symbol": "X"}}
        result = parse_position(raw)
        assert result is not None
        slug, pos = result
        assert slug == "x_unknown"
        assert pos.currency == "USD"
        assert pos.uic == 0
        assert pos.current_price == 0.0

    def test_exception_returns_none(self):
        """Invalid input causing exception returns None."""
        assert parse_position("not_a_dict") is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PositionsFetcher
# ---------------------------------------------------------------------------

RAW_AAPL = {
    "NetPositionId": "P1",
    "NetPositionBase": {
        "Uic": 123,
        "AssetType": "Stock",
        "Amount": 10,
    },
    "NetPositionView": {
        "CurrentPrice": 150.0,
        "MarketValueOpen": -1400.0,
        "ProfitLossOnTrade": 100.0,
        "CurrentPriceType": "Tradable",
        "CalculationReliability": "Ok",
    },
    "DisplayAndFormat": {
        "Symbol": "AAPL",
        "Description": "Apple Inc",
        "Currency": "USD",
    },
}


class TestPositionsFetcher:
    """Tests for PositionsFetcher.async_fetch."""

    def test_initial_state(self):
        fetcher = PositionsFetcher(enabled=True)
        assert fetcher.enabled is True
        assert fetcher.cache == PositionsCache()
        assert fetcher.has_market_data_access is None

    async def test_disabled_returns_empty(self):
        """Disabled position sensors returns empty dict without API call."""
        client = AsyncMock()
        result = await PositionsFetcher(enabled=False).async_fetch(client)
        assert result == {}
        client.get_net_positions.assert_not_called()

    async def test_success_returns_positions(self):
        """Successful fetch returns parsed positions and updates the cache."""
        fetcher = PositionsFetcher(enabled=True)
        client = AsyncMock()
        client.get_net_positions = AsyncMock(return_value={"Data": [RAW_AAPL]})
        result = await fetcher.async_fetch(client)
        assert "aapl_stock" in result
        assert result["aapl_stock"].symbol == "AAPL"
        assert fetcher.cache.positions == result
        assert fetcher.cache.position_ids == ["aapl_stock"]
        assert isinstance(fetcher.cache.last_updated, datetime)
        assert fetcher.has_market_data_access is True

    async def test_unparseable_positions_skipped(self):
        fetcher = PositionsFetcher(enabled=True)
        client = AsyncMock()
        client.get_net_positions = AsyncMock(
            return_value={"Data": [RAW_AAPL, {"DisplayAndFormat": {"Symbol": ""}}]}
        )
        result = await fetcher.async_fetch(client)
        assert list(result) == ["aapl_stock"]

    async def test_error_returns_cached(self):
        """API error returns previously cached positions."""
        fetcher = PositionsFetcher(enabled=True)
        fetcher.cache.positions = {"aapl_stock": _position()}
        client = AsyncMock()
        client.get_net_positions = AsyncMock(side_effect=RuntimeError("network"))
        result = await fetcher.async_fetch(client)
        assert "aapl_stock" in result

    async def test_empty_positions_response(self):
        """Empty positions response returns empty dict; access stays unknown."""
        fetcher = PositionsFetcher(enabled=True)
        fetcher.cache.positions = {"aapl_stock": _position()}
        client = AsyncMock()
        client.get_net_positions = AsyncMock(return_value={"Data": []})
        result = await fetcher.async_fetch(client)
        assert result == {}
        assert fetcher.cache.positions == {}
        assert fetcher.has_market_data_access is None

    async def test_no_access_warning_logged_once(self, caplog):
        """No-access warning is logged only once across multiple fetches."""
        fetcher = PositionsFetcher(enabled=True)
        raw = {
            **RAW_AAPL,
            "NetPositionView": {
                **RAW_AAPL["NetPositionView"],
                "CurrentPriceType": "None",
            },
        }
        client = AsyncMock()
        client.get_net_positions = AsyncMock(return_value={"Data": [raw]})

        with caplog.at_level(logging.WARNING):
            await fetcher.async_fetch(client)
            await fetcher.async_fetch(client)

        assert fetcher.has_market_data_access is False
        warnings = [
            r for r in caplog.records if "Market data access not available" in r.message
        ]
        assert len(warnings) == 1


class TestUpdateCache:
    """Tests for PositionsFetcher._update_cache."""

    def test_persists_positions(self):
        """Positions, IDs and timestamp are stored in the cache."""
        fetcher = PositionsFetcher(enabled=True)
        positions = {"aapl_stock": _position(), "msft_stock": _position("MSFT")}
        fetcher._update_cache(positions)
        assert fetcher.cache.positions is positions
        assert fetcher.cache.position_ids == ["aapl_stock", "msft_stock"]
        assert fetcher.cache.last_updated is not None
