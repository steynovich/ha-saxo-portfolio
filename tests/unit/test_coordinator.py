"""Comprehensive unit tests for SaxoCoordinator.

Tests cover:
- api_client property (creation, token change, no access token)
- _is_market_hours (weekday/weekend, open/closed, timezone any, cache)
- _ensure_token_valid (proactive refresh, token age)
- _proactive_refresh_token (success, 400/401, transient error)
- _fetch_portfolio_data (full flow, auth error, timeout, API error)
- _async_update_data (interval adjustment, reload trigger)
- async_shutdown (cleanup)
- client_info and positions accessors (with/without data)
- mark_sensors_initialized, mark_setup_complete
- _update_config_entry_title_if_needed

Performance and position fetching/parsing are tested in test_performance.py
and test_positions.py.
"""

from __future__ import annotations

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
)
from custom_components.saxo_portfolio.coordinator import SaxoCoordinator
from custom_components.saxo_portfolio.data import (
    BalanceData,
    ClientInfo,
    PerformanceData,
    SaxoPortfolioData,
)
from custom_components.saxo_portfolio.performance import PerformanceFetcher
from custom_components.saxo_portfolio.positions import PositionData, PositionsFetcher

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


def _portfolio_data(client_name: str = "unknown") -> SaxoPortfolioData:
    """Minimal typed coordinator data for a given client name."""
    return SaxoPortfolioData(
        balance=BalanceData(),
        client=ClientInfo(client_name=client_name),
        last_updated=datetime.now(),
    )


