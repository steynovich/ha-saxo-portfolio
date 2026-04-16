"""Comprehensive unit tests for SaxoCoordinator.

Tests cover:
- api_client property (creation, token change, no access token)
- _should_update_performance_data (cache stale/fresh)
- _fetch_performance_data_safely (timeout, exception, cache usage)
- _build_performance_defaults
- _update_performance_cache
- _populate_performance_result
- _fetch_performance_metrics (v3 + v4 batch)
- _extract_v4_batch_metrics (static method)
- _fetch_positions_data_safely (disabled, success, error)
- _check_market_data_access (available/unavailable)
- _parse_single_position (parsing, no symbol, errors)
- _is_market_hours (weekday/weekend, open/closed, timezone any, cache)
- _ensure_token_valid (proactive refresh, token age)
- _proactive_refresh_token (success, 400/401, transient error)
- _fetch_portfolio_data (full flow, auth error, timeout, API error)
- _async_update_data (interval adjustment, reload trigger)
- async_shutdown (cleanup)
- Getter methods (with/without data)
- mark_sensors_initialized, mark_setup_complete
- _update_config_entry_title_if_needed
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import aiohttp
import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.saxo_portfolio.api.saxo_client import (
    APIError,
    AuthenticationError,
)
from custom_components.saxo_portfolio.const import (
    DEFAULT_UPDATE_INTERVAL_AFTER_HOURS,
    DEFAULT_UPDATE_INTERVAL_ANY,
    DEFAULT_UPDATE_INTERVAL_MARKET_HOURS,
    PERFORMANCE_UPDATE_INTERVAL,
)
from custom_components.saxo_portfolio.coordinator import (
    PositionData,
    PositionsCache,
    SaxoCoordinator,
)

_UTC = ZoneInfo("UTC")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator(
    mock_hass,
    mock_config_entry,
    mock_oauth_session,
    *,
    timezone="any",
    enable_positions=False,
):
    """Construct a SaxoCoordinator and restore config_entry after ContextVar reset."""
    mock_config_entry.data = {
        **mock_config_entry.data,
        "timezone": timezone,
    }
    if enable_positions:
        mock_config_entry.options = {"enable_position_sensors": True}

    coord = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
    # ContextVar may override config_entry to None in DataUpdateCoordinator
    coord.config_entry = mock_config_entry
    return coord


def _bare_coordinator():
    """Build a coordinator via object.__new__ for testing individual methods."""
    coord = object.__new__(SaxoCoordinator)
    coord._performance_data_cache = {}
    coord._performance_last_updated = None
    coord._positions_cache = PositionsCache()
    coord._enable_position_sensors = False
    coord._position_market_data_warning_logged = False
    coord._has_market_data_access = None
    coord._timezone = "any"
    coord._market_hours_cache = None
    coord._market_hours_cache_time = None
    coord._last_timeout_warning = None
    coord._api_client = None
    coord._oauth_session = MagicMock()
    coord._last_known_client_name = "unknown"
    coord._sensors_initialized = False
    coord._setup_complete = False
    coord._is_startup_phase = True
    coord._successful_updates_count = 0
    coord._initial_update_offset = 0
    coord._last_successful_update = None
    coord.hass = MagicMock()
    coord.config_entry = MagicMock()
    coord.config_entry.entry_id = "test_entry"
    coord.config_entry.title = "Saxo Portfolio"
    coord.data = None
    coord.update_interval = DEFAULT_UPDATE_INTERVAL_ANY
    return coord


# ---------------------------------------------------------------------------
# PositionData.generate_slug
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


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestCoordinatorInit:
    """Tests for coordinator construction."""

    def test_init_any_timezone(self, mock_hass, mock_config_entry, mock_oauth_session):
        """Any timezone uses the fixed ANY interval."""
        coord = _make_coordinator(
            mock_hass, mock_config_entry, mock_oauth_session, timezone="any"
        )
        assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_ANY
        assert coord._timezone == "any"
        assert coord._sensors_initialized is False
        assert coord._setup_complete is False
        assert coord._is_startup_phase is True

    def test_init_market_timezone(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Non-any timezone should pick market hours interval when market is open."""
        with patch.object(SaxoCoordinator, "_is_market_hours", return_value=True):
            coord = _make_coordinator(
                mock_hass,
                mock_config_entry,
                mock_oauth_session,
                timezone="America/New_York",
            )
            assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_MARKET_HOURS

    def test_init_after_hours_timezone(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Non-any timezone should pick after-hours interval when market is closed."""
        with patch.object(SaxoCoordinator, "_is_market_hours", return_value=False):
            coord = _make_coordinator(
                mock_hass,
                mock_config_entry,
                mock_oauth_session,
                timezone="America/New_York",
            )
            assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_AFTER_HOURS

    def test_init_position_sensors_from_options(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Position sensors flag is read from config entry options."""
        coord = _make_coordinator(
            mock_hass, mock_config_entry, mock_oauth_session, enable_positions=True
        )
        assert coord._enable_position_sensors is True


# ---------------------------------------------------------------------------
# api_client property
# ---------------------------------------------------------------------------


class TestApiClientProperty:
    """Tests for the api_client property."""

    def test_creates_client(self, mock_hass, mock_config_entry, mock_oauth_session):
        """First access creates a new API client."""
        coord = _make_coordinator(mock_hass, mock_config_entry, mock_oauth_session)
        with patch(
            "custom_components.saxo_portfolio.coordinator.async_get_clientsession",
            return_value=MagicMock(),
        ):
            client = coord.api_client
            assert client is not None
            assert client.access_token == "test_access_token"

    def test_reuses_client_same_token(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Repeated access with same token returns same client instance."""
        coord = _make_coordinator(mock_hass, mock_config_entry, mock_oauth_session)
        with patch(
            "custom_components.saxo_portfolio.coordinator.async_get_clientsession",
            return_value=MagicMock(),
        ):
            c1 = coord.api_client
            c2 = coord.api_client
            assert c1 is c2

    def test_recreates_client_on_token_change(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Token change triggers creation of a new API client."""
        coord = _make_coordinator(mock_hass, mock_config_entry, mock_oauth_session)
        with patch(
            "custom_components.saxo_portfolio.coordinator.async_get_clientsession",
            return_value=MagicMock(),
        ):
            c1 = coord.api_client
            # Simulate token change
            mock_oauth_session.token = {
                **mock_oauth_session.token,
                "access_token": "new_token",
            }
            c2 = coord.api_client
            assert c2 is not c1
            assert c2.access_token == "new_token"

    def test_no_access_token_raises(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Empty access token raises ConfigEntryAuthFailed."""
        coord = _make_coordinator(mock_hass, mock_config_entry, mock_oauth_session)
        mock_oauth_session.token = {"access_token": ""}
        with pytest.raises(ConfigEntryAuthFailed, match="No access token"):
            _ = coord.api_client

    def test_no_access_token_none_raises(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Missing access token key raises ConfigEntryAuthFailed."""
        coord = _make_coordinator(mock_hass, mock_config_entry, mock_oauth_session)
        mock_oauth_session.token = {}
        with pytest.raises(ConfigEntryAuthFailed, match="No access token"):
            _ = coord.api_client


# ---------------------------------------------------------------------------
# _should_update_performance_data
# ---------------------------------------------------------------------------


class TestShouldUpdatePerformanceData:
    """Tests for _should_update_performance_data cache logic."""

    def test_no_cache_returns_true(self):
        """No cached data should trigger an update."""
        coord = _bare_coordinator()
        assert coord._should_update_performance_data() is True

    def test_stale_cache_returns_true(self):
        """Cache older than PERFORMANCE_UPDATE_INTERVAL should trigger an update."""
        coord = _bare_coordinator()
        coord._performance_last_updated = (
            datetime.now() - PERFORMANCE_UPDATE_INTERVAL - timedelta(minutes=1)
        )
        assert coord._should_update_performance_data() is True

    def test_fresh_cache_returns_false(self):
        """Recent cache should not trigger an update."""
        coord = _bare_coordinator()
        coord._performance_last_updated = datetime.now() - timedelta(minutes=5)
        assert coord._should_update_performance_data() is False


# ---------------------------------------------------------------------------
# _build_performance_defaults
# ---------------------------------------------------------------------------


class TestBuildPerformanceDefaults:
    """Tests for _build_performance_defaults."""

    def test_empty_cache(self):
        """Empty cache returns zero/unknown defaults."""
        coord = _bare_coordinator()
        defaults = coord._build_performance_defaults()
        assert defaults["client_id"] == "unknown"
        assert defaults["investment_performance_percentage"] == 0.0
        assert defaults["cash_transfer_balance"] == 0.0

    def test_populated_cache(self):
        """Populated cache values are returned in defaults."""
        coord = _bare_coordinator()
        coord._performance_data_cache = {
            "client_id": "C123",
            "account_id": "A456",
            "client_name": "John",
            "investment_performance_percentage": 5.5,
            "ytd_investment_performance_percentage": 3.2,
            "month_investment_performance_percentage": 1.1,
            "quarter_investment_performance_percentage": 2.0,
            "cash_transfer_balance": 10000.0,
            "ytd_earnings_percentage": 42.0,
        }
        defaults = coord._build_performance_defaults()
        assert defaults["client_id"] == "C123"
        assert defaults["investment_performance_percentage"] == 5.5
        assert defaults["cash_transfer_balance"] == 10000.0


# ---------------------------------------------------------------------------
# _update_performance_cache
# ---------------------------------------------------------------------------


class TestUpdatePerformanceCache:
    """Tests for _update_performance_cache."""

    def test_persists_cache(self):
        """Result is stored in the performance cache with timestamp."""
        coord = _bare_coordinator()
        result = {"client_id": "C1", "investment_performance_percentage": 1.0}
        coord._update_performance_cache(result)
        assert coord._performance_data_cache["client_id"] == "C1"
        assert coord._performance_last_updated is not None

    def test_updates_title(self):
        """Cache update triggers config entry title update."""
        coord = _bare_coordinator()
        coord.config_entry.title = "Saxo Portfolio"
        result = {"client_id": "C1"}
        coord._update_performance_cache(result)
        coord.hass.config_entries.async_update_entry.assert_called_once()


# ---------------------------------------------------------------------------
# _extract_v4_batch_metrics
# ---------------------------------------------------------------------------


class TestExtractV4BatchMetrics:
    """Tests for _extract_v4_batch_metrics static method."""

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
        metrics = SaxoCoordinator._extract_v4_batch_metrics(v4_batch)
        assert metrics["investment_performance_percentage"] == pytest.approx(12.0)
        assert metrics["cash_transfer_balance"] == 1000
        assert metrics["ytd_investment_performance_percentage"] == pytest.approx(5.0)
        assert metrics["month_investment_performance_percentage"] == pytest.approx(2.0)
        assert metrics["quarter_investment_performance_percentage"] == pytest.approx(
            3.0
        )

    def test_empty_response(self):
        """Empty batch response returns zero metrics without cash_transfer_balance."""
        metrics = SaxoCoordinator._extract_v4_batch_metrics({})
        assert metrics["investment_performance_percentage"] == 0.0
        assert "cash_transfer_balance" not in metrics

    def test_empty_cash_transfer_list(self):
        """Empty CashTransfer list does not produce cash_transfer_balance."""
        v4_batch = {"alltime": {"Balance": {"CashTransfer": []}}}
        metrics = SaxoCoordinator._extract_v4_batch_metrics(v4_batch)
        assert "cash_transfer_balance" not in metrics


# ---------------------------------------------------------------------------
# _fetch_performance_data_safely
# ---------------------------------------------------------------------------


class TestFetchPerformanceDataSafely:
    """Tests for _fetch_performance_data_safely."""

    async def test_returns_cached_when_fresh(self):
        """Fresh cache returns cached data without API call."""
        coord = _bare_coordinator()
        coord._performance_last_updated = datetime.now()
        coord._performance_data_cache = {"client_id": "cached"}
        result = await coord._fetch_performance_data_safely(MagicMock())
        assert result["client_id"] == "cached"

    async def test_fetches_when_stale(self):
        """Stale or missing cache triggers a fresh fetch."""
        coord = _bare_coordinator()
        coord._performance_last_updated = None
        client = AsyncMock()
        with patch.object(
            coord, "_populate_performance_result", new_callable=AsyncMock
        ):
            result = await coord._fetch_performance_data_safely(client)
            assert isinstance(result, dict)

    async def test_timeout_returns_defaults(self):
        """Timeout during fetch returns default values."""
        coord = _bare_coordinator()
        coord._performance_last_updated = None

        async def slow_populate(*args, **kwargs):
            await asyncio.sleep(100)

        with patch.object(
            coord, "_populate_performance_result", side_effect=slow_populate
        ):
            with patch(
                "custom_components.saxo_portfolio.coordinator.PERFORMANCE_FETCH_TIMEOUT",
                0.01,
            ):
                result = await coord._fetch_performance_data_safely(MagicMock())
                assert result["client_id"] == "unknown"

    async def test_exception_returns_defaults(self):
        """Exception during fetch returns default values."""
        coord = _bare_coordinator()
        coord._performance_last_updated = None

        with patch.object(
            coord,
            "_populate_performance_result",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await coord._fetch_performance_data_safely(MagicMock())
            assert result["client_id"] == "unknown"


# ---------------------------------------------------------------------------
# _populate_performance_result
# ---------------------------------------------------------------------------


class TestPopulatePerformanceResult:
    """Tests for _populate_performance_result."""

    async def test_populates_client_details(self):
        """Client details are extracted into the result dict."""
        coord = _bare_coordinator()
        client = AsyncMock()
        client.get_client_details = AsyncMock(
            return_value={
                "ClientKey": "ck1",
                "ClientId": "C1",
                "DefaultAccountId": "A1",
                "Name": "Test User",
            }
        )
        result = {
            "client_id": "unknown",
            "account_id": "unknown",
            "client_name": "unknown",
        }
        with patch.object(coord, "_fetch_performance_metrics", new_callable=AsyncMock):
            await coord._populate_performance_result(client, result)
        assert result["client_id"] == "C1"
        assert result["account_id"] == "A1"
        assert result["client_name"] == "Test User"

    async def test_no_client_details(self):
        """None client details leaves result unchanged."""
        coord = _bare_coordinator()
        client = AsyncMock()
        client.get_client_details = AsyncMock(return_value=None)
        result = {"client_id": "unknown"}
        await coord._populate_performance_result(client, result)
        assert result["client_id"] == "unknown"

    async def test_no_client_key(self):
        """Missing ClientKey skips performance metrics fetch."""
        coord = _bare_coordinator()
        client = AsyncMock()
        client.get_client_details = AsyncMock(
            return_value={
                "ClientId": "C1",
                "DefaultAccountId": "A1",
                "Name": "User",
            }
        )
        result = {
            "client_id": "unknown",
            "account_id": "unknown",
            "client_name": "unknown",
        }
        with patch.object(
            coord, "_fetch_performance_metrics", new_callable=AsyncMock
        ) as mock_fetch:
            await coord._populate_performance_result(client, result)
        mock_fetch.assert_not_called()
        assert result["client_id"] == "C1"

    async def test_exception_caught(self):
        """Exception in client details is caught gracefully."""
        coord = _bare_coordinator()
        client = AsyncMock()
        client.get_client_details = AsyncMock(side_effect=RuntimeError("fail"))
        result = {"client_id": "unknown"}
        await coord._populate_performance_result(client, result)
        assert result["client_id"] == "unknown"


# ---------------------------------------------------------------------------
# _fetch_performance_metrics
# ---------------------------------------------------------------------------


class TestFetchPerformanceMetrics:
    """Tests for _fetch_performance_metrics."""

    async def test_v3_and_v4_success(self):
        """Both v3 and v4 endpoints succeed and populate result."""
        coord = _bare_coordinator()
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
        result = {}
        await coord._fetch_performance_metrics(client, "ck1", result)
        assert result["ytd_earnings_percentage"] == 123.4
        assert result["investment_performance_percentage"] == pytest.approx(10.0)

    async def test_v3_failure_v4_succeeds(self):
        """V3 failure does not block v4 from succeeding."""
        coord = _bare_coordinator()
        client = AsyncMock()
        client.get_performance = AsyncMock(side_effect=RuntimeError("v3 fail"))
        client.get_performance_v4_batch = AsyncMock(
            return_value={
                "alltime": {"KeyFigures": {"ReturnFraction": 0.2}},
            }
        )
        result = {}
        await coord._fetch_performance_metrics(client, "ck1", result)
        assert "ytd_earnings_percentage" not in result
        assert result["investment_performance_percentage"] == pytest.approx(20.0)

    async def test_v4_failure_v3_succeeds(self):
        """V4 failure does not block v3 from succeeding."""
        coord = _bare_coordinator()
        client = AsyncMock()
        client.get_performance = AsyncMock(
            return_value={
                "BalancePerformance": {"AccumulatedProfitLoss": 50.0},
            }
        )
        client.get_performance_v4_batch = AsyncMock(side_effect=RuntimeError("v4 fail"))
        result = {}
        await coord._fetch_performance_metrics(client, "ck1", result)
        assert result["ytd_earnings_percentage"] == 50.0
        assert "investment_performance_percentage" not in result


# ---------------------------------------------------------------------------
# _fetch_positions_data_safely
# ---------------------------------------------------------------------------


class TestFetchPositionsDataSafely:
    """Tests for _fetch_positions_data_safely."""

    async def test_disabled_returns_empty(self):
        """Disabled position sensors returns empty dict without API call."""
        coord = _bare_coordinator()
        coord._enable_position_sensors = False
        result = await coord._fetch_positions_data_safely(MagicMock())
        assert result == {}

    async def test_success_returns_positions(self):
        """Successful fetch returns parsed positions dict."""
        coord = _bare_coordinator()
        coord._enable_position_sensors = True
        client = AsyncMock()
        client.get_net_positions = AsyncMock(
            return_value={
                "Data": [
                    {
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
                    },
                ],
            }
        )
        result = await coord._fetch_positions_data_safely(client)
        assert "aapl_stock" in result
        assert result["aapl_stock"].symbol == "AAPL"

    async def test_error_returns_cached(self):
        """API error returns previously cached positions."""
        coord = _bare_coordinator()
        coord._enable_position_sensors = True
        pos = PositionData(
            position_id="P1",
            symbol="AAPL",
            description="Apple",
            asset_type="Stock",
            amount=10,
            current_price=150.0,
            market_value=1500.0,
            profit_loss=100.0,
            uic=123,
        )
        coord._positions_cache.positions = {"aapl_stock": pos}
        client = AsyncMock()
        client.get_net_positions = AsyncMock(side_effect=RuntimeError("network"))
        result = await coord._fetch_positions_data_safely(client)
        assert "aapl_stock" in result

    async def test_empty_positions_response(self):
        """Empty positions response returns empty dict."""
        coord = _bare_coordinator()
        coord._enable_position_sensors = True
        client = AsyncMock()
        client.get_net_positions = AsyncMock(return_value={"Data": []})
        result = await coord._fetch_positions_data_safely(client)
        assert result == {}


# ---------------------------------------------------------------------------
# _check_market_data_access
# ---------------------------------------------------------------------------


class TestCheckMarketDataAccess:
    """Tests for _check_market_data_access."""

    def test_has_access(self):
        """Tradable price type with Ok reliability means access is available."""
        coord = _bare_coordinator()
        position = {
            "NetPositionView": {
                "CurrentPriceType": "Tradable",
                "CalculationReliability": "Ok",
            },
        }
        coord._check_market_data_access(position)
        assert coord._has_market_data_access is True

    def test_no_access_price_type_none(self):
        """CurrentPriceType 'None' means no market data access."""
        coord = _bare_coordinator()
        position = {
            "NetPositionView": {
                "CurrentPriceType": "None",
                "CalculationReliability": "Ok",
            },
        }
        coord._check_market_data_access(position)
        assert coord._has_market_data_access is False

    def test_no_access_no_market_access(self):
        """NoMarketAccess reliability means no market data access."""
        coord = _bare_coordinator()
        position = {
            "NetPositionView": {
                "CurrentPriceType": "Tradable",
                "CalculationReliability": "NoMarketAccess",
            },
        }
        coord._check_market_data_access(position)
        assert coord._has_market_data_access is False

    def test_no_access_approximated_price(self):
        """ApproximatedPrice reliability means no market data access."""
        coord = _bare_coordinator()
        position = {
            "NetPositionView": {
                "CurrentPriceType": "Tradable",
                "CalculationReliability": "ApproximatedPrice",
            },
        }
        coord._check_market_data_access(position)
        assert coord._has_market_data_access is False

    def test_warning_logged_once(self):
        """No-access warning is logged only once across multiple checks."""
        coord = _bare_coordinator()
        position = {"NetPositionView": {"CurrentPriceType": "None"}}
        coord._check_market_data_access(position)
        assert coord._position_market_data_warning_logged is True
        # Call again - should not change state
        coord._check_market_data_access(position)
        assert coord._position_market_data_warning_logged is True


# ---------------------------------------------------------------------------
# _parse_single_position
# ---------------------------------------------------------------------------


class TestParseSinglePosition:
    """Tests for _parse_single_position."""

    def test_parse_success(self):
        """Valid position raw data is parsed into slug and PositionData."""
        coord = _bare_coordinator()
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
        result = coord._parse_single_position(raw)
        assert result is not None
        slug, pos = result
        assert slug == "msft_stock"
        assert pos.current_price == 200.0
        assert pos.market_value == 1000.0  # abs(-900) + 100

    def test_no_symbol_returns_none(self):
        """Position with empty symbol is skipped."""
        coord = _bare_coordinator()
        raw = {
            "NetPositionId": "P1",
            "NetPositionBase": {"Uic": 100, "AssetType": "Stock", "Amount": 5},
            "NetPositionView": {},
            "DisplayAndFormat": {"Symbol": "", "Description": "No symbol"},
        }
        result = coord._parse_single_position(raw)
        assert result is None

    def test_calculated_price_when_zero(self):
        """CurrentPrice of zero triggers calculation from market value and amount."""
        coord = _bare_coordinator()
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
        result = coord._parse_single_position(raw)
        assert result is not None
        _slug, pos = result
        # market_value = abs(-1000) + 200 = 1200
        # current_price = 1200 / abs(10) = 120
        assert pos.current_price == pytest.approx(120.0)
        assert pos.market_value == pytest.approx(1200.0)

    def test_exposure_fallback(self):
        """Zero MarketValueOpen falls back to Exposure for market value."""
        coord = _bare_coordinator()
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
        result = coord._parse_single_position(raw)
        assert result is not None
        _, pos = result
        assert pos.market_value == 5000.0

    def test_profit_loss_fallback_to_base_currency(self):
        """ProfitLossOnTradeInBaseCurrency is used when ProfitLossOnTrade is absent."""
        coord = _bare_coordinator()
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
        result = coord._parse_single_position(raw)
        assert result is not None
        _, pos = result
        assert pos.profit_loss == 50.0

    def test_exception_returns_none(self):
        """Invalid input causing exception returns None."""
        coord = _bare_coordinator()
        result = coord._parse_single_position("not_a_dict")
        assert result is None


# ---------------------------------------------------------------------------
# _is_market_hours
# ---------------------------------------------------------------------------


class TestIsMarketHours:
    """Tests for _is_market_hours."""

    def test_any_timezone_returns_false(self):
        """Any timezone always returns False (market hours not applicable)."""
        coord = _bare_coordinator()
        coord._timezone = "any"
        assert coord._is_market_hours() is False

    def test_cache_hit(self):
        """Recent cache returns cached value without recalculating."""
        coord = _bare_coordinator()
        coord._timezone = "America/New_York"
        coord._market_hours_cache = True
        coord._market_hours_cache_time = datetime.now()
        assert coord._is_market_hours() is True

    def test_weekday_during_market_hours(self):
        """Monday at 10:00 ET is during market hours."""
        coord = _bare_coordinator()
        coord._timezone = "America/New_York"
        # Monday 14:00 UTC = Monday 10:00 ET (during market hours: 9:30-16:00)
        mock_monday_10am_utc = datetime(2026, 4, 13, 14, 0, 0, tzinfo=_UTC)
        with patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt:
            mock_dt.utcnow.return_value = mock_monday_10am_utc
            result = coord._is_market_hours()
            assert result is True

    def test_weekend_returns_false(self):
        """Saturday returns False regardless of time."""
        coord = _bare_coordinator()
        coord._timezone = "America/New_York"
        mock_saturday_utc = datetime(2026, 4, 18, 14, 0, 0, tzinfo=_UTC)
        with patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt:
            mock_dt.utcnow.return_value = mock_saturday_utc
            result = coord._is_market_hours()
            assert result is False

    def test_weekday_after_hours(self):
        """Monday at 18:00 ET is after market hours."""
        coord = _bare_coordinator()
        coord._timezone = "America/New_York"
        # Monday at 22:00 UTC = 18:00 ET (after hours, market closes at 16:00)
        mock_evening = datetime(2026, 4, 13, 22, 0, 0, tzinfo=_UTC)
        with patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt:
            mock_dt.utcnow.return_value = mock_evening
            result = coord._is_market_hours()
            assert result is False

    def test_unknown_timezone_falls_back(self):
        """Unknown timezone falls back to default without crashing."""
        coord = _bare_coordinator()
        coord._timezone = "Mars/Olympus_Mons"
        with patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 4, 13, 14, 0, 0, tzinfo=_UTC)
            result = coord._is_market_hours()
            assert isinstance(result, bool)
            assert coord._timezone == "America/New_York"

    def test_exception_returns_false(self):
        """Exception during check defaults to False (after-hours)."""
        coord = _bare_coordinator()
        coord._timezone = "America/New_York"
        with patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt:
            mock_dt.utcnow.side_effect = RuntimeError("boom")
            result = coord._is_market_hours()
            assert result is False


# ---------------------------------------------------------------------------
# _ensure_token_valid
# ---------------------------------------------------------------------------


class TestEnsureTokenValid:
    """Tests for _ensure_token_valid."""

    async def test_no_refresh_token_expires_in(self):
        """Without refresh_token_expires_in, only safety net is called."""
        coord = _bare_coordinator()
        coord._oauth_session.token = {"access_token": "tok"}
        coord._oauth_session.async_ensure_token_valid = AsyncMock()
        await coord._ensure_token_valid()
        coord._oauth_session.async_ensure_token_valid.assert_awaited_once()

    async def test_proactive_refresh_triggered_when_past_halflife(self):
        """Proactive refresh is triggered when elapsed time exceeds half-life."""
        coord = _bare_coordinator()
        issued = datetime.now() - timedelta(hours=2)
        coord._oauth_session.token = {
            "access_token": "tok",
            "refresh_token_expires_in": 3600,
            "token_issued_at": issued.timestamp(),
            "expires_at": (issued + timedelta(minutes=20)).timestamp(),
        }
        coord._oauth_session.async_ensure_token_valid = AsyncMock()
        with patch.object(
            coord, "_proactive_refresh_token", new_callable=AsyncMock
        ) as mock_refresh:
            await coord._ensure_token_valid()
            mock_refresh.assert_awaited_once()

    async def test_no_proactive_refresh_when_fresh(self):
        """Proactive refresh is skipped when token is recently issued."""
        coord = _bare_coordinator()
        issued = datetime.now() - timedelta(minutes=1)
        coord._oauth_session.token = {
            "access_token": "tok",
            "refresh_token_expires_in": 3600,
            "token_issued_at": issued.timestamp(),
        }
        coord._oauth_session.async_ensure_token_valid = AsyncMock()
        with patch.object(
            coord, "_proactive_refresh_token", new_callable=AsyncMock
        ) as mock_refresh:
            await coord._ensure_token_valid()
            mock_refresh.assert_not_awaited()

    async def test_expires_at_fallback(self):
        """Token issued time is derived from expires_at when token_issued_at is absent."""
        coord = _bare_coordinator()
        issued = datetime.now() - timedelta(hours=2)
        expires_at = (issued + timedelta(seconds=1200)).timestamp()
        coord._oauth_session.token = {
            "access_token": "tok",
            "refresh_token_expires_in": 3600,
            "expires_at": expires_at,
            "expires_in": 1200,
        }
        coord._oauth_session.async_ensure_token_valid = AsyncMock()
        with patch.object(
            coord, "_proactive_refresh_token", new_callable=AsyncMock
        ) as mock_refresh:
            await coord._ensure_token_valid()
            mock_refresh.assert_awaited_once()

    async def test_no_issued_at_no_expires_at_uses_now(self):
        """Missing timestamps default to now, so no proactive refresh triggers."""
        coord = _bare_coordinator()
        coord._oauth_session.token = {
            "access_token": "tok",
            "refresh_token_expires_in": 3600,
        }
        coord._oauth_session.async_ensure_token_valid = AsyncMock()
        with patch.object(
            coord, "_proactive_refresh_token", new_callable=AsyncMock
        ) as mock_refresh:
            await coord._ensure_token_valid()
            mock_refresh.assert_not_awaited()

    async def test_warning_logged_near_expiry(self):
        """Token near expiry does not raise but logs a warning."""
        coord = _bare_coordinator()
        issued = datetime.now() - timedelta(minutes=55)
        coord._oauth_session.token = {
            "access_token": "tok",
            "refresh_token_expires_in": 3600,
            "token_issued_at": issued.timestamp(),
        }
        coord._oauth_session.async_ensure_token_valid = AsyncMock()
        with patch.object(coord, "_proactive_refresh_token", new_callable=AsyncMock):
            await coord._ensure_token_valid()


# ---------------------------------------------------------------------------
# _proactive_refresh_token
# ---------------------------------------------------------------------------


class TestProactiveRefreshToken:
    """Tests for _proactive_refresh_token."""

    async def test_success(self):
        """Successful refresh persists new token to config entry."""
        coord = _bare_coordinator()
        new_token = {"access_token": "new", "refresh_token": "new_rt"}
        coord._oauth_session.implementation = MagicMock()
        coord._oauth_session.implementation.async_refresh_token = AsyncMock(
            return_value=new_token
        )
        coord.config_entry.data = {"existing": "data"}
        await coord._proactive_refresh_token()
        coord.hass.config_entries.async_update_entry.assert_called_once()
        call_kwargs = coord.hass.config_entries.async_update_entry.call_args
        assert call_kwargs[1]["data"]["token"] == new_token

    async def test_400_raises_auth_failed(self):
        """HTTP 400 from Saxo triggers reauthentication."""
        coord = _bare_coordinator()
        coord._oauth_session.implementation = MagicMock()
        error = aiohttp.ClientResponseError(MagicMock(), (), status=400)
        coord._oauth_session.implementation.async_refresh_token = AsyncMock(
            side_effect=error
        )
        with pytest.raises(ConfigEntryAuthFailed):
            await coord._proactive_refresh_token()

    async def test_401_raises_auth_failed(self):
        """HTTP 401 from Saxo triggers reauthentication."""
        coord = _bare_coordinator()
        coord._oauth_session.implementation = MagicMock()
        error = aiohttp.ClientResponseError(MagicMock(), (), status=401)
        coord._oauth_session.implementation.async_refresh_token = AsyncMock(
            side_effect=error
        )
        with pytest.raises(ConfigEntryAuthFailed):
            await coord._proactive_refresh_token()

    async def test_500_swallowed(self):
        """HTTP 500 is swallowed as transient; existing token remains valid."""
        coord = _bare_coordinator()
        coord._oauth_session.implementation = MagicMock()
        error = aiohttp.ClientResponseError(MagicMock(), (), status=500)
        coord._oauth_session.implementation.async_refresh_token = AsyncMock(
            side_effect=error
        )
        await coord._proactive_refresh_token()

    async def test_timeout_swallowed(self):
        """Timeout is swallowed as transient."""
        coord = _bare_coordinator()
        coord._oauth_session.implementation = MagicMock()
        coord._oauth_session.implementation.async_refresh_token = AsyncMock(
            side_effect=TimeoutError()
        )
        await coord._proactive_refresh_token()

    async def test_client_error_swallowed(self):
        """aiohttp.ClientError is swallowed as transient."""
        coord = _bare_coordinator()
        coord._oauth_session.implementation = MagicMock()
        coord._oauth_session.implementation.async_refresh_token = AsyncMock(
            side_effect=aiohttp.ClientError()
        )
        await coord._proactive_refresh_token()


# ---------------------------------------------------------------------------
# _fetch_portfolio_data
# ---------------------------------------------------------------------------


class TestFetchPortfolioData:
    """Tests for _fetch_portfolio_data."""

    async def test_success(self):
        """Successful fetch combines balance and performance data."""
        coord = _bare_coordinator()
        coord._last_successful_update = datetime.now()
        coord._initial_update_offset = 0
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
            patch.object(
                coord,
                "_fetch_performance_data_safely",
                new_callable=AsyncMock,
                return_value={
                    "client_id": "C1",
                    "investment_performance_percentage": 5.0,
                },
            ),
            patch.object(
                coord,
                "_fetch_positions_data_safely",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "custom_components.saxo_portfolio.coordinator.async_get_clientsession",
                return_value=MagicMock(),
            ),
        ):
            coord._oauth_session.token = {"access_token": "tok"}
            result = await coord._fetch_portfolio_data()
            assert result["cash_balance"] == 1000.0
            assert result["currency"] == "EUR"
            assert result["client_id"] == "C1"

    async def test_auth_error(self):
        """AuthenticationError raises ConfigEntryAuthFailed."""
        coord = _bare_coordinator()
        coord._initial_update_offset = 0
        with (
            patch.object(
                coord,
                "_ensure_token_valid",
                new_callable=AsyncMock,
                side_effect=AuthenticationError("bad"),
            ),
            patch.object(
                coord, "_apply_initial_stagger_offset", new_callable=AsyncMock
            ),
        ):
            with pytest.raises(ConfigEntryAuthFailed):
                await coord._fetch_portfolio_data()

    async def test_timeout_error(self):
        """TimeoutError raises UpdateFailed with timeout message."""
        coord = _bare_coordinator()
        coord._initial_update_offset = 0
        with (
            patch.object(coord, "_ensure_token_valid", new_callable=AsyncMock),
            patch.object(
                coord, "_apply_initial_stagger_offset", new_callable=AsyncMock
            ),
            patch(
                "custom_components.saxo_portfolio.coordinator.async_get_clientsession",
                return_value=MagicMock(),
            ),
        ):
            coord._oauth_session.token = {"access_token": "tok"}
            with patch.object(
                coord,
                "_fetch_balance_with_logging",
                new_callable=AsyncMock,
                side_effect=TimeoutError(),
            ):
                with pytest.raises(UpdateFailed, match="timeout"):
                    await coord._fetch_portfolio_data()

    async def test_api_error(self):
        """APIError raises UpdateFailed."""
        coord = _bare_coordinator()
        coord._initial_update_offset = 0
        with (
            patch.object(coord, "_ensure_token_valid", new_callable=AsyncMock),
            patch.object(
                coord, "_apply_initial_stagger_offset", new_callable=AsyncMock
            ),
            patch(
                "custom_components.saxo_portfolio.coordinator.async_get_clientsession",
                return_value=MagicMock(),
            ),
        ):
            coord._oauth_session.token = {"access_token": "tok"}
            with patch.object(
                coord,
                "_fetch_balance_with_logging",
                new_callable=AsyncMock,
                side_effect=APIError("api"),
            ):
                with pytest.raises(UpdateFailed, match="API error"):
                    await coord._fetch_portfolio_data()

    async def test_client_error(self):
        """aiohttp.ClientError raises UpdateFailed with network message."""
        coord = _bare_coordinator()
        coord._initial_update_offset = 0
        with (
            patch.object(coord, "_ensure_token_valid", new_callable=AsyncMock),
            patch.object(
                coord, "_apply_initial_stagger_offset", new_callable=AsyncMock
            ),
            patch(
                "custom_components.saxo_portfolio.coordinator.async_get_clientsession",
                return_value=MagicMock(),
            ),
        ):
            coord._oauth_session.token = {"access_token": "tok"}
            with patch.object(
                coord,
                "_fetch_balance_with_logging",
                new_callable=AsyncMock,
                side_effect=aiohttp.ClientError(),
            ):
                with pytest.raises(UpdateFailed, match="Network error"):
                    await coord._fetch_portfolio_data()

    async def test_config_entry_auth_failed_reraised(self):
        """ConfigEntryAuthFailed is re-raised without wrapping."""
        coord = _bare_coordinator()
        coord._initial_update_offset = 0
        with (
            patch.object(
                coord, "_apply_initial_stagger_offset", new_callable=AsyncMock
            ),
            patch.object(
                coord,
                "_ensure_token_valid",
                new_callable=AsyncMock,
                side_effect=ConfigEntryAuthFailed("reauth"),
            ),
        ):
            with pytest.raises(ConfigEntryAuthFailed):
                await coord._fetch_portfolio_data()

    async def test_unexpected_error(self):
        """Unexpected ValueError raises UpdateFailed."""
        coord = _bare_coordinator()
        coord._initial_update_offset = 0
        with (
            patch.object(coord, "_ensure_token_valid", new_callable=AsyncMock),
            patch.object(
                coord, "_apply_initial_stagger_offset", new_callable=AsyncMock
            ),
            patch(
                "custom_components.saxo_portfolio.coordinator.async_get_clientsession",
                return_value=MagicMock(),
            ),
        ):
            coord._oauth_session.token = {"access_token": "tok"}
            with patch.object(
                coord,
                "_fetch_balance_with_logging",
                new_callable=AsyncMock,
                side_effect=ValueError("oops"),
            ):
                with pytest.raises(UpdateFailed, match="Unexpected"):
                    await coord._fetch_portfolio_data()


# ---------------------------------------------------------------------------
# _apply_initial_stagger_offset
# ---------------------------------------------------------------------------


class TestApplyInitialStaggerOffset:
    """Tests for _apply_initial_stagger_offset."""

    async def test_skips_on_first_update(self):
        """First update (no previous success) skips the stagger offset."""
        coord = _bare_coordinator()
        coord._initial_update_offset = 10.0
        coord._last_successful_update = None
        await coord._apply_initial_stagger_offset()
        assert coord._initial_update_offset == 10.0

    async def test_applies_and_clears(self):
        """After first success, offset is applied and cleared."""
        coord = _bare_coordinator()
        coord._initial_update_offset = 0.01
        coord._last_successful_update = datetime.now()
        await coord._apply_initial_stagger_offset()
        assert coord._initial_update_offset == 0

    async def test_zero_offset_noop(self):
        """Zero offset is a no-op."""
        coord = _bare_coordinator()
        coord._initial_update_offset = 0
        coord._last_successful_update = datetime.now()
        await coord._apply_initial_stagger_offset()


# ---------------------------------------------------------------------------
# _log_portfolio_timeout
# ---------------------------------------------------------------------------


class TestLogPortfolioTimeout:
    """Tests for _log_portfolio_timeout."""

    def test_with_start_time(self):
        """Timeout with a start time records the warning timestamp."""
        coord = _bare_coordinator()
        coord._log_portfolio_timeout(datetime.now() - timedelta(seconds=5))
        assert coord._last_timeout_warning is not None

    def test_without_start_time(self):
        """Timeout without start time still records the warning."""
        coord = _bare_coordinator()
        coord._log_portfolio_timeout(None)
        assert coord._last_timeout_warning is not None

    def test_rate_limited_logging(self):
        """Recent warning suppresses subsequent warnings to debug level."""
        coord = _bare_coordinator()
        coord._last_timeout_warning = datetime.now() - timedelta(seconds=10)
        coord._log_portfolio_timeout(datetime.now())

    def test_warning_after_cooldown(self):
        """After 5-minute cooldown, warning is logged again at warning level."""
        coord = _bare_coordinator()
        coord._last_timeout_warning = datetime.now() - timedelta(minutes=10)
        coord._log_portfolio_timeout(datetime.now())
        assert (datetime.now() - coord._last_timeout_warning).total_seconds() < 2


# ---------------------------------------------------------------------------
# _async_update_data
# ---------------------------------------------------------------------------


class TestAsyncUpdateData:
    """Tests for _async_update_data."""

    async def test_any_timezone_uses_fixed_interval(self):
        """Any timezone switches to the fixed ANY interval."""
        coord = _bare_coordinator()
        coord._timezone = "any"
        coord.update_interval = DEFAULT_UPDATE_INTERVAL_MARKET_HOURS
        with patch.object(
            coord,
            "_fetch_portfolio_data",
            new_callable=AsyncMock,
            return_value={"client_name": "unknown"},
        ):
            with patch(
                "custom_components.saxo_portfolio.coordinator.dt_util"
            ) as mock_dt:
                mock_dt.utcnow.return_value = datetime.now()
                await coord._async_update_data()
        assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_ANY

    async def test_market_hours_updates_interval(self):
        """Market open switches to market hours interval."""
        coord = _bare_coordinator()
        coord._timezone = "America/New_York"
        coord.update_interval = DEFAULT_UPDATE_INTERVAL_AFTER_HOURS
        with (
            patch.object(coord, "_is_market_hours", return_value=True),
            patch.object(
                coord,
                "_fetch_portfolio_data",
                new_callable=AsyncMock,
                return_value={"client_name": "unknown"},
            ),
            patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt,
        ):
            mock_dt.utcnow.return_value = datetime.now()
            await coord._async_update_data()
        assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_MARKET_HOURS

    async def test_after_hours_updates_interval(self):
        """Market closed switches to after-hours interval."""
        coord = _bare_coordinator()
        coord._timezone = "America/New_York"
        coord.update_interval = DEFAULT_UPDATE_INTERVAL_MARKET_HOURS
        with (
            patch.object(coord, "_is_market_hours", return_value=False),
            patch.object(
                coord,
                "_fetch_portfolio_data",
                new_callable=AsyncMock,
                return_value={"client_name": "unknown"},
            ),
            patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt,
        ):
            mock_dt.utcnow.return_value = datetime.now()
            await coord._async_update_data()
        assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_AFTER_HOURS

    async def test_reload_triggered_when_client_name_resolves(self):
        """Config entry reload is triggered when client name changes from unknown."""
        coord = _bare_coordinator()
        coord._last_known_client_name = "unknown"
        coord._sensors_initialized = False
        coord._setup_complete = True
        with (
            patch.object(
                coord,
                "_fetch_portfolio_data",
                new_callable=AsyncMock,
                return_value={"client_name": "John Doe"},
            ),
            patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt,
        ):
            mock_dt.utcnow.return_value = datetime.now()
            await coord._async_update_data()
        coord.hass.async_create_task.assert_called_once()

    async def test_no_reload_when_sensors_initialized(self):
        """No reload when sensors are already initialized."""
        coord = _bare_coordinator()
        coord._last_known_client_name = "unknown"
        coord._sensors_initialized = True
        coord._setup_complete = True
        with (
            patch.object(
                coord,
                "_fetch_portfolio_data",
                new_callable=AsyncMock,
                return_value={"client_name": "John Doe"},
            ),
            patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt,
        ):
            mock_dt.utcnow.return_value = datetime.now()
            await coord._async_update_data()
        coord.hass.async_create_task.assert_not_called()

    async def test_no_reload_when_setup_not_complete(self):
        """No reload when initial setup is not yet complete."""
        coord = _bare_coordinator()
        coord._last_known_client_name = "unknown"
        coord._sensors_initialized = False
        coord._setup_complete = False
        with (
            patch.object(
                coord,
                "_fetch_portfolio_data",
                new_callable=AsyncMock,
                return_value={"client_name": "John Doe"},
            ),
            patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt,
        ):
            mock_dt.utcnow.return_value = datetime.now()
            await coord._async_update_data()
        coord.hass.async_create_task.assert_not_called()

    async def test_startup_phase_exits_after_3_updates(self):
        """Startup phase exits after 3 successful updates."""
        coord = _bare_coordinator()
        coord._successful_updates_count = 2
        coord._is_startup_phase = True
        with (
            patch.object(
                coord,
                "_fetch_portfolio_data",
                new_callable=AsyncMock,
                return_value={"client_name": "unknown"},
            ),
            patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt,
        ):
            mock_dt.utcnow.return_value = datetime.now()
            await coord._async_update_data()
        assert coord._is_startup_phase is False
        assert coord._successful_updates_count == 3

    async def test_none_data_does_not_update_timestamp(self):
        """None data from fetch does not update the last successful timestamp."""
        coord = _bare_coordinator()
        with patch.object(
            coord, "_fetch_portfolio_data", new_callable=AsyncMock, return_value=None
        ):
            await coord._async_update_data()
        assert coord._last_successful_update is None

    async def test_interval_unchanged_no_log(self):
        """When interval matches, no switch happens."""
        coord = _bare_coordinator()
        coord._timezone = "any"
        coord.update_interval = DEFAULT_UPDATE_INTERVAL_ANY
        with patch.object(
            coord,
            "_fetch_portfolio_data",
            new_callable=AsyncMock,
            return_value={"client_name": "unknown"},
        ):
            with patch(
                "custom_components.saxo_portfolio.coordinator.dt_util"
            ) as mock_dt:
                mock_dt.utcnow.return_value = datetime.now()
                await coord._async_update_data()
        assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_ANY


# ---------------------------------------------------------------------------
# async_shutdown
# ---------------------------------------------------------------------------


class TestAsyncShutdown:
    """Tests for async_shutdown."""

    async def test_cleanup(self, mock_hass, mock_config_entry, mock_oauth_session):
        """Shutdown clears the API client and calls parent shutdown."""
        coord = _make_coordinator(mock_hass, mock_config_entry, mock_oauth_session)
        coord._api_client = MagicMock()
        with patch(
            "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.async_shutdown",
            new_callable=AsyncMock,
        ):
            await coord.async_shutdown()
        assert coord._api_client is None


# ---------------------------------------------------------------------------
# Getter methods
# ---------------------------------------------------------------------------


class TestGetters:
    """Tests for all getter methods."""

    def test_get_cash_balance_no_data(self):
        """No data returns 0.0 for cash balance."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_cash_balance() == 0.0

    def test_get_cash_balance_with_data(self):
        """Cash balance is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"cash_balance": 1234.56}
        assert coord.get_cash_balance() == 1234.56

    def test_get_total_value_no_data(self):
        """No data returns 0.0 for total value."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_total_value() == 0.0

    def test_get_total_value_with_data(self):
        """Total value is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"total_value": 9999.99}
        assert coord.get_total_value() == 9999.99

    def test_get_non_margin_positions_value_no_data(self):
        """No data returns 0.0 for non-margin positions value."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_non_margin_positions_value() == 0.0

    def test_get_non_margin_positions_value_with_data(self):
        """Non-margin positions value is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"non_margin_positions_value": 5000.0}
        assert coord.get_non_margin_positions_value() == 5000.0

    def test_get_currency_no_data(self):
        """No data returns USD default."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_currency() == "USD"

    def test_get_currency_with_data(self):
        """Currency is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"currency": "EUR"}
        assert coord.get_currency() == "EUR"

    def test_get_ytd_earnings_percentage_no_data(self):
        """No data returns 0.0 for YTD earnings."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_ytd_earnings_percentage() == 0.0

    def test_get_ytd_earnings_percentage_with_data(self):
        """YTD earnings percentage is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"ytd_earnings_percentage": 12.5}
        assert coord.get_ytd_earnings_percentage() == 12.5

    def test_get_client_id_no_data(self):
        """No data returns 'unknown' for client ID."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_client_id() == "unknown"

    def test_get_client_id_with_data(self):
        """Client ID is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"client_id": "C123"}
        assert coord.get_client_id() == "C123"

    def test_get_investment_performance_percentage_no_data(self):
        """No data returns 0.0 for investment performance."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_investment_performance_percentage() == 0.0

    def test_get_investment_performance_percentage_with_data(self):
        """Investment performance is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"investment_performance_percentage": 7.3}
        assert coord.get_investment_performance_percentage() == 7.3

    def test_get_cash_transfer_balance_no_data(self):
        """No data returns 0.0 for cash transfer balance."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_cash_transfer_balance() == 0.0

    def test_get_cash_transfer_balance_with_data(self):
        """Cash transfer balance is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"cash_transfer_balance": 50000.0}
        assert coord.get_cash_transfer_balance() == 50000.0

    def test_get_ytd_investment_performance_percentage_no_data(self):
        """No data returns 0.0 for YTD investment performance."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_ytd_investment_performance_percentage() == 0.0

    def test_get_ytd_investment_performance_percentage_with_data(self):
        """YTD investment performance is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"ytd_investment_performance_percentage": 3.2}
        assert coord.get_ytd_investment_performance_percentage() == 3.2

    def test_get_month_investment_performance_percentage_no_data(self):
        """No data returns 0.0 for month investment performance."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_month_investment_performance_percentage() == 0.0

    def test_get_month_investment_performance_percentage_with_data(self):
        """Month investment performance is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"month_investment_performance_percentage": 1.5}
        assert coord.get_month_investment_performance_percentage() == 1.5

    def test_get_quarter_investment_performance_percentage_no_data(self):
        """No data returns 0.0 for quarter investment performance."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_quarter_investment_performance_percentage() == 0.0

    def test_get_quarter_investment_performance_percentage_with_data(self):
        """Quarter investment performance is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"quarter_investment_performance_percentage": 2.8}
        assert coord.get_quarter_investment_performance_percentage() == 2.8

    def test_get_account_id_no_data(self):
        """No data returns 'unknown' for account ID."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_account_id() == "unknown"

    def test_get_account_id_with_data(self):
        """Account ID is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"account_id": "A456"}
        assert coord.get_account_id() == "A456"

    def test_get_client_name_no_data(self):
        """No data returns 'unknown' for client name."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.get_client_name() == "unknown"

    def test_get_client_name_with_data(self):
        """Client name is returned from data."""
        coord = _bare_coordinator()
        coord.data = {"client_name": "John"}
        assert coord.get_client_name() == "John"

    def test_get_positions_empty(self):
        """Empty cache returns empty positions dict."""
        coord = _bare_coordinator()
        assert coord.get_positions() == {}

    def test_get_positions_with_data(self):
        """Cached positions are returned."""
        coord = _bare_coordinator()
        pos = PositionData(
            position_id="P1",
            symbol="AAPL",
            description="Apple",
            asset_type="Stock",
            amount=10,
            current_price=150.0,
            market_value=1500.0,
            profit_loss=100.0,
            uic=123,
        )
        coord._positions_cache.positions = {"aapl_stock": pos}
        assert len(coord.get_positions()) == 1

    def test_get_position_found(self):
        """Existing position is returned by slug."""
        coord = _bare_coordinator()
        pos = PositionData(
            position_id="P1",
            symbol="AAPL",
            description="Apple",
            asset_type="Stock",
            amount=10,
            current_price=150.0,
            market_value=1500.0,
            profit_loss=100.0,
            uic=123,
        )
        coord._positions_cache.positions = {"aapl_stock": pos}
        assert coord.get_position("aapl_stock") is pos

    def test_get_position_not_found(self):
        """Missing slug returns None."""
        coord = _bare_coordinator()
        assert coord.get_position("nonexistent") is None

    def test_get_position_ids(self):
        """Position IDs list is returned from cache."""
        coord = _bare_coordinator()
        coord._positions_cache.position_ids = ["a", "b"]
        assert coord.get_position_ids() == ["a", "b"]

    def test_has_market_data_access(self):
        """Market data access reflects internal state."""
        coord = _bare_coordinator()
        assert coord.has_market_data_access() is None
        coord._has_market_data_access = True
        assert coord.has_market_data_access() is True

    def test_position_sensors_enabled(self):
        """Position sensors enabled reflects internal flag."""
        coord = _bare_coordinator()
        coord._enable_position_sensors = False
        assert coord.position_sensors_enabled is False
        coord._enable_position_sensors = True
        assert coord.position_sensors_enabled is True

    def test_last_successful_update_time(self):
        """Last successful update time reflects internal state."""
        coord = _bare_coordinator()
        assert coord.last_successful_update_time is None
        now = datetime.now()
        coord._last_successful_update = now
        assert coord.last_successful_update_time is now

    def test_is_startup_phase(self):
        """Startup phase property reflects internal flag."""
        coord = _bare_coordinator()
        assert coord.is_startup_phase is True
        coord._is_startup_phase = False
        assert coord.is_startup_phase is False


# ---------------------------------------------------------------------------
# mark_sensors_initialized / mark_setup_complete
# ---------------------------------------------------------------------------


class TestMarkMethods:
    """Tests for mark_sensors_initialized and mark_setup_complete."""

    def test_mark_sensors_initialized(self):
        """Sensors initialized flag is set to True."""
        coord = _bare_coordinator()
        assert coord._sensors_initialized is False
        coord.mark_sensors_initialized()
        assert coord._sensors_initialized is True

    def test_mark_setup_complete(self):
        """Setup complete flag is set to True."""
        coord = _bare_coordinator()
        assert coord._setup_complete is False
        coord.mark_setup_complete()
        assert coord._setup_complete is True


# ---------------------------------------------------------------------------
# _update_config_entry_title_if_needed
# ---------------------------------------------------------------------------


class TestUpdateConfigEntryTitleIfNeeded:
    """Tests for _update_config_entry_title_if_needed."""

    def test_unknown_client_id_noop(self):
        """Unknown client ID does not trigger title update."""
        coord = _bare_coordinator()
        coord._update_config_entry_title_if_needed("unknown")
        coord.hass.config_entries.async_update_entry.assert_not_called()

    def test_generic_title_updated(self):
        """Generic 'Saxo Portfolio' title is updated with client ID."""
        coord = _bare_coordinator()
        coord.config_entry.title = "Saxo Portfolio"
        coord._update_config_entry_title_if_needed("C123")
        coord.hass.config_entries.async_update_entry.assert_called_once()
        call_kwargs = coord.hass.config_entries.async_update_entry.call_args
        assert call_kwargs[1]["title"] == "Saxo Portfolio (C123)"

    def test_title_without_parens_updated(self):
        """Title without parentheses and client ID is updated."""
        coord = _bare_coordinator()
        coord.config_entry.title = "My Saxo"
        coord._update_config_entry_title_if_needed("C123")
        coord.hass.config_entries.async_update_entry.assert_called_once()

    def test_already_has_client_id_noop(self):
        """Title already containing client ID is not changed."""
        coord = _bare_coordinator()
        coord.config_entry.title = "Saxo Portfolio (C123)"
        coord._update_config_entry_title_if_needed("C123")
        coord.hass.config_entries.async_update_entry.assert_not_called()

    def test_title_with_different_parens_noop(self):
        """Title with existing parentheses is not changed."""
        coord = _bare_coordinator()
        coord.config_entry.title = "Saxo (other)"
        coord._update_config_entry_title_if_needed("C123")
        coord.hass.config_entries.async_update_entry.assert_not_called()


# ---------------------------------------------------------------------------
# _update_positions_cache
# ---------------------------------------------------------------------------


class TestUpdatePositionsCache:
    """Tests for _update_positions_cache."""

    def test_updates_cache(self):
        """Positions are stored in cache with IDs and timestamp."""
        coord = _bare_coordinator()
        pos = PositionData(
            position_id="P1",
            symbol="AAPL",
            description="Apple",
            asset_type="Stock",
            amount=10,
            current_price=150.0,
            market_value=1500.0,
            profit_loss=100.0,
            uic=123,
        )
        coord._update_positions_cache({"aapl_stock": pos})
        assert coord._positions_cache.positions == {"aapl_stock": pos}
        assert coord._positions_cache.position_ids == ["aapl_stock"]
        assert coord._positions_cache.last_updated is not None


# ---------------------------------------------------------------------------
# _fetch_balance_with_logging
# ---------------------------------------------------------------------------


class TestFetchBalanceWithLogging:
    """Tests for _fetch_balance_with_logging."""

    async def test_strips_margin_detail(self):
        """MarginCollateralNotAvailableDetail is removed from response."""
        coord = _bare_coordinator()
        client = AsyncMock()
        client.get_account_balance = AsyncMock(
            return_value={
                "CashBalance": 1000.0,
                "Currency": "EUR",
                "TotalValue": 5000.0,
                "MarginCollateralNotAvailableDetail": {"some": "data"},
            }
        )
        client.base_url = "https://gateway.saxobank.com/openapi"
        result = await coord._fetch_balance_with_logging(client)
        assert "MarginCollateralNotAvailableDetail" not in result
        assert result["CashBalance"] == 1000.0


# ---------------------------------------------------------------------------
# async_update_interval_if_needed
# ---------------------------------------------------------------------------


class TestAsyncUpdateIntervalIfNeeded:
    """Tests for async_update_interval_if_needed."""

    async def test_any_timezone(self):
        """Any timezone sets the fixed ANY interval."""
        coord = _bare_coordinator()
        coord._timezone = "any"
        coord.update_interval = DEFAULT_UPDATE_INTERVAL_MARKET_HOURS
        await coord.async_update_interval_if_needed()
        assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_ANY

    async def test_market_timezone_open(self):
        """Open market sets market hours interval."""
        coord = _bare_coordinator()
        coord._timezone = "America/New_York"
        coord.update_interval = DEFAULT_UPDATE_INTERVAL_AFTER_HOURS
        with patch.object(coord, "_is_market_hours", return_value=True):
            await coord.async_update_interval_if_needed()
        assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_MARKET_HOURS

    async def test_market_timezone_closed(self):
        """Closed market sets after-hours interval."""
        coord = _bare_coordinator()
        coord._timezone = "America/New_York"
        coord.update_interval = DEFAULT_UPDATE_INTERVAL_MARKET_HOURS
        with patch.object(coord, "_is_market_hours", return_value=False):
            await coord.async_update_interval_if_needed()
        assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_AFTER_HOURS

    async def test_any_timezone_same_interval_noop(self):
        """Same ANY interval is a no-op."""
        coord = _bare_coordinator()
        coord._timezone = "any"
        coord.update_interval = DEFAULT_UPDATE_INTERVAL_ANY
        await coord.async_update_interval_if_needed()
        assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_ANY

    async def test_market_timezone_same_interval_noop(self):
        """Same after-hours interval is a no-op."""
        coord = _bare_coordinator()
        coord._timezone = "America/New_York"
        coord.update_interval = DEFAULT_UPDATE_INTERVAL_AFTER_HOURS
        with patch.object(coord, "_is_market_hours", return_value=False):
            await coord.async_update_interval_if_needed()
        assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_AFTER_HOURS


# ---------------------------------------------------------------------------
# PositionsCache dataclass
# ---------------------------------------------------------------------------


class TestPositionsCache:
    """Tests for PositionsCache dataclass."""

    def test_defaults(self):
        """Default PositionsCache has empty positions and no timestamp."""
        cache = PositionsCache()
        assert cache.positions == {}
        assert cache.last_updated is None
        assert cache.position_ids == []
