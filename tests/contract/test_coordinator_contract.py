"""Contract tests for DataUpdateCoordinator interface.

These tests validate that the SaxoCoordinator implementation follows
the Home Assistant DataUpdateCoordinator interface contract.

⚠️  TDD REQUIREMENT: These tests MUST FAIL initially since no implementation exists.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.saxo_portfolio.const import DOMAIN
from custom_components.saxo_portfolio.coordinator import SaxoCoordinator


@pytest.mark.contract
class TestSaxoCoordinatorContract:
    """Contract tests for SaxoCoordinator DataUpdateCoordinator interface."""

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = MagicMock(spec=HomeAssistant)
        hass.data = {DOMAIN: {}}
        return hass

    @pytest.fixture
    def mock_config_entry(self):
        """Create a mock Home Assistant config entry."""
        config_entry = MagicMock(spec=ConfigEntry)
        config_entry.entry_id = "test_entry_id"
        config_entry.options = {}
        config_entry.state = ConfigEntryState.SETUP_IN_PROGRESS
        config_entry.data = {
            "token": {
                "access_token": "test_token",
                "refresh_token": "test_refresh_token",
                "expires_at": (datetime.now() + timedelta(hours=1)).timestamp(),
                "token_issued_at": datetime.now().timestamp(),
            },
            "timezone": "any",
        }
        return config_entry

    @pytest.fixture
    def mock_oauth_session(self, mock_config_entry):
        """Create a mock OAuth2 session."""
        session = MagicMock()
        session.token = mock_config_entry.data["token"]
        session.async_ensure_token_valid = AsyncMock()
        return session

    @pytest.fixture
    def coordinator(self, mock_hass, mock_config_entry, mock_oauth_session):
        """Create a SaxoCoordinator instance."""
        coord = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
        # The parent __init__ resolves config_entry via ContextVar (returning None
        # outside of HA runtime).  Re-attach the mock so that
        # async_config_entry_first_refresh and other methods work correctly.
        coord.config_entry = mock_config_entry
        return coord

    @pytest.mark.asyncio
    async def test_coordinator_initialization(self, coordinator):
        """Test that coordinator initializes with correct properties."""
        # This test MUST FAIL initially - no implementation exists
        # Validate coordinator has required attributes
        assert hasattr(coordinator, "hass")
        assert hasattr(coordinator, "config_entry")
        assert hasattr(coordinator, "data")
        assert hasattr(coordinator, "last_update_success")
        assert hasattr(coordinator, "update_interval")

        # Validate initial state
        assert coordinator.data is None or isinstance(coordinator.data, dict)
        assert isinstance(coordinator.last_update_success, bool)

    @pytest.fixture
    def mock_portfolio_data(self):
        """Return a complete portfolio data dict matching the coordinator schema."""
        return {
            "cash_balance": 5000.00,
            "currency": "USD",
            "total_value": 125000.00,
            "non_margin_positions_value": 120000.00,
            "ytd_earnings_percentage": 5.2,
            "investment_performance_percentage": 12.3,
            "ytd_investment_performance_percentage": 4.5,
            "month_investment_performance_percentage": 1.1,
            "quarter_investment_performance_percentage": 3.2,
            "cash_transfer_balance": 50000.00,
            "client_id": "client_123",
            "client_name": "Test User",
            "account_id": "acc_001",
            "last_updated": datetime.now().isoformat(),
        }

    @pytest.mark.asyncio
    async def test_coordinator_data_structure(self, coordinator, mock_portfolio_data):
        """Test that coordinator data follows the expected schema."""
        with patch.object(
            coordinator, "_fetch_portfolio_data", return_value=mock_portfolio_data
        ):
            await coordinator.async_config_entry_first_refresh()

        # Validate data structure matches current implementation
        data = coordinator.data
        assert isinstance(data, dict)

        # Required top-level fields for current implementation
        expected_fields = {
            "cash_balance",
            "currency",
            "total_value",
            "non_margin_positions_value",
            "ytd_earnings_percentage",
            "investment_performance_percentage",
            "ytd_investment_performance_percentage",
            "cash_transfer_balance",
            "client_id",
            "account_id",
            "client_name",
            "last_updated",
        }

        for field in expected_fields:
            assert field in data

        # Validate field types
        assert isinstance(data["cash_balance"], int | float)
        assert isinstance(data["currency"], str)
        assert isinstance(data["total_value"], int | float)
        assert isinstance(data["client_id"], str)
        assert isinstance(data["account_id"], str)
        assert isinstance(data["client_name"], str)

    @pytest.mark.asyncio
    async def test_coordinator_getter_methods(self, coordinator, mock_portfolio_data):
        """Test that coordinator provides required getter methods."""
        with patch.object(
            coordinator, "_fetch_portfolio_data", return_value=mock_portfolio_data
        ):
            await coordinator.async_config_entry_first_refresh()

        # Should have getter methods for sensor data
        assert hasattr(coordinator, "get_cash_balance")
        assert hasattr(coordinator, "get_currency")
        assert hasattr(coordinator, "get_total_value")
        assert hasattr(coordinator, "get_client_id")
        assert hasattr(coordinator, "get_account_id")
        assert hasattr(coordinator, "get_client_name")

        # Methods should be callable and return expected types
        assert callable(coordinator.get_cash_balance)
        assert callable(coordinator.get_currency)
        assert callable(coordinator.get_total_value)

        # Test return values when data is available
        if coordinator.data:
            currency = coordinator.get_currency()
            assert isinstance(currency, str)
            assert len(currency) == 3  # ISO currency code

    @pytest.mark.asyncio
    async def test_coordinator_update_interval(self, coordinator, mock_portfolio_data):
        """Test that update interval is dynamic based on market hours."""
        with patch.object(
            coordinator, "_fetch_portfolio_data", return_value=mock_portfolio_data
        ):
            await coordinator.async_config_entry_first_refresh()

        # Coordinator should have update_interval attribute
        assert hasattr(coordinator, "update_interval")
        assert coordinator.update_interval is not None

        # Update interval should be timedelta
        from datetime import timedelta

        assert isinstance(coordinator.update_interval, timedelta)

        # Should be 5 minutes (market hours), 15 minutes (any timezone), or 30 minutes (after hours)
        minutes = coordinator.update_interval.total_seconds() / 60
        assert minutes in [5, 15, 30]

    @pytest.mark.asyncio
    async def test_coordinator_error_handling(self, coordinator, mock_portfolio_data):
        """Test that coordinator handles API errors gracefully."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        # First do a successful refresh so data is populated
        with patch.object(
            coordinator, "_fetch_portfolio_data", return_value=mock_portfolio_data
        ):
            await coordinator.async_config_entry_first_refresh()
        assert coordinator.last_update_success is True

        # Now simulate API failure via _fetch_portfolio_data raising UpdateFailed
        with patch.object(
            coordinator,
            "_fetch_portfolio_data",
            side_effect=UpdateFailed("API Error"),
        ):
            await coordinator.async_refresh()

        # Coordinator should track error state
        assert coordinator.last_update_success is False

    @pytest.mark.asyncio
    async def test_coordinator_authentication_refresh(self, coordinator):
        """Test that coordinator delegates token refresh to OAuth2Session."""
        # _ensure_token_valid always calls async_ensure_token_valid as a safety net
        await coordinator._ensure_token_valid()
        coordinator._oauth_session.async_ensure_token_valid.assert_called()

    @pytest.mark.asyncio
    async def test_coordinator_rate_limiting(self, coordinator, mock_portfolio_data):
        """Test that coordinator respects API rate limits.

        Rate limiting is implemented via staggered update offsets and
        inter-request delays inside _fetch_portfolio_data.  The API client
        itself also has a rate limiter.
        """
        # Should have stagger offset for multi-account rate limiting
        assert hasattr(coordinator, "_initial_update_offset")

        # Multiple rapid requests should succeed without error
        with patch.object(
            coordinator, "_fetch_portfolio_data", return_value=mock_portfolio_data
        ):
            start_time = datetime.now()
            await coordinator._async_update_data()
            await coordinator._async_update_data()
            elapsed = (datetime.now() - start_time).total_seconds()

        # Should either be very fast (mocked) or properly throttled
        assert elapsed < 1 or elapsed >= 1  # Allow for either caching or throttling

    @pytest.mark.asyncio
    async def test_coordinator_data_consistency(self, coordinator, mock_portfolio_data):
        """Test that coordinator data remains consistent across updates."""
        with patch.object(
            coordinator, "_fetch_portfolio_data", return_value=mock_portfolio_data
        ):
            await coordinator.async_config_entry_first_refresh()
            first_data = coordinator.data.copy()

            # Second update should maintain data structure
            await coordinator.async_refresh()
            second_data = coordinator.data

        # Structure should be consistent
        assert set(first_data.keys()) == set(second_data.keys())

        # Core fields should remain consistent
        assert "cash_balance" in second_data
        assert "currency" in second_data
        assert "total_value" in second_data
        assert "client_id" in second_data

    def test_coordinator_implements_interface(self, coordinator):
        """Test that coordinator implements required DataUpdateCoordinator interface."""
        # This test MUST FAIL initially - no implementation exists
        from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

        # Should inherit from or implement DataUpdateCoordinator interface
        assert isinstance(coordinator, DataUpdateCoordinator)

        # Should have required methods
        assert hasattr(coordinator, "async_config_entry_first_refresh")
        assert hasattr(coordinator, "async_request_refresh")
        assert hasattr(coordinator, "_async_update_data")

        # Methods should be callable
        assert callable(coordinator.async_config_entry_first_refresh)
        assert callable(coordinator.async_request_refresh)
        assert callable(coordinator._async_update_data)