def _bare_coordinator():
    """Build a coordinator via object.__new__ for testing individual methods."""
    coord = object.__new__(SaxoCoordinator)
    coord._performance = PerformanceFetcher(
        on_client_info=lambda client: coord._update_config_entry_title_if_needed(
            client.client_id
        )
    )
    coord._positions = PositionsFetcher(enabled=False)
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
        assert coord.position_sensors_enabled is True

    def test_init_position_sensors_default_off(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Position sensors are opt-in."""
        coord = _make_coordinator(mock_hass, mock_config_entry, mock_oauth_session)
        assert coord.position_sensors_enabled is False


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

    def test_token_change_keeps_client_and_rate_limit_state(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """A rotated access token reaches the same client, keeping its limiter."""
        coord = _make_coordinator(mock_hass, mock_config_entry, mock_oauth_session)
        with patch(
            "custom_components.saxo_portfolio.coordinator.async_get_clientsession",
            return_value=MagicMock(),
        ):
            c1 = coord.api_client
            c1._rate_limiter.set_rate_limited_until(60)
            limiter = c1._rate_limiter
            # Simulate token change
            mock_oauth_session.token = {
                **mock_oauth_session.token,
                "access_token": "new_token",
            }
            c2 = coord.api_client
            assert c2 is c1
            assert c2.access_token == "new_token"
            assert c2._rate_limiter is limiter
            assert c2._rate_limiter._rate_limited_until > 0

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

    def test_unknown_timezone_does_not_overwrite_configured(self):
        """Falling back for an unknown zone must not mutate self._timezone."""
        coord = _bare_coordinator()
        coord._timezone = "Mars/Olympus_Mons"
        with patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 4, 13, 14, 0, 0, tzinfo=_UTC)
            coord._is_market_hours()
        assert coord._timezone == "Mars/Olympus_Mons"

    def test_frankfurt_market_open(self):
        """Frankfurt users get market hours: Monday 10:00 CEST is open."""
        coord = _bare_coordinator()
        coord._timezone = "Europe/Berlin"
        with patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 4, 13, 8, 0, 0, tzinfo=_UTC)
            assert coord._is_market_hours() is True

    def test_market_hour_keys_are_valid_iana_zones(self):
        """Every timezone key must resolve via ZoneInfo (except 'any')."""
        from custom_components.saxo_portfolio.const import (
            MARKET_HOURS,
            TIMEZONE_OPTIONS,
        )

        for key in (*MARKET_HOURS, *TIMEZONE_OPTIONS):
            if key != "any":
                ZoneInfo(key)
        assert set(MARKET_HOURS) == set(TIMEZONE_OPTIONS) - {"any"}

    def test_exception_returns_false(self):
        """Exception during check defaults to False (after-hours)."""
        coord = _bare_coordinator()
        coord._timezone = "America/New_York"
        with patch("custom_components.saxo_portfolio.coordinator.dt_util") as mock_dt:
            mock_dt.utcnow.side_effect = RuntimeError("boom")
            result = coord._is_market_hours()
            assert result is False


class TestPublicAccessors:
    """Tests for the public read-only coordinator accessors used by sensors."""

    def test_timezone(self):
        coord = _bare_coordinator()
        coord._timezone = "Europe/Amsterdam"
        assert coord.timezone == "Europe/Amsterdam"

    def test_timezone_is_read_only(self):
        coord = _bare_coordinator()
        with pytest.raises(AttributeError):
            coord.timezone = "any"  # type: ignore[misc]

    def test_is_market_hours_delegates(self):
        coord = _bare_coordinator()
        with patch.object(coord, "_is_market_hours", return_value=True):
            assert coord.is_market_hours is True
        with patch.object(coord, "_is_market_hours", return_value=False):
            assert coord.is_market_hours is False

    def test_is_market_hours_any_timezone(self):
        coord = _bare_coordinator()
        coord._timezone = "any"
        assert coord.is_market_hours is False

    def test_performance_last_updated(self):
        coord = _bare_coordinator()
        assert coord.performance_last_updated is None
        stamp = datetime(2026, 1, 1, 12, 0)
        coord._performance.last_updated = stamp
        assert coord.performance_last_updated == stamp


class TestApiRequestDelay:
    """The inter-request rate-limit delay is one named constant."""

    def test_constant_value(self):
        from custom_components.saxo_portfolio.const import API_REQUEST_DELAY

        assert API_REQUEST_DELAY == 0.5

    def test_no_literal_delays_in_source(self):
        """No module sleeps on a hard-coded 0.5 literal."""
        import pathlib

        import custom_components.saxo_portfolio as pkg

        root = pathlib.Path(pkg.__file__).parent
        offenders = [
            str(path.relative_to(root))
            for path in root.rglob("*.py")
            if "asyncio.sleep(0.5)" in path.read_text()
        ]
        assert offenders == []


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
                return_value=BalanceData(
                    cash_balance=1000.0,
                    currency="EUR",
                    total_value=5000.0,
                    non_margin_positions_value=4000.0,
                ),
            ),
            patch.object(
                coord._performance, "async_update", new_callable=AsyncMock
            ) as performance_update,
            patch.object(
                coord._positions,
                "async_fetch",
                new_callable=AsyncMock,
                return_value={},
            ) as positions_fetch,
            patch(
                "custom_components.saxo_portfolio.coordinator.async_get_clientsession",
                return_value=MagicMock(),
            ),
        ):
            coord._oauth_session.token = {"access_token": "tok"}
            coord._performance.client = ClientInfo(client_id="C1")
            coord._performance.metrics = PerformanceData(
                investment_performance_percentage=5.0
            )
            result = await coord._fetch_portfolio_data()
            performance_update.assert_awaited_once()
            positions_fetch.assert_awaited_once()
            assert result.balance == BalanceData(
                cash_balance=1000.0,
                currency="EUR",
                total_value=5000.0,
                non_margin_positions_value=4000.0,
            )
            assert result.client == ClientInfo(client_id="C1")
            assert result.performance == PerformanceData(
                investment_performance_percentage=5.0
            )
            assert isinstance(result.last_updated, datetime)

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
            return_value=_portfolio_data("unknown"),
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
                return_value=_portfolio_data("unknown"),
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
                return_value=_portfolio_data("unknown"),
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
                return_value=_portfolio_data("John Doe"),
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
                return_value=_portfolio_data("John Doe"),
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
                return_value=_portfolio_data("John Doe"),
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
                return_value=_portfolio_data("unknown"),
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
            return_value=_portfolio_data("unknown"),
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
    """Tests for the public accessors."""

    def test_client_info_no_data(self):
        """No data yet: every client field is "unknown"."""
        coord = _bare_coordinator()
        coord.data = None
        assert coord.client_info == ClientInfo()
        assert coord.client_info.client_id == "unknown"
        assert coord.client_info.account_id == "unknown"
        assert coord.client_info.client_name == "unknown"

    def test_client_info_with_data(self):
        """Client identity comes from the typed coordinator data."""
        coord = _bare_coordinator()
        client = ClientInfo(client_id="C123", account_id="A456", client_name="John")
        coord.data = SaxoPortfolioData(
            balance=BalanceData(), client=client, last_updated=datetime.now()
        )
        assert coord.client_info is client

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
        coord._positions.cache.positions = {"aapl_stock": pos}
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
        coord._positions.cache.positions = {"aapl_stock": pos}
        assert coord.get_position("aapl_stock") is pos

    def test_get_position_not_found(self):
        """Missing slug returns None."""
        coord = _bare_coordinator()
        assert coord.get_position("nonexistent") is None

    def test_get_position_ids(self):
        """Position IDs list is returned from cache."""
        coord = _bare_coordinator()
        coord._positions.cache.position_ids = ["a", "b"]
        assert coord.get_position_ids() == ["a", "b"]

    def test_has_market_data_access(self):
        """Market data access reflects internal state."""
        coord = _bare_coordinator()
        assert coord.has_market_data_access() is None
        coord._positions.has_market_data_access = True
        assert coord.has_market_data_access() is True

    def test_position_sensors_enabled(self):
        """Position sensors enabled reflects internal flag."""
        coord = _bare_coordinator()
        assert coord.position_sensors_enabled is False
        coord._positions = PositionsFetcher(enabled=True)
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

    async def test_performance_fetch_updates_title(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """A performance fetch passes the fetched ClientId to the title update."""
        coord = _make_coordinator(mock_hass, mock_config_entry, mock_oauth_session)
        client = AsyncMock()
        client.get_client_details = AsyncMock(
            return_value={"ClientId": "C123", "Name": "Someone"}
        )
        with patch(
            "custom_components.saxo_portfolio.performance.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await coord._performance.async_update(client)

        mock_hass.config_entries.async_update_entry.assert_called_once_with(
            mock_config_entry, title="Saxo Portfolio (C123)"
        )

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
# _fetch_balance_with_logging
# ---------------------------------------------------------------------------


class TestFetchBalanceWithLogging:
    """Tests for _fetch_balance_with_logging."""

    async def test_strips_margin_detail(self):
        """The response is parsed; MarginCollateralNotAvailableDetail is dropped."""
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
        assert result == BalanceData(
            cash_balance=1000.0,
            currency="EUR",
            total_value=5000.0,
            non_margin_positions_value=0.0,
        )


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
# async_apply_options (timezone change without restart)
# ---------------------------------------------------------------------------


class TestApplyOptions:
    """A changed market timezone applies to the running coordinator."""

    @pytest.mark.asyncio
    async def test_new_timezone_is_applied(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ) -> None:
        coord = _make_coordinator(
            mock_hass, mock_config_entry, mock_oauth_session, timezone="any"
        )
        coord.async_request_refresh = AsyncMock()
        assert coord.timezone == "any"
        assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_ANY

        mock_config_entry.data = {**mock_config_entry.data, "timezone": "Europe/London"}
        with patch.object(coord, "_is_market_hours", return_value=True):
            await coord.async_apply_options()

        assert coord.timezone == "Europe/London"
        assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_MARKET_HOURS
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_market_hours_cache_is_dropped(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ) -> None:
        coord = _make_coordinator(
            mock_hass, mock_config_entry, mock_oauth_session, timezone="Asia/Tokyo"
        )
        coord.async_request_refresh = AsyncMock()
        coord._market_hours_cache = True
        coord._market_hours_cache_time = datetime.now()

        mock_config_entry.data = {**mock_config_entry.data, "timezone": "any"}
        await coord.async_apply_options()

        assert coord.is_market_hours is False
        assert coord.update_interval == DEFAULT_UPDATE_INTERVAL_ANY

    @pytest.mark.asyncio
    async def test_listeners_notified_even_if_data_unchanged(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ) -> None:
        """always_update=False must not leave the Timezone sensor stale."""
        coord = _make_coordinator(
            mock_hass, mock_config_entry, mock_oauth_session, timezone="any"
        )
        coord.async_request_refresh = AsyncMock()
        coord.async_update_listeners = MagicMock()

        mock_config_entry.data = {**mock_config_entry.data, "timezone": "Asia/Tokyo"}
        await coord.async_apply_options()

        coord.async_update_listeners.assert_called_once()

    @pytest.mark.asyncio
    async def test_unchanged_configured_timezone_is_a_noop(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ) -> None:
        """Token-only entry updates, even with an unknown timezone, do nothing."""
        coord = _make_coordinator(
            mock_hass, mock_config_entry, mock_oauth_session, timezone="Mars/Olympus"
        )
        coord.async_request_refresh = AsyncMock()
        with patch("custom_components.saxo_portfolio.coordinator.dt_util.utcnow"):
            coord._is_market_hours()  # normalises the unknown timezone

        await coord.async_apply_options()

        coord.async_request_refresh.assert_not_awaited()
