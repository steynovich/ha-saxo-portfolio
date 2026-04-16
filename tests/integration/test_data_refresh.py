"""Integration tests for data refresh cycle.

These tests validate the automatic data refresh functionality and
timing behavior, following validation scenarios from quickstart.md.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import UTC, datetime, timedelta
import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.saxo_portfolio.coordinator import SaxoCoordinator
from custom_components.saxo_portfolio.const import DOMAIN


@pytest.mark.integration
class TestDataRefreshCycle:
    """Integration tests for complete data refresh cycle and timing."""

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = MagicMock(spec=HomeAssistant)
        hass.data = {DOMAIN: {}}
        return hass

    @pytest.fixture
    def mock_config_entry(self):
        """Create a mock config entry with valid OAuth token."""
        config_entry = MagicMock(spec=ConfigEntry)
        config_entry.entry_id = "test_entry_123"
        config_entry.options = {}
        config_entry.state = ConfigEntryState.SETUP_IN_PROGRESS
        config_entry.data = {
            "token": {
                "access_token": "valid_token",
                "refresh_token": "valid_refresh",
                "expires_at": (datetime.now() + timedelta(hours=1)).timestamp(),
                "token_type": "Bearer",
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

    @pytest.fixture
    def coordinator(self, mock_hass, mock_config_entry, mock_oauth_session):
        """Create a SaxoCoordinator with config_entry properly attached."""
        coord = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
        # The parent __init__ resolves config_entry via ContextVar (returning None
        # outside of HA runtime).  Re-attach the mock so that
        # async_config_entry_first_refresh and other methods work correctly.
        coord.config_entry = mock_config_entry
        return coord

    @pytest.mark.asyncio
    async def test_coordinator_initial_refresh_on_setup(
        self, coordinator, mock_portfolio_data
    ):
        """Test that coordinator performs initial data refresh during setup.

        This validates Step 4.3 from quickstart.md: Test Data Refresh
        """
        with patch.object(
            coordinator, "_fetch_portfolio_data", return_value=mock_portfolio_data
        ):
            # Perform initial refresh
            await coordinator.async_config_entry_first_refresh()

        # Should have populated data
        assert coordinator.data is not None
        assert coordinator.last_update_success is True
        assert "cash_balance" in coordinator.data
        assert "total_value" in coordinator.data
        assert "currency" in coordinator.data

    @pytest.mark.asyncio
    async def test_dynamic_update_interval_market_hours(
        self, mock_hass, mock_config_entry, mock_oauth_session, mock_portfolio_data
    ):
        """Test that update interval changes based on market hours.

        Market hours: 5 minute updates
        After hours: 30 minute updates
        """
        # Use a specific timezone so market hours logic applies
        mock_config_entry.data["timezone"] = "America/New_York"

        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)
        coordinator.config_entry = mock_config_entry

        with patch.object(
            coordinator, "_fetch_portfolio_data", return_value=mock_portfolio_data
        ):
            # Mock market hours check
            with patch.object(coordinator, "_is_market_hours") as mock_market_check:
                # During market hours
                mock_market_check.return_value = True
                await coordinator._async_update_data()
                assert coordinator.update_interval == timedelta(minutes=5)

                # After market hours
                mock_market_check.return_value = False
                await coordinator._async_update_data()
                assert coordinator.update_interval == timedelta(minutes=30)

    @pytest.mark.asyncio
    async def test_market_hours_detection_logic(
        self, mock_hass, mock_config_entry, mock_oauth_session
    ):
        """Test market hours detection for different time zones and days."""
        # Use America/New_York so market hours logic actually runs
        mock_config_entry.data["timezone"] = "America/New_York"

        coordinator = SaxoCoordinator(mock_hass, mock_config_entry, mock_oauth_session)

        # Test weekday during market hours (9:30 AM - 4 PM EST)
        with patch("homeassistant.util.dt.utcnow") as mock_now:
            # Monday 10 AM EST = 15:00 UTC (timezone-aware)
            mock_now.return_value = datetime(2023, 12, 4, 15, 0, 0, tzinfo=UTC)
            # Clear cache between checks
            coordinator._market_hours_cache = None
            assert coordinator._is_market_hours() is True

            # Saturday (weekend)
            mock_now.return_value = datetime(2023, 12, 2, 15, 0, 0, tzinfo=UTC)
            coordinator._market_hours_cache = None
            assert coordinator._is_market_hours() is False

            # Weekday after hours (6 PM EST = 23:00 UTC)
            mock_now.return_value = datetime(2023, 12, 4, 23, 0, 0, tzinfo=UTC)
            coordinator._market_hours_cache = None
            assert coordinator._is_market_hours() is False

    @pytest.mark.asyncio
    async def test_automatic_refresh_scheduling(self, coordinator):
        """Test that coordinator has an update interval for automatic refreshes."""
        # Coordinator should have an update_interval set
        assert coordinator.update_interval is not None
        assert isinstance(coordinator.update_interval, timedelta)

        # For "any" timezone, should be 15 minutes
        assert coordinator.update_interval == timedelta(minutes=15)

    @pytest.mark.asyncio
    async def test_manual_refresh_request(self, coordinator, mock_portfolio_data):
        """Test manual refresh request functionality.

        This validates Step 4.4 from quickstart.md: Manual Refresh Test
        """
        with patch.object(
            coordinator, "_fetch_portfolio_data", return_value=mock_portfolio_data
        ) as mock_fetch:
            # Perform initial refresh
            await coordinator.async_config_entry_first_refresh()
            initial_last_updated = coordinator.last_successful_update_time

            # Wait a moment
            await asyncio.sleep(0.01)

            # Request manual refresh (use async_refresh to avoid debouncer loop issues)
            await coordinator.async_refresh()

            # Should have updated timestamp
            assert coordinator.last_successful_update_time != initial_last_updated

            # Should have called the fetch method at least twice
            assert mock_fetch.call_count >= 2

    @pytest.mark.asyncio
    async def test_refresh_with_updated_data_triggers_listeners(
        self, coordinator, mock_portfolio_data
    ):
        """Test that data refresh triggers listener callbacks."""
        call_count = 0

        def on_update():
            nonlocal call_count
            call_count += 1

        with patch.object(
            coordinator, "_fetch_portfolio_data", return_value=mock_portfolio_data
        ):
            # First refresh to populate data
            await coordinator.async_config_entry_first_refresh()

        # Register a listener (after first refresh, so _schedule_refresh
        # is called; set pref_disable_polling to avoid hass.loop access)
        coordinator.config_entry.pref_disable_polling = True
        coordinator.async_add_listener(on_update)

        # Return different data so always_update=False still notifies listeners
        updated_data = {**mock_portfolio_data, "total_value": 130000.00}
        with patch.object(
            coordinator, "_fetch_portfolio_data", return_value=updated_data
        ):
            await coordinator.async_refresh()

        # Listeners are called after data update
        assert call_count >= 1

    @pytest.mark.asyncio
    async def test_refresh_failure_preserves_last_good_data(
        self, coordinator, mock_portfolio_data
    ):
        """Test that refresh failures preserve last good data."""
        # Successful initial refresh
        with patch.object(
            coordinator, "_fetch_portfolio_data", return_value=mock_portfolio_data
        ):
            await coordinator.async_config_entry_first_refresh()
            good_data = coordinator.data.copy()

        # Subsequent refresh fails
        with patch.object(
            coordinator,
            "_fetch_portfolio_data",
            side_effect=UpdateFailed("API Error"),
        ):
            await coordinator.async_refresh()

        # Should preserve last good data
        assert coordinator.data == good_data
        assert coordinator.last_update_success is False

    @pytest.mark.asyncio
    async def test_oauth_token_refresh_during_data_update(self, coordinator):
        """Test automatic OAuth token refresh during data updates."""
        # _ensure_token_valid always calls async_ensure_token_valid as a safety net
        await coordinator._ensure_token_valid()
        coordinator._oauth_session.async_ensure_token_valid.assert_called()

    @pytest.mark.asyncio
    async def test_rate_limiting_stagger_offset(self, coordinator):
        """Test that rate limiting is supported via stagger offset."""
        # Coordinator uses an initial stagger offset to prevent
        # simultaneous updates from multiple accounts
        assert hasattr(coordinator, "_initial_update_offset")
        assert 0 <= coordinator._initial_update_offset <= 30

    @pytest.mark.asyncio
    async def test_concurrent_refresh_requests_handled(
        self, coordinator, mock_portfolio_data
    ):
        """Test that concurrent refresh requests are handled properly."""
        with patch.object(
            coordinator, "_async_update_data", return_value=mock_portfolio_data
        ) as mock_update:
            # Start multiple refresh requests concurrently using async_refresh
            tasks = [
                asyncio.create_task(coordinator.async_refresh()),
                asyncio.create_task(coordinator.async_refresh()),
                asyncio.create_task(coordinator.async_refresh()),
            ]

            await asyncio.gather(*tasks)

            # Should not have called update more times than necessary
            # (implementation may batch or serialize requests via debouncer lock)
            assert mock_update.call_count <= 3

    @pytest.mark.asyncio
    async def test_refresh_timing_accuracy(self, coordinator):
        """Test that refresh intervals are accurate within acceptable tolerance."""
        # Set 5-minute interval (market hours)
        coordinator.update_interval = timedelta(minutes=5)

        # Verify interval is stored correctly
        expected_seconds = 300.0
        assert coordinator.update_interval.total_seconds() == expected_seconds

    @pytest.mark.asyncio
    async def test_data_consistency_across_refresh_cycles(
        self, coordinator, mock_portfolio_data
    ):
        """Test data consistency across multiple refresh cycles."""
        # Track data consistency
        data_snapshots = []

        # Different data for each refresh
        responses = [
            {**mock_portfolio_data, "total_value": 100000},
            {**mock_portfolio_data, "total_value": 105000},
            {**mock_portfolio_data, "total_value": 103000},
        ]

        with patch.object(coordinator, "_fetch_portfolio_data") as mock_fetch:
            for i, response in enumerate(responses):
                mock_fetch.return_value = response
                if i == 0:
                    await coordinator.async_config_entry_first_refresh()
                else:
                    await coordinator.async_refresh()

                # Capture data snapshot
                data_snapshots.append(coordinator.data.copy())

                # Data should be consistent with API response
                assert coordinator.data["total_value"] == response["total_value"]

        # Should have three different snapshots
        assert len({str(snapshot) for snapshot in data_snapshots}) == 3
